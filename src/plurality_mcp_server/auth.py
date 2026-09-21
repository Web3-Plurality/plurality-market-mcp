import json
import httpx
from plurality_mcp_server.config import (
    http_client,
    MCP_RESOURCE_URL,
    BACKEND_API_URL,
    current_token,
)

# Plurality personal access tokens are the only accepted credential.
PAT_PREFIX = "plur_pat_"


class PATAuthMiddleware:
    """Pure ASGI middleware: requires Authorization: Bearer plur_pat_... on every
    request, forwards to the backend's /pat/tokens/verify endpoint, and stashes
    the resolved user_id + token in contextvars for the tool handlers.

    Pure ASGI on purpose — Starlette's BaseHTTPMiddleware buffers SSE responses,
    which breaks FastMCP's Streamable HTTP transport (see FastMCP Issue #858).
    """

    def __init__(self, app):
        self.app = app

    async def _send_json_error(self, scope, receive, send, status, body, extra_headers=None):
        payload = json.dumps(body).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ]
        if extra_headers:
            for k, v in extra_headers.items():
                headers.append((k.encode("latin-1"), v.encode("latin-1")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # Parse headers from ASGI scope (byte tuples)
        headers_dict = {}
        for key, value in scope.get("headers", []):
            headers_dict[key.decode("latin-1").lower()] = value.decode("latin-1")

        # Discovery + health endpoints stay open. The discovery paths remain
        # advertised for clients that probe them, even though Plurality is
        # PAT-only — they'll just see no DCR endpoint.
        if path in ["/health", "/docs", "/openapi.json", "/register"] or \
           path.startswith("/.well-known/") or \
           path.startswith("/oauth2/"):
            await self.app(scope, receive, send)
            return

        # CORS preflight short-circuit (the DevCorsMiddleware in front already
        # answers OPTIONS, but this is defensive in case it's disabled).
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        auth_header = headers_dict.get("authorization", "")

        if not auth_header:
            await self._send_json_error(scope, receive, send, 401, {
                "error": "Missing Authorization header",
                "message": "Please provide a Bearer token in the Authorization header",
            }, {"WWW-Authenticate": f'Bearer resource_metadata="{MCP_RESOURCE_URL}/.well-known/oauth-protected-resource"'})
            return

        if not auth_header.startswith("Bearer "):
            await self._send_json_error(scope, receive, send, 401, {
                "error": "Invalid Authorization header format",
                "message": "Authorization header must be in format: Bearer <token>",
            })
            return

        token = auth_header.removeprefix("Bearer ").strip()

        if not token.startswith(PAT_PREFIX):
            await self._send_json_error(scope, receive, send, 401, {
                "error": "not_a_pat",
                "message": "Only Personal Access Tokens (plur_pat_...) are accepted",
            }, {"WWW-Authenticate": f'Bearer resource_metadata="{MCP_RESOURCE_URL}/.well-known/oauth-protected-resource"'})
            return

        # Forward to the backend for verification. The backend hashes the
        # token, looks it up in personal_access_token, and returns the
        # owner's user_id + scopes (or an error).
        try:
            verify_resp = await http_client.get(
                f"{BACKEND_API_URL}/pat/tokens/verify",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0,
            )
        except httpx.RequestError as e:
            await self._send_json_error(scope, receive, send, 502, {
                "error": "pat_verify_failed",
                "message": f"Failed to verify PAT with backend: {str(e)}",
            })
            return

        if verify_resp.status_code != 200:
            err_body = {}
            try:
                err_body = verify_resp.json()
            except Exception:
                pass
            await self._send_json_error(scope, receive, send, 401, {
                "error": err_body.get("error", "invalid_pat"),
                "message": "Invalid or expired API token",
            }, {"WWW-Authenticate": f'Bearer resource_metadata="{MCP_RESOURCE_URL}/.well-known/oauth-protected-resource"'})
            return

        info = verify_resp.json()
        pat_scopes = info.get("scopes", [])
        if "mcp:tools" not in pat_scopes:
            await self._send_json_error(scope, receive, send, 403, {
                "error": "insufficient_scope",
                "message": "Token missing required scope: mcp:tools",
            }, {"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="mcp:tools"'})
            return

        # Backend's PAT verify endpoint returns auth_address as the canonical
        # identity. user_id is still in the payload for legacy callers, but
        # the MCP server only needs the wallet — backend resolves bucket
        # access from it via NFT ownership.
        wallet_address = info.get("auth_address", "")
        print(f"[AUTH] {method} {path} | wallet={wallet_address}", flush=True)

        # Per-request context for tool functions
        current_token.set(token)

        await self.app(scope, receive, send)
