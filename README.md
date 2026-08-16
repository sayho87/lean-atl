# lean-atl

mcp-atlassian보다 토큰을 절약하는 로컬 Jira/Confluence MCP 서버.

## 왜 가벼운가 (실측)

MCP에서 LLM은 **세션마다 모든 도구 정의 스키마를 다시 전송**받는다. 도구 수와 스키마 크기가 그대로 토큰 비용이 된다.

| 설정 | 도구 수 | 스키마 전체 | ≈ 토큰 |
|---|---:|---:|---:|
| mcp-atlassian (기본, TOOLSETS 미설정) | 98 | 65,295 B | ~16,300 |
| mcp-atlassian `TOOLSETS=default` | 35 | 32,177 B | ~8,000 |
| mcp-atlassian `ENABLED_TOOLS` 4종만 | 5 | 7,292 B | ~1,800 |
| **lean-atl (이 서버)** | **10** | **1,394 B** | **~350** |

- 기본 상태 대비 **도구 91% 감소, 스키마 98% 감소 (세션당 약 16,000토큰 절약)**
- mcp-atlassian을 최소 구성(5개 도구)으로 줄여도, 이 서버는 10개 도구로 더 가볍다 (스키마 평균 139B vs 1,458B)

### 토큰 절약 설계 원칙
1. **도구 10개** — mcp-atlassian의 98개 중 실제 쓰는 핵심만 (검색/조회/댓글/목록)
2. **docstring 한 줄, 파라미터 설명 최소** — 스키마가 평균 132B
3. **결과 축약** — 목록은 `limit` 캡, 설명/댓글/본문은 `max_chars`로 서버에서 절단
4. **Confluence HTML → plain text 변환** 후 반환 (원본 HTML의 불필요한 토큰 소비 방지)
5. **Jira REST도 `fields=` 명시** — 와이어 응답 자체를 작게

## 설치 및 실행

```bash
uv venv .venv
uv pip install --python .venv/bin/python fastmcp httpx
```

### 환경변수 (mcp-atlassian과 동일한 변수명)

**Jira Cloud:**
| 변수 | 설명 |
|---|---|
| `JIRA_URL` | 예: `https://your-domain.atlassian.net` |
| `JIRA_USERNAME` | 계정 이메일 |
| `JIRA_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens |

**Confluence Cloud:**
| 변수 | 설명 |
|---|---|
| `CONFLUENCE_URL` | 예: `https://your-domain.atlassian.net/wiki` |
| `CONFLUENCE_USERNAME` | 계정 이메일 |
| `CONFLUENCE_API_TOKEN` | API 토큰 |

**Server/Data Center (PAT 사용 시):**
| 변수 | 설명 |
|---|---|
| `JIRA_URL` / `CONFLUENCE_URL` | 자체 호스팅 주소 |
| `JIRA_PERSONAL_TOKEN` / `CONFLUENCE_PERSONAL_TOKEN` | PAT (Bearer 인증, Jira는 REST v2 자동 전환) |
| `JIRA_SSL_VERIFY` / `CONFLUENCE_SSL_VERIFY` | `false` 시 SSL 검증 해제 (기본 `true`) |

**보안 (mTLS / 키 검증):**
| 변수 | 설명 |
|---|---|
| `JIRA_CLIENT_CERT` / `CONFLUENCE_CLIENT_CERT` | mTLS 클라이언트 인증서 PEM 경로 (결합 or 인증서만) |
| `JIRA_CLIENT_KEY` / `CONFLUENCE_CLIENT_KEY` | 개인키가 분리된 경우 PEM 경로 |
| `JIRA_ISSUE_KEY_PATTERN` | 이슈키 허용 정규식 (기본 `^[A-Z][A-Z0-9_]+-\d+(?:-\d+)*$`) |

**공통:**
| 변수 | 설명 |
|---|---|
| `CONFLUENCE_SPACES_FILTER` | 허용 스페이스만 (콤마 구분, 예: `DEV,PM`) |
| `JIRA_PROJECTS_FILTER` | 허용 프로젝트만 (콤마 구분, 예: `PROJ,TEST`) |
| `LEAN_MAX_RESULTS` | 목록 기본 캡 (기본 20) |
| `LEAN_BODY_CHARS` | 본문 기본 캡 (기본 8000) |

**하위호환**: `ATLASSIAN_SITE_URL` / `ATLASSIAN_USER_EMAIL` / `ATLASSIAN_API_TOKEN`이
있으면 Jira·Confluence 공용으로 사용한다 (`JIRA_*`/`CONFLUENCE_*`가 우선).
인증은 `*_PERSONAL_TOKEN`이 있으면 Bearer(PAT), 없으면 Basic(Cloud API Token)으로
자동 판별한다.

### 클라이언트 설정 예시 (Claude Desktop / Cursor)

```json
{
  "mcpServers": {
    "lean-atl": {
      "command": "/Users/howoomac/Projects/lean-atl/.venv/bin/python",
      "args": ["/Users/howoomac/Projects/lean-atl/lean_atl.py"],
      "env": {
        "JIRA_URL": "https://your-domain.atlassian.net",
        "JIRA_USERNAME": "you@company.com",
        "JIRA_API_TOKEN": "your_token",
        "CONFLUENCE_URL": "https://your-domain.atlassian.net/wiki",
        "CONFLUENCE_USERNAME": "you@company.com",
        "CONFLUENCE_API_TOKEN": "your_token",
        "CONFLUENCE_SPACES_FILTER": "DEV,PM",
        "JIRA_PROJECTS_FILTER": "PROJ"
      }
    }
  }
}
```

