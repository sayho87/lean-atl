"""lean-atlassian-mcp — mcp-atlassian(98 tools)보다 토큰을 아껴 먹는 Jira/Confluence MCP.

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
from typing import Any

import httpx
from fastmcp import FastMCP

mcp = FastMCP("lean-atlassian")


def _first(*names: str) -> str:
    """여러 변수명 중 처음으로 설정된 값. 미설정이면 빈 문자열."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def _flag(name: str, default: bool = True) -> bool:
    return os.environ.get(name, "true" if default else "false").strip().lower() != "false"


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
MAX_RESULTS = int(os.environ.get("LEAN_MAX_RESULTS", "20"))
BODY_CHARS = int(os.environ.get("LEAN_BODY_CHARS", "8000"))
CONF_SPACES = {s.strip() for s in os.environ.get("CONFLUENCE_SPACES_FILTER", "").split(",") if s.strip()}
JIRA_PROJECTS = {s.strip() for s in os.environ.get("JIRA_PROJECTS_FILTER", "").split(",") if s.strip()}

# --- 보안: 이슈키 형식 검증 / mTLS (mcp-atlassian과 동일 변수명·기본 패턴) ---
ISSUE_KEY_RE = re.compile(os.environ.get(
    "JIRA_ISSUE_KEY_PATTERN", r"^[A-Z][A-Z0-9_]+-\d+(?:-\d+)*$"))
JIRA_CERT = _first("JIRA_CLIENT_CERT")
JIRA_CERT_KEY = _first("JIRA_CLIENT_KEY")
CONF_CERT = _first("CONFLUENCE_CLIENT_CERT")
CONF_CERT_KEY = _first("CONFLUENCE_CLIENT_KEY")

_jira: httpx.Client | None = None
_conf: httpx.Client | None = None


def _make_client(url: str, username: str, api_token: str, pat: str, ssl: bool,
                 cert: str = "", cert_key: str = "") -> httpx.Client:
    if not url:
        raise RuntimeError(
            "URL 환경변수 필요 (JIRA_URL / CONFLUENCE_URL 또는 ATLASSIAN_SITE_URL)")
    # mTLS: 결합 PEM이면 cert만, 분리면 (cert, key)
    cert_arg: Any = (cert, cert_key) if cert_key else (cert or None)
    if pat:
        # Server/Data Center: Personal Access Token (Bearer)
        return httpx.Client(base_url=url, headers={"Authorization": f"Bearer {pat}"},
                            verify=ssl, cert=cert_arg, timeout=30)
    if username and api_token:
        # Cloud: Basic Auth (email + API token)
        return httpx.Client(base_url=url, auth=(username, api_token),
                            verify=ssl, cert=cert_arg, timeout=30)
    raise RuntimeError(
        f"인증 환경변수 필요 ({url}): API_TOKEN+USERNAME (Cloud) 또는 PERSONAL_TOKEN (Server/DC)")


def jira_client() -> httpx.Client:
    global _jira
    if _jira is None:
        _jira = _make_client(JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN, JIRA_PAT, JIRA_SSL,
                             JIRA_CERT, JIRA_CERT_KEY)
    return _jira


def conf_client() -> httpx.Client:
    global _conf
    if _conf is None:
        _conf = _make_client(CONF_URL, CONF_USERNAME, CONF_API_TOKEN, CONF_PAT, CONF_SSL,
                             CONF_CERT, CONF_CERT_KEY)
    return _conf


