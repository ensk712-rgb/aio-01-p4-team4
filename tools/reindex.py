# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""knowledge/*.md를 다시 색인하고 공개 검색·직원 문서 비노출을 확인한다.

In-Memory 색인은 n8n이 다시 켜지면 사라질 수 있으므로 flow.py push 뒤에 다시 돌린다.
OpenAI 임베딩을 호출하므로 필요할 때만 실행한다.
직원 검색은 호출하지 않는다. 종료 코드 0도 직원 저장소의 실제 저장 성공을 뜻하지 않는다.

  uv run --env-file .env tools/reindex.py

팀 키는 환경 변수 TM_TEAM_KEY로 준다. n8n 주소는 N8N_URL로 바꿀 수 있다 (기본 http://localhost:5678).
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
N8N_URL = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
KEY = os.environ.get("TM_TEAM_KEY") or os.environ.get("FLOW_WEBHOOK_KEY", "")
ACCESS_LEVEL = re.compile(r"^>\s*access_level:\s*(all|staff)\b", re.IGNORECASE | re.MULTILINE)
STAFF_ONLY_TERMS = ("책임자 코드", "수기 모드")


class RequestFailure(Exception):
    """웹훅 요청 실패를 색인·검색 단계별로 보고하기 위한 오류."""


def post(path: str, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        f"{N8N_URL}/webhook/{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Team-Key": KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RequestFailure(f"{path}: HTTP {error.code}. 팀 키, 워크플로우 게시 상태를 확인한다.") from error
    except urllib.error.URLError as error:
        raise RequestFailure(f"{path}: 연결 실패 ({error.reason}). n8n이 켜져 있는지 확인한다.") from error
    except TimeoutError:
        raise RequestFailure(f"{path}: {timeout}초 안에 응답이 없다.") from None
    except json.JSONDecodeError as error:
        raise RequestFailure(f"{path}: 응답이 JSON이 아니다.") from error


def check_index(result: object, document_count: int, public_count: int, staff_count: int) -> list[str]:
    """색인 응답의 완전성을 검사한다. 실제 저장 레코드 수는 확인하지 못한다."""
    if not isinstance(result, dict):
        return ["색인 응답이 JSON 객체가 아님; 기존 키의 빈/부분 저장 가능성 미확인"]
    problems = []
    outcome = result.get("outcome")
    if outcome != "store_output_received":
        problems.append(f"outcome={outcome!r}; 저장 실패·부분 저장 또는 빈 새 청크 가능")
    if result.get("input_document_count") != document_count:
        problems.append("색인 입력 문서 수 불일치")
    if result.get("valid_document_count") != document_count:
        problems.append("검증 실패 문서 존재; 일부만 색인됐을 가능성")
    if result.get("public_document_count") != public_count or result.get("staff_document_count") != staff_count:
        problems.append("권한별 유효 문서 수 불일치; 한쪽 저장소에 오래된 데이터가 남을 가능성")
    chunk_count = result.get("chunk_count")
    if isinstance(chunk_count, bool) or not isinstance(chunk_count, int) or chunk_count <= 0:
        problems.append("유효 청크 0개 또는 청크 수 미확인; 새 인덱스가 비었을 가능성")
    if not isinstance(result.get("issues"), list):
        problems.append("issues 목록이 없어 검증·저장 오류 여부 미확인")
    elif result["issues"]:
        problems.append("검증 또는 저장 issues 존재; 부분 성공 가능")
    return problems


def check_public_hits(
    result: object, public_docs: set[str], staff_docs: set[str], expected_docs: set[str] | None = None,
) -> list[str]:
    """공개 검색 응답의 근거와 직원 정보 누출을 검사한다."""
    if not isinstance(result, dict):
        return ["검색 응답이 JSON 객체가 아님"]
    if result.get("error"):
        return [f"검색 오류: {result['error']}"]
    if result.get("indexed") is not True:
        return ["공개 인덱스 사용 가능 여부 미확인 또는 빈 인덱스"]
    hits = result.get("hits")
    if not isinstance(hits, list) or not hits:
        return ["공개 문서 근거가 반환되지 않음"]
    problems = []
    for index, hit in enumerate(hits, 1):
        if not isinstance(hit, dict):
            problems.append(f"{index}번째 검색 결과 형식 오류")
            continue
        doc, section, content = hit.get("doc"), hit.get("section"), hit.get("text")
        if doc in staff_docs or hit.get("access_level") == "staff":
            problems.append(f"{index}번째 결과에 직원 문서 또는 직원 권한 노출")
        if doc not in public_docs:
            problems.append(f"{index}번째 결과의 문서가 승인된 공개 문서가 아님")
        if not isinstance(section, str) or not section.strip() or not isinstance(content, str) or not content.strip():
            problems.append(f"{index}번째 결과의 절 또는 본문이 비어 있음")
        elif not content.replace("\r\n", "\n").lstrip().startswith(f"# {doc}\n## {section}\n"):
            problems.append(f"{index}번째 결과의 본문·doc·section 연결 불일치")
        if isinstance(content, str) and any(term in content for term in STAFF_ONLY_TERMS):
            problems.append(f"{index}번째 결과에 직원 전용 본문 표현 노출")
        score = hit.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            problems.append(f"{index}번째 결과의 점수가 유효하지 않음")
    if expected_docs and not any(isinstance(hit, dict) and hit.get("doc") in expected_docs for hit in hits):
        problems.append("QR 질문에 예상한 공개 문서 근거가 없음")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="knowledge/*.md를 다시 색인하고 검색이 되는지 확인한다. 기존 색인은 지워진다.")
    parser.add_argument("--knowledge", type=Path, default=ROOT / "knowledge", help="색인할 문서 폴더 (기본: 저장소 knowledge/)")
    args = parser.parse_args()

    if not KEY:
        sys.exit("TM_TEAM_KEY가 없다. uv run --env-file .env tools/reindex.py 로 실행한다.")

    files = sorted(args.knowledge.glob("*.md"))
    if not files:
        sys.exit(f"{args.knowledge}에 .md 문서가 없다.")
    documents = [{"doc": path.stem, "text": path.read_text(encoding="utf-8")} for path in files]
    public_docs, staff_docs = set(), set()
    for document in documents:
        match = ACCESS_LEVEL.search(document["text"])
        if match:
            (staff_docs if match[1].lower() == "staff" else public_docs).add(document["doc"])
    if not public_docs or not staff_docs or len(public_docs) + len(staff_docs) != len(documents):
        print("색인 전 점검: 공개·직원 문서가 모두 필요하며 모든 문서에 유효한 access_level이 있어야 함")
        print("색인·검색: 미실시 — 기존 인덱스를 변경하지 않음 / 직원 저장소: 미검증")
        return 1

    try:
        result = post("ticketmoa-index", {"documents": documents}, timeout=180)
    except RequestFailure as error:
        print(f"색인 단계: 요청 실패 ({error})")
        print("저장 상태: 미검증 — 기존 인덱스가 비었거나 일부만 저장됐을 가능성")
        print("공개 검색·직원 문서 비노출: 미실시 / 직원 저장소: 미검증")
        return 1
    if not isinstance(result, dict):
        result = {"outcome": "invalid_response"}
    length = result.get("chunk_length") if isinstance(result.get("chunk_length"), dict) else {}
    print(f"문서 {result.get('valid_document_count')}/{len(documents)} "
          f"(일반 {result.get('public_document_count')}, 스태프 {result.get('staff_document_count')})")
    print(f"청크 {result.get('chunk_count')}개, 길이 최소 {length.get('min')} · "
          f"중앙값 {length.get('median')} · 최대 {length.get('max')} (문자 수)")
    print(f"색인 응답 outcome: {result.get('outcome')}")

    issues = result.get("issues") if isinstance(result.get("issues"), list) else []
    for issue in issues:
        print(f"문제: {issue.get('doc')} {issue.get('stage')} {issue.get('errors')}" if isinstance(issue, dict) else f"문제: {issue}")
    index_problems = check_index(result, len(documents), len(public_docs), len(staff_docs))
    if index_problems:
        print("색인 단계: 실패 또는 부분 성공 가능")
        for problem in index_problems:
            print(f"색인 점검: {problem}")
        print("저장 상태: 미검증 — clearStore 후 빈/부분 인덱스 또는 이전 버전 잔존 가능")
        print("공개 검색·직원 문서 비노출: 미실시 / 직원 저장소: 미검증")
        return 1

    print("색인 단계: 응답상 완료 — 청크 수는 저장 전 수량, 실제 저장 수·직원 저장소는 미검증")
    expected_docs = public_docs & {"mobile-ticket-troubleshooting", "onsite-entry-fallback"}
    checks = (
        ("공개 검색", "QR 입장", 3, expected_docs),
        ("직원 문서 비노출", "스태프 수기 입장 절차와 책임자 코드 입력 방법", 8, None),
    )
    passed = True
    for label, query, top_k, expected in checks:
        try:
            search = post("ticketmoa-search", {"query": query, "access_level": "all", "top_k": top_k}, timeout=30)
            problems = check_public_hits(search, public_docs, staff_docs, expected)
        except RequestFailure as error:
            problems = [str(error)]
        if problems:
            passed = False
            print(f"{label}: 실패 또는 미검증 — {'; '.join(problems)}")
        else:
            print(f"{label}: PASS (승인된 공개 문서의 본문·절 확인, 반환 결과 범위)")
    print("직원 저장소 실제 저장: 미검증 — 공개 Search에서 차단 유지, 별도 제한된 검증 필요")
    print("저장 레코드 전수·실패 시 자동 롤백: 미검증/미구현")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
