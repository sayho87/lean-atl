# lean-atlassian-mcp

mcp-atlassian보다 토큰을 아껴 먹는 로컬 Jira/Confluence MCP 서버.

## 왜 가벼운가 (실측)

MCP에서 LLM은 **세션마다 모든 도구 정의 스키마를 다시 전송**받는다. 도구 수와 스키마 크기가 그대로 토큰 비용이 된다.

| 설정 | 도구 수 | 스키마 전체 | ≈ 토큰 |
|---|---:|---:|---:|
| mcp-atlassian (기본, TOOLSETS 미설정) | 98 | 65,295 B | ~16,300 |
| mcp-atlassian `TOOLSETS=default` | 35 | 32,177 B | ~8,000 |
| mcp-atlassian `ENABLED_TOOLS` 4종만 | 5 | 7,292 B | ~1,800 |
| **lean-atlassian (이 서버)** | **10** | **1,394 B** | **~350** |

- 기본 상태 대비 **도구 91% 감소, 스키마 98% 감소 (~16,000 tokens/세션 절약)**
- mcp-atlassian을 최대한 꺼서 5개 도구만 써도, 이 서버는 9개 도구로 더 싸다 (스키마 평균 134B vs 그쪽 1,458B/tool)

### 토큰 절약 설계 원칙
1. **도구 10개** — mcp-atlassian의 98개 중 실제 쓰는 핵심만 (검색/조회/생성/전이/댓글/목록)
2. **docstring 한 줄, 파라미터 설명 최소** — 스키마가 평균 132B
3. **결과 축약** — 목록은 `limit` 캡, 설명/댓글/본문은 `max_chars`로 서버에서 절단
4. **Confluence HTML → plain text 변환** 후 반환 (원본 HTML 토큰 낭비 제거)
5. **Jira REST도 `fields=` 명시** — 와이어 응답 자체를 작게

## 설치 및 실행

```bash
uv venv .venv
uv pip install --python .venv/bin/python fastmcp httpx
```

### 환경변수
| 변수 | 설명 |
|---|---|
| `ATLASSIAN_SITE_URL` | 예: `https://your-domain.atlassian.net` |
| `ATLASSIAN_USER_EMAIL` | 계정 이메일 |
| `ATLASSIAN_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens |
| `CONFLUENCE_SPACES_FILTER` | 허용 스페이스만 (콤마 구분, 예: `DEV,PM`) |
| `JIRA_PROJECTS_FILTER` | 허용 프로젝트만 (콤마 구분, 예: `PROJ,TEST`) |
| `LEAN_MAX_RESULTS` | 목록 기본 캡 (기본 20) |
| `LEAN_BODY_CHARS` | 본문 기본 캡 (기본 8000) |

### 클라이언트 설정 예시 (Claude Desktop / Cursor)

```json
{
  "mcpServers": {
    "lean-atlassian": {
      "command": "/Users/howoomac/Projects/lean-atlassian-mcp/.venv/bin/python",
      "args": ["/Users/howoomac/Projects/lean-atlassian-mcp/lean_atlassian.py"],
      "env": {
        "ATLASSIAN_SITE_URL": "https://your-domain.atlassian.net",
        "ATLASSIAN_USER_EMAIL": "you@company.com",
        "ATLASSIAN_API_TOKEN": "your_token"
      }
    }
  }
}
```

## 도구 목록 (탐색 위주 9개)

| 도구 | 설명 |
|---|---|
| `jira_search` | JQL 검색 (핵심 필드만) |
| `jira_get` | 이슈 상세 (설명/댓글 절단) |
| `jira_my_tasks` | 내 미해결 이슈 |
| `jira_projects` | 프로젝트 목록 |
| `confluence_search` | CQL 검색 (`include_snippet` 옵션으로 본문 200자 미리보기) |
| `confluence_get` | 페이지 본문 (text, max_chars 절단) |
| `confluence_get_children` | 하위 페이지 목록 |
| `confluence_get_comments` | 페이지 댓글 목록 (본문 절단) |
| `confluence_space_tree` | 스페이스 페이지 트리 (max_depth, 제목만) |
| `confluence_spaces` | 스페이스 목록 |

### 문서 탐색 워크플로 예시
1. `confluence_spaces` → 어떤 스페이스가 있는지
2. `confluence_space_tree(space_key, max_depth=2)` → 스페이스 구조 파악
3. `confluence_search(cql, include_snippet=True)` → 원하는 문서 검색 (스니펫으로 판별)
4. `confluence_get(id)` → 문서 본문 읽기
5. `confluence_get_children(id)` → 하위 문서로 파고들기

## 테스트 (실 API 키 없이)

```bash
.venv/bin/python tests/mock_atlassian.py &   # 모의 서버 (127.0.0.1:8765)
.venv/bin/python tests/test_client.py        # 10개 도구 프로토콜 통합 테스트
.venv/bin/python tests/measure_schema.py     # 스키마 크기 벤치마크
```

## 참고: mcp-atlassian의 도구 온오프 (비교용)

mcp-atlassian도 필터링을 지원하지만 한계가 있다:
- `TOOLSETS=default` → 35개, `TOOLSETS=all` → 98개 (현재 기본값은 전체, v0.22.0부터 default로 변경 예정)
- `ENABLED_TOOLS=도구명1,도구명2` → 개별 허용 목록 (`TOOLSETS`와 교집합)
- Jira만 / Confluence만 설치 구성 가능, `READ_ONLY_MODE`, `JIRA_PROJECTS_FILTER` 등 범위 제한도 있음
- **함정**: 문서의 도구명 예시(`jira_search_issues` 등)가 실제 배포판과 다르다 — 이 버전 실제 이름은 `search`, `get_issue`, `get_page` 등. 이름이 안 맞으면 도구가 0개로 fail-closed된다.
- 남는 문제: 35개로 줄여도 스키마 자체가 무겁고(평균 ~700B/tool), 개별 도구 스키마의 긴 설명이 그대로 전송된다.
