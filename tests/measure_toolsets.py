"""mcp-atlassian TOOLSETS/ENABLED_TOOLS 실제 적용 측정 (패키지 자체 필터 사용)."""
import asyncio
import json
import os
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "default"
if mode == "default":
    os.environ["TOOLSETS"] = "default"
elif mode == "enabled":
    os.environ["ENABLED_TOOLS"] = "get_issue,search,get_page,get_comments"

from fastmcp import FastMCP  # noqa: E402
from mcp_atlassian.servers.confluence import confluence_mcp  # noqa: E402
from mcp_atlassian.servers.jira import jira_mcp  # noqa: E402
from mcp_atlassian.utils.tools import get_enabled_tools, should_include_tool  # noqa: E402
from mcp_atlassian.utils.toolsets import get_enabled_toolsets, should_include_tool_by_toolset  # noqa: E402


def tool_tags(t) -> set[str]:
    return set(getattr(t, "tags", None) or getattr(t, "metadata", None) or {})


async def mb(server: FastMCP) -> tuple[int, int, list[str]]:
    tools = await server.list_tools()
    enabled_toolsets = get_enabled_toolsets()
    enabled_tools = get_enabled_tools()
    kept = []
    total = 0
    for t in tools:
        if not should_include_tool_by_toolset(tool_tags(t), enabled_toolsets):
            continue
        if not should_include_tool(t.name, enabled_tools):
            continue
        kept.append(t.name)
        total += len(json.dumps(t.parameters, separators=(",", ":")).encode())
    return len(kept), total, kept


async def main() -> None:
    nj, bj, names_j = await mb(jira_mcp)
    nc, bc, names_c = await mb(confluence_mcp)
    n, b = nj + nc, bj + bc
    print(f"[{mode}] tools={n} schema_total={b:,}B ≈ {b // 4:,} tokens")
    if mode == "enabled":
        print("남은 도구:", sorted(names_j + names_c))


asyncio.run(main())
