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
# answers preflight + adds CORS headers in-process. Leave EMPTY in prod:
# Traefik fronts the MCP and adds CORS headers there. Both layers enabling
# CORS produces duplicate headers that browsers reject.
MCP_DEV_CORS_ORIGIN = os.getenv("MCP_DEV_CORS_ORIGIN", "")

# ── Shared httpx client (connection pooling, reused across requests) ──
http_client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_connections=20))

# ── Per-request context (async-safe via contextvars) ──
# Auth middleware sets this after PAT validation. Tool functions read
# current_token to forward the PAT bearer to backend API calls. The backend
# resolves bucket access from the token's owner wallet (via NFT ownership),
# so tools don't need a separate identity context.
current_token: contextvars.ContextVar[str] = contextvars.ContextVar('auth_token', default='')

# ── Server instructions ──
# Sent to every MCP client in the initialize handshake (FastMCP `instructions`).
# This is the one place that tells an agent how the Skills model works, so
# tool docstrings can stay short.
SERVER_INSTRUCTIONS = """Plurality Memory Marketplace MCP server.

Every memory bucket here holds memory (files, notes and saved chats) and may come with a Skill: a markdown playbook written by the bucket creator that says how to use that memory. You can use a bucket if the authenticated wallet created it or holds its NFT.

How to use a bucket:
1. Call get_user_memory_buckets to see the available buckets and their ids.
2. Before answering anything from a bucket, call get_bucket_skill(profile_id) and follow the instructions it returns. They take priority over your default behaviour for that task.
3. For supporting knowledge use search_memory and read_context scoped to that bucket (pass profile_ids=["<profile_id>"] to search_memory).
4. A bucket without a custom skill returns the default knowledge assistant: answer only from the bucket's memory and cite the item each answer comes from.

The use_skill prompt does steps 1 and 2 in one go when the user names a bucket.

Reply in plain conversational text unless the Skill's instructions say otherwise."""
