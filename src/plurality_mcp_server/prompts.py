from typing import Annotated
from pydantic import Field
from plurality_mcp_server.config import current_token
from plurality_mcp_server.tools import list_profiles, fetch_skill, format_memory_index


def _profile_name(p: dict) -> str:
    return str(p.get("profileName") or p.get("name") or "Unnamed")


def _resolve_bucket(profiles: list, wanted: str):
    """Exact id match first, then case-insensitive name match. None if neither."""
    for p in profiles:
        if str(p.get("id", "")) == wanted:
            return p
    lowered = wanted.lower()
    for p in profiles:
        if _profile_name(p).strip().lower() == lowered:
            return p
    return None


def register_prompts(mcp_app):
    """Register MCP prompts (slash commands in Claude Code) on the FastMCP app.

    Prompts go through the same PAT middleware as tools: the middleware wraps
    the whole ASGI app, so current_token is populated here too.
    """

    @mcp_app.prompt(
        name="use_skill",
        description="Load a memory bucket's Skill and follow its instructions",
    )
    async def use_skill(
        bucket: Annotated[str, Field(description="Skill (memory bucket) id or name")],
    ) -> str:
        """Returns a single user message: the Skill's instructions, its memory index and the tool scoping rule.

        Errors are returned as plain "Error: ..." text so the client shows
        something useful instead of a failed prompt render.
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            wanted = (bucket or "").strip()
            if not wanted:
                return "Error: Pass a bucket id or name as the bucket argument, for example /mcp__plurality__use_skill My cooking notes"

            profiles, err = await list_profiles(token)
            if err:
                return err

            match = _resolve_bucket(profiles, wanted)
            if match is None:
                if not profiles:
                    return (
                        f'Error: No bucket matches "{wanted}" and this wallet does not own any memory buckets yet. '
                        "Create one in the Plurality Memory Marketplace first."
                    )
                available = "\n".join(
                    f"- {_profile_name(p)} (id: {p.get('id', 'unknown')})" for p in profiles
                )
                return f'Error: No Skill matches "{wanted}". Available Skills:\n{available}'

            pid = str(match.get("id"))
            data, err = await fetch_skill(pid, token)
            if err:
                return err

            name = (data.get("name") or _profile_name(match)).strip()
            instructions = (data.get("instructions") or "").strip() or "(no instructions)"
            index_lines = format_memory_index(data.get("memoryIndex"))
            memory_block = "\n".join(index_lines) if index_lines else "- (no items yet)"

            parts = [f'You are now using the Skill "{name}" from Plurality.']
            if data.get("isDefault"):
                parts.append("(This bucket has no custom skill, so the default knowledge assistant applies.)")
            parts.append(instructions)
            parts.append(f"Memory in this Skill:\n{memory_block}")
            parts.append(
                f'For supporting knowledge call search_memory / read_context with profile_ids=["{pid}"]. '
                "Reply in plain conversational text."
            )
            return "\n\n".join(parts)

        except Exception as e:
            return f"Error loading skill: {str(e)}"
