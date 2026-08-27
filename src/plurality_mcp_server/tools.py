from collections import defaultdict
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from plurality_mcp_server.config import http_client, current_token, BACKEND_API_URL


class ChatMessage(BaseModel):
    """A single message in a conversation."""
    role: Literal["user", "assistant"] = Field(description="The role of the message sender")
    content: str = Field(description="The text content of the message")


def register_tools(mcp_app):
    """Register all MCP tools on the given FastMCP app instance."""

    @mcp_app.tool()
    async def get_user_memory_buckets() -> str:
        """
        List all memory buckets (AI profiles) for the authenticated user.

        Each bucket is a themed collection of documents, notes, and files.
        Returns bucket IDs, names, and item counts.
        Use this first to discover available memory buckets before browsing
        or searching their contents.

        Returns both owned buckets and buckets shared with the user.
        Each bucket has a `role` ('owner', 'editor', or 'viewer') and
        shared buckets include `sharedBy` information.
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            # includeMinted=true so the agent sees minted buckets the user's
            # wallet still holds an NFT for (Studio hides those — they live
            # in My Minted NFTs instead — but the agent should still be able
            # to search them). Writes on those buckets are blocked by the
            # backend's assertEditable.
            resp = await http_client.get(
                f"{BACKEND_API_URL}/ai/profile",
                params={"includeMinted": "true"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            profiles = data if isinstance(data, list) else data.get("profiles", data.get("data", []))

            if not profiles:
                return "No memory buckets found. The user hasn't created any yet."

            owned_lines = []
            shared_lines = []
            for p in profiles:
                name = p.get("profileName", p.get("name", "Unnamed"))
                pid = p.get("id", "unknown")
                count = p.get("contextCount", p.get("context_count", 0))
                desc = p.get("description", "")
                role = p.get("role", "owner")
                is_owner = p.get("isOwner", True)

                line = f"- **{name}** (id: {pid}, {count} items)"
                if not is_owner:
                    line += f" [role: {role}]"
                    shared_by = p.get("sharedBy", {})
                    shared_by_name = shared_by.get("name") or shared_by.get("email") or shared_by.get("wallet") or "unknown"
                    line += f"\n  Shared by: {shared_by_name}"
                if desc:
                    line += f"\n  {desc}"

                if is_owner:
                    owned_lines.append(line)
                else:
                    shared_lines.append(line)

            parts = []
            if owned_lines:
                parts.append(f"**Your buckets ({len(owned_lines)}):**\n\n" + "\n".join(owned_lines))
            if shared_lines:
                parts.append(f"**Shared with you ({len(shared_lines)}):**\n\n" + "\n".join(shared_lines))

            return f"Found {len(profiles)} memory bucket(s):\n\n" + "\n\n".join(parts)

        except Exception as e:
            return f"Error fetching memory buckets: {str(e)}"

    @mcp_app.tool()
    async def list_items_in_memory_bucket(profile_id: str) -> str:
        """
        List all stored items (documents, files, notes) inside a specific memory bucket.

        Returns item metadata including title, description, source type, file name,
        size, and chunk count — but not the actual content.
        Use this to browse what's stored in a bucket before reading or searching
        specific items.

        Args:
            profile_id: The ID of the memory bucket (profile) to list items from.
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            resp = await http_client.get(
                f"{BACKEND_API_URL}/ai/context",
                params={"profileId": profile_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            contexts = data if isinstance(data, list) else data.get("contexts", data.get("data", []))

            if not contexts:
                return f"No items found in memory bucket {profile_id}."

            result_lines = []
            for c in contexts:
                ctx_id = c.get("contextId", "unknown")
                title = c.get("title", "Untitled")
                description = c.get("description", "")
                source_type = c.get("sourceType", "")
                original_file = c.get("originalFileName", "")
                content_size = c.get("contentSize", 0)
                vector_ids = c.get("vectorIds", [])
                chunk_count = len(vector_ids) if isinstance(vector_ids, list) else 0
                can_edit = c.get("canEdit")
                line = f"- **{title}** (contextId: {ctx_id})"
                details = []
                if source_type:
                    details.append(source_type)
                if original_file:
                    details.append(original_file)
                if chunk_count:
                    details.append(f"{chunk_count} chunks")
                if content_size:
                    details.append(f"{content_size} bytes")
                if can_edit is not None:
                    details.append("editable" if can_edit else "read-only")
                if details:
                    line += f" [{', '.join(details)}]"
                if description:
                    line += f"\n  Summary: {description}"
                result_lines.append(line)

            return f"Found {len(contexts)} item(s) in bucket {profile_id}:\n\n" + "\n".join(result_lines)

        except Exception as e:
            return f"Error listing items: {str(e)}"

    @mcp_app.tool()
    async def search_memory(
        query: str,
        profile_ids: Optional[List[str]] = None,
        k: int = 5,
    ) -> str:
        """
        Search across the user's stored memory using semantic vector similarity.

        Finds relevant content even when the query doesn't exactly match stored text.
        Searches all memory buckets by default, or specify bucket IDs to narrow scope.
        Searches across both owned and shared buckets automatically.
        Returns results grouped by memory bucket and context, with content previews
        and relevance scores.
        Use this to discover which contexts contain relevant information,
        then use read_context to get the full content.

        Args:
            query: The search query to find relevant memories.
            profile_ids: Optional list of memory bucket IDs to search within.
                         If not provided, searches across all buckets.
            k: Number of results to return (default: 5).
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            body: dict = {"query": query, "k": k}
            if profile_ids:
                body["profileIds"] = profile_ids

            resp = await http_client.post(
                f"{BACKEND_API_URL}/mcp/semantic-search",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
            if resp.status_code != 200:
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            results = data.get("results", [])

            if not results:
                return f"No results found for query: \"{query}\""

            # Group results by profileId → contextId
            buckets: dict = defaultdict(lambda: defaultdict(list))
            for r in results:
                metadata = r.get("metadata", {})
                pid = metadata.get("profileId", "unknown")
                ctx_id = metadata.get("contextId", metadata.get("fileId", "unknown"))
                title = metadata.get("title", "Untitled")
                chunk_index = metadata.get("chunkIndex", "?")
                score = r.get("similarity_score", 0)
                content = r.get("content", "").strip()
                # Truncate long content for preview
                preview = content[:300] + "..." if len(content) > 300 else content

                buckets[pid][(ctx_id, title)].append({
                    "chunk_index": chunk_index,
                    "score": score,
                    "preview": preview,
                })

            # Format grouped output
            output_lines = [f"Search results for \"{query}\" ({len(results)} matches across {len(buckets)} bucket(s)):"]

            for pid, contexts in buckets.items():
                output_lines.append(f"\n## Bucket (profileId: {pid})")
                for (ctx_id, title), chunks in contexts.items():
                    best_score = max(c["score"] for c in chunks)
                    output_lines.append(f"\n### {title} (contextId: {ctx_id}, {len(chunks)} match(es), best score: {best_score:.2f})")
                    for c in sorted(chunks, key=lambda x: x["score"], reverse=True):
                        output_lines.append(f"- [chunk {c['chunk_index']}, score: {c['score']:.2f}]: {c['preview']}")

            return "\n".join(output_lines)

        except Exception as e:
            return f"Error searching memory ({type(e).__name__}): {str(e)}"

    @mcp_app.tool()
    async def read_context(
        context_id: str,
        start_chunk: int = 0,
        limit: int = 0,
    ) -> str:
        """
        Read the full content of a specific stored memory item (document, file, or note).

        Returns the actual text content with pagination support for large documents.
        Use start_chunk and limit to read specific portions — defaults to returning
        all content.
        Use this after finding an item via list_items_in_memory_bucket or search_memory.

        Args:
            context_id: The ID of the context/item to read.
            start_chunk: Chunk index to start reading from (default: 0).
            limit: Maximum number of chunks to return (default: 0 = all chunks).
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            resp = await http_client.get(
                f"{BACKEND_API_URL}/ai/context/{context_id}/content",
                params={
                    "startChunk": start_chunk,
                    "limit": limit,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            title = data.get("title", "Untitled")
            total_chunks = data.get("totalChunks", 0)
            content = data.get("content", "")
            next_chunk = data.get("nextChunk")
            description = data.get("description", "")
            source_type = data.get("sourceType", "")
            original_file = data.get("originalFileName", "")

            # Build header
            header_parts = [f"**{title}**"]
            if original_file:
                header_parts.append(f"(file: {original_file})")
            if source_type:
                header_parts.append(f"[{source_type}]")
            header = " ".join(header_parts)

            meta = f"Chunks: {start_chunk}-{(next_chunk - 1) if next_chunk else total_chunks - 1} of {total_chunks}"
            if description:
                meta += f"\nDescription: {description}"

            result = f"{header}\n{meta}\n\n{content}"

            if next_chunk is not None:
                result += f"\n\n---\n_More content available. Call read_context with start_chunk={next_chunk} to continue._"

            return result

        except Exception as e:
            return f"Error reading context: {str(e)}"

    @mcp_app.tool()
    async def save_memory(
        profile_id: str,
        content: str,
        title: Optional[str] = None,
        source_platform: str = "unknown",
    ) -> str:
        """
        Save text content to a specific memory bucket.

        IMPORTANT — Before calling this tool:
        1. Call get_user_memory_buckets to list available buckets
        2. Ask the user which bucket to save to, or offer to create a new one
        3. If the user wants a new bucket, call create_memory_bucket first

        Args:
            profile_id: The ID of the memory bucket to save to (required).
            content: The text content to save.
            title: Optional custom title for this memory. If not provided, a title
                   is generated automatically from the content.
            source_platform: The name of this MCP client platform
                             (e.g. "claude", "chatgpt", "cursor").
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            body = {
                "profileId": profile_id,
                "context": content,
                "sourcePlatform": f"mcp-{source_platform}",
            }
            if title:
                body["title"] = title

            resp = await http_client.post(
                f"{BACKEND_API_URL}/ai/context/add-raw-context",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
            if resp.status_code != 200:
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            title = data.get("title", "Untitled")
            ctx_id = data.get("contextId", "unknown")
            desc = data.get("description", "")
            pid = data.get("profileId", profile_id)

            result = f"Memory saved successfully!\n\n"
            result += f"- **Title:** {title}\n"
            result += f"- **Context ID:** {ctx_id}\n"
            result += f"- **Bucket ID:** {pid}\n"
            if desc:
                result += f"- **Description:** {desc}\n"

            return result

        except Exception as e:
            return f"Error saving memory: {str(e)}"

    @mcp_app.tool()
    async def save_conversation(
        profile_id: str,
        chat_history: List[ChatMessage],
        title: Optional[str] = None,
        source_platform: str = "unknown",
    ) -> str:
        """
        Save a conversation (chat history) to a specific memory bucket.

        IMPORTANT — Before calling this tool:
        1. Call get_user_memory_buckets to list available buckets
        2. Ask the user which bucket to save to, or offer to create a new one
        3. If the user wants a new bucket, call create_memory_bucket first

        Args:
            profile_id: The ID of the memory bucket to save to (required).
            chat_history: List of chat messages, each with 'role' ("user" or "assistant")
                          and 'content' (the message text).
            title: Optional custom title for this conversation. If not provided, a title
                   is generated automatically from the conversation content.
            source_platform: The name of this MCP client platform
                             (e.g. "claude", "chatgpt", "cursor").
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            body = {
                "profileId": profile_id,
                "chatHistory": [msg.model_dump() for msg in chat_history],
                "platform": f"mcp-{source_platform}",
            }
            if title:
                body["title"] = title

            resp = await http_client.post(
                f"{BACKEND_API_URL}/ai/context/add-chat-context",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
            if resp.status_code != 200:
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            title = data.get("title", "Untitled")
            ctx_id = data.get("contextId", "unknown")
            desc = data.get("description", "")
            pid = data.get("profileId", profile_id)
            msg_count = len(chat_history)

            result = f"Conversation saved successfully!\n\n"
            result += f"- **Title:** {title}\n"
            result += f"- **Context ID:** {ctx_id}\n"
            result += f"- **Bucket ID:** {pid}\n"
            result += f"- **Messages:** {msg_count}\n"
            if desc:
                result += f"- **Description:** {desc}\n"

            return result

        except Exception as e:
            return f"Error saving conversation: {str(e)}"

    @mcp_app.tool()
    async def create_memory_bucket(
        bucket_name: str,
    ) -> str:
        """
        Create a new memory bucket (AI profile) for organizing saved content.

        Only use this when the user explicitly wants a new bucket.
        Always ask the user for confirmation before creating.

        Args:
            bucket_name: A descriptive name for the new bucket.
        """
        token = current_token.get()
        if not token:
            return "Error: Not authenticated"

        try:
            resp = await http_client.post(
                f"{BACKEND_API_URL}/ai/profile",
                json={"profileName": bucket_name},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code not in (200, 201):
                return f"Error: Backend API returned status {resp.status_code}: {resp.text}"

            data = resp.json()
            pid = data.get("id", "unknown")
            name = data.get("profileName", bucket_name)

            return f"Memory bucket created successfully!\n\n- **Name:** {name}\n- **Bucket ID:** {pid}\n\nYou can now use this ID with save_memory or save_conversation."

        except Exception as e:
            return f"Error creating memory bucket: {str(e)}"
