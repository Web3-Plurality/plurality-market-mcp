# Plurality Market MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server for the **Plurality Market stack** (Studio + C2C Marketplace + Talk to Memory). Gives any MCP-compatible client — the in-browser Talk to Memory agent, Claude Code, Cursor — read and write access to a user's memory buckets.

> This is the **market stack** MCP server, deliberately separate from Plurality's production MCP server: different ports, different database, no shared identity.

## Authentication

**Personal Access Tokens (PATs) only.** No OAuth, no Hydra. Format: `plur_pat_<random>`.

Every MCP request must carry `Authorization: Bearer plur_pat_…`. The MCP server forwards each token to the backend's `/pat/tokens/verify` endpoint, which hashes it (HMAC + pepper) and looks up the user. Users mint PATs in the marketplace UI: **wallet pill → API tokens → Generate new token**.

The MCP server is stateless about PATs — it doesn't store hashes, doesn't know the pepper, just relays.

## Architecture

```
                  ┌───────────────────────────────────────────────────┐
                  │              Marketplace UI (:3001)              │
                  │   ┌────────┐  ┌─────────────┐  ┌────────────────┐│
                  │   │ Studio │  │ C2C Market  │  │ Talk to Memory ││
                  │   └────────┘  └─────────────┘  └─────┬──────────┘│
                  └────────────────────┬─────────────────┼───────────┘
                                       │ session JWT      │ PAT bearer
                                       ▼                  ▼
        Claude Code  ──── PAT bearer ───►  market-mcp (:5051)
        / Cursor                                          │
                                                          │ PAT forwarded
                                                          ▼
                                              market-backend (:5001)
                                                          │
                                                          ▼
                                              market-ai-service (:8001)
                                                          │
                                                          ▼
                                                   Vector DB (S3 Vectors)
```

In production, Traefik fronts the MCP. In local dev, set `MCP_DEV_CORS_ORIGIN` so the in-browser agent can hit the MCP directly.

## Tools Exposed

| Tool | Description |
|---|---|
| `get_user_memory_buckets` | List all memory buckets (AI profiles) for the user |
| `list_items_in_memory_bucket` | List items in a bucket (metadata only) |
| `search_memory` | Semantic search within a bucket or across all of the user's buckets |
| `read_context` | Read full content of a stored item with pagination |
| `save_memory` | Save text to a specific bucket |
| `save_conversation` | Save a conversation (chat history) to a bucket |
| `create_memory_bucket` | Create a new bucket |

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- A running **plurality-market-backend** at `http://localhost:5001` (or wherever — see `BACKEND_API_URL` below)
- A running **plurality-market-ai-service** at `http://localhost:8001` (called by the backend, not the MCP directly)

## Local Setup

### 1. Install dependencies

```bash
cd plurality-market-mcp
pip install uv
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Default values for local dev:

```env
MCP_RESOURCE_URL=http://localhost:5051
BACKEND_API_URL=http://localhost:5001
MCP_DEV_CORS_ORIGIN=http://localhost:3001
```

> **Why `MCP_DEV_CORS_ORIGIN`?** Production runs behind Traefik, which adds CORS headers. Local dev without Traefik needs this server to answer CORS itself for the in-browser agent. The middleware also checks for an existing `Access-Control-Allow-Origin` header before injecting, so production + this var enabled never double-CORS.

### 3. Start the MCP server

```bash
uv run uvicorn main:mcp_server --host 0.0.0.0 --port 5051 --reload
```

### 4. Verify

```bash
# Should return the "Missing Authorization header" JSON (proves server is up + auth middleware loaded)
curl -X POST http://localhost:5051/
```

To test with a real PAT, mint one in the marketplace UI's API tokens dialog, then point any MCP-compatible client at `http://localhost:5051/` with `Authorization: Bearer plur_pat_…` — see the Client Integration section below.

> The MCP server itself does NOT serve the `.well-known/oauth-protected-resource/mcp` discovery document. Plurality is PAT-only, so MCP-spec clients that probe for OAuth discovery get a `WWW-Authenticate` header pointing at the backend (which IS where the discovery doc lives). For curl tests, hit the backend directly: `curl http://localhost:5001/.well-known/oauth-protected-resource/mcp`.

---

## Creating a PAT (cli alternative)

If you want to script it instead of using the UI, the backend exposes the standard endpoint:

