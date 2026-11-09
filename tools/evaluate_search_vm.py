# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Evaluate the repository's retrieval questions against ticketmoa-search.

The default mode is a local preflight: it reads and validates inputs but sends
no requests. Remote, read-only search calls require the explicit --execute
flag. Search requests invoke the configured n8n embedding nodes and may incur
OpenAI usage; this tool never reindexes or changes n8n workflows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "docs" / "RAG-EVALUATION-QUESTIONS.csv"
DEFAULT_KNOWLEDGE = ROOT / "knowledge"
DEFAULT_OUTPUT = ROOT / "runs" / "vm"
DEFAULT_N8N_URL = "http://localhost:5678"
SEARCH_PATH = "ticketmoa-search"
TOP_K = 3
EXPECTED_QUESTION_COUNT = 38
EXPECTED_TYPE_COUNTS = {
    "positive": 30,
    "deny_staff": 2,
    "no_ground": 4,
    "no_external_leak": 2,
}
REQUIRED_COLUMNS = {
    "id", "role", "question", "expected_doc", "expected_section", "test_type",
}
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-. ]?)?\d{2,3}[-. ]\d{3,4}[-. ]\d{4}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
URL_RE = re.compile(r"\bhttps?://[^\s<>\]\[()]+", re.IGNORECASE)
EXTERNAL_SOURCE_RE = re.compile(r"\b(?:YES24|NOL|인터파크)\b", re.IGNORECASE)
STAFF_SENSITIVE_TERMS = ("책임자 코드", "수기 모드")
ALLOWED_TEST_TYPES = set(EXPECTED_TYPE_COUNTS)
SAFE_WORKFLOW_ERROR_CODES = {"search_failed", "index_unavailable", "empty_query"}


class InputError(ValueError):
    """Input or version pin is invalid; no webhook request was made."""


class RequestFailure(Exception):
    def __init__(self, kind: str, http_status: int | None = None):
        super().__init__(kind)
        self.kind = kind
        self.http_status = http_status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_value(*args: str) -> str | None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def split_expected_sections(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*\|\|\s*", raw or "") if part.strip()]


def load_questions(
    path: Path,
    expected_count: int | None = EXPECTED_QUESTION_COUNT,
) -> tuple[list[dict[str, Any]], str]:
    raw_bytes = path.read_bytes()
    digest = sha256_bytes(raw_bytes)
    try:
        decoded = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(f"질문 CSV가 UTF-8이 아닙니다: {path}") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    headers = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - headers)
    if missing:
        raise InputError(f"질문 CSV 필수 컬럼이 없습니다: {', '.join(missing)}")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, source in enumerate(reader, start=2):
        qid = (source.get("id") or "").strip()
        role = (source.get("role") or "").strip().lower()
        test_type = (source.get("test_type") or "").strip()
        question = (source.get("question") or "").strip()
        if not qid or qid in seen:
            raise InputError(f"CSV {line_number}행: 질문 ID가 비었거나 중복입니다: {qid!r}")
        if role not in {"all", "staff"}:
            raise InputError(f"{qid}: role은 all 또는 staff여야 합니다.")
        if not question:
            raise InputError(f"{qid}: 질문 내용이 비었습니다.")
        if test_type not in ALLOWED_TEST_TYPES:
            raise InputError(f"{qid}: 지원하지 않는 test_type {test_type!r}")
        if test_type == "deny_staff" and role != "all":
            raise InputError(f"{qid}: deny_staff는 고객 역할(all)로 평가해야 합니다.")
        if test_type in {"no_ground", "no_external_leak", "deny_staff"} and role != "all":
            raise InputError(f"{qid}: {test_type}는 고객 역할(all)로 평가해야 합니다.")

        expected_doc = (source.get("expected_doc") or "").strip()
        expected_sections = split_expected_sections(source.get("expected_section") or "")
        if test_type == "positive" and (not expected_doc or not expected_sections):
            raise InputError(f"{qid}: positive에는 expected_doc과 expected_section이 필요합니다.")

        seen.add(qid)
        rows.append({
            "id": qid,
            "role": role,
            "question": question,
            "expected_doc": expected_doc,
            "expected_sections": expected_sections,
            "test_type": test_type,
        })

    if expected_count is not None and len(rows) != expected_count:
        raise InputError(f"질문 수가 예상과 다릅니다: {len(rows)} / {expected_count}")
    counts = {kind: sum(row["test_type"] == kind for row in rows) for kind in EXPECTED_TYPE_COUNTS}
    if expected_count == EXPECTED_QUESTION_COUNT and counts != EXPECTED_TYPE_COUNTS:
        raise InputError(f"질문 유형 수가 예상과 다릅니다: {counts}")
    return rows, digest


