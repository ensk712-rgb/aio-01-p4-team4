"""스텁 n8n·데이터 API를 임시 포트에 띄워 웹앱 프록시를 검증한다.

실행: python3 -m unittest webapp/test_app.py -v
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app  # noqa: E402

app.Handler.log_message = lambda *args: None  # 테스트 출력에 접속 로그가 섞이지 않게 한다.

TEAM_KEY = "test-team-key"
REPO = Path(__file__).resolve().parent.parent


class Stub(BaseHTTPRequestHandler):
    """받은 요청을 server.calls에 기록하고 경로별로 답한다."""

    def log_message(self, *args):
        pass

    def reply(self, status, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.server.calls.append({
            "method": self.command,
            "path": self.path,
            "key": self.headers.get("X-Team-Key"),
            "body": body,
        })
        self.server.respond(self, body)

    do_GET = handle_any
    do_POST = handle_any


def respond_n8n(handler, body):
    path = handler.path
    if path == "/healthz":
        return handler.reply(200, {"status": "ok"})
    if handler.headers.get("X-Team-Key") != TEAM_KEY:
        return handler.reply(403, b"Authorization data is wrong!", "text/plain")
    if path == "/webhook/ticketmoa-ops":
        return handler.reply(200, {"total": 3, "echo": json.loads(body)})
    if path == "/webhook/ticketmoa-support":
        question = json.loads(body).get("question")
        if not question:
            return handler.reply(400, {"error": "invalid request", "codes": ["empty_question"]})
        if question == "html":
            return handler.reply(200, b"<html></html>", "text/html")
        return handler.reply(200, {"request_id": "r1", "route": "자동 답변", "answer": question})
    return handler.reply(404, {"message": "not registered"})


def respond_data(handler, body):
    return handler.reply(200, {"path": handler.path, "method": handler.command})


def start_stub(respond):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    server.calls = []
    server.respond = respond
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def closed_port_url():
    """닫힌 포트를 얻어 연결 실패를 재현한다."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    server.server_close()
    return f"http://127.0.0.1:{port}"


class WebappCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.n8n = start_stub(respond_n8n)
        cls.data = start_stub(respond_data)
        cls.base_config = app.Config(
            host="127.0.0.1",
            port=0,
            n8n_url=f"http://127.0.0.1:{cls.n8n.server_address[1]}",
            team_key=TEAM_KEY,
            data_api_url=f"http://127.0.0.1:{cls.data.server_address[1]}",
            users_file=REPO / "data" / "users.json",
            repo=REPO,
        )
        cls.web = cls.start_web(cls.base_config)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.web, cls.n8n, cls.data):
            server.shutdown()
            server.server_close()

    @classmethod
    def start_web(cls, config):
        server = app.create_server(config)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def setUp(self):
        self.n8n.calls.clear()
        self.data.calls.clear()

    def request(self, method, path, body=None, headers=None, server=None):
        """http.client를 써서 `..` 같은 경로가 정규화되지 않은 채 서버에 닿게 한다."""
        port = (server or self.web).server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        all_headers = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            all_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=payload, headers=all_headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response, raw

    def request_json(self, method, path, body=None, **kwargs):
        response, raw = self.request(method, path, body, **kwargs)
        return response.status, json.loads(raw)


