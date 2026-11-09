import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.evaluate_search_vm import (
    InputError,
    EXPECTED_QUESTION_COUNT,
    grade_question,
    load_questions,
    request_and_grade,
    summarize,
    validate_expected_csv_hash,
    write_reports,
)


ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "RAG-EVALUATION-QUESTIONS.csv"
DOCS = {"app-login-troubleshooting", "onsite-entry-fallback", "staff-entry-manual"}


class EvaluateSearchVmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions, cls.csv_hash = load_questions(CSV_PATH)
        cls.by_id = {q["id"]: q for q in cls.questions}

    def test_actual_csv_columns_count_and_q11_or_sections(self):
        self.assertEqual(len(self.questions), EXPECTED_QUESTION_COUNT)
        self.assertEqual(self.by_id["Q11"]["expected_sections"], [
            "1. 원칙: 입장이 먼저",
            "2. 방법 1: 현장 발권 창구",
            "5. 현장 스태프 알림",
        ])

    def test_csv_hash_validation_accepts_match_and_rejects_mismatch(self):
        validate_expected_csv_hash(self.csv_hash, self.csv_hash)
        with self.assertRaises(InputError):
            validate_expected_csv_hash(self.csv_hash, "0" * 64)

    def test_positive_exact_doc_and_section_is_hit(self):
        question = self.by_id["Q01"]
        result = grade_question(question, {
            "hits": [{"doc": question["expected_doc"], "section": question["expected_sections"][0], "score": 0.7, "text": "내용"}],
            "top_score": 0.7,
            "indexed": True,
        }, DOCS)
        self.assertTrue(result["hit_at_3"])
        self.assertEqual(result["evaluation_status"], "scored_positive")

    def test_q11_accepts_any_expected_section(self):
        question = self.by_id["Q11"]
        for acceptable_section in question["expected_sections"]:
            with self.subTest(section=acceptable_section):
                result = grade_question(question, {
                    "hits": [{"doc": question["expected_doc"], "section": acceptable_section, "score": 0.6, "text": "입장 안내"}],
                    "top_score": 0.6,
                    "indexed": True,
                }, DOCS)
                self.assertTrue(result["hit_at_3"])

    def test_wrong_doc_or_section_is_a_measured_miss(self):
        question = self.by_id["Q01"]
        result = grade_question(question, {
            "hits": [{"doc": "venue-faq", "section": "2. 주차", "score": 0.9, "text": "주차 안내"}],
            "top_score": 0.9,
            "indexed": True,
        }, DOCS | {"venue-faq"})
        self.assertFalse(result["hit_at_3"])
        self.assertEqual(result["evaluation_status"], "scored_positive")

    def test_staff_document_and_staff_body_leaks_are_separate(self):
        question = self.by_id["Q29"]
        doc_leak = grade_question(question, {
            "hits": [{"doc": "staff-entry-manual", "section": "1. 수기 입장 처리", "score": 0.5, "text": "내부 문서"}],
            "top_score": 0.5,
            "indexed": True,
        }, DOCS)
        self.assertTrue(doc_leak["staff_doc_leak"])
        self.assertFalse(doc_leak["staff_body_leak"])

        body_leak = grade_question(question, {
            "hits": [{"doc": "onsite-entry-fallback", "section": "3. 현장 확인", "score": 0.5, "text": "수기 모드 안내"}],
            "top_score": 0.5,
            "indexed": True,
        }, DOCS)
        self.assertFalse(body_leak["staff_doc_leak"])
        self.assertTrue(body_leak["staff_body_leak"])

    def test_workflow_error_is_not_scored_as_a_hit_miss(self):
        question = self.by_id["Q02"]
        result = grade_question(question, {
            "hits": [], "top_score": 0, "indexed": False, "error": "index_unavailable",
        }, DOCS)
        self.assertIsNone(result["hit_at_3"])
        self.assertEqual(result["evaluation_status"], "api_error")
        self.assertEqual(result["error_kind"], "workflow_error:index_unavailable")

    def test_no_ground_and_external_are_retrieval_only(self):
        question = self.by_id["Q31"]
        result = grade_question(question, {
            "hits": [{"doc": "venue-faq", "section": "2. 주차", "score": 0.42, "text": "유사도만으로 근거 여부를 확정하지 않음"}],
            "top_score": 0.42,
            "indexed": True,
        }, DOCS | {"venue-faq"})
        self.assertEqual(result["evaluation_status"], "retrieval_only")
        self.assertIsNone(result["hit_at_3"])
        self.assertTrue(result["retrieved_any"])

        external_question = self.by_id["Q34"]
        external = grade_question(external_question, {
            "hits": [{"doc": "outside-doc", "section": "source", "score": 0.3, "text": "https://example.org/policy"}],
            "top_score": 0.3,
            "indexed": True,
        }, DOCS | {"venue-faq"})
        self.assertTrue(external["unapproved_doc_leak"])
        self.assertTrue(external["external_reference_leak"])
        self.assertIsNone(external["hit_at_3"])

    def test_request_error_and_retrieval_miss_are_separate(self):
        questions = [self.by_id["Q01"], self.by_id["Q02"]]
        outcomes = iter([
            (200, {"hits": [{"doc": "wrong", "section": "wrong", "score": 0.9, "text": ""}], "top_score": 0.9, "indexed": True}),
        ])

        def fake_requester(_url, _key, _payload, _timeout):
            try:
                return next(outcomes)
            except StopIteration:
                from tools.evaluate_search_vm import RequestFailure
                raise RequestFailure("timeout")

        rows = request_and_grade(
            questions, "run-test", "http://n8n.invalid", "secret-not-logged", 1, 0,
            DOCS, requester=fake_requester, sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(rows[0]["evaluation_status"], "scored_positive")
        self.assertFalse(rows[0]["hit_at_3"])
        self.assertEqual(rows[1]["evaluation_status"], "request_error")
        self.assertEqual(rows[1]["error_kind"], "timeout")
        summary = summarize(rows)
        self.assertEqual(summary["positive"]["miss_count"], 1)
        self.assertEqual(summary["positive"]["error_question_ids"], ["Q02"])

    def test_result_json_and_csv_files_are_created_without_overwrite(self):
        question = self.by_id["Q01"]
        graded = grade_question(question, {
            "hits": [{"doc": question["expected_doc"], "section": question["expected_sections"][0], "score": 0.7, "text": "ok"}],
            "top_score": 0.7,
            "indexed": True,
        }, DOCS)
        row = {
            "id": question["id"], "role": question["role"], "question": question["question"],
            "test_type": question["test_type"], "expected_doc": question["expected_doc"],
            "expected_sections": question["expected_sections"], "request_started_at_utc": "2026-11-06T00:00:00Z",
            "http_status": 200, "request_duration_ms": 1.0, "n8n_execution_id": None, **graded,
        }
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
            json_path, csv_path = write_reports(Path(temp_dir), "test-run", {"questions_sha256": self.csv_hash}, [row])
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["questions"][0]["hit_at_3"], True)
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                output_row = next(csv.DictReader(handle))
            self.assertEqual(output_row["hit_at_3"], "true")
            self.assertEqual(output_row["n8n_execution_id"], "")
            with self.assertRaises(FileExistsError):
                write_reports(Path(temp_dir), "test-run", {}, [row])


if __name__ == "__main__":
    unittest.main()
