"""필터 변수(CONFLUENCE_SPACES_FILTER / JIRA_PROJECTS_FILTER) 검증.

1) 순수 함수 유닛 테스트 — 모듈 리로드로 env 변화 반영
2) mock 서버 통합 테스트 — 필터 켠 상태에서 도구 호출
"""
import asyncio
import importlib
import os
import sys

sys.path.insert(0, ".")
import lean_atlassian as la
from fastmcp import Client

fails = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'✓' if ok else '✗'} {label}: {got}")
    if not ok:
        fails.append(label)


def unit() -> None:
    # 필터 미설정 → 그대로
    check("필터없음 conf", la._filter_conf([{"key": "DEV"}, {"key": "PM"}]), [{"key": "DEV"}, {"key": "PM"}])
    check("필터없음 jira", la._filter_proj([{"key": "PROJ"}, {"key": "TEST"}]), [{"key": "PROJ"}, {"key": "TEST"}])
    # CONF 필터 설정 후 reload
    os.environ["CONFLUENCE_SPACES_FILTER"] = "DEV"
    la_re = importlib.reload(la)
    check("CONF=DEV", la_re._filter_conf([{"key": "DEV"}, {"key": "PM"}]), [{"key": "DEV"}])
    # JIRA 필터 설정 후 reload
    os.environ["JIRA_PROJECTS_FILTER"] = "PROJ,DEV"
    la_re2 = importlib.reload(la_re)
    check("JIRA=PROJ,DEV", la_re2._filter_proj([{"key": "PROJ"}, {"key": "TEST"}]), [{"key": "PROJ"}])


async def integration() -> None:
    os.environ["ATLASSIAN_SITE_URL"] = "http://127.0.0.1:8765"
    os.environ["ATLASSIAN_USER_EMAIL"] = "test@test.com"
    os.environ["ATLASSIAN_API_TOKEN"] = "fake"
    os.environ["CONFLUENCE_SPACES_FILTER"] = "DEV"
    os.environ["JIRA_PROJECTS_FILTER"] = "PROJ"
    m = importlib.reload(la).mcp
    async with Client(m) as c:
        r = await c.call_tool("confluence_spaces", {})
        data = getattr(r, "data", r)
        check("confluence_spaces 필터", data, [{"key": "DEV", "name": "개발팀 스페이스", "type": "global"}])
        r = await c.call_tool("jira_projects", {})
        data = getattr(r, "data", r)
        check("jira_projects 필터", data, [{"key": "PROJ", "name": "프로젝트 알파"}])
        r = await c.call_tool("confluence_space_tree", {"space_key": "PM"})
        data = getattr(r, "data", r)
        check("space_tree 차단", data.get("error") is not None, True)
        r = await c.call_tool("confluence_search", {"cql": 'text ~ "릴리스"'})
        data = getattr(r, "data", r)
        keys = [x.get("space") for x in data]
        check("search 필터(DEV만)", keys, ["DEV", "DEV"])


async def main() -> None:
    unit()
    await integration()
    print(f"\n{'전부 통과' if not fails else f'실패: {fails}'}")


if __name__ == "__main__":
    asyncio.run(main())