class SupportProxyTest(WebappCase):
    def test_200_전달과_팀_키(self):
        status, body = self.request_json("POST", "/api/support", {"question": "QR"})
        self.assertEqual(status, 200)
        self.assertEqual(body["route"], "자동 답변")
        self.assertEqual(self.n8n.calls[0]["key"], TEAM_KEY)
        self.assertEqual(self.n8n.calls[0]["path"], "/webhook/ticketmoa-support")

    def test_400_상태와_본문을_그대로_전달(self):
        status, body = self.request_json("POST", "/api/support", {"question": ""})
        self.assertEqual(status, 400)
        self.assertEqual(body, {"error": "invalid request", "codes": ["empty_question"]})

    def test_키_미설정이면_503이고_업스트림을_부르지_않음(self):
        config = app.Config(**{**self.base_config.__dict__, "team_key": ""})
        web = self.start_web(config)
        try:
            for path in ("/api/support", "/api/ops"):
                status, _ = self.request_json("POST", path, {"question": "QR"}, server=web)
                self.assertEqual(status, 503)
            self.assertEqual(self.n8n.calls, [])
        finally:
            web.shutdown()
            web.server_close()

    def test_틀린_키는_상태를_유지하고_키를_노출하지_않음(self):
        config = app.Config(**{**self.base_config.__dict__, "team_key": "wrong-key-value"})
        web = self.start_web(config)
        try:
            response, raw = self.request("POST", "/api/support", {"question": "QR"}, server=web)
            self.assertEqual(response.status, 403)
            self.assertNotIn(b"wrong-key-value", raw)
        finally:
            web.shutdown()
            web.server_close()

    def test_업스트림_연결_실패는_502(self):
        config = app.Config(**{**self.base_config.__dict__, "n8n_url": closed_port_url()})
        web = self.start_web(config)
        try:
            status, body = self.request_json("POST", "/api/support", {"question": "QR"}, server=web)
            self.assertEqual(status, 502)
            self.assertIn("error", body)
        finally:
            web.shutdown()
            web.server_close()

    def test_200인데_JSON이_아니면_502(self):
        status, body = self.request_json("POST", "/api/support", {"question": "html"})
        self.assertEqual(status, 502)
        self.assertEqual(body["upstream_status"], 200)

    def test_JSON이_아닌_요청은_415_깨진_JSON은_400(self):
        response, _ = self.request("POST", "/api/support", headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status, 415)
        connection = http.client.HTTPConnection("127.0.0.1", self.web.server_address[1], timeout=10)
        connection.request("POST", "/api/support", body=b"{broken", headers={"Content-Type": "application/json"})
        self.assertEqual(connection.getresponse().status, 400)
        connection.close()
        self.assertEqual(self.n8n.calls, [])

    def test_ops_웹훅(self):
        status, body = self.request_json("POST", "/api/ops", {"from": "2026-11-01", "to": "2026-11-02"})
        self.assertEqual(status, 200)
        self.assertEqual(body["echo"]["to"], "2026-11-02")
        self.assertEqual(self.n8n.calls[0]["path"], "/webhook/ticketmoa-ops")


class DataProxyTest(WebappCase):
    def test_허용_경로의_GET과_쿼리_전달(self):
        status, body = self.request_json("GET", "/api/data/logs?source=live&from=2026-11-01&to=2026-11-02")
        self.assertEqual(status, 200)
        self.assertEqual(body["path"], "/logs?source=live&from=2026-11-01&to=2026-11-02")

    def test_모든_허용_경로가_정해진_메서드로_통과(self):
        for name, methods in app.DATA_ROUTES.items():
            for method in methods:
                body = {} if method == "POST" else None
                status, result = self.request_json(method, f"/api/data/{name}", body)
                self.assertEqual(status, 200, name)
                self.assertEqual(result["path"], f"/{name}")

    def test_장애_주입_본문_전달(self):
        status, _ = self.request_json("POST", "/api/data/admin/fault", {"tickets": "error"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.data.calls[0]["body"]), {"tickets": "error"})

    def test_화이트리스트_밖은_404(self):
        for path in ("tickets/C-2001", "cache/x", "employees", "logs/query", "admin/fault/../../employees", ""):
            status, _ = self.request_json("GET", f"/api/data/{path}")
            self.assertEqual(status, 404, path)
        self.assertEqual(self.data.calls, [])

    def test_읽기_경로에_POST와_초기화에_GET은_405(self):
        self.assertEqual(self.request_json("POST", "/api/data/logs", {})[0], 405)
        self.assertEqual(self.request_json("POST", "/api/data/dlq", {})[0], 405)
        self.assertEqual(self.request_json("GET", "/api/data/tickets-reset")[0], 405)
        self.assertEqual(self.data.calls, [])

    def test_데이터_API에_팀_키를_보내지_않음(self):
        self.request_json("GET", "/api/data/health")
        self.assertIsNone(self.data.calls[0]["key"])


