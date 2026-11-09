"""python3 -m unittest webapp/test_app.py"""
import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app import ChatLog, Config, build_request, create_server, fetch_ops, load_config, mask_deep


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / ".env").write_text(
            "TM_TEAM_KEY='k'\nTM_N8N_URL=http://localhost:5678\nTM_VM_N8N_URL=https://vm.example:5678/\n", encoding="utf-8")

    def test_local_uses_tm_n8n_url(self):
        c = load_config({}, self.repo)
        self.assertEqual((c.target, c.n8n_url, c.team_key), ("local", "http://localhost:5678", "k"))

    def test_vm_ignores_local_url(self):
        # .env에 TM_N8N_URL(로컬)이 있어도 vm이면 VM 주소로 간다
        c = load_config({"TM_TARGET": "vm"}, self.repo)
        self.assertEqual(c.n8n_url, "https://vm.example:5678")

    def test_vm_without_url_stops(self):
        (self.repo / ".env").write_text("TM_TEAM_KEY=k\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            load_config({"TM_TARGET": "vm"}, self.repo)


class RequestTest(unittest.TestCase):
    def test_contract_fields_only(self):
        r = build_request({"user": "김하늘", "question": "QR", "attempt": "2", "context": {"confirm": True}, "x": 1})
        self.assertEqual(set(r), {"request_id", "user", "channel", "question", "attempt", "context"})
        self.assertEqual((r["channel"], r["attempt"], r["context"]), ("web", 2, {"confirm": True}))
        self.assertTrue(r["request_id"].startswith("web-"))

    def test_bad_attempt_and_context(self):
        r = build_request({"attempt": "x", "context": "nope"})
        self.assertEqual((r["attempt"], r["context"]), (1, {}))


class MaskTest(unittest.TestCase):
    def test_phone_and_email(self):
        out = mask_deep({"q": "연락처 010-0000-5678, kim@example.com", "n": [1, "01000005432"]})
        self.assertEqual(out["q"], "연락처 010-****-5678, k***@example.com")
        self.assertEqual(out["n"], [1, "010-****-5432"])


class ChatLogTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "var" / "chats.jsonl"

    def test_add_since_get_and_reload(self):
        log = ChatLog(self.path)
        log.add({"request_id": "r1", "question": "제 번호 010-0000-2222"}, 200, {"route": "자동 답변"}, 10)
        log.add({"request_id": "r2", "question": "b"}, 200, {"route": "차단"}, 5)
        items, last = log.since(1)
        self.assertEqual((last, [i["request"]["request_id"] for i in items]), (2, ["r2"]))
        self.assertIn("010-****-2222", log.get("r1")["request"]["question"])
        self.assertNotIn("1111", self.path.read_text(encoding="utf-8"))  # 파일에도 가려서 쓴다
        again = ChatLog(self.path)
        self.assertEqual((again.seq, len(again.items)), (2, 2))
        again.clear()
        self.assertEqual((again.since(0), self.path.exists()), (([], 2), False))

    def test_keep_limit(self):
        log = ChatLog(self.path, keep=3)
        for i in range(5):
            log.add({"request_id": f"r{i}"}, 200, {}, 1)
        self.assertEqual([i["seq"] for i in log.items], [3, 4, 5])


def _config(**kw):
    base = dict(host="127.0.0.1", port=0, target="local", n8n_url="http://127.0.0.1:9", team_key="k",
                data_api_url="http://127.0.0.1:9", data_api_key="d")
    return Config(**{**base, **kw})


class OpsTest(unittest.TestCase):
    def test_unknown_op(self):
        self.assertEqual(fetch_ops(_config(), "admin/fault?tickets=error")[0], 404)

    def test_data_api_down_is_reported_not_raised(self):
        status, body = fetch_ops(_config(), "tickets")
        self.assertEqual(status, 200)
        self.assertTrue(body["unavailable"])


class ServerTest(unittest.TestCase):
    def start(self, config):
        server = create_server(config, ChatLog(Path(tempfile.mkdtemp()) / "c.jsonl"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def get(self, url, password=None):
        req = urllib.request.Request(url)
        if password:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{password}".encode()).decode())
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_public_host_needs_password(self):
        with self.assertRaises(SystemExit):
            create_server(_config(host="0.0.0.0"))

    def test_admin_password(self):
        url = self.start(_config(admin_password="pw"))
        self.assertEqual(self.get(url + "/api/admin/chats")[0], 401)
        self.assertEqual(self.get(url + "/admin")[0], 401)
        self.assertEqual(self.get(url + "/api/admin/chats", "pw")[0], 200)
        self.assertEqual(self.get(url + "/")[0], 200)  # 고객 화면은 열려 있다

    def test_admin_pages_and_no_keys(self):
        url = self.start(_config(team_key="TEAMSECRET", data_api_key="DATASECRET"))
        for path in ("/admin", "/demo", "/api/admin/chats", "/api/admin/ops/tickets", "/api/config"):
            status, raw = self.get(url + path)
            self.assertEqual(status, 200, path)
            self.assertNotIn(b"SECRET", raw, path)
        self.assertEqual(json.loads(self.get(url + "/api/admin/chats?since=0")[1])["last_seq"], 0)


if __name__ == "__main__":
    unittest.main()
