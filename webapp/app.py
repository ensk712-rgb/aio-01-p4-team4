#!/usr/bin/env python3
"""티켓모아 상담 채팅 웹앱: 채팅 화면을 내주고 질문을 n8n 웹훅 ticketmoa-support로 넘긴다.

팀 키(TM_TEAM_KEY)는 이 프로세스 안에만 있고 브라우저로 내려보내지 않는다.
표준 라이브러리만 쓴다.

  python3 webapp/app.py                  # 대상: TM_TARGET (기본 local → http://localhost:5678)
  TM_TARGET=vm python3 webapp/app.py     # 대상: VM n8n (TM_VM_N8N_URL)

/        고객 상담 채팅
/admin   관리자 화면 (대화 기록·장애 패널·티켓·알림·DLQ)
/demo    고객 + 관리자 나란히 (발표용)
"""

import base64
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBAPP_DIR / "static"
REPO = WEBAPP_DIR.parent
WEBHOOK = "ticketmoa-support"
OPS_WEBHOOK = "ticketmoa-ops"
CHAT_LOG = WEBAPP_DIR / "var" / "chats.jsonl"
CHAT_KEEP = 500
# 관리자 화면이 읽는 데이터 API (읽기 전용). local은 직접, vm은 ticketmoa-ops 웹훅으로 같은 op를 부른다.
OPS = {
    "tickets": "/tickets-created",
    "alerts": "/alerts",
    "dlq": "/dlq",
    "logs": "/logs?limit=200",
    "fault": "/admin/fault",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
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
    data_api_url: str = "http://localhost:8800"
    data_api_key: str = ""
    admin_password: str = ""


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
        data_api_url=(merged.get("TM_DATA_API_URL") or "http://localhost:8800").rstrip("/"),
        data_api_key=merged.get("TM_DATA_API_KEY") or "",
        admin_password=merged.get("TM_ADMIN_PASSWORD") or "",
    )


# lib/common.js maskPII와 같은 규칙 (전화 010-****-1234, 메일 a***@example.com)
_PHONE = re.compile(r"\b(01[016789])[-.\s]?(\d{3,4})[-.\s]?(\d{4})\b")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def mask_text(text):
    text = _PHONE.sub(lambda m: f"{m.group(1)}-****-{m.group(3)}", text)
    return _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)


def mask_deep(value):
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [mask_deep(v) for v in value]
    if isinstance(value, dict):
        return {k: mask_deep(v) for k, v in value.items()}
    return value


