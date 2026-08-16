"""보안 기능 검증: 이슈키 형식 검증 + mTLS.

- 이슈키: 정상 통과 / 악성 입력 거부 / 커스텀 패턴(JIRA_ISSUE_KEY_PATTERN)
- mTLS: JIRA_CLIENT_CERT(+KEY)로 실제 PEM을 로드해 httpx 클라이언트 생성 확인
- 회귀: 스키마 크기 변화 없음은 measure_schema.py로 별도 확인
"""
import asyncio
import importlib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")
import lean_atlassian as la
from fastmcp import Client
from fastmcp.exceptions import ToolError

fails = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'✓' if ok else '✗'} {label}: {got}")
    if not ok:
        fails.append(label)


def unit_key_validation() -> None:
    os.environ["JIRA_URL"] = "http://127.0.0.1:8765"
    os.environ["JIRA_USERNAME"] = "test@test.com"
    os.environ["JIRA_API_TOKEN"] = "fake"
    m = importlib.reload(la)

    # 정상 키
    try:
        m._check_issue_key("TEST-1")
        check("정상 키 TEST-1 통과", True, True)
    except ValueError:
        check("정상 키 TEST-1 통과", False, True)

    # 비정상 키 (프롬프트 인젝션류)
    for bad in ["../../admin", "TEST-1/../../x", "test-1", "TEST", "PROJ--1", "1ME-23"]:
        try:
            m._check_issue_key(bad)
            check(f"거부: {bad}", "통과(위험!)", "거부")
        except ValueError:
            check(f"거부: {bad}", "거부", "거부")


def unit_custom_pattern() -> None:
    # 숫자로 시작하는 프로젝트키 (Server/DC 사례: 4ME-123)
    os.environ["JIRA_ISSUE_KEY_PATTERN"] = r"^[A-Z0-9][A-Z0-9_]*-\d+(?:-\d+)*$"
    m = importlib.reload(la)
    try:
        m._check_issue_key("4ME-123")
        check("커스텀 패턴 4ME-123", "통과", "통과")
    except ValueError:
        check("커스텀 패턴 4ME-123", "거부(실패)", "통과")


def unit_mtls() -> None:
    d = tempfile.mkdtemp()
    cert, key = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
         "-out", cert, "-days", "1", "-nodes", "-subj", "/CN=lean-test"],
        check=True, capture_output=True)
    os.environ["JIRA_CLIENT_CERT"] = cert
    os.environ["JIRA_CLIENT_KEY"] = key
    m = importlib.reload(la)
    try:
        c = m.jira_client()
        check("mTLS 인증서 로드 + 클라이언트 생성", "OK", "OK")
    except Exception as e:  # noqa: BLE001
        check(f"mTLS 클라이언트 생성: {type(e).__name__}", str(e)[:60], "OK")


async def _call(c, name, args):
    try:
        r = await c.call_tool(name, args)
        return getattr(r, "data", r)
    except ToolError as e:
        return str(e)


async def integration_guards() -> None:
    os.environ["JIRA_URL"] = "http://127.0.0.1:8765"
    os.environ["JIRA_USERNAME"] = "test@test.com"
    os.environ["JIRA_API_TOKEN"] = "fake"
    os.environ["CONFLUENCE_URL"] = "http://127.0.0.1:8765"
    os.environ["CONFLUENCE_USERNAME"] = "test@test.com"
    os.environ["CONFLUENCE_API_TOKEN"] = "fake"
    os.environ.pop("JIRA_PROJECTS_FILTER", None)
    os.environ.pop("CONFLUENCE_SPACES_FILTER", None)
    os.environ.pop("JIRA_ISSUE_KEY_PATTERN", None)
    os.environ.pop("JIRA_CLIENT_CERT", None)
    os.environ.pop("JIRA_CLIENT_KEY", None)
    m = importlib.reload(la)
    async with Client(m.mcp) as c:
        r = await _call(c, "jira_get", {"key": "TEST-1"})
        check("jira_get 정상 키 동작", r.get("key") if isinstance(r, dict) else r, "TEST-1")
        r = await _call(c, "jira_get", {"key": "../../admin"})
        check("jira_get 악성 키 거부", "형식이 아님" in str(r), True)
        r = await _call(c, "confluence_get", {"id": "../../admin"})
        check("confluence_get 경로조작 거부", "숫자만 허용" in str(r), True)
        r = await _call(c, "confluence_get_children", {"id": "12345?x=1"})
        check("children 쿼리주입 거부", "숫자만 허용" in str(r), True)
        r = await _call(c, "confluence_get", {"id": "12345", "max_chars": 10_000_000})
        body = (r.get("body") if isinstance(r, dict) else "") or ""
        check("max_chars 상한", len(body) <= m.BODY_CHARS, True)

    os.environ["JIRA_PROJECTS_FILTER"] = "PROJ"
    os.environ["CONFLUENCE_SPACES_FILTER"] = "PM"
    m = importlib.reload(la)
    async with Client(m.mcp) as c:
        r = await _call(c, "jira_get", {"key": "TEST-1"})
        check("jira_get 필터 전 거절", "없는 프로젝트" in str(r), True)
        r = await _call(c, "confluence_get", {"id": "12345"})
        check("confluence_get 스페이스 거절",
              isinstance(r, dict) and r.get("error") is not None, True)
        r = await _call(c, "confluence_space_tree", {"space_key": "../etc"})
        check("space_key 경로조작 거부", "형식이 아님" in str(r), True)


async def main() -> None:
    unit_key_validation()
    unit_custom_pattern()
    unit_mtls()
    await integration_guards()
    print(f"\n{'전부 통과' if not fails else f'실패: {fails}'}")


if __name__ == "__main__":
    asyncio.run(main())
