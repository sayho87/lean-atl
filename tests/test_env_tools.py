"""환경별 도구 등록 검증.

1) Jira URL 미설정(Confluence 전용) → Jira 도구 4개가 목록에서 제외 (6개만 노출)
2) Jira URL 설정 → 10개 전부 노출
"""
import asyncio
import importlib
import os
import sys

sys.path.insert(0, ".")
import lean_atl as la
from fastmcp import Client

fails = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'✓' if ok else '✗'} {label}: {got}")
    if not ok:
        fails.append(label)


def _clear_jira_env() -> None:
    for k in ("ATLASSIAN_SITE_URL", "JIRA_URL", "JIRA_USERNAME",
              "JIRA_API_TOKEN", "JIRA_PERSONAL_TOKEN"):
        os.environ.pop(k, None)


async def jira_disabled() -> None:
    """Confluence 전용: jira 도구 호출 자체가 불가능해야 한다."""
    _clear_jira_env()
    os.environ["CONFLUENCE_URL"] = "http://127.0.0.1:8765"
    os.environ["CONFLUENCE_USERNAME"] = ""
    os.environ["CONFLUENCE_API_TOKEN"] = ""
    os.environ["CONFLUENCE_PERSONAL_TOKEN"] = "conf-pat"
    m = importlib.reload(la).mcp
    async with Client(m) as c:
        tools = await c.list_tools()
        names = sorted(t.name for t in tools)
        check("Jira 미설정 도구 6개", names,
              ["confluence_get", "confluence_get_children", "confluence_get_comments",
               "confluence_search", "confluence_space_tree", "confluence_spaces"])
        try:
            await c.call_tool("jira_search", {"jql": "project = TEST"})
            check("jira_search 목록에 없음", "호출됨(실패)", "호출 불가")
        except Exception:
            check("jira_search 목록에 없음", "호출 불가", "호출 불가")
        # Confluence 도구는 정상 동작
        r = await c.call_tool("confluence_spaces", {})
        data = getattr(r, "data", r)
        check("Confluence 전용 동작", len(data), 20)


async def jira_enabled() -> None:
    """Jira 설정 시 10개 전부 노출."""
    os.environ["ATLASSIAN_SITE_URL"] = "http://127.0.0.1:8765"
    os.environ["ATLASSIAN_USER_EMAIL"] = "test@test.com"
    os.environ["ATLASSIAN_API_TOKEN"] = "fake"
    m = importlib.reload(la).mcp
    async with Client(m) as c:
        tools = await c.list_tools()
        check("Jira 설정 도구 10개", len(tools), 10)


async def main() -> None:
    await jira_disabled()
    await jira_enabled()
    print(f"\n{'전부 통과' if not fails else f'실패: {fails}'}")


if __name__ == "__main__":
    asyncio.run(main())