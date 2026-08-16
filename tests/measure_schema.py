"""도구 정의 스키마 토큰 비교: lean-atlassian vs mcp-atlassian.

도구 스키마 JSON 바이트를 합산해 LLM이 매 세션에 지불하는
도구 정의 비용의 근사치를 낸다 (토큰 ≈ bytes / 4).
"""
import asyncio
import json
import os
import sys

from fastmcp import FastMCP


async def schema_bytes(server: FastMCP) -> tuple[int, int, float]:
    """(도구 수, 전체 스키마 바이트, 도구당 평균 바이트)"""
    tools = await server.list_tools()
    total = 0
    for t in tools:
        schema = t.parameters
        total += len(json.dumps(schema, separators=(",", ":")).encode("utf-8"))
    return len(tools), total, total / max(len(tools), 1)


def report(label: str, n: int, b: int) -> None:
    print(f"[{label}] tools={n:>3} schema_total={b:>9,}B  ≈ {b // 4:>7,} tokens  "
          f"(avg {b // max(n, 1):>4,}B/tool)")


async def main() -> None:
    # 1) lean-atlassian (env 없이 import 가능)
    sys.path.insert(0, ".")
    import lean_atlassian  # noqa: F401
    n1, b1, _ = await schema_bytes(lean_atlassian.mcp)
    report("lean-atlassian", n1, b1)

    # 2) mcp-atlassian — Jira/Confluence 서버 분리, 전부 vs TOOLSETS=default
    from mcp_atlassian.servers.confluence import confluence_mcp
    from mcp_atlassian.servers.jira import jira_mcp

    os.environ.pop("TOOLSETS", None)
    os.environ.pop("ENABLED_TOOLS", None)
    nj, bj, _ = await schema_bytes(jira_mcp)
    nc, bc, _ = await schema_bytes(confluence_mcp)
    report("mcp-atlassian jira", nj, bj)
    report("mcp-atlassian conf ", nc, bc)
    n2, b2 = nj + nc, bj + bc
    report("mcp-atlassian 합계", n2, b2)

    # 3) TOOLSETS=default 제한 시
    os.environ["TOOLSETS"] = "default"
    nj2, bj2, _ = await schema_bytes(jira_mcp)
    nc2, bc2, _ = await schema_bytes(confluence_mcp)
    report("mcp-atlassian TOOLSETS=default", nj2 + nc2, bj2 + bc2)

    print(f"\n비교 (전부 기준): 도구 {n2}→{n1} ({(1 - n1 / n2) * 100:.0f}% 감소), "
          f"스키마 {b2:,}B→{b1:,}B ({(1 - b1 / b2) * 100:.0f}% 감소) "
          f"≈ 매 세션 {b2 // 4 - b1 // 4:,} tokens 절약")
    print(f"비교 (default 제한 기준): {bj2 + bc2:,}B→{b1:,}B "
          f"({(1 - b1 / (bj2 + bc2)) * 100:.0f}% 감소)")


if __name__ == "__main__":
    asyncio.run(main())
