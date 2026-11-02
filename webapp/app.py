#!/usr/bin/env python3
"""티켓모아 시연 웹앱: 정적 화면을 내주고 n8n 웹훅과 데이터 API로 요청을 넘긴다.

팀 키(TM_TEAM_KEY)는 이 프로세스 안에만 있고 브라우저로 내려보내지 않는다.
표준 라이브러리만 쓰며 Windows와 Ubuntu에서 같은 명령으로 실행한다.
"""

import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBAPP_DIR / "static"
DEFAULT_REPO = WEBAPP_DIR.parent

MAX_BODY_BYTES = 1024 * 1024
WEBHOOK_TIMEOUT_SECONDS = 30
DATA_TIMEOUT_SECONDS = 10
STATUS_TIMEOUT_SECONDS = 3

# 데이터 API 화이트리스트. 읽기 경로에 POST를 열면 /logs·/dlq에 가짜 기록을 쓸 수 있어 메서드까지 제한한다.
DATA_ROUTES = {
    "health": {"GET"},
    "tickets-created": {"GET"},
    "alerts": {"GET"},
    "dlq": {"GET"},
    "logs": {"GET"},
    "cache-stats": {"GET"},
    "admin/fault": {"GET", "POST"},
    "tickets-reset": {"POST"},
    "dlq-clear": {"POST"},
    "alerts-clear": {"POST"},
    "cache-clear": {"POST"},
    "logs-reset": {"POST"},
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}

# 환경 변수의 프록시 설정이 localhost 호출을 가로채지 않게 한다.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    n8n_url: str
    team_key: str
    data_api_url: str
    users_file: Path
    repo: Path