Server/DC(PAT)를 쓴다면 `JIRA_PERSONAL_TOKEN`·`CONFLUENCE_PERSONAL_TOKEN`만 채우고
`JIRA_SSL_VERIFY=false` 등을 추가하면 된다.

## 도구 목록 (탐색 위주 10개)

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

### 문서 탐색 순서 예시
1. `confluence_spaces` → 어떤 스페이스가 있는지
2. `confluence_space_tree(space_key, max_depth=2)` → 스페이스 구조 파악
3. `confluence_search(cql, include_snippet=True)` → 원하는 문서 검색 (스니펫으로 판별)
4. `confluence_get(id)` → 문서 본문 읽기
5. `confluence_get_children(id)` → 하위 문서로 이어서 읽기

## 보안 검토 (mcp-atlassian 대비)

**결론: mcp-atlassian보다 공격 표면이 작고, 쓰기 도구가 없어 피해 범위가 제한적.**

- **읽기 전용** — 쓰기 도구(생성/수정/삭제/전이/첨부)가 없어, LLM이 잘못된 도구를 호출해도 데이터 변경 불가 (mcp-atlassian은 쓰기 도구 다수 보유)
- **스코프 필터는 강제 경계** — `JIRA_PROJECTS_FILTER`는 JQL에 AND로 붙고, `jira_get`은 프로젝트 접두가 허용 목록에 없으면 API 호출 전에 거절. `CONFLUENCE_SPACES_FILTER`는 CQL에 AND로 붙고, `confluence_get`/`get_children`/`get_comments`/`space_tree`도 허용 밖이면 본문을 돌려주지 않음 (mcp-atlassian과 같은 방식)
- **경로 조작 차단** — 컨플루언스 `id`는 숫자만, 스페이스 키는 영문·숫자·밑줄만. `../../admin` 같은 입력은 URL에 붙이기 전에 거절
- **출력 한도 강제** — `limit`/`max_chars`는 `LEAN_MAX_RESULTS`/`LEAN_BODY_CHARS`로 자르고 음수는 1로 올림. `LEAN_BODY_CHARS`가 실제로 적용됨
- **이슈키 형식 검증** — `jira_get`의 key를 API 호출 전에 정규식으로 검증 (`JIRA_ISSUE_KEY_PATTERN`, mcp-atlassian과 동일 기본 패턴)
- **mTLS 지원** — `JIRA_CLIENT_CERT`(+`KEY`) / `CONFLUENCE_CLIENT_CERT`(+`KEY`)로 Server/DC mTLS 대응 (mcp-atlassian과 동일 변수명)
- **토큰 노출 경로 없음** — 토큰은 env에서 읽어 Authorization 헤더로만 사용. 코드·로그·에러 메시지·도구 출력에 토큰이 나오는 경로 없음 (grep 검증)
- **리다이렉트 미허용** — httpx 기본값(follow_redirects=False) 유지 → 리다이렉트로 다른 호스트에 자격증명이 전송될 위험 없음
- **의존성 2개** (fastmcp, httpx) vs mcp-atlassian 28개 → 공급망 공격 표면 축소
- **stdio 전용** — 네트워크 리스닝 없음 (mcp-atlassian은 HTTP/S SE 지원으로 노출 시 인증 필요)
- **보안 기능 추가로 토큰 영향 없음** — 키 검증·mTLS·필터·한도는 서버 코드/환경변수 영역이라 도구 스키마가 변하지 않음 (실측: 1,394B 유지)

**한계 (사용자 책임 영역):**
- HTTPS가 아니면 평문 전송 — 반드시 `https://` URL 사용
- `*_SSL_VERIFY=false`는 MITM 위험 — 자체 서명 인증서가 아니면 끄지 말 것
- `CONFLUENCE_SPACES_FILTER`/`JIRA_PROJECTS_FILTER`는 검색 질의에 강제로 AND되고 단건 조회도 막는다. 다만 진짜 권한 통제의 마지막 선은 여전히 Atlassian 측 프로젝트/스페이스 권한이다.
- OAuth 2.0 / 프록시 헤더 인증(IGNORE_HEADER_AUTH)은 **HTTP 배포(멀티 사용자) 시나리오 전용**이라 stdio 로컬에선 적용될 환경이 없어 미지원 — 로컬 단일 사용자에선 토큰·PAT이 더 단순하면서 같은 수준의 보안을 제공한다

## 테스트 (실 API 키 없이)

```bash
.venv/bin/python tests/mock_atlassian.py &   # 모의 서버 (127.0.0.1:8765)
.venv/bin/python tests/test_client.py        # 10개 도구 프로토콜 통합 테스트
.venv/bin/python tests/measure_schema.py     # 스키마 크기 벤치마크
```

## 참고: mcp-atlassian의 도구 구성 옵션 (비교용)

mcp-atlassian도 필터링을 지원하지만 한계가 있다:
- `TOOLSETS=default` → 35개, `TOOLSETS=all` → 98개 (현재 기본값은 전체, v0.22.0부터 default로 변경 예정)
- `ENABLED_TOOLS=도구명1,도구명2` → 개별 허용 목록 (`TOOLSETS`와 교집합)
- Jira만 / Confluence만 설치 구성 가능, `READ_ONLY_MODE`, `JIRA_PROJECTS_FILTER` 등 범위 제한도 있음
- **주의점**: 문서의 도구명 예시(`jira_search_issues` 등)가 실제 배포판과 다르다 — 이 버전의 실제 이름은 `search`, `get_issue`, `get_page` 등. 이름이 맞지 않으면 도구가 0개가 되어 동작하지 않는다.
- 남은 한계: 35개로 줄여도 스키마 자체가 무겁고(평균 ~700B/tool), 개별 도구 스키마의 긴 설명이 그대로 전송된다.