def _jget(path: str, **params: Any) -> dict:
    # Server/DC(Jira)는 REST v3 미지원 → v2 경로로 변환
    if JIRA_PAT and path.startswith("/rest/api/3"):
        path = "/rest/api/2" + path[len("/rest/api/3"):]
    r = jira_client().get(path, params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


def _cget(path: str, **params: Any) -> dict:
    r = conf_client().get(path, params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


# ---------- 변환 헬퍼 ----------

def _html_to_text(raw: str, max_chars: int) -> str:
    """Confluence storage HTML → plain text, max_chars로 절단."""
    s = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", raw)
    s = re.sub(r"<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(re.sub(r"[ \t]+", " ", s))
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:max_chars] + "…" if len(s) > max_chars else s


def _adf_to_text(node: dict, buf: list[str]) -> None:
    """Jira ADF(JSON) → plain text."""
    t = node.get("type")
    if t == "text":
        buf.append(node.get("text", ""))
    elif t == "hardBreak":
        buf.append("\n")
    else:
        for c in node.get("content") or []:
            _adf_to_text(c, buf)
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
    """CONFLUENCE_SPACES_FILTER 적용 (key 또는 space 기준). 필터 미설정이면 그대로."""
    if not CONF_SPACES:
        return results
    return [r for r in results if (r.get("key") or r.get("space")) in CONF_SPACES]


def _filter_proj(results: list[dict]) -> list[dict]:
    """JIRA_PROJECTS_FILTER 적용 (key 기준). 필터 미설정이면 그대로."""
    if not JIRA_PROJECTS:
        return results
    return [r for r in results if r.get("key") in JIRA_PROJECTS]


def _check_issue_key(key: str) -> None:
    """이슈키 형식 검증 (기본: PROJ-123, 커스텀: JIRA_ISSUE_KEY_PATTERN)."""
    if not ISSUE_KEY_RE.match(key):
        raise ValueError(
            f"이슈키 형식이 아님: {key!r} (허용 패턴: {ISSUE_KEY_RE.pattern})")


# ---------- Jira 도구 ----------

@mcp.tool
def jira_search(jql: str, limit: int = 20) -> list[dict]:
    """JQL로 이슈를 검색하고 핵심 필드만 돌려준다."""
    data = _jget("/rest/api/3/search", jql=jql,
                 fields="summary,status,assignee,priority,labels,updated,project",
                 maxResults=min(limit, MAX_RESULTS))
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


@mcp.tool
def jira_get(key: str, max_chars: int = 8000) -> dict:
    """이슈 상세. 설명·코멘트 본문은 max_chars로 절단."""
    _check_issue_key(key)
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


@mcp.tool
def jira_my_tasks(limit: int = 20) -> list[dict]:
    """나에게 배정된 미해결 이슈 목록."""
    return jira_search("assignee = currentUser() AND resolution = unresolved",
                       limit=limit)


@mcp.tool
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
def confluence_search(cql: str, limit: int = 20, include_snippet: bool = False) -> list[dict]:
    """CQL로 페이지 검색. include_snippet=True면 본문 첫 200자 포함."""
    data = _cget("/rest/api/content/search", cql=cql,
                 limit=min(limit, MAX_RESULTS),
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
def confluence_get_children(id: str, limit: int = 50) -> list[dict]:
    """페이지의 하위 페이지 목록(id, 제목)."""
    data = _cget(f"/rest/api/content/{id}/child/page", limit=min(limit, MAX_RESULTS))
    return [{"id": p.get("id"), "title": p.get("title"),
             "url": f"{CONF_URL}/pages/{p.get('id')}"}
            for p in data.get("results", [])]


@mcp.tool
def confluence_space_tree(space_key: str, max_depth: int = 2, limit: int = 100) -> dict:
    """스페이스의 페이지 트리. max_depth까지 제목만, 본문 없음."""
    if CONF_SPACES and space_key not in CONF_SPACES:
        return {"space": space_key,
                "error": f"CONFLUENCE_SPACES_FILTER에 없는 스페이스 (허용: {sorted(CONF_SPACES)})"}
    data = _cget("/rest/api/content", spaceKey=space_key, type="page",
                 expand="ancestors", limit=min(limit, 100))
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
    data = _cget(f"/rest/api/content/{id}", expand="body.storage,space")
    sp = (data.get("space") or {}).get("key")
    storage = (data.get("body") or {}).get("storage", {}).get("value", "")
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "space": sp,
        "url": f"{CONF_URL}/spaces/{sp}/pages/{data.get('id')}",
        "body": _html_to_text(storage, max_chars),
    }


@mcp.tool
def confluence_get_comments(id: str, limit: int = 50, max_chars: int = 1500) -> list[dict]:
    """페이지에 달린 댓글 목록. 본문은 max_chars로 절단."""
    data = _cget(f"/rest/api/content/{id}/child/comment",
                 limit=min(limit, MAX_RESULTS), expand="body.storage")
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
def confluence_spaces() -> list[dict]:
    """스페이스 목록(key, 이름). CONFLUENCE_SPACES_FILTER 적용."""
    data = _cget("/rest/api/space", limit=50)
    return _filter_conf([{"key": s.get("key"), "name": s.get("name"), "type": s.get("type")}
                         for s in data.get("results", [])])


if __name__ == "__main__":
    mcp.run()
