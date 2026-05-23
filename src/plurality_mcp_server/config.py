import contextvars
import os
import httpx

# ── Environment configuration ──
# MCP_RESOURCE_URL: public-facing URL of this MCP server (used in WWW-Authenticate headers)
# BACKEND_API_URL: trusted backend API for PAT verification + data access
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", "http://localhost:5051")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:5001")

# ── Dev-only CORS ──
# When set to a non-empty origin (e.g. http://localhost:3001), the MCP server
# answers preflight + adds CORS headers in-process. Leave EMPTY in prod —
# Traefik fronts the MCP and adds CORS headers there. Both layers enabling
# CORS produces duplicate headers that browsers reject.
MCP_DEV_CORS_ORIGIN = os.getenv("MCP_DEV_CORS_ORIGIN", "")

# ── Shared httpx client (connection pooling, reused across requests) ──
http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_connections=20))

# ── Per-request context (async-safe via contextvars) ──
# Auth middleware sets these after PAT validation. Tool functions read
# current_token to forward the PAT bearer to backend API calls. Wallet
# address is the canonical identity post-rewrite — the backend resolves
# bucket access from the wallet (via NFT ownership) so tools never need
# to send a separate user_id.
current_token: contextvars.ContextVar[str] = contextvars.ContextVar('auth_token', default='')
current_wallet_address: contextvars.ContextVar[str] = contextvars.ContextVar('wallet_address', default='')
