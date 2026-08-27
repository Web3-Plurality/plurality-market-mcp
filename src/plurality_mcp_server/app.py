from mcp.server.fastmcp import FastMCP
from plurality_mcp_server.auth import PATAuthMiddleware
from plurality_mcp_server.config import MCP_DEV_CORS_ORIGIN
from plurality_mcp_server.tools import register_tools

# ── MCP app ──
# host="0.0.0.0" for container networking; transport security is disabled
# because the PAT auth middleware is the real security gate.
mcp_app = FastMCP(
    name="mcp",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=5051,
)
register_tools(mcp_app)

# ── ASGI app (Starlette under the hood) ──
mcp_server = mcp_app.streamable_http_app()

# ── Middleware (pure ASGI — no BaseHTTPMiddleware) ──
# PAT auth middleware forwards Authorization: Bearer plur_pat_... to the
# backend for verification, then forwards the request with user_id/token
# stamped into per-request contextvars for the tool handlers.
mcp_server = PATAuthMiddleware(mcp_server)


# ── Dev-only CORS ──
# Production: Traefik fronts the MCP and adds CORS headers — leave
# MCP_DEV_CORS_ORIGIN unset and this layer is a no-op.
# Local dev (no Traefik): set MCP_DEV_CORS_ORIGIN=http://localhost:3001 (or
# whatever the marketplace UI's origin is) and this middleware:
#   - answers OPTIONS preflights with the right headers (status 204)
#   - injects Access-Control-Allow-* headers on every response
# Pure ASGI — no Starlette BaseHTTPMiddleware (which would buffer SSE).
class DevCorsMiddleware:
    def __init__(self, app, allow_origin: str):
        self.app = app
        self.allow_origin = allow_origin
        self._common_headers = [
            (b"access-control-allow-origin", self.allow_origin.encode("latin-1")),
            (b"access-control-allow-credentials", b"true"),
            (b"access-control-expose-headers", b"mcp-session-id"),
            (b"vary", b"Origin"),
        ]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")

        # Preflight short-circuit — answer ourselves, never hand to inner app.
        if method == "OPTIONS":
            req_headers = b""
            for k, v in scope.get("headers", []):
                if k == b"access-control-request-headers":
                    req_headers = v
                    break
            allow_headers = req_headers if req_headers else b"authorization,content-type,mcp-session-id"
            preflight_headers = list(self._common_headers) + [
                (b"access-control-allow-methods", b"GET,POST,DELETE,OPTIONS"),
                (b"access-control-allow-headers", allow_headers),
                (b"access-control-max-age", b"600"),
                (b"content-length", b"0"),
            ]
            await send({"type": "http.response.start", "status": 204, "headers": preflight_headers})
            await send({"type": "http.response.body", "body": b""})
            return

        # Non-preflight — inject CORS headers into the inner app's response.
        async def _send_wrapper(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                # Skip if Traefik or someone else already set Access-Control-Allow-Origin
                already_set = any(k.lower() == b"access-control-allow-origin" for k, _ in headers)
                if not already_set:
                    headers.extend(self._common_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_wrapper)


if MCP_DEV_CORS_ORIGIN:
    print(f"[CORS] Dev-mode CORS enabled for origin: {MCP_DEV_CORS_ORIGIN}", flush=True)
    mcp_server = DevCorsMiddleware(mcp_server, MCP_DEV_CORS_ORIGIN)


# ── Outer request logging ──
_original_app = mcp_server

async def _app_with_logging(scope, receive, send):
    """Logs every incoming HTTP request at the outermost layer (after CORS,
    before auth middleware). Lifespan events pass straight through."""
    if scope["type"] == "http":
        path = scope.get("path", "?")
        method = scope.get("method", "?")
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        host = headers.get("host", "?")
        has_auth = "authorization" in headers
        auth_preview = headers["authorization"][:30] + "..." if has_auth else "NONE"
        print(f"[REQ] {method} {path} | host={host} | auth={auth_preview}", flush=True)

        async def _send_wrapper(message):
            if message.get("type") == "http.response.start":
                status = message.get("status", "?")
                print(f"[RES] {method} {path} | status={status}", flush=True)
            await send(message)

        await _original_app(scope, receive, _send_wrapper)
    else:
        await _original_app(scope, receive, send)

mcp_server = _app_with_logging