class StaticAndOwnApiTest(WebappCase):
    def test_첫_화면과_정적_파일(self):
        for path, expected in (
            ("/", "text/html"),
            ("/static/app.js", "text/javascript"),
            ("/static/style.css", "text/css"),
        ):
            response, _ = self.request("GET", path)
            self.assertEqual(response.status, 200, path)
            self.assertIn(expected, response.getheader("Content-Type"))

    def test_경로_탈출_차단(self):
        for path in (
            "/static/../app.py",
            "/static/%2e%2e/app.py",
            "/static/..%2f..%2fdata%2fusers.json",
            "/static/%2e%2e%2f%2e%2e%2fAGENTS.md",
            "/static//etc/passwd",
            "/static/%2fetc%2fpasswd",
            "/static/..%5capp.py",
            "/static/a%00b",
            "/static/",
            "/app.py",
            "/../AGENTS.md",
        ):
            response, raw = self.request("GET", path)
            self.assertEqual(response.status, 404, path)
            self.assertNotIn(b"import", raw)

    def test_사용자_목록은_파일_그대로(self):
        response, raw = self.request("GET", "/api/users")
        self.assertEqual(response.status, 200)
        self.assertEqual(raw, (REPO / "data" / "users.json").read_bytes())

    def test_프리셋_개수는_저장소_파일과_일치(self):
        status, presets = self.request_json("GET", "/api/presets")
        self.assertEqual(status, 200)
        by_group = {}
        for preset in presets:
            self.assertEqual(set(preset), {"group", "name", "request"})
            by_group[preset["group"]] = by_group.get(preset["group"], 0) + 1
        self.assertEqual(by_group, {
            "requests": len(list((REPO / "requests").glob("*.json"))),
            "common": len(json.loads((REPO / "cases/common.json").read_text(encoding="utf-8"))["cases"]),
            "team": len(json.loads((REPO / "cases/team.json").read_text(encoding="utf-8"))["cases"]),
        })

    def test_프리셋_조립(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / "requests").mkdir()
            (repo / "cases").mkdir()
            (repo / "requests" / "a.json").write_text('{"request_id": "a"}', encoding="utf-8")
            (repo / "cases" / "team.json").write_text(
                '{"cases": [{"name": "T", "body": {"request_id": "t"}, "expect": {}}]}', encoding="utf-8")
            self.assertEqual(app.load_presets(repo), [
                {"group": "requests", "name": "a", "request": {"request_id": "a"}},
                {"group": "team", "name": "T", "request": {"request_id": "t"}},
            ])

    def test_상태_요약에_키_값이_없음(self):
        response, raw = self.request("GET", "/api/status")
        status = json.loads(raw)
        self.assertEqual(response.status, 200)
        self.assertTrue(status["n8n"]["ok"])
        self.assertTrue(status["data_api"]["ok"])
        self.assertTrue(status["team_key_configured"])
        self.assertNotIn(TEAM_KEY.encode(), raw)

    def test_없는_API는_404(self):
        self.assertEqual(self.request_json("GET", "/api/none")[0], 404)
        self.assertEqual(self.request_json("GET", "/api/support")[0], 404)


class ConfigTest(unittest.TestCase):
    def test_env_파일은_기본값이고_환경변수가_우선(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, ".env").write_text(
                '﻿# 주석\nTM_TEAM_KEY="from-file"\nexport TM_PORT=9001\nTM_N8N_URL=http://file/\nBROKEN\n',
                encoding="utf-8",
            )
            config = app.load_config({"TM_REPO": folder, "TM_N8N_URL": "http://env/"})
        self.assertEqual(config.team_key, "from-file")
        self.assertEqual(config.port, 9001)
        self.assertEqual(config.n8n_url, "http://env")

    def test_기본값(self):
        with tempfile.TemporaryDirectory() as folder:
            config = app.load_config({"TM_REPO": folder})
        self.assertEqual((config.host, config.port), ("127.0.0.1", 8080))
        self.assertEqual(config.n8n_url, "http://localhost:5678")
        self.assertEqual(config.data_api_url, "http://localhost:8800")
        self.assertEqual(config.team_key, "")
        self.assertEqual(config.users_file, Path(folder).resolve() / "data" / "users.json")


if __name__ == "__main__":
    unittest.main()
