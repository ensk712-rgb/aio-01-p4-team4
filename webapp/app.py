#!/usr/bin/env python3
"""티켓모아 상담 채팅 웹앱: 채팅 화면을 내주고 질문을 n8n 웹훅 ticketmoa-support로 넘긴다.

팀 키(TM_TEAM_KEY)는 이 프로세스 안에만 있고 브라우저로 내려보내지 않는다.
표준 라이브러리만 쓴다.

  python3 webapp/app.py                  # 대상: TM_TARGET (기본 local → http://localhost:5678)
  TM_TARGET=vm python3 webapp/app.py     # 대상: VM n8n (TM_VM_N8N_URL)
"""

import json
import os
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBAPP_DIR / "static"
REPO = WEBAPP_DIR.parent
WEBHOOK = "ticketmoa-support"
WEBHOOK_TIMEOUT_SECONDS = 30
MAX_BODY_BYTES = 64 * 1024

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}

# 환경 변수의 프록시 설정이 localhost 호출을 가로채지 않게 한다.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    target: str
    n8n_url: str
    team_key: str


def parse_env_file(path):
    """`KEY=VALUE` 줄을 읽는다. 값을 감싼 따옴표는 벗긴다. 파일이 없으면 빈 사전."""
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


def load_config(environ=None, repo=REPO):
    """이미 있는 환경 변수가 저장소 뿌리 .env보다 우선한다."""
    environ = os.environ if environ is None else environ
    merged = {**parse_env_file(Path(repo) / ".env"), **environ}
    # .env의 TM_N8N_URL은 로컬 n8n 주소로 쓰이고 있으므로 vm일 때는 TM_VM_N8N_URL만 본다.
    target = (merged.get("TM_TARGET") or "local").lower()
    if target == "vm":
        n8n_url = merged.get("TM_VM_N8N_URL") or ""
        if not n8n_url:
            raise SystemExit("TM_TARGET=vm인데 TM_VM_N8N_URL이 없다")
    else:
        n8n_url = merged.get("TM_N8N_URL") or "http://localhost:5678"
    return Config(
        host=merged.get("TM_WEB_HOST") or "127.0.0.1",
        port=int(merged.get("TM_WEB_PORT") or 8080),
        target=target,
        n8n_url=n8n_url.rstrip("/"),
        team_key=merged.get("TM_TEAM_KEY") or "",
    )


def new_request_id():
    return f"web-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(2)}"


def build_request(payload):
    """화면이 보낸 값에서 공통 계약의 요청만 만든다. 모르는 키는 버린다."""
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    try:
        attempt = max(1, int(payload.get("attempt") or 1))
    except (TypeError, ValueError):
        attempt = 1
    return {
        "request_id": str(payload.get("request_id") or new_request_id())[:80],
        "user": str(payload.get("user") or ""),
        "channel": "web",
        "question": str(payload.get("question") or ""),
        "attempt": attempt,
        "context": context,
    }


def call_webhook(config, body):
    """(상태 코드, JSON 본문, 걸린 ms). 연결 실패·timeout은 (502, {"error"}, ms)."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{config.n8n_url}/webhook/{WEBHOOK}", data=data, method="POST",
        headers={"Content-Type": "application/json", "X-Team-Key": config.team_key},
    )
    started = time.monotonic()
    try:
        with _opener.open(req, timeout=WEBHOOK_TIMEOUT_SECONDS) as res:
            status, raw = res.status, res.read()
    except urllib.error.HTTPError as error:
        with error:
            status, raw = error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 502, {"error": f"n8n 연결 실패: {getattr(error, 'reason', error)}"}, int((time.monotonic() - started) * 1000)
    ms = int((time.monotonic() - started) * 1000)
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 502, {"error": "n8n 응답이 JSON이 아님", "upstream_status": status}, ms
    return status, parsed, ms


class Handler(BaseHTTPRequestHandler):
    server_version = "TicketmoaChat"
    sys_version = ""

    @property
    def config(self):
        return self.server.config

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
        self.send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), CONTENT_TYPES[".json"])

    def do_GET(self):
        path = self.path.partition("?")[0]
        if path == "/api/config":
            return self.send_json(200, {
                "target": self.config.target,
                "n8n_host": self.config.n8n_url.split("://", 1)[-1],
                "team_key_configured": bool(self.config.team_key),
                "users": json.loads((REPO / "data" / "users.json").read_text(encoding="utf-8")),
                "examples": json.loads((WEBAPP_DIR / "examples.json").read_text(encoding="utf-8")),
            })
        if path.startswith("/api/"):
            return self.send_json(404, {"error": "not found"})
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        file = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in file.parents or not file.is_file():
            return self.send_bytes(404, b"not found", "text/plain; charset=utf-8")
        self.send_bytes(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        if self.path.partition("?")[0] != "/api/chat":
            return self.send_json(404, {"error": "not found"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send_json(415, {"error": "application/json만 받는다"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            return self.send_json(413, {"error": "본문이 너무 크다"})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json(400, {"error": "JSON이 아님"})
        if not self.config.team_key:
            return self.send_json(503, {"error": "TM_TEAM_KEY가 설정되지 않음"})
        request = build_request(payload if isinstance(payload, dict) else {})
        status, body, ms = call_webhook(self.config, request)
        self.send_json(200, {"status": status, "body": body, "elapsed_ms": ms, "request": request})


def create_server(config):
    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.config = config
    return server


def main():
    config = load_config()
    server = create_server(config)
    print(f"티켓모아 상담 채팅: http://{config.host}:{config.port}")
    print(f"대상: {config.target} · n8n {config.n8n_url} · 팀 키 {'있음' if config.team_key else '없음 (전송 불가)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
