# lean-atl

가벼운 **읽기전용** 로컬 Jira/Confluence MCP 서버.
클라우드와 서버/데이터센터(Data Center) 배포를 모두 지원한다.
도구 10개, 도구 정의 스키마 1.4KB — 세션당 약 350토큰만 전송한다.

## 왜 가벼운가

MCP에서 LLM은 **세션마다 모든 도구 정의 스키마를 다시 전송**받는다. 도구 수와 스키마 크기가 곧 토큰 비용이다. lean-atl은 이 고정 비용을 설계로 최소화한다.

| 구성 | 도구 수 | 스키마 전체 | ≈ 토큰 |
|---|---:|---:|---:|
| **lean-atl** | **10** | **1,394 B** | **~350** |
| mcp-atlassian (기본 구성) | 98 | 65,295 B | ~16,300 |
| mcp-atlassian (TOOLSETS=default) | 35 | 32,177 B | ~8,000 |
| mcp-atlassian (ENABLED_TOOLS 4종) | 5 | 7,292 B | ~1,800 |

같은 API·인증 방식을 쓰는 서버 기준으로, 기본 구성 대비 **스키마 98% 감소 (세션당 약 16,000토큰 절약)**. mcp-atlassian을 최소 구성(5개 도구)으로 줄여도 lean-atl의 10개 도구가 더 가볍다 (스키마 평균 139B vs 1,458B).

### 토큰 절약 설계 원칙
1. **도구 10개** — 실제 쓰는 핵심만 (검색/조회/댓글/목록)
2. **docstring 한 줄, 파라미터 설명 최소** — 스키마 평균 139B
3. **결과 축약** — 목록은 `limit` 캡, 본문은 `max_chars`로 서버에서 절단
4. **Confluence HTML → plain text 변환** — 원본 HTML의 불필요한 토큰 소비 방지
5. **Jira REST `fields=` 명시** — 응답 자체를 작게

## 설치 및 실행

### macOS

```bash
# 0) uv 설치 (없을 때만)
brew install uv
# 1) lean-atl 저장소 내려받기
git clone https://github.com/sayho87/lean-atl.git
cd lean-atl
# 2) 가상환경 생성 (uv가 Python 3.12를 자동으로 준비)
uv venv .venv
# 3) 의존성 설치
uv pip install --python .venv/bin/python fastmcp httpx
```

### Windows (PowerShell)

```powershell
# 0) uv 설치 (없을 때만)
winget install --id=astral-sh.uv
# 1) lean-atl 저장소 내려받기
git clone https://github.com/sayho87/lean-atl.git
cd lean-atl
# 2) 가상환경 생성 (uv가 Python 3.12를 자동으로 준비)
uv venv .venv
# 3) 의존성 설치 (Windows는 Scripts 경로)
uv pip install --python .venv\Scripts\python.exe fastmcp httpx
```

> uv가 없는 환경이라면 공식 설치 스크립트를 써도 된다:
> `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

## 환경변수

mcp-atlassian과 동일한 변수명을 사용해 기존 설정을 그대로 쓸 수 있다.

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

> Windows라면 `command` 경로를 `.venv\Scripts\python.exe`로 바꾼다 (예: `C:\Users\you\Projects\lean-atl\.venv\Scripts\python.exe`).

## 도구 목록 (10개)

| 도구 | 설명 |
|---|---|
| `jira_search` | JQL 검색 (핵심 필드만) |
| `jira_get` | 이슈 상세 (설명/댓글 앞부분만) |
| `jira_my_tasks` | 내 미해결 이슈 |
| `jira_projects` | 프로젝트 목록 |
| `confluence_search` | CQL 검색 (`include_snippet` 옵션으로 본문 200자 미리보기) |
| `confluence_get` | 페이지 본문 (text, max_chars로 앞부분만) |
| `confluence_get_children` | 하위 페이지 목록 |
| `confluence_get_comments` | 페이지 댓글 목록 (본문 앞부분만) |
| `confluence_space_tree` | 스페이스 페이지 트리 (max_depth, 제목만) |
| `confluence_spaces` | 스페이스 목록 |

### 문서 탐색 순서 예시
1. `confluence_spaces` → 어떤 스페이스가 있는지
2. `confluence_space_tree(space_key, max_depth=3)` → 스페이스 구조 파악
3. `confluence_search(cql, include_snippet=True)` → 원하는 문서 검색 (스니펫으로 판별)
4. `confluence_get(id)` → 문서 본문 읽기
5. `confluence_get_children(id)` → 하위 문서로 이어서 읽기

## 보안 설계

**쓰기 도구를 배제한 읽기 전용 서버 — 잘못된 호출이 데이터를 바꿀 수 없다.**

- **읽기 전용** — 생성/수정/삭제/전이/첨부 도구 없음. LLM이 잘못된 도구를 호출해도 데이터 변경 불가
- **스코프 필터는 강제 경계** — `JIRA_PROJECTS_FILTER`는 JQL에 AND, `CONFLUENCE_SPACES_FILTER`는 CQL에 AND. 단건 조회(`jira_get`, `confluence_get` 등)도 허용 범위 밖이면 API 호출 전에 거절
- **경로 조작 차단** — 컨플루언스 `id`는 숫자만, 스페이스 키는 영문·숫자·밑줄만. `../../admin` 같은 입력은 URL에 붙이기 전에 거절
- **출력 한도 강제** — `limit`/`max_chars`는 `LEAN_MAX_RESULTS`/`LEAN_BODY_CHARS` 상한으로 자르고 음수는 차단
- **이슈키 형식 검증** — `JIRA_ISSUE_KEY_PATTERN` 정규식으로 API 호출 전 검증
- **mTLS 지원** — `JIRA_CLIENT_CERT`(+`KEY`) / `CONFLUENCE_CLIENT_CERT`(+`KEY`)
- **토큰 노출 경로 없음** — 토큰은 env에서 Authorization 헤더로만 사용 (grep 검증)
- **리다이렉트 미허용** — 자격증명이 다른 호스트로 전송될 경로 없음
- **의존성 2개** (fastmcp, httpx)
- **stdio 전용** — 네트워크 리스닝 없음

**사용자 유의사항:**
- HTTPS가 아니면 평문 전송 — 반드시 `https://` URL 사용
- `*_SSL_VERIFY=false`는 MITM 위험 — 자체 서명 인증서가 아니면 끄지 말 것
- 필터는 검색 질의와 단건 조회를 막지만, 최종 권한 통제는 Atlassian 측 프로젝트/스페이스 권한
- OAuth 2.0 / 프록시 헤더 인증은 HTTP 배포(멀티 사용자) 전용이라 stdio 로컬에선 미지원

## 테스트 (실 API 키 없이)

```bash
.venv/bin/python tests/mock_atlassian.py &   # 모의 서버 (127.0.0.1:8765)
.venv/bin/python tests/test_client.py        # 10개 도구 프로토콜 통합 테스트
.venv/bin/python tests/test_filters.py       # 스코프 필터 강제 검증
.venv/bin/python tests/test_security.py      # 경로 조작·한도·mTLS 검증
.venv/bin/python tests/test_pat.py           # Server/DC PAT 모드 검증
.venv/bin/python tests/measure_schema.py     # 스키마 크기 벤치마크
```
