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

from app.agent.tools import ToolApproval, ToolDefinition
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

            async def prepare(
                arguments, context, *, server_name=server.name, url=server.url, name=remote_name
            ):
                context.raise_if_cancelled()
                return ToolApproval(
                    query=(
                        f"确认调用 MCP 写工具 {server_name}/{name}？\n"
                        f"服务地址：{url}\n"
                        f"参数：{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}\n"
                        "此操作可能修改远端数据；结果未知时不会自动重试。"
                    ),
                    # Bind approval to the configured destination across restarts.
                    payload={"url": url, "name": name, "arguments": arguments},
                )

            async def execute(payload, context, *, url=server.url, name=remote_name, call=invoke):
                if payload.get("url") != url or payload.get("name") != name:
                    return {
                        "ok": False,
                        "write_state": "failed",
                        "error": {"type": "McpTargetChanged", "message": "MCP target changed."},
                    }
                return await call(payload["arguments"], context)

            options = dict(
                name=local_name,
                description=remote.description or f"MCP {server.name}: {remote_name}",
                parameters=remote.inputSchema,
                strict=False,
                read_only=read_only,
                group=f"MCP {server.name}",
                keywords=(server.name, remote_name),
            )
            definitions.append(
                ToolDefinition(handler=invoke, effect="read", **options)
                if read_only
                else ToolDefinition.approved(
                    prepare=prepare, execute=execute, approval_replay_safe=False, **options
                )
            )
    return definitions
