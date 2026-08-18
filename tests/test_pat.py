"""PAT(Server/DC) 모드 검증: Bearer 헤더, Jira v2 경로 전환, SSL 플래그."""
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


def unit() -> None:
    os.environ["JIRA_URL"] = "http://127.0.0.1:8765"
    os.environ["JIRA_USERNAME"] = ""
    os.environ["JIRA_API_TOKEN"] = ""
    os.environ["JIRA_PERSONAL_TOKEN"] = "jira-pat"
    os.environ["JIRA_SSL_VERIFY"] = "false"
    os.environ["CONFLUENCE_URL"] = "http://127.0.0.1:8765"
    os.environ["CONFLUENCE_USERNAME"] = ""
    os.environ["CONFLUENCE_API_TOKEN"] = ""
    os.environ["CONFLUENCE_PERSONAL_TOKEN"] = "conf-pat"
    m = importlib.reload(la)

    check("JIRA_PAT 인식", m.JIRA_PAT, "jira-pat")
    check("JIRA_SSL=false 파싱", m.JIRA_SSL, False)
    check("CONF_PAT 인식", m.CONF_PAT, "conf-pat")
    jc = m.jira_client()
    check("Jira Bearer 헤더", jc.headers.get("Authorization"), "Bearer jira-pat")
    cc = m.conf_client()
    check("Conf Bearer 헤더", cc.headers.get("Authorization"), "Bearer conf-pat")
    # v2 경로 전환은 integration에서 실제 호출로 검증 (mock의 /rest/api/2 라우트)


async def integration() -> None:
    m = importlib.reload(la)
    async with Client(m.mcp) as c:
        r = await c.call_tool("jira_projects", {})
        data = getattr(r, "data", r)
        check("jira_projects v2 배열", data,
              [{"key": "PROJ", "name": "프로젝트 알파"},
               {"key": "TEST", "name": "테스트 프로젝트"}])
        r = await c.call_tool("jira_search", {"jql": "project = TEST"})
        data = getattr(r, "data", r)
        check("jira_search v2 경로 동작", data[0]["key"], "TEST-1")
        r = await c.call_tool("jira_get", {"key": "TEST-1", "max_chars": 200})
        data = getattr(r, "data", r)
        check("DC 위키 본문", "위키" in (data.get("description") or ""), True)
        check("DC 위키 댓글", data.get("comments_recent")[0]["body"], "수정 진행 중입니다.")
        r = await c.call_tool("confluence_spaces", {})
        data = getattr(r, "data", r)
        check("conf PAT 스페이스 목록", len(data), 20)  # 기본 limit 캡 20


async def main() -> None:
    unit()
    await integration()
    print(f"\n{'전부 통과' if not fails else f'실패: {fails}'}")


if __name__ == "__main__":
    asyncio.run(main())
