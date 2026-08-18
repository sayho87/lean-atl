"""Mock Atlassian REST 서버 — lean-atl 검증용 (실 API 키 없이 테스트)."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8765

ISSUE = {
    "id": "10101", "key": "TEST-1",
    "fields": {
        "project": {"key": "TEST"},
        "summary": "로그인 페이지 버튼 정렬 오류",
        "status": {"name": "In Progress"},
        "assignee": {"displayName": "홍길동"},
        "reporter": {"displayName": "세호"},
        "priority": {"name": "High"},
        "issuetype": {"name": "Bug"},
        "labels": ["frontend", "urgent"],
        "created": "2026-08-01T09:00:00.000+0900",
        "updated": "2026-08-15T14:30:00.000+0900",
        "description": {
            "type": "doc", "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "모바일에서 버튼이 겹침."}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "재현: iOS 18, 390px 뷰포트."}]},
            ],
        },
        "comment": {
            "total": 2,
            "comments": [
                {"id": "1", "author": {"displayName": "김개발"},
                 "created": "2026-08-02T10:00:00.000+0900",
                 "body": {"type": "doc", "version": 1, "content": [
                     {"type": "paragraph", "content": [{"type": "text", "text": "수정 진행 중입니다."}]}]}},
                {"id": "2", "author": {"displayName": "홍길동"},
                 "created": "2026-08-15T15:00:00.000+0900",
                 "body": {"type": "doc", "version": 1, "content": [
                     {"type": "paragraph", "content": [{"type": "text", "text": "내일 배포 예정."}]}]}},
            ],
        },
    },
}

PROJECTS = {"values": [
    {"key": "PROJ", "name": "프로젝트 알파"},
    {"key": "TEST", "name": "테스트 프로젝트"},
]}

SPACES = {"results": [
    {"key": "DEV", "name": "개발팀 스페이스", "type": "global"},
    {"key": "PM", "name": "기획팀 스페이스", "type": "global"},
]}

# 페이지네이션 검증용: 스페이스 120개 — 필터 대상 키(PromotionCell·ENMeProduct·productplan)는
# 정렬 순서상 뒤쪽(100번 이후)에 배치해 "첫 페이지에 안 잡히는" 실서버 상황을 재현한다.
_MANY_SPACES = (
    [{"key": "DEV", "name": "개발팀 스페이스", "type": "global"},
     {"key": "PM", "name": "기획팀 스페이스", "type": "global"}]
    + [{"key": f"SPACE_{i:03d}", "name": f"스페이스 {i:03d}", "type": "global"} for i in range(1, 112)]
    + [
        {"key": "PromotionCell", "name": "프로모션 셀", "type": "global"},
        {"key": "ENMeProduct", "name": "ENMe 상품", "type": "global"},
        {"key": "productplan", "name": "상품 계획", "type": "global"},
        {"key": "SPACE_112", "name": "스페이스 112", "type": "global"},
        {"key": "SPACE_113", "name": "스페이스 113", "type": "global"},
        {"key": "SPACE_114", "name": "스페이스 114", "type": "global"},
        {"key": "SPACE_115", "name": "스페이스 115", "type": "global"},
        {"key": "SPACE_116", "name": "스페이스 116", "type": "global"},
        {"key": "SPACE_117", "name": "스페이스 117", "type": "global"},
        {"key": "SPACE_118", "name": "스페이스 118", "type": "global"},
        {"key": "SPACE_119", "name": "스페이스 119", "type": "global"},
        {"key": "SPACE_120", "name": "스페이스 120", "type": "global"},
    ]
)

PAGE = {
    "id": "12345", "title": "릴리스 노트 3.2",
    "space": {"key": "DEV"},
    "body": {"storage": {"value": "<p>3.2 릴리스 내용</p><ul><li>버그 12건 수정</li><li>성능 개선 30%</li></ul><p>자세한 내용은 <a href='#'>링크</a> 참고.</p>"}},
}

CHILDREN = {"results": [
    {"id": "12350", "title": "3.2 백엔드 변경점", "space": {"key": "DEV"}},
    {"id": "12351", "title": "3.2 프론트엔드 변경점", "space": {"key": "DEV"}},
]}

COMMENTS = {"results": [
    {"id": "30001", "author": {"displayName": "홍길동"},
     "created": "2026-08-16T09:00:00.000+0900",
     "body": {"storage": {"value": "<p>3.2에 배포 일정이 빠져 있어요.</p>"}}},
    {"id": "30002", "author": {"displayName": "김기획"},
     "created": "2026-08-16T11:30:00.000+0900",
     "body": {"storage": {"value": "<p>일정 추가했습니다. <a href='#'>링크</a> 참고.</p>"}}},
]}

# spaceKey=DEV 트리: A(최상위) → A-1 → A-1-1, B(최상위)
SPACE_PAGES = {"results": [
    {"id": "20001", "title": "개발 가이드", "space": {"key": "DEV"}, "ancestors": []},
    {"id": "20002", "title": "API 문서", "space": {"key": "DEV"},
     "ancestors": [{"id": "20001", "title": "개발 가이드"}]},
    {"id": "20003", "title": "인증 API", "space": {"key": "DEV"},
     "ancestors": [{"id": "20001", "title": "개발 가이드"}, {"id": "20002", "title": "API 문서"}]},
    {"id": "20004", "title": "배포 프로세스", "space": {"key": "DEV"}, "ancestors": []},
]}


class H(BaseHTTPRequestHandler):
    # 5xx 재시도 검증용: FLAP-1은 첫 호출만 503, 이후 200
    flap_count = 0

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/rest/api/3/search" or p == "/rest/api/2/search":
            self._json({"issues": [ISSUE]})
        elif p == "/rest/api/3/issue/TEST-1":
            self._json(ISSUE)
        elif p == "/rest/api/3/issue/FLAP-1":
            H.flap_count += 1
            if H.flap_count == 1:
                self._json({"error": "temporary server error"}, 503)
            else:
                self._json(ISSUE)
        elif p == "/rest/api/3/issue/TEST-1/transitions":
            self._json({"transitions": [
                {"id": "31", "name": "진행 중", "to": {"name": "In Progress"}},
                {"id": "41", "name": "완료", "to": {"name": "Done"}},
            ]})
        elif p == "/rest/api/3/project/search":
            self._json(PROJECTS)
        elif p == "/rest/api/2/project":
            self._json(PROJECTS["values"])  # Server/DC v2는 배열 반환
        elif p == "/rest/api/search":
            cql = parse_qs(u.query).get("cql", [""])[0]
            if "siteSearch" in cql:
                self._json({"results": [{
                    "content": {
                        "id": "182209768", "type": "page",
                        "title": "다운로드 쿠폰안",
                        "space": {"key": "productplan", "name": "상품 계획"},
                    },
                    "excerpt": "쿠폰 받기 버튼 노출 조건",
                }]})
            elif "currentUser" in cql and "주간" in cql:
                self._json({"results": [{
                    "content": {
                        "id": "70001", "type": "page",
                        "title": "8월 3주 주간보고",
                    },
                    "resultGlobalContainer": {
                        "title": "개발팀 스페이스",
                        "displayUrl": "/display/DEV/8월+3주+주간보고",
                    },
                    "excerpt": "금주 진행 사항",
                }]})
            else:
                self._json({"results": []})
        elif p == "/rest/api/content/search":
            cql = parse_qs(u.query).get("cql", [""])[0]
            expand = parse_qs(u.query).get("expand", [""])[0]
            if "없는고유어" in cql:
                results = []
            elif "주간" in cql or "currentUser" in cql:
                results = [
                    {"id": "70001", "title": "8월 3주 주간보고",
                     "space": {"key": "DEV"}, "type": "page"},
                ]
            elif "HIDDENDOC" in cql:
                results = [
                    {"id": "90001", "title": "숨은 문서",
                     "space": {"key": "HIDDENDOC", "name": "숨은 스페이스"},
                     "ancestors": []},
                ]
            else:
                cql_cf = cql.casefold()
                known = {s["key"].casefold(): s for s in _MANY_SPACES}
                hit = next((s for cf, s in known.items()
                            if cf in cql_cf and "space" in cql_cf
                            and cf not in ("dev",)), None)
                if hit:
                    results = [{"id": "80001", "title": f"{hit['key']} 문서",
                                "space": hit, "ancestors": []}]
                else:
                    results = [
                        {"id": "12345", "title": "릴리스 노트 3.2", "space": {"key": "DEV"}},
                        {"id": "12346", "title": "릴리스 노트 3.1", "space": {"key": "DEV"}},
                    ]
                    if "3.2" in cql:
                        results = results[:1]
            if "body.storage" in expand:
                for r in results:
                    r["body"] = {"storage": {"value": PAGE["body"]["storage"]["value"]}}
            self._json({"results": results})
        elif p.startswith("/rest/api/content/12345/child/page"):
            self._json(CHILDREN)
        elif p.startswith("/rest/api/content/12345/child/comment"):
            self._json(COMMENTS)
        elif p == "/rest/api/content":
            sk = parse_qs(u.query).get("spaceKey", [""])[0]
            if sk == "DEV":
                self._json(SPACE_PAGES)
            else:
                # 실서버 재현: 목록/단건에 없는 공간은 spaceKey 조회도 404
                self._json({"error": f"space not found: {sk}"}, 404)
        elif p.startswith("/rest/api/content/12345"):
            self._json(PAGE)
        elif p.startswith("/rest/api/space/"):
            key = p[len("/rest/api/space/"):]
            found = next((s for s in _MANY_SPACES if s["key"] == key), None)
            if found:
                self._json(found)
            else:
                self._json({"error": f"space not found: {key}"}, 404)
        elif p == "/rest/api/space":
            # 실제 Confluence 페이지네이션 응답 형식: results/start/limit/size/_links.next
            q = parse_qs(u.query)
            start = int(q.get("start", ["0"])[0])
            limit = int(q.get("limit", ["25"])[0])
            source = _MANY_SPACES
            page = source[start:start + limit]
            resp = {
                "results": page,
                "start": start,
                "limit": limit,
                "size": len(page),
                "_links": {
                    "base": "http://127.0.0.1:8765",
                    "self": f"/rest/api/space?limit={limit}&start={start}",
                },
            }
            if start + len(page) < len(source):
                resp["_links"]["next"] = f"/rest/api/space?limit={limit}&start={start + len(page)}"
            self._json(resp)
        else:
            self._json({"error": f"not mocked: {p}"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if u.path == "/rest/api/3/issue":
            self._json({"id": "999", "key": "TEST-99"}, 201)
        elif u.path == "/rest/api/3/issue/TEST-1/transitions":
            self._json({}, 204)
        elif u.path == "/rest/api/3/issue/TEST-1/comment":
            self._json({"id": "777"}, 201)
        else:
            self._json({"error": f"not mocked: {u.path}"}, 404)


if __name__ == "__main__":
    print(f"mock atlassian on http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
