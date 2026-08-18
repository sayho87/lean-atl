"""lean-atl — mcp-atlassian(98 tools)보다 토큰을 아껴 먹는 Jira/Confluence MCP.

절약 설계:
- 도구 10개 (mcp-atlassian의 98개 대비) → 매 요청마다 전송되는 도구 정의 스키마가 1/10
- docstring 한 줄, 파라미터 설명 최소화 → 스키마 크기 축소
- 결과는 핵심 필드만, 목록은 limit 캡, 긴 본문은 max_chars로 서버에서 잘라서 반환
- Confluence HTML 본문을 서버에서 plain text로 변환 (원본 HTML 반환 금지)
- Jira REST도 fields= 명시 → 와이어 응답 자체가 작음

환경변수 (mcp-atlassian과 동일한 이름):
  JIRA_URL / JIRA_USERNAME / JIRA_API_TOKEN      Jira Cloud (Basic Auth)
  JIRA_PERSONAL_TOKEN / JIRA_SSL_VERIFY          Jira Server/DC (Bearer, REST v2)
  CONFLUENCE_URL / CONFLUENCE_USERNAME / CONFLUENCE_API_TOKEN   Confluence Cloud
  CONFLUENCE_PERSONAL_TOKEN / CONFLUENCE_SSL_VERIFY             Confluence Server/DC
  CONFLUENCE_SPACES_FILTER / JIRA_PROJECTS_FILTER               스코프 제한 (콤마 구분)
  LEAN_MAX_RESULTS / LEAN_BODY_CHARS                             출력 캡 (기본 20 / 8000)

하위호환: ATLASSIAN_SITE_URL / ATLASSIAN_USER_EMAIL / ATLASSIAN_API_TOKEN이
있으면 Jira·Confluence 공용으로 사용한다 (JIRA_*/CONFLUENCE_* 우선).
"""

from __future__ import annotations

import html
import os
import re
import sys
import time
from typing import Annotated, Any

import httpx
from fastmcp import FastMCP

mcp = FastMCP("lean-atl")