def parse_env_file(path):
    """`KEY=VALUE` 줄을 읽는다. 파일이 없으면 빈 사전."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_config(environ=None):
    """이미 있는 환경 변수가 저장소 뿌리 .env보다 우선한다."""
    environ = os.environ if environ is None else environ
    repo = Path(environ.get("TM_REPO") or DEFAULT_REPO).resolve()
    merged = {**parse_env_file(repo / ".env"), **environ}
    return Config(
        host=merged.get("TM_HOST") or "127.0.0.1",
        port=int(merged.get("TM_PORT") or 8080),
        n8n_url=(merged.get("TM_N8N_URL") or "http://localhost:5678").rstrip("/"),
        team_key=merged.get("TM_TEAM_KEY") or "",
        data_api_url=(merged.get("TM_DATA_API_URL") or "http://localhost:8800").rstrip("/"),
        users_file=Path(merged.get("TM_USERS_FILE") or repo / "data" / "users.json"),
        repo=repo,
    )


def load_presets(repo):
    """시연 프리셋: requests/*.json과 cases의 각 case 요청 본문."""
    presets = []
    for path in sorted((repo / "requests").glob("*.json")):
        presets.append({
            "group": "requests",
            "name": path.stem,
            "request": json.loads(path.read_text(encoding="utf-8")),
        })
    for group in ("common", "team"):
        path = repo / "cases" / f"{group}.json"
        if not path.exists():
            continue
        for case in json.loads(path.read_text(encoding="utf-8")).get("cases", []):
            presets.append({"group": group, "name": case["name"], "request": case["body"]})
    return presets


def call_upstream(method, url, body=None, headers=None, timeout=DATA_TIMEOUT_SECONDS):
    """(상태 코드, 본문 바이트)를 돌려준다. 4xx·5xx도 정상 반환이고 연결 실패만 예외다."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with _opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read()


class Handler(BaseHTTPRequestHandler):
    server_version = "TicketmoaWeb"
    sys_version = ""

    @property
    def config(self):
        return self.server.config

    # --- 응답 ---

    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    # --- 라우팅 ---

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        path, _, query = self.path.partition("?")
        try:
            if path.startswith("/api/"):
                self.route_api(method, path, query)
            elif method == "GET":
                self.serve_static(path)
            else:
                self.send_json(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as error:  # 화면이 원인을 볼 수 있게 JSON으로 답하고 내용은 서버 로그에만 남긴다.
            self.log_error("처리 실패 %s %s: %r", method, path, error)
            self.send_json(500, {"error": "internal error"})

    def route_api(self, method, path, query):
        if path.startswith("/api/data/"):
            return self.proxy_data(method, path.removeprefix("/api/data/"), query)
        routes = {
            ("GET", "/api/users"): self.get_users,
            ("GET", "/api/presets"): lambda: self.send_json(200, load_presets(self.config.repo)),
            ("GET", "/api/status"): self.get_status,
            ("POST", "/api/support"): lambda: self.proxy_webhook("ticketmoa-support"),
            ("POST", "/api/ops"): lambda: self.proxy_webhook("ticketmoa-ops"),
        }
        handler = routes.get((method, path))
        if handler is None:
            return self.send_json(404, {"error": "not found"})
        return handler()

    # --- 자체 API ---

    def get_users(self):
        self.send_bytes(200, self.config.users_file.read_bytes(), "application/json; charset=utf-8")

    def get_status(self):
        self.send_json(200, {
            "data_api": self.probe(f"{self.config.data_api_url}/health"),
            "n8n": self.probe(f"{self.config.n8n_url}/healthz"),
            "team_key_configured": bool(self.config.team_key),
        })

    @staticmethod
    def probe(url):
        try:
            status, _ = call_upstream("GET", url, timeout=STATUS_TIMEOUT_SECONDS)
        except (OSError, http.client.HTTPException) as error:
            return {"ok": False, "detail": type(error).__name__}
        return {"ok": 200 <= status < 300, "detail": f"HTTP {status}"}

    # --- 프록시 ---

    def read_body(self):
        """POST 본문을 읽는다. 실패하면 이미 응답을 보내고 None을 돌려준다.

        application/json을 요구해야 다른 사이트의 폼 전송(CSRF)이 사전 요청에서 막힌다.
        """
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self.send_json(415, {"error": "Content-Type은 application/json이어야 합니다"})
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self.send_json(400, {"error": "Content-Length가 잘못되었습니다"})
            return None
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            self.send_json(413, {"error": "요청 본문이 너무 큽니다"})
            return None
        return self.rfile.read(length)

    def proxy_webhook(self, webhook):
        raw = self.read_body()
        if raw is None:
            return
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            return self.send_json(400, {"error": "요청 본문은 JSON 객체여야 합니다"})
        if not self.config.team_key:
            return self.send_json(503, {"error": "TM_TEAM_KEY가 설정되지 않았습니다"})
        self.relay(
            "n8n", "POST", f"{self.config.n8n_url}/webhook/{webhook}", raw,
            {"Content-Type": "application/json", "X-Team-Key": self.config.team_key},
            WEBHOOK_TIMEOUT_SECONDS,
        )

    def proxy_data(self, method, name, query):
        allowed = DATA_ROUTES.get(name)
        if allowed is None:
            return self.send_json(404, {"error": "허용되지 않은 경로입니다"})
        if method not in allowed:
            return self.send_json(405, {"error": "허용되지 않은 메서드입니다"})
        body = None
        headers = {}
        if method == "POST":
            body = self.read_body()
            if body is None:
                return
            body = body or b"{}"
            headers["Content-Type"] = "application/json"
        url = f"{self.config.data_api_url}/{name}"
        if query:
            url += f"?{query}"
        self.relay("데이터 API", method, url, body, headers, DATA_TIMEOUT_SECONDS)

    def relay(self, label, method, url, body, headers, timeout):
        """상태 코드와 JSON 본문을 그대로 돌려준다."""
        try:
            status, raw = call_upstream(method, url, body, headers, timeout)
        except (OSError, http.client.HTTPException, ValueError) as error:
            return self.send_json(502, {"error": f"{label} 연결 실패: {type(error).__name__}"})
        try:
            json.loads(raw)
        except ValueError:
            # 상태 코드는 남겨 키 오류(403)와 빈 응답을 화면에서 구분할 수 있게 한다.
            return self.send_json(status if status >= 400 else 502, {
                "error": f"{label}가 JSON이 아닌 응답을 보냈습니다",
                "upstream_status": status,
            })
        self.send_bytes(status, raw, "application/json; charset=utf-8")

    # --- 정적 파일 ---

    def serve_static(self, path):
        if path == "/favicon.ico":
            return self.send_bytes(204, b"", "image/x-icon")
        if path == "/":
            relative = "index.html"
        elif path.startswith("/static/"):
            relative = urllib.parse.unquote(path.removeprefix("/static/"))
        else:
            return self.send_json(404, {"error": "not found"})
        base = STATIC_DIR.resolve()
        try:
            target = (base / relative).resolve()
            is_file = target.is_relative_to(base) and target.is_file()
        except (OSError, ValueError):
            is_file = False
        if not is_file:
            return self.send_json(404, {"error": "not found"})
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send_bytes(200, target.read_bytes(), content_type)


def create_server(config):
    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.daemon_threads = True
    server.config = config
    return server


def main():
    config = load_config()
    if not config.team_key:
        print("[경고] TM_TEAM_KEY가 없습니다. /api/support, /api/ops는 503으로 답합니다.", file=sys.stderr)
    server = create_server(config)
    print(f"티켓모아 웹앱: http://{config.host}:{server.server_address[1]}", flush=True)
    print(f"n8n: {config.n8n_url} / 데이터 API: {config.data_api_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
