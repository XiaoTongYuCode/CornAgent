"""Allowlisted remote MCP tools exposed through CornAgent's normal tool lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

from app.agent.tools import ToolDefinition
from app.settings import AgentMcpServer


@asynccontextmanager
async def _session(url: str):
    async with (
        streamable_http_client(url) as (reader, writer, _),
        ClientSession(reader, writer) as client,
    ):
        await client.initialize()
        yield client


async def discover_mcp_tools(servers: tuple[AgentMcpServer, ...]) -> list[ToolDefinition]:
    """Freeze remote schemas at service startup; fail startup on missing allowlisted tools."""

    definitions: list[ToolDefinition] = []
    names: set[str] = set()
    for server in servers:
        offered = {}
        seen_cursors: set[str] = set()
        async with asyncio.timeout(15):
            async with _session(server.url) as client:
                response = await client.list_tools()
                while True:
                    offered.update((item.name, item) for item in response.tools)
                    cursor = response.nextCursor
                    if cursor is None:
                        break
                    if cursor in seen_cursors:
                        raise ValueError(f"MCP server {server.name!r} repeated a tools cursor")
                    seen_cursors.add(cursor)
                    response = await client.list_tools(params=PaginatedRequestParams(cursor=cursor))
        missing = set(server.tools) - offered.keys()
        if missing:
            raise ValueError(
                f"MCP server {server.name!r} lacks allowlisted tools: {sorted(missing)}"
            )
        for remote_name in server.tools:
            remote = offered[remote_name]
            local_name = f"mcp_{server.name}_{re.sub(r'[^a-zA-Z0-9_]', '_', remote_name)}"
            if len(local_name) > 64:
                digest = hashlib.sha256(local_name.encode()).hexdigest()[:8]
                local_name = f"{local_name[:55]}_{digest}"
            if local_name in names:
                raise ValueError(f"Duplicate MCP tool name: {local_name}")
            names.add(local_name)
            read_only = remote_name in server.read_only_tools

            async def invoke(
                arguments, context, *, url=server.url, name=remote_name, read=read_only
            ):
                context.raise_if_cancelled()
                try:
                    async with asyncio.timeout(30):
                        async with _session(url) as client:
                            result = await client.call_tool(name, arguments=arguments)
                except Exception:
                    return {
                        "ok": False,
                        "write_state": "failed" if read else "unknown",
                        "error": {
                            "type": "McpCallFailed",
                            "message": "MCP tool result unavailable.",
                        },
                    }
                # Never store binary/image blocks in the conversation or tool receipts.
                content = [
                    item.text[:65536]
                    for item in result.content
                    if getattr(item, "type", None) == "text"
                ]
                structured = result.structuredContent
                structured_too_large = (
                    structured is not None
                    and len(json.dumps(structured, ensure_ascii=False, default=str)) > 65536
                )
                return {
                    "ok": not result.isError,
                    **({"write_state": "unknown"} if not read else {}),
                    "content": content[:8],
                    "source_truncated": len(content) > 8
                    or structured_too_large
                    or any(
                        len(item.text) > 65536
                        for item in result.content
                        if getattr(item, "type", None) == "text"
                    ),
                    **(
                        {"structured": structured}
                        if structured is not None and not structured_too_large
                        else {}
                    ),
                }

            definitions.append(
                ToolDefinition(
                    name=local_name,
                    description=remote.description or f"MCP {server.name}: {remote_name}",
                    parameters=remote.inputSchema,
                    strict=False,
                    handler=invoke,
                    read_only=read_only,
                    effect="read" if read_only else "write",
                    group=f"MCP {server.name}",
                    keywords=(server.name, remote_name),
                )
            )
    return definitions
