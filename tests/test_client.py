"""MCP 프로토콜 계층 통합 테스트 — 인메모리 클라이언트로 10개 도구 전부 호출."""
import asyncio
import json
import os
import sys

os.environ["ATLASSIAN_SITE_URL"] = "http://127.0.0.1:8765"
os.environ["ATLASSIAN_USER_EMAIL"] = "test@test.com"
os.environ["ATLASSIAN_API_TOKEN"] = "fake"

sys.path.insert(0, ".")
import lean_atl  # noqa: E402
from fastmcp import Client  # noqa: E402


async def main() -> None:
    async with Client(lean_atl.mcp) as c:
        tools = await c.list_tools()
        print(f"도구 수: {len(tools)}")
        calls = [
            ("jira_search", {"jql": "project = TEST", "limit": 5}),
            ("jira_get", {"key": "TEST-1", "max_chars": 50}),
            ("jira_my_tasks", {}),
            ("jira_projects", {}),
            ("confluence_search", {"cql": 'text ~ "릴리스"', "limit": 5}),
            ("confluence_search", {"cql": 'text ~ "릴리스"', "limit": 5, "include_snippet": True}),
            ("confluence_get", {"id": "12345", "max_chars": 120}),
            ("confluence_get_children", {"id": "12345"}),
            ("confluence_get_comments", {"id": "12345", "max_chars": 500}),
            ("confluence_space_tree", {"space_key": "DEV", "max_depth": 3}),
            ("confluence_spaces", {}),
        ]
        for name, args in calls:
            try:
                r = await c.call_tool(name, args)
                data = getattr(r, "data", r)
                if not isinstance(data, str):
                    data = json.dumps(data, ensure_ascii=False)
                txt = data[:700] if data.startswith("[") else data[:900]
                print(f"\n✓ {name} {json.dumps(args, ensure_ascii=False)}")
                print(txt)
            except Exception as e:  # noqa: BLE001
                print(f"\n✗ {name}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