class ChatLog:
    """웹앱을 지나간 대화를 jsonl로 남긴다 (연락처는 가려서). 관리자 화면이 seq 이후만 가져간다."""

    def __init__(self, path=CHAT_LOG, keep=CHAT_KEEP):
        self.path = Path(path)
        self.keep = keep
        self.lock = threading.Lock()
        self.items = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self.items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self.items = self.items[-keep:]
        self.seq = self.items[-1]["seq"] if self.items else 0

    def add(self, request, status, body, elapsed_ms):
        with self.lock:
            self.seq += 1
            item = mask_deep({
                "seq": self.seq,
                "at": datetime.now().isoformat(timespec="seconds"),
                "request": request,
                "status": status,
                "body": body,
                "elapsed_ms": elapsed_ms,
            })
            self.items.append(item)
            self.items = self.items[-self.keep:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            return item

    def since(self, seq):
        with self.lock:
            return [i for i in self.items if i["seq"] > seq], self.seq

    def get(self, request_id):
        with self.lock:
            return next((i for i in reversed(self.items) if i["request"].get("request_id") == request_id), None)

    def clear(self):
        with self.lock:
            self.items = []
            self.path.unlink(missing_ok=True)


def fetch_ops(config, op):
    """(상태, 본문). local은 데이터 API를 직접, vm은 ticketmoa-ops 웹훅을 부른다. 읽기만 한다."""
    if op not in OPS:
        return 404, {"error": f"모르는 op: {op}"}
    if config.target == "vm":
        status, body, _ = call_json(f"{config.n8n_url}/webhook/{OPS_WEBHOOK}", {"op": op}, {"X-Team-Key": config.team_key}, 10)
        if status == 404:
            return 200, {"error": "VM에 ticketmoa-ops 웹훅이 아직 없다", "unavailable": True}
        if isinstance(body, dict) and "data" in body:
            return status, mask_deep(body["data"])
        return status, mask_deep(body)
    req = urllib.request.Request(config.data_api_url + OPS[op], headers={"X-Api-Key": config.data_api_key})
    try:
        with _opener.open(req, timeout=5) as res:
            return res.status, mask_deep(json.loads(res.read().decode("utf-8") or "{}"))
    except urllib.error.HTTPError as error:
        return 200, {"error": f"데이터 API HTTP {error.code}", "unavailable": True}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return 200, {"error": f"데이터 API 연결 실패: {getattr(error, 'reason', error)}", "unavailable": True}


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
    return call_json(f"{config.n8n_url}/webhook/{WEBHOOK}", body, {"X-Team-Key": config.team_key}, WEBHOOK_TIMEOUT_SECONDS)


def call_json(url, body, headers, timeout):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    started = time.monotonic()
    try:
        with _opener.open(req, timeout=timeout) as res:
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

    def admin_allowed(self):
        """TM_ADMIN_PASSWORD가 있으면 관리자 경로에 Basic 인증을 건다 (사용자 이름은 아무거나)."""
        password = self.config.admin_password
        if not password:
            return True
        scheme, _, value = (self.headers.get("Authorization") or "").partition(" ")
        try:
            given = base64.b64decode(value).decode("utf-8").partition(":")[2] if scheme == "Basic" else ""
        except (ValueError, UnicodeDecodeError):
            given = ""
        if hmac.compare_digest(given.encode(), password.encode()):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ticketmoa-admin"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/admin", "/demo") or path.startswith("/api/admin/"):
            if not self.admin_allowed():
                return None
        if path == "/admin":
            path = "/admin.html"
        elif path == "/demo":
            path = "/demo.html"
        if path == "/api/admin/chats":
            try:
                since = int(urllib.parse.parse_qs(query).get("since", ["0"])[0])
            except ValueError:
                since = 0
            items, last = self.server.chats.since(since)
            return self.send_json(200, {"items": items, "last_seq": last, "target": self.config.target})
        if path.startswith("/api/admin/chats/"):
            item = self.server.chats.get(urllib.parse.unquote(path.removeprefix("/api/admin/chats/")))
            return self.send_json(200 if item else 404, item or {"error": "없는 대화"})
        if path.startswith("/api/admin/ops/"):
            status, body = fetch_ops(self.config, path.removeprefix("/api/admin/ops/"))
            return self.send_json(status, body)
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
        path = self.path.partition("?")[0]
        if path == "/api/admin/chats/clear":
            if not self.admin_allowed():
                return None
            self.server.chats.clear()
            return self.send_json(200, {"cleared": True})
        if path != "/api/chat":
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
        self.server.chats.add(request, status, body, ms)
        self.send_json(200, {"status": status, "body": body, "elapsed_ms": ms, "request": request})


def create_server(config, chats=None):
    if config.host not in LOCAL_HOSTS and not config.admin_password:
        raise SystemExit(f"{config.host}에 열려면 TM_ADMIN_PASSWORD가 필요하다 (관리자 화면 보호)")
    server = ThreadingHTTPServer((config.host, config.port), Handler)
    server.config = config
    server.chats = chats if chats is not None else ChatLog()
    return server


def main():
    config = load_config()
    server = create_server(config)
    print(f"티켓모아 상담 채팅: http://{config.host}:{config.port}  · 관리자 /admin · 발표 /demo")
    print(f"대상: {config.target} · n8n {config.n8n_url} · 팀 키 {'있음' if config.team_key else '없음 (전송 불가)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