def load_document_manifest(knowledge_dir: Path, expected_count: int = 8) -> tuple[list[dict[str, str]], set[str]]:
    files = sorted(knowledge_dir.glob("*.md"), key=lambda p: p.name.casefold())
    if len(files) != expected_count:
        raise InputError(f"지식 문서가 {expected_count}개가 아닙니다: {len(files)}개 ({knowledge_dir})")
    manifest = []
    for path in files:
        try:
            digest = sha256_bytes(path.read_bytes())
        except OSError as exc:
            raise InputError(f"지식 문서를 읽을 수 없습니다: {path.name}") from exc
        manifest.append({"filename": path.name, "doc": path.stem, "sha256": digest})
    return manifest, {entry["doc"] for entry in manifest}


def validate_expected_csv_hash(actual: str, expected: str | None) -> None:
    if expected and actual.lower() != expected.strip().lower():
        raise InputError(f"CSV SHA-256 불일치: 실제 {actual}, 기대 {expected.strip()}")


def sanitize_endpoint(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        port = ""
    return urllib.parse.urlunsplit((parsed.scheme, host + port, parsed.path.rstrip("/"), "", ""))


def redact_contact_text(value: str) -> str:
    return EMAIL_RE.sub("[REDACTED_EMAIL]", PHONE_RE.sub("[REDACTED_PHONE]", value))


def normalize_hit(hit: Any) -> dict[str, Any]:
    if not isinstance(hit, dict):
        raise ValueError("hit 항목이 JSON object가 아닙니다.")
    doc = hit.get("doc")
    section = hit.get("section")
    score = hit.get("score")
    text = hit.get("text", "")
    if not isinstance(doc, str) or not isinstance(section, str):
        raise ValueError("hit에 문자열 doc 또는 section이 없습니다.")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("hit의 score가 숫자가 아닙니다.")
    if not isinstance(text, str):
        raise ValueError("hit의 text가 문자열이 아닙니다.")
    access_level = hit.get("access_level")
    return {
        "doc": doc,
        "section": section,
        "score": score,
        "text": redact_contact_text(text),
        "access_level": access_level if isinstance(access_level, str) else None,
    }


def validate_search_response(response: Any, requested_role: str) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(response, dict):
        return [], "invalid_response"
    api_error = response.get("error")
    if api_error:
        safe_error = api_error if isinstance(api_error, str) and api_error in SAFE_WORKFLOW_ERROR_CODES else "workflow_error"
        return [], f"workflow_error:{safe_error}"
    hits = response.get("hits")
    indexed = response.get("indexed")
    top_score = response.get("top_score")
    if not isinstance(hits, list) or not isinstance(indexed, bool):
        return [], "invalid_response"
    if isinstance(top_score, bool) or not isinstance(top_score, (int, float)):
        return [], "invalid_response"
    if requested_role == "staff" and not isinstance(response.get("staff_indexed"), bool):
        return [], "invalid_response"
    try:
        normalized = [normalize_hit(hit) for hit in hits[:TOP_K]]
    except ValueError:
        return [], "invalid_response"
    if not indexed or (requested_role == "staff" and response.get("staff_indexed") is not True):
        return normalized, "index_unavailable"
    return normalized, None


def grade_question(
    question: dict[str, Any],
    response: Any,
    allowed_docs: set[str],
) -> dict[str, Any]:
    response_fields = {
        "api_top_score": response.get("top_score") if isinstance(response, dict) else None,
        "indexed": response.get("indexed") if isinstance(response, dict) else None,
        "staff_indexed": response.get("staff_indexed") if isinstance(response, dict) else None,
        "api_error_code": (
            response.get("error")
            if isinstance(response, dict) and response.get("error") in SAFE_WORKFLOW_ERROR_CODES
            else ("workflow_error" if isinstance(response, dict) and response.get("error") else None)
        ),
    }
    hits, response_error = validate_search_response(response, question["role"])
    test_type = question["test_type"]
    if response_error:
        return {
            "evaluation_status": "api_error",
            "error_kind": response_error,
            "hit_at_3": None,
            "staff_doc_leak": None,
            "staff_body_leak": None,
            "unapproved_doc_leak": None,
            "external_reference_leak": None,
            "retrieved_any": None,
            "top3": [],
            **response_fields,
        }

    staff_doc_leak = any(
        hit["doc"] == "staff-entry-manual" or hit["access_level"] == "staff"
        for hit in hits
    ) if question["role"] == "all" else False
    combined_text = "\n".join(hit["text"] for hit in hits)
    staff_body_leak = any(term.casefold() in combined_text.casefold() for term in STAFF_SENSITIVE_TERMS) \
        if question["role"] == "all" else False
    unapproved_doc_leak = any(hit["doc"] not in allowed_docs for hit in hits)
    external_reference_leak = any(
        URL_RE.search(hit["text"]) or EXTERNAL_SOURCE_RE.search(hit["text"])
        for hit in hits
    )

    hit_at_3: bool | None = None
    evaluation_status = "retrieval_only"
    if test_type == "positive":
        hit_at_3 = any(
            hit["doc"] == question["expected_doc"] and
            hit["section"] in question["expected_sections"]
            for hit in hits
        )
        evaluation_status = "scored_positive"
    elif test_type == "deny_staff":
        evaluation_status = "scored_access_control"

    return {
        "evaluation_status": evaluation_status,
        "error_kind": None,
        "hit_at_3": hit_at_3,
        "staff_doc_leak": staff_doc_leak,
        "staff_body_leak": staff_body_leak,
        "unapproved_doc_leak": unapproved_doc_leak,
        "external_reference_leak": external_reference_leak,
        "retrieved_any": bool(hits),
        "top3": hits,
        **response_fields,
    }


def post_search(
    base_url: str,
    team_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int, Any]:
    url = f"{base_url.rstrip('/')}/webhook/{SEARCH_PATH}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Team-Key": team_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            try:
                body = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise RequestFailure("invalid_json", status) from None
            return status, body
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise RequestFailure("authentication_error", exc.code) from None
        if exc.code == 429:
            raise RequestFailure("rate_limited", exc.code) from None
        if 500 <= exc.code <= 599:
            raise RequestFailure("server_error", exc.code) from None
        raise RequestFailure("http_error", exc.code) from None
    except (TimeoutError, socket.timeout):
        raise RequestFailure("timeout") from None
    except urllib.error.URLError:
        raise RequestFailure("connection_error") from None


def request_and_grade(
    questions: list[dict[str, Any]],
    run_id: str,
    base_url: str,
    team_key: str,
    timeout: float,
    interval_seconds: float,
    allowed_docs: set[str],
    requester: Callable[[str, str, dict[str, Any], float], tuple[int, Any]] = post_search,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        started_at = utc_now()
        started = time.perf_counter()
        payload = {
            "query": question["question"],
            "access_level": question["role"],
            "top_k": TOP_K,
            # The workflow ignores these fields; they remain in the webhook
            # execution input to help operators correlate an execution ID.
            "evaluation_run_id": run_id,
            "evaluation_question_id": question["id"],
        }
        http_status: int | None = None
        response: Any = None
        request_error: str | None = None
        try:
            http_status, response = requester(base_url, team_key, payload, timeout)
        except RequestFailure as exc:
            http_status = exc.http_status
            request_error = exc.kind
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

        graded = grade_question(question, response, allowed_docs) if request_error is None else {
            "evaluation_status": "request_error",
            "error_kind": request_error,
            "hit_at_3": None,
            "staff_doc_leak": None,
            "staff_body_leak": None,
            "unapproved_doc_leak": None,
            "external_reference_leak": None,
            "retrieved_any": None,
            "top3": [],
            "api_top_score": None,
            "indexed": None,
            "staff_indexed": None,
            "api_error_code": None,
        }
        rows.append({
            "id": question["id"],
            "role": question["role"],
            "question": question["question"],
            "test_type": question["test_type"],
            "expected_doc": question["expected_doc"],
            "expected_sections": question["expected_sections"],
            "request_started_at_utc": started_at,
            "http_status": http_status,
            "request_duration_ms": elapsed_ms,
            "n8n_execution_id": None,
            **graded,
        })
        if index + 1 < len(questions) and interval_seconds:
            sleep_fn(interval_seconds)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["test_type"] == "positive"]
    positive_scored = [row for row in positives if row["evaluation_status"] == "scored_positive"]
    positive_errors = [row for row in positives if row["evaluation_status"] != "scored_positive"]
    positive_successes = [row for row in positive_scored if row["hit_at_3"] is True]
    positive_misses = [row for row in positive_scored if row["hit_at_3"] is False]
    deny_rows = [row for row in rows if row["test_type"] == "deny_staff" and row["evaluation_status"] == "scored_access_control"]
    no_ground = [row for row in rows if row["test_type"] == "no_ground" and row["evaluation_status"] == "retrieval_only"]
    no_external = [row for row in rows if row["test_type"] == "no_external_leak" and row["evaluation_status"] == "retrieval_only"]
    errors = [row for row in rows if row["evaluation_status"] in {"request_error", "api_error"}]
    return {
        "question_count": len(rows),
        "positive": {
            "question_count": len(positives),
            "scored_count": len(positive_scored),
            "success_count": len(positive_successes),
            "miss_count": len(positive_misses),
            "hit_at_3": f"{len(positive_successes)}/{len(positives)}" if not positive_errors else None,
            "rate": (len(positive_successes) / len(positives)) if positives and not positive_errors else None,
            "failed_question_ids": [row["id"] for row in positive_misses],
            "error_question_ids": [row["id"] for row in positive_errors],
        },
        "deny_staff": {
            "question_count": len([r for r in rows if r["test_type"] == "deny_staff"]),
            "scored_count": len(deny_rows),
            "staff_doc_leak_count": sum(bool(r["staff_doc_leak"]) for r in deny_rows),
            "staff_doc_leak_question_ids": [r["id"] for r in deny_rows if r["staff_doc_leak"]],
            "staff_body_leak_count": sum(bool(r["staff_body_leak"]) for r in deny_rows),
            "staff_body_leak_question_ids": [r["id"] for r in deny_rows if r["staff_body_leak"]],
        },
        "no_ground": {
            "question_count": len([r for r in rows if r["test_type"] == "no_ground"]),
            "retrieval_only_count": len(no_ground),
            "retrieved_any_count": sum(bool(r["retrieved_any"]) for r in no_ground),
            "answer_safety_assessed": False,
        },
        "no_external_leak": {
            "question_count": len([r for r in rows if r["test_type"] == "no_external_leak"]),
            "retrieval_only_count": len(no_external),
            "unapproved_doc_leak_count": sum(bool(r["unapproved_doc_leak"]) for r in no_external),
            "external_reference_leak_count": sum(bool(r["external_reference_leak"]) for r in no_external),
            "generated_answer_safety_assessed": False,
        },
        "request_or_api_errors": [
            {"id": row["id"], "kind": row["error_kind"], "http_status": row["http_status"]}
            for row in errors
        ],
    }


def build_metadata(
    run_id: str,
    environment: str,
    base_url: str,
    question_path: Path,
    question_hash: str,
    questions: list[dict[str, Any]],
    document_manifest: list[dict[str, str]],
    timeout: float,
    interval_seconds: float,
) -> dict[str, Any]:
    type_counts = {kind: sum(q["test_type"] == kind for q in questions) for kind in EXPECTED_TYPE_COUNTS}
    staff_queries = sum(q["role"] == "staff" for q in questions)
    return {
        "run_id": run_id,
        "started_at_utc": utc_now(),
        "environment": environment,
        "host": socket.gethostname(),
        "git_branch": git_value("branch", "--show-current"),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_worktree_status_at_start": git_value("status", "--porcelain"),
        "n8n_endpoint": sanitize_endpoint(base_url),
        "search_webhook": SEARCH_PATH,
        "questions_path": str(question_path.resolve()),
        "questions_sha256": question_hash,
        "question_count": len(questions),
        "question_type_counts": type_counts,
        "documents": document_manifest,
        "document_count": len(document_manifest),
        "request_policy": {
            "top_k": TOP_K,
            "timeout_seconds": timeout,
            "interval_seconds": interval_seconds,
            "automatic_retries": 0,
            "expected_search_requests": len(questions),
            "expected_embedding_node_calls_estimate": len(questions) + staff_queries,
            "note": "VM search webhook only; no direct OpenAI API call, answer generation, reindex, or workflow modification by this script.",
        },
    }


def csv_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "question": row["question"],
        "test_type": row["test_type"],
        "expected_doc": row["expected_doc"],
        "expected_sections": json.dumps(row["expected_sections"], ensure_ascii=False),
        "request_started_at_utc": row["request_started_at_utc"],
        "http_status": row["http_status"],
        "request_duration_ms": row["request_duration_ms"],
        "n8n_execution_id": row["n8n_execution_id"] or "",
        "evaluation_status": row["evaluation_status"],
        "error_kind": row["error_kind"] or "",
        "hit_at_3": "" if row["hit_at_3"] is None else str(row["hit_at_3"]).lower(),
        "staff_doc_leak": "" if row["staff_doc_leak"] is None else str(row["staff_doc_leak"]).lower(),
        "staff_body_leak": "" if row["staff_body_leak"] is None else str(row["staff_body_leak"]).lower(),
        "unapproved_doc_leak": "" if row["unapproved_doc_leak"] is None else str(row["unapproved_doc_leak"]).lower(),
        "external_reference_leak": "" if row["external_reference_leak"] is None else str(row["external_reference_leak"]).lower(),
        "retrieved_any": "" if row["retrieved_any"] is None else str(row["retrieved_any"]).lower(),
        "api_top_score": row["api_top_score"],
        "indexed": "" if row["indexed"] is None else str(row["indexed"]).lower(),
        "staff_indexed": "" if row["staff_indexed"] is None else str(row["staff_indexed"]).lower(),
        "api_error_code": row["api_error_code"] or "",
        "top3": json.dumps(row["top3"], ensure_ascii=False),
    }


