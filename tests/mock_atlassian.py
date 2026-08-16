"""Mock Atlassian REST 서버 — lean-atlassian-mcp 검증용 (실 API 키 없이 테스트)."""
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
        elif p == "/rest/api/3/issue/TEST-1/transitions":
            self._json({"transitions": [
                {"id": "31", "name": "진행 중", "to": {"name": "In Progress"}},
                {"id": "41", "name": "완료", "to": {"name": "Done"}},
            ]})
        elif p == "/rest/api/3/project/search":
            self._json(PROJECTS)
        elif p == "/rest/api/2/project":
            self._json(PROJECTS["values"])  # Server/DC v2는 배열 반환
        elif p == "/rest/api/content/search":
            cql = parse_qs(u.query).get("cql", [""])[0]
            expand = parse_qs(u.query).get("expand", [""])[0]
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
        elif p == "/rest/api/content" and parse_qs(u.query).get("spaceKey", [""])[0] == "DEV":
            self._json(SPACE_PAGES)
        elif p.startswith("/rest/api/content/12345"):
            self._json(PAGE)
        elif p == "/rest/api/space":
            self._json(SPACES)
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