```bash
# Requires the wallet-session cookie. Easiest from a browser console while
# logged in to the marketplace UI:
await fetch('http://localhost:5001/pat/tokens', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'claude-code-laptop', scopes: ['mcp:tools'] }),
}).then(r => r.json());
```

The response includes `token: "plur_pat_…"`. **Copy it once** — the backend stores only the HMAC hash and you can never re-display the plaintext.

### Scopes

| Scope | Grants (v1) |
|---|---|
| `mcp:tools` | **All tools (read + write).** Default when you mint a PAT without specifying scopes. |
| `mcp:tools:read` | Reserved for a future read-only split. **Currently grants nothing.** A PAT with only this scope is rejected with `403 insufficient_scope` on every endpoint. |
| `mcp:tools:write` | Reserved for a future write-only split. **Currently grants nothing.** Same as above. |

In v1, the backend's PAT-gated endpoints require literal `mcp:tools`. The narrower `:read` / `:write` slots exist in the schema so we can split enforcement later without a migration, but right now they are placeholders — **mint your PAT with `mcp:tools` (or with no scopes at all, which defaults to `mcp:tools`)**.

---

## MCP Client Integration

### Talk to Memory (in-browser, in the Marketplace UI itself)

Open the marketplace UI → click the **Talk to Memory** tab. Settings:

- Provider dropdown: Claude / OpenAI / Google Gemini
- Paste your **LLM API key** (browser-only, never POSTed)
- Paste your **MCP PAT** (`plur_pat_…`) — create one via wallet pill → API tokens

Status pill flips to **"Ready · N MCP tools"** once everything's wired. The Context dropdown above the chat lets you scope tool calls to a single bucket.

### Claude Code — Terminal

```bash
claude mcp add plurality-market http://localhost:5051/ \
  --transport http \
  --header "Authorization: Bearer plur_pat_…"
```

Replace `http://localhost:5051/` with your public MCP host in production. Tools become available in Claude Code immediately — no `/mcp` auth flow needed since the header carries the token.

### Claude Code — VSCode Extension

Add `.mcp.json` to your project root:

```json
{
  "mcpServers": {
    "plurality-market": {
      "type": "http",
      "url": "http://localhost:5051/",
      "headers": {
        "Authorization": "Bearer plur_pat_…"
      }
    }
  }
}
```

### Cursor / Other HTTP MCP clients

Any client that speaks Streamable HTTP MCP and lets you set a custom `Authorization` header can connect. Just point at `<MCP_HOST>/` and pass the PAT.

### MCP Inspector (for debugging)

```bash
npx @modelcontextprotocol/inspector
```

Enter `http://localhost:5051/` as the server URL and `Bearer plur_pat_…` as the auth header. The inspector lets you call tools interactively.

---

## Project Structure

```
plurality-market-mcp/
├── main.py                             # Entry point
├── pyproject.toml                      # Dependencies (managed by uv)
├── .env.example                        # Environment template
└── src/plurality_mcp_server/
    ├── app.py                          # FastMCP app + middleware stack (PAT auth + dev CORS)
    ├── config.py                       # Env vars, shared HTTP client, context vars
    ├── auth.py                         # PATAuthMiddleware — forwards Bearer to backend /pat/tokens/verify
    └── tools.py                        # MCP tool definitions
```

## Troubleshooting

**Browser BYOK agent gets CORS rejected on MCP requests**
- Set `MCP_DEV_CORS_ORIGIN=http://localhost:3001` (your UI origin) and restart. Boot log should show `[CORS] Dev-mode CORS enabled for origin: …`.

**MCP client gets 401 Unauthorized**
- The PAT was revoked or expired. Check via `GET /pat/tokens` on the backend (with wallet cookie) — the relevant row will show `status: 'revoked'` or `status: 'expired'`. Mint a new one in the UI.
- Or the bearer header is mangled (e.g. missing the `Bearer ` prefix).

**Token works in the marketplace UI but not in Claude Code**
- The PAT carries the userId of whatever wallet was logged in when it was created. If you've logged out and back in with a different wallet, mint a fresh PAT.

**MCP server returns 502 on tool calls**
- The backend (`BACKEND_API_URL`) isn't reachable from the MCP process. Check the URL + that the backend is running on the configured port.

**Vector queries return prod-stack data**
- The market AI service needs `NAMESPACE_PREFIX=market:` set so its writes/reads are scoped to a tenant prefix in the shared vector DB. Without it, market and prod stacks share the same key space.
