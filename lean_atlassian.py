"""lean-atlassian-mcp — mcp-atlassian(98 tools)보다 토큰을 아껴 먹는 Jira/Confluence MCP.

절약 설계:
- 도구 10개 (mcp-atlassian의 98개 대비) → 매 요청마다 전송되는 도구 정의 스키마가 1/10
- docstring 한 줄, 파라미터 설명 최소화 → 스키마 크기 축소
- 결과는 핵심 필드만, 목록은 limit 캡, 긴 본문은 max_chars로 서버에서 잘라서 반환
- Confluence HTML 본문을 서버에서 plain text로 변환 (원본 HTML 반환 금지)
- Jira REST도 fields= 명시 → 와이어 응답 자체가 작음

환경변수:
  ATLASSIAN_SITE_URL     예: https://your-domain.atlassian.net
  ATLASSIAN_USER_EMAIL   계정 이메일
  ATLASSIAN_API_TOKEN    https://id.atlassian.com/manage-profile/security/api-tokens
  LEAN_MAX_RESULTS       목록 기본 캡 (기본 20)
  LEAN_BODY_CHARS        본문 기본 캡 (기본 8000)
"""

from __future__ import annotations

import html
import os
import re
from typing import Any

import httpx
from fastmcp import FastMCP

mcp = FastMCP("lean-atlassian")

SITE = os.environ.get("ATLASSIAN_SITE_URL", "").rstrip("/")
EMAIL = os.environ.get("ATLASSIAN_USER_EMAIL", "")
TOKEN = os.environ.get("ATLASSIAN_API_TOKEN", "")
MAX_RESULTS = int(os.environ.get("LEAN_MAX_RESULTS", "20"))
BODY_CHARS = int(os.environ.get("LEAN_BODY_CHARS", "8000"))

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        if not (SITE and EMAIL and TOKEN):
            raise RuntimeError(
                "ATLASSIAN_SITE_URL / ATLASSIAN_USER_EMAIL / ATLASSIAN_API_TOKEN 필요"
            )
        _client = httpx.Client(base_url=SITE, auth=(EMAIL, TOKEN), timeout=30)
    return _client


def _get(path: str, **params: Any) -> dict:
    r = client().get(path, params={k: v for k, v in params.items() if v is not None})
    r.raise_for_status()
    return r.json()


def _post(path: str, payload: dict) -> dict:
    r = client().post(path, json=payload)
    r.raise_for_status()
    if r.status_code == 204 or not r.content:
        return {}
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


# ---------- Jira 도구 ----------

@mcp.tool
def jira_search(jql: str, limit: int = 20) -> list[dict]:
    """JQL로 이슈를 검색하고 핵심 필드만 돌려준다."""
    data = _get("/rest/api/3/search", jql=jql,
                fields="summary,status,assignee,priority,labels,updated",
                maxResults=min(limit, MAX_RESULTS))
    out = []
    for it in data.get("issues", []):
        f = it.get("fields", {})
        out.append({
            "key": it.get("key"),
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
    data = _get(f"/rest/api/3/issue/{key}",
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
        "url": f"{SITE}/browse/{data.get('key')}",
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
    data = _get("/rest/api/3/project/search", maxResults=100)
    return [{"key": p.get("key"), "name": p.get("name")}
            for p in data.get("values", [])]


# ---------- Confluence 도구 ----------

@mcp.tool
def confluence_search(cql: str, limit: int = 20, include_snippet: bool = False) -> list[dict]:
    """CQL로 페이지 검색. include_snippet=True면 본문 첫 200자 포함."""
    data = _get("/rest/api/content/search", cql=cql,
                limit=min(limit, MAX_RESULTS),
                expand="body.storage" if include_snippet else None)
    out = []
    for it in data.get("results", []):
        sp = (it.get("space") or {}).get("key")
        item = {
            "id": it.get("id"),
            "title": it.get("title"),
            "space": sp,
            "url": f"{SITE}/spaces/{sp}/pages/{it.get('id')}",
        }
        if include_snippet:
            storage = (it.get("body") or {}).get("storage", {}).get("value", "")
            item["snippet"] = _html_to_text(storage, 200)
        out.append(item)
    return out


@mcp.tool
def confluence_get_children(id: str, limit: int = 50) -> list[dict]:
    """페이지의 하위 페이지 목록(id, 제목)."""
    data = _get(f"/rest/api/content/{id}/child/page", limit=min(limit, MAX_RESULTS))
    return [{"id": p.get("id"), "title": p.get("title"),
             "url": f"{SITE}/pages/{p.get('id')}"}
            for p in data.get("results", [])]


@mcp.tool
def confluence_space_tree(space_key: str, max_depth: int = 2, limit: int = 100) -> dict:
    """스페이스의 페이지 트리. max_depth까지 제목만, 본문 없음."""
    data = _get("/rest/api/content", spaceKey=space_key, type="page",
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
    data = _get(f"/rest/api/content/{id}", expand="body.storage,space")
    sp = (data.get("space") or {}).get("key")
    storage = (data.get("body") or {}).get("storage", {}).get("value", "")
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "space": sp,
        "url": f"{SITE}/spaces/{sp}/pages/{data.get('id')}",
        "body": _html_to_text(storage, max_chars),
    }


@mcp.tool
def confluence_spaces() -> list[dict]:
    """스페이스 목록(key, 이름)."""
    data = _get("/rest/api/space", limit=50)
    return [{"key": s.get("key"), "name": s.get("name"), "type": s.get("type")}
            for s in data.get("results", [])]


if __name__ == "__main__":
    mcp.run()
