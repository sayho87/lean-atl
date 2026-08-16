"""실서버 스모크 테스트 — 실제 Confluence/Jira에 연결해 도구 검증.

mock이 아닌 실제 서버로 각 도구를 한 번씩 호출해, 인증·연결·응답 구조를
한 번에 확인한다. 실패 시 원인(인증/SSL/필드 구조)을 구분해 보여준다.

사용법 (실서버 접근 가능한 환경에서):
  export CONFLUENCE_URL=https://confluence.your-domain.com
  export CONFLUENCE_PERSONAL_TOKEN=발급받은PAT
  export CONFLUENCE_SSL_VERIFY=false        # 사내 자체 인증서일 때만
  # Jira도 쓴다면:
  export JIRA_URL=https://jira.your-domain.com
  export JIRA_PERSONAL_TOKEN=발급받은PAT
  .venv/bin/python tests/smoke_live.py
"""
import os
import sys

sys.path.insert(0, ".")
import lean_atl as la  # noqa: E402

PASS, FAIL = [], []


def step(name: str, fn):
    try:
        r = fn()
        PASS.append(name)
        print(f"  ✓ {name}")
        return r
    except Exception as e:  # noqa: BLE001
        FAIL.append(name)
        print(f"  ✗ {name}  → {type(e).__name__}: {str(e)[:160]}")
        return None


def main() -> None:
    print("== lean-atl 실서버 스모크 테스트 ==")
    print(f"Confluence: {la.CONF_URL or '(미설정)'} / Jira: {la.JIRA_URL or '(미설정)'}")
    if not la.CONF_URL and not la.JIRA_URL:
        print("URL이 없습니다. 환경변수를 설정하세요 (위 주석 참고).")
        sys.exit(2)

    if la.CONF_URL:
        print("\n[Confluence]")
        spaces = step("confluence_spaces — 인증·연결 확인", la.confluence_spaces)
        if spaces:
            print("   스페이스:", [s.get("key") for s in spaces][:5])
        if spaces:
            step("confluence_search — CQL 검색", lambda: la.confluence_search("type = page"))
        first_key = spaces[0].get("key") if spaces else None
        if first_key:
            step("confluence_space_tree — 스페이스 구조",
                 lambda: la.confluence_space_tree(str(first_key)))

    if la.JIRA_URL:
        print("\n[Jira]")
        projs = step("jira_projects — 인증·연결 확인", la.jira_projects)
        if projs:
            print("   프로젝트:", [p.get("key") for p in projs][:5])
        step("jira_search — JQL 검색", lambda: la.jira_search("resolution = unresolved", limit=3))

    print(f"\n결과: 통과 {len(PASS)} / 실패 {len(FAIL)}")
    if FAIL:
        print("실패 항목:", ", ".join(FAIL))
        print("→ 인증 오류(401/403)면 PAT 확인, SSL 오류면 *_SSL_VERIFY=false,"
              " 필드 구조 오류면 응답을 공유해 주세요.")
        sys.exit(1)
    print("→ 모든 도구가 실제 서버에서 동작합니다.")


if __name__ == "__main__":
    main()
