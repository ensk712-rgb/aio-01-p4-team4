"""python3 -m unittest webapp/test_app.py"""
import tempfile
import unittest
from pathlib import Path

from app import build_request, load_config


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


if __name__ == "__main__":
    unittest.main()
