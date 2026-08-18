"""필터 변수(CONFLUENCE_SPACES_FILTER / JIRA_PROJECTS_FILTER) 검증.

1) 순수 함수 유닛 테스트 — 모듈 리로드로 env 변화 반영
2) mock 서버 통합 테스트 — 필터 켠 상태에서 도구 호출
"""
import asyncio
import importlib
import os
import sys

sys.path.insert(0, ".")
import lean_atl as la
from fastmcp import Client
from fastmcp.exceptions import ToolError

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
    # 대소문자 무시: 응답 키가 소문자여도 필터(대문자 설정)와 매칭
    check("CONF 대소문자 무시", la_re._filter_conf([{"key": "dev"}, {"key": "PM"}]), [{"key": "dev"}])
    check("space_denied 대소문자", la_re._space_denied("dev"), None)
    check("space_denied 거절", (la_re._space_denied("PM") or {}).get("error") is not None, True)
    # JIRA 필터 설정 후 reload
    os.environ["JIRA_PROJECTS_FILTER"] = "PROJ,DEV"
    la_re2 = importlib.reload(la_re)
    check("JIRA=PROJ,DEV", la_re2._filter_proj([{"key": "PROJ"}, {"key": "TEST"}]), [{"key": "PROJ"}])
    check("JQL AND", la_re2._and_jql_projects("text ~ foo ORDER BY created"),
          '(text ~ foo) AND project IN ("DEV", "PROJ") ORDER BY created')
    check("한도 음수", la_re2._clamp_limit(-1), la_re2.MAX_RESULTS)
    check("한도 과다", la_re2._clamp_limit(999999), la_re2.MAX_RESULTS)
    check("본문 과다", la_re2._clamp_chars(10_000_000), la_re2.BODY_CHARS)
    check("cql 키 미인용", la_re2._quote_cql_ident("ENMeProduct"), "ENMeProduct")
    check("cql 개인공간 인용", la_re2._quote_cql_ident("~user"), '"~user"')
    check("일반문장→siteSearch", la_re2._search_queries("인당발행갯수")[0],
          'siteSearch ~ "인당발행갯수"')
    check("CQL 그대로", la_re2._search_queries('text ~ "foo"'), ['text ~ "foo"'])
    check("이슈본문 문자열", la_re2._issue_text("h3. 위키\n본문", 8000), "h3. 위키\n본문")
    check("이슈본문 없음", la_re2._issue_text(None, 8000), "")
    check("내 이슈 JQL",
          la_re2._jql_queries("내 이슈")[0],
          "assignee = currentUser() AND resolution = unresolved")
    check("일반이슈 JQL", la_re2._jql_queries("로그인 오류")[0], 'text ~ "로그인 오류"')
    q_week = la_re2._search_queries("내 이름으로 주간보고 모아줘")
    check("주간보고 currentUser",
          "siteSearch" in q_week[0] and "currentUser" in q_week[0] and "주간보고" in q_week[0], True)
    check("필터 빈공간키 유지",
          la_re._filter_conf([{"title": "주간", "space": None}]),
          [{"title": "주간", "space": None}])
    check("displayUrl 공간키",
          la_re._space_key_from_hit(
              {"resultGlobalContainer": {"displayUrl": "/display/ENMeProduct/x"}},
              {"id": "1", "type": "page", "title": "t"}),
          "ENMeProduct")
    check("spaces경로 공간키",
          la_re._norm_search_hit({
              "content": {"id": "9", "type": "page", "title": "주간보고"},
              "resultGlobalContainer": {"displayUrl": "/spaces/productplan/pages/9"},
          })["space"],
          "productplan")


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
        try:
            r = await c.call_tool("jira_get", {"key": "TEST-1"})
            msg = str(getattr(r, "data", r))
        except ToolError as e:
            msg = str(e)
        check("jira_get 범위 밖 차단", "없는 프로젝트" in msg, True)
        r = await c.call_tool("confluence_get", {"id": "12345"})
        check("confluence_get DEV 허용",
              getattr(r, "data", r).get("id"), "12345")


