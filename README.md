# Plurality Market MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server for the **Plurality Memory Marketplace** (Studio + C2C Marketplace + Talk to Memory). It gives any MCP-compatible client (the in-browser Talk to Memory agent, Claude Code, Claude Desktop, Cursor) access to the memory buckets a wallet owns: their memory plus the creator's optional Skill instructions.

> This is the **market stack** MCP server, deliberately separate from Plurality's production MCP server: different ports, different database, no shared identity.

## Everything you own is a Skill

A **Skill** is a memory bucket with two parts:

- **Instructions**: a markdown playbook written by the bucket creator that tells an agent how to behave when it uses this bucket (what to look up, how to answer, what to refuse).
- **Memory**: the bucket's contexts (files, notes, saved chats), searchable through the vector index.

One bucket is one Skill. Instructions are optional: a bucket whose creator never wrote any still works and answers with the built-in **default skill** ("Knowledge assistant": answer only from the memory, cite the item each answer comes from). The default skill text lives in the backend and is served through the same endpoint, so this server never hardcodes it.

Who can read what:

| Data | Who sees it |
|---|---|
| Skill name and summary | Public (marketplace cards, NFT metadata) |
| Full instructions | The bucket creator and wallets holding the bucket's NFT |
| Memory (contexts) | Same as instructions |

Minted buckets are frozen: instructions and memory cannot change after the NFT exists, and the skill's hash is part of the on-chain bucket hash.

From an MCP client the rule of thumb is: **call `get_bucket_skill(profile_id)` before answering from a bucket, follow the instructions it returns, then use `search_memory` / `read_context` scoped to that bucket for supporting knowledge.** The server sends this rule to every client as MCP server `instructions` during the initialize handshake (see `SERVER_INSTRUCTIONS` in `config.py`).

## Authentication

**Personal Access Tokens (PATs) only.** No OAuth, no Hydra. Format: `plur_pat_<random>`.

Every MCP request must carry `Authorization: Bearer plur_pat_...`. The MCP server forwards each token to the backend's `/pat/tokens/verify` endpoint, which hashes it (HMAC + pepper) and looks up the user. Users mint PATs in the marketplace UI: **wallet pill > API tokens > Generate new token**.

The MCP server is stateless about PATs: it doesn't store hashes, doesn't know the pepper, just relays. Which Skills a token can use is resolved by the backend from the token's wallet (creator or NFT holder).

## Architecture

```
                  +---------------------------------------------------+
                  |              Marketplace UI (:3001)               |
                  |   +--------+  +-------------+  +----------------+ |
                  |   | Studio |  | C2C Market  |  |  Use a Skill   | |
                  |   +--------+  +-------------+  +-------+--------+ |
                  +--------------------+-------------------+----------+
                                       | session JWT       | PAT bearer
                                       v                   v
        Claude Code  ---- PAT bearer ---->  market-mcp (:5051, path /mcp)
        / Desktop / Cursor                                 |
                                                           | PAT forwarded
                                                           v
                                              market-backend (:5001)
                                                           |
                                                           v
                                              market-ai-service (:8001)
                                                           |
                                                           v
                                                   Vector DB (S3 Vectors)
```

In production, Traefik fronts the MCP. In local dev, set `MCP_DEV_CORS_ORIGIN` so the in-browser agent can hit the MCP directly.

## Tools Exposed

| Tool | Description |
|---|---|
| `get_user_memory_buckets` | List the Skills (memory buckets) the wallet can use. Each line shows `Skill: <name>` or `(no custom skill; default knowledge assistant)` |
| `get_bucket_skill` | Load one Skill: instructions (or the default skill) plus an index of its memory items |
| `list_items_in_memory_bucket` | List items in a bucket (full metadata, no content) |
| `search_memory` | Semantic search within a bucket (`profile_ids=["<id>"]`) or across all of the wallet's buckets |
| `read_context` | Read full content of a stored item with pagination |
| `save_memory` | Save text into a draft bucket's memory |
| `save_conversation` | Save a conversation (chat history) into a draft bucket's memory |
| `create_memory_bucket` | Create a new bucket (starts with the default skill) |

Tool names are stable across releases.

### `get_bucket_skill(profile_id)`

Calls `GET {BACKEND_API_URL}/ai/profile/{profile_id}/skill` with the PAT and returns markdown:

```
# Skill: Sous chef
Turns the recipes in this bucket into step-by-step cooking plans.

<the creator's instructions, verbatim>

## Memory in this bucket
- Weeknight pasta: Five 20-minute pasta dinners
- Knife skills: Notes from the Saturday class

Use search_memory / read_context with profile_ids=["<profile_id>"] for details.
```

When the bucket has no custom skill the header is followed by `(Default skill: the creator did not write a custom one.)` and the default knowledge assistant instructions. Errors come back as plain `Error: ...` strings (404 covers both "no such bucket" and "your wallet does not own it").

## Prompts Exposed

| Prompt | Argument | Description |
|---|---|---|
| `use_skill` | `bucket` (id or name) | Load a memory bucket's Skill and follow its instructions |

In Claude Code the prompt shows up as a slash command: `/mcp__plurality__use_skill <bucket id or name>` (the middle part is whatever name you gave the server when adding it). It resolves the bucket by exact id first, then by case-insensitive name, and returns one user message:

```
You are now using the Skill "Sous chef" from Plurality.

<instructions>

Memory in this Skill:
- Weeknight pasta: Five 20-minute pasta dinners
- Knife skills: Notes from the Saturday class

For supporting knowledge call search_memory / read_context with profile_ids=["<profile_id>"]. Reply in plain conversational text.
```