def _first(*names: str) -> str:
    """여러 변수명 중 처음으로 설정된 값. 미설정이면 빈 문자열."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def _flag(name: str, default: bool = True) -> bool:
    """false 계열 표현('false'/'0'/'off'/'no')이면 False, 그 외엔 True."""
    v = os.environ.get(name, "true" if default else "false").strip().lower()
    return v not in ("false", "0", "off", "no")


def _env_int(name: str, default: int) -> int:
    """정수 환경변수 파싱. 오타·비정수면 기본값으로 폴백 (서버 시작 크래시 방지)."""
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# --- Jira 설정 ---
JIRA_URL = _first("JIRA_URL", "ATLASSIAN_SITE_URL").rstrip("/")
JIRA_USERNAME = _first("JIRA_USERNAME", "ATLASSIAN_USER_EMAIL")
JIRA_API_TOKEN = _first("JIRA_API_TOKEN", "ATLASSIAN_API_TOKEN")
JIRA_PAT = _first("JIRA_PERSONAL_TOKEN")
JIRA_SSL = _flag("JIRA_SSL_VERIFY")

# --- Confluence 설정 ---
CONF_URL = _first("CONFLUENCE_URL", "ATLASSIAN_SITE_URL").rstrip("/")
CONF_USERNAME = _first("CONFLUENCE_USERNAME", "ATLASSIAN_USER_EMAIL")
CONF_API_TOKEN = _first("CONFLUENCE_API_TOKEN", "ATLASSIAN_API_TOKEN")
CONF_PAT = _first("CONFLUENCE_PERSONAL_TOKEN")
CONF_SSL = _flag("CONFLUENCE_SSL_VERIFY")

# --- 출력 캡 / 스코프 필터 ---
MAX_RESULTS = _env_int("LEAN_MAX_RESULTS", 20)
BODY_CHARS = _env_int("LEAN_BODY_CHARS", 8000)
_MAX_LIST_LIMIT = 100  # limit 명시 시 최대 상한 (2단계 캡: 기본 20, 명시 시 100까지)
CONF_SPACES = {s.strip() for s in os.environ.get("CONFLUENCE_SPACES_FILTER", "").split(",") if s.strip()}
JIRA_PROJECTS = {s.strip() for s in os.environ.get("JIRA_PROJECTS_FILTER", "").split(",") if s.strip()}
# 매칭은 대소문자 무시(스페이스/프로젝트 키는 대소문자만 다른 표기가 같은 키를 가리킴),
# 질의 생성은 원본 키 유지
_CONF_SPACES_CF = {s.casefold() for s in CONF_SPACES}
_JIRA_PROJECTS_CF = {s.casefold() for s in JIRA_PROJECTS}

# --- 보안: 이슈키 형식 검증 / mTLS (mcp-atlassian과 동일 변수명·기본 패턴) ---
_DEFAULT_ISSUE_KEY = r"^[A-Z][A-Z0-9_]+-\d+(?:-\d+)*$"
_CONTENT_ID_RE = re.compile(r"^\d+$")
_SPACE_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")
_MAX_TREE_DEPTH = 5
_ADF_MAX_DEPTH = 32


def _compile_issue_key_re() -> re.Pattern[str]:
    raw = os.environ.get("JIRA_ISSUE_KEY_PATTERN", _DEFAULT_ISSUE_KEY)
    try:
        return re.compile(raw)
    except re.error:
        return re.compile(_DEFAULT_ISSUE_KEY)


ISSUE_KEY_RE = _compile_issue_key_re()
JIRA_CERT = _first("JIRA_CLIENT_CERT")
JIRA_CERT_KEY = _first("JIRA_CLIENT_KEY")
CONF_CERT = _first("CONFLUENCE_CLIENT_CERT")
CONF_CERT_KEY = _first("CONFLUENCE_CLIENT_KEY")

_jira: httpx.Client | None = None
_conf: httpx.Client | None = None
_UA = {"User-Agent": "lean-atl/1.0 (https://github.com/sayho87/lean-atl)"}


def _proxy_args(prefix: str) -> dict:
    """서비스 프록시 env → httpx.Client 인자 (mcp-atlassian과 동일 변수명).

    - CONFLUENCE_HTTPS_PROXY / CONFLUENCE_HTTP_PROXY (Jira는 JIRA_*) 또는
      일반 HTTPS_PROXY / HTTP_PROXY를 읽는다.
    - 하나만 있으면 proxy=로, http/https가 다르면 mounts=로 전달.
    - 미설정이면 빈 dict (직접 연결).
    """
    h = _first(f"{prefix}_HTTP_PROXY", "HTTP_PROXY")
    s = _first(f"{prefix}_HTTPS_PROXY", "HTTPS_PROXY")
    if h and s and h != s:
        return {"mounts": {"http://": httpx.Proxy(h), "https://": httpx.Proxy(s)}}
    url = s or h
    return {"proxy": url} if url else {}


def _make_client(url: str, username: str, api_token: str, pat: str, ssl: bool,
                 cert: str = "", cert_key: str = "",
                 proxy_args: dict | None = None) -> httpx.Client:
    if not url:
        raise RuntimeError(
            "URL 환경변수 필요 (JIRA_URL / CONFLUENCE_URL 또는 ATLASSIAN_SITE_URL)")
    # mTLS: 결합 PEM이면 cert만, 분리면 (cert, key). KEY만 있고 CERT가 없으면 명확한 오류.
    if cert_key and not cert:
        raise RuntimeError("클라이언트 인증서 KEY만 설정됨 — CERT(CLIENT_CERT) 경로도 함께 설정하세요")
    cert_arg: Any = (cert, cert_key) if cert_key else (cert or None)
    common = {"verify": ssl, "cert": cert_arg, "timeout": 30, **(proxy_args or {})}
    if pat:
        # Server/Data Center: Personal Access Token (Bearer)
        return httpx.Client(base_url=url,
                            headers={**_UA, "Authorization": f"Bearer {pat}"}, **common)
    if username and api_token:
        # Cloud: Basic Auth (email + API token)
        return httpx.Client(base_url=url, headers=_UA, auth=(username, api_token), **common)
    raise RuntimeError(
        f"인증 환경변수 필요 ({url}): API_TOKEN+USERNAME (Cloud) 또는 PERSONAL_TOKEN (Server/DC)")


def jira_client() -> httpx.Client:
    global _jira
    if _jira is None:
        _jira = _make_client(JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN, JIRA_PAT, JIRA_SSL,
                             JIRA_CERT, JIRA_CERT_KEY, _proxy_args("JIRA"))
    return _jira


def conf_client() -> httpx.Client:
    global _conf
    if _conf is None:
        _conf = _make_client(CONF_URL, CONF_USERNAME, CONF_API_TOKEN, CONF_PAT, CONF_SSL,
                             CONF_CERT, CONF_CERT_KEY, _proxy_args("CONFLUENCE"))
    return _conf


def _jget(path: str, **params: Any) -> dict:
    # Server/DC(Jira)는 REST v3 미지원 → v2 경로로 변환
    if JIRA_PAT and path.startswith("/rest/api/3"):
        path = "/rest/api/2" + path[len("/rest/api/3"):]
    return _get_retry(jira_client(), path, params)


def _cget(path: str, **params: Any) -> dict:
    return _get_retry(conf_client(), path, params)


def _get_retry(client: httpx.Client, path: str, params: dict) -> dict:
    """429(속도 제한)·5xx(서버 일시 오류)면 1초 뒤 1회 재시도. 그 외 오류는 즉시 전달."""
    clean = {k: v for k, v in params.items() if v is not None}
    for attempt in range(2):
        r = client.get(path, params=clean)
        if r.status_code in (429, 500, 502, 503) and attempt == 0:
            time.sleep(1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"재시도 실패: {path}")


# ---------- 변환 헬퍼 ----------

def _html_to_text(raw: str, max_chars: int) -> str:
    """Confluence storage HTML → plain text, max_chars로 절단. script/style은 통째로 제거."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", raw)
    s = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", s)
    s = re.sub(r"<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(re.sub(r"[ \t]+", " ", s))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:max_chars] + "…" if len(s) > max_chars else s


def _adf_to_text(node: dict, buf: list[str], depth: int = 0) -> None:
    """Jira ADF(JSON) → plain text."""
    if depth > _ADF_MAX_DEPTH:
        return
    t = node.get("type")
    if t == "text":
        buf.append(node.get("text", ""))
    elif t == "hardBreak":
        buf.append("\n")
    else:
        for c in node.get("content") or []:
            _adf_to_text(c, buf, depth + 1)
        if t in ("paragraph", "heading", "listItem", "codeBlock", "blockquote",
                 "panel", "rule", "tableRow"):
            buf.append("\n")


def _adf_text(adf: dict | None, max_chars: int) -> str:
    if not adf:
        return ""
    buf: list[str] = []
    for c in adf.get("content") or []:
        _adf_to_text(c, buf)
    s = re.sub(r"\n{3,}", "\n\n", "".join(buf)).strip()
    return s[:max_chars] + "…" if len(s) > max_chars else s


def _user(f: dict, key: str) -> str | None:
    u = f.get(key)
    return u.get("displayName") if isinstance(u, dict) else None


def _filter_conf(results: list[dict]) -> list[dict]:
    """CONFLUENCE_SPACES_FILTER 적용 (key 또는 space 기준, 대소문자 무시). 필터 미설정이면 그대로."""
    if not CONF_SPACES:
        return results
    return [r for r in results if (r.get("key") or r.get("space") or "").casefold() in _CONF_SPACES_CF]


_MAX_SPACE_PAGES = 50  # 페이지네이션 안전 상한 (50페이지 × 100개 = 5,000개 스페이스면 충분)


def _cget_spaces_page(start: int, page_limit: int = 100) -> tuple[list[dict], int | None]:
    """스페이스 목록 한 페이지 조회 → (results, next_start). next_start None이면 끝.

    _links.next 상대경로(예: /rest/api/space?limit=100&start=100)에서 start 추출,
    없으면 이번 배치 크기로 계산. start가 None일 때만 종료 (무한 루프 방지).
    """
    data = _cget("/rest/api/space", limit=page_limit, start=start)
    results = data.get("results") or []
    next_link = (data.get("_links") or {}).get("next")
    if not next_link:
        return results, None
    m = re.search(r"[?&]start=(\d+)", str(next_link))
    return results, (int(m.group(1)) if m else start + len(results))


def _filter_proj(results: list[dict]) -> list[dict]:
    """JIRA_PROJECTS_FILTER 적용 (key 기준, 대소문자 무시). 필터 미설정이면 그대로."""
    if not JIRA_PROJECTS:
        return results
    return [r for r in results if (r.get("key") or "").casefold() in _JIRA_PROJECTS_CF]


def _check_issue_key(key: str) -> None:
    """이슈키 형식 검증 (기본: PROJ-123, 커스텀: JIRA_ISSUE_KEY_PATTERN)."""
    if not ISSUE_KEY_RE.match(key):
        raise ValueError(
            f"이슈키 형식이 아님: {key!r} (허용 패턴: {ISSUE_KEY_RE.pattern})")


def _clamp_limit(limit: int) -> int:
    """목록 개수. 1~100이면 그대로, 그 외(음수·0·비정수)면 기본값(20)."""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= _MAX_LIST_LIMIT:
        n = MAX_RESULTS
    return n


def _clamp_chars(max_chars: int) -> int:
    try:
        n = int(max_chars)
    except (TypeError, ValueError):
        n = BODY_CHARS
    return max(1, min(n, BODY_CHARS))


def _clamp_depth(max_depth: int) -> int:
    try:
        n = int(max_depth)
    except (TypeError, ValueError):
        n = _MAX_TREE_DEPTH
    return max(0, min(n, _MAX_TREE_DEPTH))


def _quote_ident(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _and_query(q: str, clause: str) -> str:
    """질의에 AND 절을 강제. 끝의 ORDER BY는 보존."""
    if not q or not q.strip():
        return clause
    order = re.search(r"\s+(ORDER\s+BY\s+.*)$", q, re.IGNORECASE)
    if order:
        return f"({q[:order.start()]}) AND {clause} {order.group(1)}"
    return f"({q}) AND {clause}"


def _and_jql_projects(jql: str) -> str:
    """JIRA_PROJECTS_FILTER를 JQL에 강제 AND (mcp-atlassian과 동일 방식)."""
    if not JIRA_PROJECTS:
        return jql
    keys = sorted(JIRA_PROJECTS)
    if len(keys) == 1:
        clause = f"project = {_quote_ident(keys[0])}"
    else:
        clause = "project IN (" + ", ".join(_quote_ident(k) for k in keys) + ")"
    return _and_query(jql, clause)


def _and_cql_spaces(cql: str) -> str:
    """CONFLUENCE_SPACES_FILTER를 CQL에 강제 AND."""
    if not CONF_SPACES:
        return cql
    clause = " OR ".join(f"space = {_quote_ident(s)}" for s in sorted(CONF_SPACES))
    if len(CONF_SPACES) > 1:
        clause = f"({clause})"
    return _and_query(cql, clause)


def _check_content_id(id: str) -> None:
    if not _CONTENT_ID_RE.match(id or ""):
        raise ValueError(f"페이지 id는 숫자만 허용: {id!r}")


def _check_space_key(space_key: str) -> None:
    if not _SPACE_KEY_RE.match(space_key or ""):
        raise ValueError(f"스페이스 키 형식이 아님: {space_key!r}")


def _check_issue_scope(key: str) -> None:
    """jira_get: 허용 프로젝트 밖이면 API 전에 거절 (대소문자 무시)."""
    if not JIRA_PROJECTS:
        return
    prefix = key.split("-", 1)[0]
    if prefix.casefold() not in _JIRA_PROJECTS_CF:
        raise ValueError(
            f"JIRA_PROJECTS_FILTER에 없는 프로젝트: {prefix} (허용: {sorted(JIRA_PROJECTS)})")


def _space_denied(space: str | None) -> dict | None:
    if CONF_SPACES and (space or "").casefold() not in _CONF_SPACES_CF:
        return {"space": space,
                "error": f"CONFLUENCE_SPACES_FILTER에 없는 스페이스 (허용: {sorted(CONF_SPACES)})"}
    return None


def _require_conf_space(id: str) -> dict | None:
    """ID 도구용. 필터가 있으면 본문 없이 스페이스만 확인."""
    if not CONF_SPACES:
        return None
    data = _cget(f"/rest/api/content/{id}", expand="space")
    return _space_denied((data.get("space") or {}).get("key"))


# ---------- Jira 도구 ----------
# Jira 도구는 JIRA_URL 미설정 시 등록하지 않는다 (모듈 끝의 조건부 등록 참고).
# 등록하지 않으면 LLM 도구 목록에 아예 나타나지 않아
# "URL 환경변수 필요" 같은 혼선 오류가 발생하지 않는다.

def jira_search(jql: str, limit: Annotated[int, "목록 개수, 최대 100"] = 20) -> list[dict]:
    """JQL로 이슈를 검색하고 핵심 필드만 돌려준다."""
    jql = _and_jql_projects(jql)
    data = _jget("/rest/api/3/search", jql=jql,
                 fields="summary,status,assignee,priority,labels,updated,project",
                 maxResults=_clamp_limit(limit))
    out = []
    for it in data.get("issues", []):
        f = it.get("fields", {})
        proj = (f.get("project") or {}).get("key")
        if JIRA_PROJECTS and proj not in JIRA_PROJECTS:
            continue
        out.append({
            "key": it.get("key"),
            "project": proj,
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "assignee": _user(f, "assignee"),
            "priority": (f.get("priority") or {}).get("name"),
            "labels": f.get("labels", []),
            "updated": f.get("updated"),
        })
    return out


def jira_get(key: str, max_chars: int = 8000) -> dict:
    """이슈 상세. 설명·코멘트 본문은 max_chars로 절단."""
    _check_issue_key(key)
    _check_issue_scope(key)
    max_chars = _clamp_chars(max_chars)
    data = _jget(f"/rest/api/3/issue/{key}",
                 fields="summary,status,assignee,reporter,priority,issuetype,"
                        "labels,created,updated,description,comment")
    f = data.get("fields", {})
    comments = f.get("comment", {}) or {}
    last = []
    for c in (comments.get("comments") or [])[-3:]:
        last.append({"author": _user(c, "author"),
                     "created": c.get("created"),
                     "body": _adf_text(c.get("body"), max_chars // 2)})
    return {
        "key": data.get("key"),
        "url": f"{JIRA_URL}/browse/{data.get('key')}",
        "type": (f.get("issuetype") or {}).get("name"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "assignee": _user(f, "assignee"),
        "reporter": _user(f, "reporter"),
        "priority": (f.get("priority") or {}).get("name"),
        "labels": f.get("labels", []),
        "created": f.get("created"),
        "updated": f.get("updated"),
        "description": _adf_text(f.get("description"), max_chars),
        "comments_total": comments.get("total", 0),
        "comments_recent": last,
    }


def jira_my_tasks(limit: Annotated[int, "목록 개수, 최대 100"] = 20) -> list[dict]:
    """나에게 배정된 미해결 이슈 목록."""
    return jira_search("assignee = currentUser() AND resolution = unresolved",
                       limit=_clamp_limit(limit))


def jira_projects() -> list[dict]:
    """프로젝트 목록(key, 이름)."""
    if JIRA_PAT:
        # Server/DC v2: 배열 반환
        return _filter_proj([{"key": p.get("key"), "name": p.get("name")}
                             for p in _jget("/rest/api/2/project")])
    data = _jget("/rest/api/3/project/search", maxResults=100)
    return _filter_proj([{"key": p.get("key"), "name": p.get("name")}
                         for p in data.get("values", [])])


# ---------- Confluence 도구 ----------

@mcp.tool
def confluence_search(cql: str, limit: Annotated[int, "목록 개수, 최대 100"] = 20,
                      include_snippet: bool = False) -> list[dict]:
    """CQL로 페이지 검색. include_snippet=True면 본문 첫 200자 포함."""
    cql = _and_cql_spaces(cql)
    data = _cget("/rest/api/content/search", cql=cql,
                 limit=_clamp_limit(limit),
                 expand="body.storage" if include_snippet else None)
    out = []
    for it in data.get("results", []):
        sp = (it.get("space") or {}).get("key")
        item = {
            "id": it.get("id"),
            "title": it.get("title"),
            "space": sp,
            "url": f"{CONF_URL}/spaces/{sp}/pages/{it.get('id')}",
        }
        if include_snippet:
            storage = (it.get("body") or {}).get("storage", {}).get("value", "")
            item["snippet"] = _html_to_text(storage, 200)
        out.append(item)
    return _filter_conf(out)


@mcp.tool
def confluence_get_children(id: str, limit: Annotated[int, "목록 개수, 최대 100"] = 20) -> list[dict]:
    """페이지의 하위 페이지 목록(id, 제목)."""
    _check_content_id(id)
    denied = _require_conf_space(id)
    if denied:
        return [denied]
    data = _cget(f"/rest/api/content/{id}/child/page", limit=_clamp_limit(limit))
    return [{"id": p.get("id"), "title": p.get("title"),
             "url": f"{CONF_URL}/pages/{p.get('id')}"}
            for p in data.get("results", [])]


@mcp.tool
def confluence_space_tree(space_key: str, max_depth: int = 5, limit: int = 100) -> dict:
    """스페이스의 페이지 트리. max_depth까지 제목만, 본문 없음."""
    _check_space_key(space_key)
    if CONF_SPACES and space_key.casefold() not in _CONF_SPACES_CF:
        return {"space": space_key,
                "error": f"CONFLUENCE_SPACES_FILTER에 없는 스페이스 (허용: {sorted(CONF_SPACES)})"}
    max_depth = _clamp_depth(max_depth)
    data = _cget("/rest/api/content", spaceKey=space_key, type="page",
                 expand="ancestors", limit=_clamp_limit(limit))
    raw = [{"id": p.get("id"), "title": p.get("title"),
            "depth": len(p.get("ancestors") or []),
            "parent_id": (p.get("ancestors") or [{}])[-1].get("id") if p.get("ancestors") else None}
           for p in data.get("results", [])]
    nodes = {p["id"]: {"id": p["id"], "title": p["title"], "children": []} for p in raw}
    roots = []
    for p in raw:
        node = nodes[p["id"]]
        parent = nodes.get(p["parent_id"])
        if p["depth"] > max_depth:
            continue
        if parent is not None:
            parent["children"].append(node)
        else:
            roots.append(node)
    return {"space": space_key, "max_depth": max_depth,
            "page_count": len(raw), "roots": roots}


@mcp.tool
def confluence_get(id: str, max_chars: int = 8000) -> dict:
    """페이지 본문을 plain text로 돌려준다. max_chars로 절단."""
    _check_content_id(id)
    max_chars = _clamp_chars(max_chars)
    data = _cget(f"/rest/api/content/{id}", expand="body.storage,space")
    sp = (data.get("space") or {}).get("key")
    denied = _space_denied(sp)
    if denied:
        return denied
    storage = (data.get("body") or {}).get("storage", {}).get("value", "")
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "space": sp,
        "url": f"{CONF_URL}/spaces/{sp}/pages/{data.get('id')}",
        "body": _html_to_text(storage, max_chars),
    }


@mcp.tool
def confluence_get_comments(id: str, limit: Annotated[int, "목록 개수, 최대 100"] = 20,
                            max_chars: int = 1500) -> list[dict]:
    """페이지에 달린 댓글 목록. 본문은 max_chars로 절단."""
    _check_content_id(id)
    denied = _require_conf_space(id)
    if denied:
        return [denied]
    max_chars = _clamp_chars(max_chars)
    data = _cget(f"/rest/api/content/{id}/child/comment",
                 limit=_clamp_limit(limit), expand="body.storage")
    out = []
    for c in data.get("results", []):
        body = (c.get("body") or {}).get("storage", {}).get("value", "")
        author = (c.get("author") or {}).get("displayName") or \
                 (c.get("version") or {}).get("by", {}).get("displayName")
        out.append({
            "id": c.get("id"),
            "author": author,
            "created": c.get("created"),
            "body": _html_to_text(body, max_chars),
        })
    return out


@mcp.tool
def confluence_spaces(limit: Annotated[int, "목록 개수, 최대 100"] = 20) -> list[dict]:
    """스페이스 목록(key, 이름). CONFLUENCE_SPACES_FILTER 적용."""
    if CONF_SPACES:
        # 필터 설정 시: 전체 스페이스 페이지네이션 조회 후 필터 매칭 —
        # 스페이스가 많아 첫 페이지에 없어도 뒤쪽에서 정확히 찾는다.
        all_spaces: list[dict] = []
        start: int | None = 0
        for _ in range(_MAX_SPACE_PAGES):
            batch, start = _cget_spaces_page(start)
            all_spaces.extend(batch)
            if start is None:
                break
        return _filter_conf(all_spaces)
    data = _cget("/rest/api/space", limit=_clamp_limit(limit))
    return [{"key": s.get("key"), "name": s.get("name"), "type": s.get("type")}
            for s in data.get("results", [])]


# ---------- 조건부 등록 ----------
# JIRA_URL 미설정 환경(Confluence 전용)에서는 Jira 도구 4개를 아예 등록하지 않아
# LLM 도구 목록에서 제외한다. fastmcp add_tool은 docstring에서 설명을 추출하므로
# @mcp.tool 데코레이터와 동일한 스키마가 생성된다.
_JIRA_TOOLS = (jira_search, jira_get, jira_my_tasks, jira_projects)
if JIRA_URL:
    for _fn in _JIRA_TOOLS:
        mcp.add_tool(_fn)


if __name__ == "__main__":
    # 시작 로그 — stdout은 MCP 프로토콜 채널이므로 반드시 stderr로 출력
    _n_jira = 4 if JIRA_URL else 0
    _suffix = "" if _n_jira else " — Jira URL 미설정(도구 4개 제외, Confluence 전용)"
    print(f"lean-atl: 읽기 전용 서버 (쓰기 도구 0개, 도구 {6 + _n_jira}개{_suffix})", file=sys.stderr)
    for name, u in (("Jira", JIRA_URL), ("Confluence", CONF_URL)):
        if u.startswith("http://"):
            print(f"lean-atl 경고: {name} URL이 HTTPS가 아닙니다 — "
                  f"인증 토큰이 평문으로 전송될 수 있습니다 ({u})", file=sys.stderr)
    if CONF_URL:
        spaces = ",".join(sorted(CONF_SPACES)) or "전체"
        print(f"lean-atl: Confluence {CONF_URL} | 스페이스 필터: {spaces}", file=sys.stderr)
    if JIRA_URL:
        projects = ",".join(sorted(JIRA_PROJECTS)) or "전체"
        print(f"lean-atl: Jira {JIRA_URL} | 프로젝트 필터: {projects}", file=sys.stderr)
    mcp.run()
