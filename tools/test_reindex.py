"""reindex.py의 판정만 검사한다. 웹훅·임베딩 API는 호출하지 않는다."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import reindex


def hit(doc="mobile-ticket-troubleshooting", section="1. QR 확인", text=None):
    return {
        "doc": doc,
        "section": section,
        "score": 0.6,
        "text": text if text is not None else f"# {doc}\n## {section}\n공개 안내입니다.",
    }


def index_response(**changes):
    response = {
        "input_document_count": 2,
        "valid_document_count": 2,
        "public_document_count": 1,
        "staff_document_count": 1,
        "chunk_count": 6,
        "chunk_length": {"min": 20, "median": 30, "max": 40},
        "issues": [],
        "outcome": "store_output_received",
    }
    response.update(changes)
    return response


class ReindexTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path("in-memory-test-knowledge")
        self.documents = {}
        for doc, access in (("mobile-ticket-troubleshooting", "all"), ("staff-entry-manual", "staff")):
            self.documents[doc] = (
                f"# {doc}\n> access_level: {access}\n## 1. QR 확인\n내용\n"
                "## 2. 해결\n내용\n## 3. 추가\n내용\n"
            )

    def run_main(self, responses):
        stdout = io.StringIO()
        paths = [self.folder / f"{doc}.md" for doc in self.documents]
        with patch.object(reindex, "KEY", "test-only"), patch.object(
            sys, "argv", ["reindex.py", "--knowledge", str(self.folder)]
        ), patch.object(Path, "glob", autospec=True, return_value=paths), patch.object(
            Path, "read_text", autospec=True, side_effect=lambda path, **_: self.documents[path.stem]
        ), patch.object(reindex, "post", side_effect=responses) as post, redirect_stdout(stdout):
            status = reindex.main()
        return status, stdout.getvalue(), post.call_args_list

    def test_public_success_never_requests_staff_search(self):
        response = {"indexed": True, "hits": [hit()]}
        status, output, calls = self.run_main([index_response(), response, response])
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call.args[1]["access_level"] == "all" for call in calls[1:]))
        self.assertIn("공개 검색: PASS", output)
        self.assertIn("직원 문서 비노출: PASS", output)
        self.assertIn("직원 저장소 실제 저장: 미검증", output)

    def test_validation_issue_is_partial_and_skips_search(self):
        status, output, calls = self.run_main([index_response(valid_document_count=1, issues=[{
            "doc": "staff-entry-manual", "stage": "validation", "errors": ["빈 절"]
        }])])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("부분 성공 가능", output)
        self.assertIn("공개 검색·직원 문서 비노출: 미실시", output)

    def test_store_error_reports_possible_partial_index(self):
        status, output, calls = self.run_main([index_response(outcome="store_error")])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("빈/부분 인덱스", output)

    def test_zero_chunks_is_failure_not_success(self):
        status, output, calls = self.run_main([index_response(
            valid_document_count=0, public_document_count=0, staff_document_count=0,
            chunk_count=0, outcome="no_valid_chunks"
        )])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("유효 청크 0개", output)

    def test_missing_issues_is_not_silently_accepted(self):
        response = index_response()
        del response["issues"]
        status, output, calls = self.run_main([response])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("issues 목록이 없어", output)

    def test_index_transport_error_keeps_storage_unknown(self):
        status, output, calls = self.run_main([reindex.RequestFailure("ticketmoa-index: timeout")])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("저장 상태: 미검증", output)

    def test_wrong_public_doc_is_not_evidence(self):
        wrong = {"indexed": True, "hits": [hit("venue-faq", "1. 위치")]}
        safe = {"indexed": True, "hits": [hit()]}
        status, output, _ = self.run_main([index_response(), wrong, safe])
        self.assertEqual(status, 1)
        self.assertIn("공개 검색: 실패", output)

    def test_staff_document_or_body_leak_fails_public_check(self):
        safe = {"indexed": True, "hits": [hit()]}
        leaked = {"indexed": True, "hits": [hit(
            "staff-entry-manual", "1. 직원 절차", "# staff-entry-manual\n## 1. 직원 절차\n책임자 코드"
        )]}
        status, output, calls = self.run_main([index_response(), safe, leaked])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 3)
        self.assertIn("직원 문서 비노출: 실패", output)

    def test_staff_block_response_to_public_request_is_not_pass(self):
        safe = {"indexed": True, "hits": [hit()]}
        status, output, _ = self.run_main([
            index_response(), safe, {"indexed": False, "hits": [], "error": "staff_search_disabled"}
        ])
        self.assertEqual(status, 1)
        self.assertIn("staff_search_disabled", output)

    def test_search_transport_error_is_separate_from_index_response(self):
        safe = {"indexed": True, "hits": [hit()]}
        status, output, calls = self.run_main([
            index_response(), reindex.RequestFailure("ticketmoa-search: timeout"), safe
        ])
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 3)
        self.assertIn("색인 단계: 응답상 완료", output)
        self.assertIn("공개 검색: 실패 또는 미검증", output)

    def test_incomplete_corpus_is_rejected_before_webhook(self):
        del self.documents["staff-entry-manual"]
        status, output, calls = self.run_main([])
        self.assertEqual(status, 1)
        self.assertEqual(calls, [])
        self.assertIn("색인 전 점검", output)


if __name__ == "__main__":
    unittest.main()