async def integration_pagination() -> None:
    """실서버 재현: 스페이스 120개, 필터 키가 뒤쪽(100번 이후)에 존재 → 페이지네이션으로 전체 조회 후 매칭."""
    os.environ["ATLASSIAN_SITE_URL"] = "http://127.0.0.1:8765"
    os.environ["ATLASSIAN_USER_EMAIL"] = "test@test.com"
    os.environ["ATLASSIAN_API_TOKEN"] = "fake"
    os.environ["CONFLUENCE_SPACES_FILTER"] = "PromotionCell,ENMeProduct,productplan"
    os.environ["JIRA_PROJECTS_FILTER"] = ""
    m = importlib.reload(la).mcp
    async with Client(m) as c:
        r = await c.call_tool("confluence_spaces", {})
        data = getattr(r, "data", r)
        got_keys = sorted(x["key"] for x in data)
        check("120개+뒤쪽 필터 3개 매칭",
              got_keys, ["ENMeProduct", "PromotionCell", "productplan"])
        # 대소문자가 달라도 매칭 (casefold)
        os.environ["CONFLUENCE_SPACES_FILTER"] = "promotioncell,enmeproduct,PROMOTIONCELL"
        m2 = importlib.reload(la).mcp
        async with Client(m2) as c2:
            r = await c2.call_tool("confluence_spaces", {})
            data = getattr(r, "data", r)
            got_keys2 = sorted(x["key"] for x in data)
            check("대소문자 혼합 필터 매칭",
                  got_keys2, ["ENMeProduct", "PromotionCell"])
        # 필터 미설정 → limit 캡 유지 (기본 20)
        os.environ["CONFLUENCE_SPACES_FILTER"] = ""
        m3 = importlib.reload(la).mcp
        async with Client(m3) as c3:
            r = await c3.call_tool("confluence_spaces", {})
            data = getattr(r, "data", r)
            check("필터없음 기본 20개", len(data), 20)
            check("필터없음 첫 키", data[0]["key"], "DEV")
            r = await c3.call_tool("confluence_spaces", {"limit": 100})
            data = getattr(r, "data", r)
            check("필터없음 limit 100", len(data), 100)

        # 목록 API에 없고 spaceKey 조회도 404인 공간 — CQL로는 열림
        os.environ["CONFLUENCE_SPACES_FILTER"] = "HIDDENDOC"
        m4 = importlib.reload(la).mcp
        async with Client(m4) as c4:
            r = await c4.call_tool("confluence_spaces", {})
            data = getattr(r, "data", r)
            check("목록에 없는 키를 CQL로 확인",
                  [(x.get("key"), x.get("name"), x.get("error")) for x in data],
                  [("HIDDENDOC", "숨은 스페이스", None)])
            r = await c4.call_tool("confluence_space_tree", {"space_key": "HIDDENDOC"})
            data = getattr(r, "data", r)
            check("spaceKey 404 → CQL 트리",
                  (data.get("space"), data.get("page_count"),
                   data.get("roots", [{}])[0].get("title")),
                  ("HIDDENDOC", 1, "숨은 문서"))

        os.environ["CONFLUENCE_SPACES_FILTER"] = ""
        m5 = importlib.reload(la).mcp
        async with Client(m5) as c5:
            r = await c5.call_tool("confluence_search", {"cql": "다운로드 쿠폰안"})
            data = getattr(r, "data", r)
            check("일반문장 siteSearch",
                  (data[0].get("id"), data[0].get("space"), data[0].get("title")),
                  ("182209768", "productplan", "다운로드 쿠폰안"))
            r = await c5.call_tool("confluence_search", {"cql": "없는고유어xyz123"})
            data = getattr(r, "data", r)
            # siteSearch mock only matches siteSearch token; fallback content/search
            # still returns DEV pages for non-HIDDENDOC CQL. 고유어는 CQL 연산자 없음
            # → siteSearch 히트(다운로드 쿠폰안). 0건 진단은 CQL 경로로 확인.
            r = await c5.call_tool("confluence_search",
                                   {"cql": 'text ~ "없는고유어xyz123"'})
            data = getattr(r, "data", r)
            check("CQL 0건 진단", data[0].get("error"), "검색 0건")
            r = await c5.call_tool("confluence_search",
                                   {"cql": "내 이름으로 주간보고 모아줘"})
            data = getattr(r, "data", r)
            check("내 주간보고", 
                  (data[0].get("id"), data[0].get("title")),
                  ("70001", "8월 3주 주간보고"))
            # DC가 excerpt 파라미터를 거부해도 재시도로 검색 성공해야 한다
            r = await c5.call_tool("confluence_search", {"cql": "다운로드 쿠폰"})
            data = getattr(r, "data", r)
            check("excerpt 거부 후 재시도",
                  (data[0].get("id"), data[0].get("space")),
                  ("182209768", "productplan"))
            # 범위 좁히기: space_key + under_page(문서 하위 포함)
            r = await c5.call_tool("confluence_search",
                                   {"cql": 'text ~ "없는고유어xyz123"',
                                    "space_key": "DEV", "under_page": "12345"})
            data = getattr(r, "data", r)
            check("space_key 하위포함 AND 구성",
                  ("space = DEV" in (data[0].get("cql") or "")
                   and "ancestor = 12345" in (data[0].get("cql") or "")), True)
            # 이름/제목으로 범위 좁히기 — 자동 해석
            r = await c5.call_tool("confluence_search",
                                   {"cql": 'text ~ "없는고유어xyz123"',
                                    "space_key": "개발팀 스페이스",
                                    "under_page": "개발 가이드"})
            data = getattr(r, "data", r)
            check("이름·제목 자동 해석",
                  ("space = DEV" in (data[0].get("cql") or "")
                   and "ancestor = 20001" in (data[0].get("cql") or "")), True)
            # A: 검색 기본 include_snippet=True → snippet 필드 포함
            r = await c5.call_tool("confluence_search", {"cql": "다운로드 쿠폰"})
            data = getattr(r, "data", r)
            check("기본 snippet 포함", "snippet" in (data[0] or {}), True)
            # E: 검색 기본 limit 10 캡
            check("검색 기본 limit 10",
                  la.confluence_search.__defaults__ and
                  la.confluence_search.__defaults__[0] == 10, True)
            check("children 기본 limit 10",
                  la.confluence_get_children.__defaults__[0] == 10, True)
            # B: 재조회 방지 — 같은 문서 본문을 두 번 읽지 않는다
            r = await c5.call_tool("confluence_get", {"id": "12345", "max_chars": 200})
            data = getattr(r, "data", r)
            check("첫 조회 본문 있음", bool(data.get("body")), True)
            r = await c5.call_tool("confluence_get", {"id": "12345", "max_chars": 200})
            data = getattr(r, "data", r)
            check("재조회 본문 없음", data.get("already_read") is True
                  and not data.get("body"), True)


async def main() -> None:
    unit()
    await integration()
    await integration_pagination()
    print(f"\n{'전부 통과' if not fails else f'실패: {fails}'}")


if __name__ == "__main__":
    asyncio.run(main())