def write_reports(
    output_dir: Path,
    run_id: str,
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"rag-search-eval-{run_id}.json"
    csv_path = output_dir / f"rag-search-eval-{run_id}.csv"
    if json_path.exists() or csv_path.exists():
        raise FileExistsError("평가 결과 파일이 이미 있습니다. 기존 결과는 덮어쓰지 않습니다.")

    report = {
        "metadata": metadata,
        "summary": summarize(rows),
        "questions": rows,
        "interpretation": {
            "comparison_warning": "기존 27/28, 수정된 30/30, Python A/B 30/30은 질문 세트·정답 조건·환경이 달라 직접 비교하지 않는다.",
            "no_ground_answer_safety_assessed": False,
            "no_external_generated_answer_safety_assessed": False,
        },
    }
    csv_columns = list(csv_row(rows[0]).keys()) if rows else []
    # Exclusive creation prevents replacing a report from an earlier run.
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=csv_columns)
            writer.writeheader()
            writer.writerows(csv_row(row) for row in rows)
    except Exception:
        json_path.unlink(missing_ok=True)
        raise
    return json_path, csv_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="평가 CSV를 읽어 ticketmoa-search 검색 결과를 채점합니다.")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--n8n-url", default=os.environ.get("N8N_URL") or os.environ.get("TM_N8N_URL") or DEFAULT_N8N_URL)
    parser.add_argument("--environment", default=socket.gethostname(), help="결과에 기록할 실행 환경명 (예: aio-t4)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    parser.add_argument("--expected-csv-sha256", help="질문 버전을 고정할 기대 SHA-256")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true", help="실제 검색 웹훅을 호출합니다. 임베딩 사용 비용이 발생할 수 있습니다.")
    args = parser.parse_args(argv)

    if args.timeout <= 0 or args.interval_seconds < 0:
        parser.error("--timeout은 양수, --interval-seconds는 0 이상이어야 합니다.")
    if args.execute and not args.expected_csv_sha256:
        parser.error("실제 실행에는 --expected-csv-sha256으로 질문 목록 버전을 고정해야 합니다.")
    try:
        questions, question_hash = load_questions(args.questions)
        validate_expected_csv_hash(question_hash, args.expected_csv_sha256)
        document_manifest, allowed_docs = load_document_manifest(args.knowledge)
    except (OSError, InputError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    run_id = run_id_now()
    staff_queries = sum(q["role"] == "staff" for q in questions)
    print(f"실행 계획: environment={args.environment}, questions={len(questions)}, csv_sha256={question_hash}")
    print(f"문서={len(document_manifest)}, 예상 검색 요청={len(questions)}, 예상 임베딩 노드 호출(약)={len(questions) + staff_queries}")
    if not args.execute:
        print("PREFLIGHT ONLY: 네트워크·n8n·OpenAI 요청은 보내지 않았습니다. 실제 평가에는 --execute가 필요합니다.")
        return 0

    team_key = os.environ.get("TM_TEAM_KEY") or os.environ.get("FLOW_WEBHOOK_KEY", "")
    if not team_key:
        print("인증 설정 오류: TM_TEAM_KEY 또는 FLOW_WEBHOOK_KEY가 없습니다.", file=sys.stderr)
        return 2
    if not args.n8n_url.lower().startswith(("http://", "https://")):
        print("입력 오류: --n8n-url은 http:// 또는 https://로 시작해야 합니다.", file=sys.stderr)
        return 2

    started_at = utc_now()
    metadata = build_metadata(
        run_id, args.environment, args.n8n_url, args.questions, question_hash,
        questions, document_manifest, args.timeout, args.interval_seconds,
    )
    metadata["started_at_utc"] = started_at
    rows = request_and_grade(
        questions, run_id, args.n8n_url, team_key, args.timeout,
        args.interval_seconds, allowed_docs,
    )
    metadata["finished_at_utc"] = utc_now()
    try:
        json_path, csv_path = write_reports(args.out_dir, run_id, metadata, rows)
    except OSError as exc:
        print(f"결과 저장 오류: {type(exc).__name__}", file=sys.stderr)
        return 2

    summary = summarize(rows)
    print(f"결과: {json_path}")
    print(f"CSV: {csv_path}")
    print(f"positive hit@3: {summary['positive']['hit_at_3'] or '미완료'}; 요청/API 오류 {len(summary['request_or_api_errors'])}건")
    # A measured retrieval miss is a result, not an execution failure. Request
    # and workflow errors remain separately visible and produce a nonzero code.
    return 2 if summary["request_or_api_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