If nothing matches, the message lists the Skills the wallet can use. Prompts pass through the same PAT middleware as tools.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- A running **plurality-market-backend** at `http://localhost:5001` (or wherever; see `BACKEND_API_URL` below)
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
curl -X POST http://localhost:5051/mcp
```

The MCP endpoint is `/mcp` (FastMCP's Streamable HTTP path). To test with a real PAT, mint one in the marketplace UI's API tokens dialog, then point any MCP-compatible client at `http://localhost:5051/mcp` with `Authorization: Bearer plur_pat_...` (see Client Integration below).

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

The response includes `token: "plur_pat_..."`. **Copy it once**: the backend stores only the HMAC hash and can never re-display the plaintext.

### Scopes

| Scope | Grants (v1) |
|---|---|
| `mcp:tools` | **All tools and prompts (read + write).** Default when you mint a PAT without specifying scopes. |
| `mcp:tools:read` | Reserved for a future read-only split. **Currently grants nothing.** A PAT with only this scope is rejected with `403 insufficient_scope` on every endpoint. |
| `mcp:tools:write` | Reserved for a future write-only split. **Currently grants nothing.** Same as above. |

In v1, the backend's PAT-gated endpoints require literal `mcp:tools`. The narrower `:read` / `:write` slots exist in the schema so we can split enforcement later without a migration, but right now they are placeholders. **Mint your PAT with `mcp:tools` (or with no scopes at all, which defaults to `mcp:tools`).**

---

## MCP Client Integration

Replace `http://localhost:5051/mcp` with your public MCP URL in production, and `<TOKEN>` with the `plur_pat_...` value. The marketplace UI shows these same snippets, pre-filled, right after it reveals a new token.

### Use a Skill (in-browser, in the Marketplace UI itself)

Open the marketplace UI and click the **Use a Skill** tab. Settings:

- Provider dropdown: Claude / OpenAI / Google Gemini
- Paste your **LLM API key** (browser-only, never POSTed)
- Paste your **MCP PAT** (`plur_pat_...`), created via wallet pill > API tokens

Status pill flips to **"Ready · N MCP tools"** once everything's wired. The Skill picker above the chat scopes tool calls to one bucket and loads its instructions into the system prompt.

### Claude Code (CLI)

```bash
claude mcp add --transport http plurality http://localhost:5051/mcp --header "Authorization: Bearer <TOKEN>"
```

Tools become available immediately, no `/mcp` auth flow needed since the header carries the token. Your Skills show up as tools, and `/mcp__plurality__use_skill <bucket id or name>` loads one by name.

### Claude Desktop / Cursor / other JSON-configured clients

```json
{
  "mcpServers": {
    "plurality": {
      "url": "http://localhost:5051/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

For Claude Code's project-level `.mcp.json` add `"type": "http"` next to `url`. Any client that speaks Streamable HTTP MCP and lets you set a custom `Authorization` header can connect the same way.

### MCP Inspector (for debugging)

```bash
npx @modelcontextprotocol/inspector
```

Enter `http://localhost:5051/mcp` as the server URL and `Bearer plur_pat_...` as the auth header. The inspector lets you call tools and render the `use_skill` prompt interactively.

---

## Project Structure

```
plurality-market-mcp/
+-- main.py                             # Entry point
+-- pyproject.toml                      # Dependencies (managed by uv)
+-- .env.example                        # Environment template
+-- src/plurality_mcp_server/
    +-- app.py                          # FastMCP app + middleware stack (PAT auth + dev CORS)
    +-- config.py                       # Env vars, shared HTTP client, context vars, SERVER_INSTRUCTIONS
    +-- auth.py                         # PATAuthMiddleware: forwards Bearer to backend /pat/tokens/verify
    +-- tools.py                        # MCP tool definitions (incl. get_bucket_skill) + shared backend helpers
    +-- prompts.py                      # MCP prompts (use_skill)
```

## Troubleshooting

**Browser BYOK agent gets CORS rejected on MCP requests**
- Set `MCP_DEV_CORS_ORIGIN=http://localhost:3001` (your UI origin) and restart. Boot log should show `[CORS] Dev-mode CORS enabled for origin: ...`.

**MCP client gets 401 Unauthorized**
- The PAT was revoked or expired. Check via `GET /pat/tokens` on the backend (with wallet cookie); the relevant row will show `status: 'revoked'` or `status: 'expired'`. Mint a new one in the UI.
- Or the bearer header is mangled (e.g. missing the `Bearer ` prefix).

**Client connects but sees no tools (404 on the URL)**
- The endpoint is `/mcp`, not `/`. Point the client at `http://<host>:5051/mcp`.

**Token works in the marketplace UI but not in Claude Code**
- The PAT carries the userId of whatever wallet was logged in when it was created. If you've logged out and back in with a different wallet, mint a fresh PAT.

**`get_bucket_skill` / `use_skill` returns "not found or this token's wallet does not own it"**
- Instructions are only readable by the bucket creator and by wallets holding the bucket's NFT. Check the wallet behind the PAT, and that the backend running at `BACKEND_API_URL` has the skill endpoints (`GET /ai/profile/:id/skill`).

**MCP server returns 502 on tool calls**
- The backend (`BACKEND_API_URL`) isn't reachable from the MCP process. Check the URL + that the backend is running on the configured port.

**Vector queries return prod-stack data**
- The market AI service needs `NAMESPACE_PREFIX=market:` set so its writes/reads are scoped to a tenant prefix in the shared vector DB. Without it, market and prod stacks share the same key space.
