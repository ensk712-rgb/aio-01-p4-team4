#!/usr/bin/env python3
"""Build expected TicketMoa chunks and compare an exhaustive read-only store snapshot.

This tool never calls n8n. The configured Simple Vector Store exposes similarity Get Many,
not a supported full-store enumeration/export API. Therefore live extraction is UNVERIFIABLE.
A top-N similarity result must never be promoted to an exhaustive snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KEY_BY_LEVEL = {"all": "ticketmoa_kb_v1_all", "staff": "ticketmoa_kb_v1_staff"}


def expected_chunks(knowledge_dir: Path = ROOT / "knowledge") -> list[dict[str, str]]:
    chunks = []
    for path in sorted(knowledge_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        access = re.search(r"^>\s*access_level:\s*(all|staff)\b", text, re.I | re.M)
        sections = list(re.finditer(r"^##\s+(.+)\s*$", text, re.M))
        if not access or len(sections) < 3:
            raise ValueError(f"invalid source document: {path.name}")
        for index, heading in enumerate(sections):
            end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
            body = text[heading.end():end].strip()
            if not body:
                raise ValueError(f"empty section: {path.stem} / {heading.group(1).strip()}")
            section = heading.group(1).strip()
            chunks.append({
                "doc": path.stem,
                "section": section,
                "access_level": access.group(1).lower(),
                "text": f"# {path.stem}\n## {section}\n{body}",
            })
    return chunks


def check_sources(knowledge_dir: Path = ROOT / "knowledge") -> dict[str, Any]:
    """Read-only preflight for the approved eight-document, 42-chunk source set."""
    try:
        chunks = expected_chunks(knowledge_dir)
    except (OSError, UnicodeError, ValueError) as error:
        return {"status": "FAIL", "issues": [str(error)]}
    documents = {(row["doc"], row["access_level"]) for row in chunks}
    public_docs = sum(level == "all" for _, level in documents)
    staff_docs = sum(level == "staff" for _, level in documents)
    public_chunks = sum(row["access_level"] == "all" for row in chunks)
    staff_chunks = sum(row["access_level"] == "staff" for row in chunks)
    unique_sections = len({(row["doc"], row["section"]) for row in chunks})
    issues = []
    if (len(documents), public_docs, staff_docs) != (8, 7, 1):
        issues.append("document count/access mismatch: expected 8 (public 7, staff 1)")
    if (len(chunks), public_chunks, staff_chunks) != (42, 37, 5):
        issues.append("chunk count/access mismatch: expected 42 (public 37, staff 5)")
    if unique_sections != len(chunks):
        issues.append("duplicate doc/section in source chunks")
    return {"status": "FAIL" if issues else "PASS", "documents": len(documents),
            "public_documents": public_docs, "staff_documents": staff_docs,
            "expected": len(chunks), "public": public_chunks, "staff": staff_chunks,
            "issues": issues, "store_records_verified": False}


def live_extraction_status() -> dict[str, Any]:
    """Fail closed: n8n Simple Vector Store has no supported full enumeration API here."""
    return {
        "status": "UNVERIFIABLE",
        "issues": [
            "n8n Simple Vector Store Get Many is similarity top-N, not full-store enumeration",
            "no authenticated read-only full-store export endpoint is implemented",
        ],
    }

def compare_snapshot(expected: list[dict[str, str]], snapshot: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    proof = snapshot.get("enumeration_proof")
    if (snapshot.get("exhaustive") is not True or not isinstance(proof, dict)
            or proof.get("method") != "native_full_enumeration"
            or proof.get("cursor_exhausted") is not True):
        return {"status": "UNVERIFIABLE", "issues": ["snapshot lacks proof of full native enumeration"]}
    if not isinstance(snapshot.get("records"), list):
        return {"status": "UNVERIFIABLE", "issues": ["snapshot records missing or malformed"]}
    records = snapshot["records"]
    if not isinstance(snapshot.get("reported_total"), int):
        return {"status": "UNVERIFIABLE", "issues": ["reported_total missing"]}
    if snapshot["reported_total"] != len(records):
        issues.append("reported_total does not match returned record count")
    if proof.get("store_total") != snapshot["reported_total"] or proof.get("extracted_total") != len(records):
        issues.append("enumeration proof totals do not match snapshot")

    expected_by_key = {(x["doc"], x["section"]): x for x in expected}
    actual_counts: Counter[tuple[str, str]] = Counter()
    for row in records:
        if not isinstance(row, dict) or not all(k in row for k in ("doc", "section", "access_level", "text")):
            return {"status": "UNVERIFIABLE", "issues": ["record missing required metadata or text"]}
        actual_counts[(str(row["doc"]), str(row["section"]))] += 1

    for key, count in actual_counts.items():
        if count > 1:
            issues.append(f"duplicate record: {key[0]} / {key[1]} ({count})")
        if key not in expected_by_key:
            issues.append(f"unexpected record: {key[0]} / {key[1]}")
    expected_for_store = [x for x in expected if KEY_BY_LEVEL[x["access_level"]] == snapshot.get("store_key")]
    for wanted in expected_for_store:
        key = (wanted["doc"], wanted["section"])
        if actual_counts[key] == 0:
            issues.append(f"missing record: {key[0]} / {key[1]}")
    for row in records:
        key = (str(row["doc"]), str(row["section"]))
        wanted = expected_by_key.get(key)
        if wanted is None:
            continue
        if row["access_level"] != wanted["access_level"]:
            issues.append(f"wrong access_level: {key[0]} / {key[1]}")
        expected_store = KEY_BY_LEVEL[wanted["access_level"]]
        if snapshot.get("store_key") != expected_store:
            issues.append(f"wrong store: {snapshot.get('store_key')} for {key[0]} / {key[1]}")
        if row["text"] != wanted["text"]:
            issues.append(f"body mismatch: {key[0]} / {key[1]}")
    if len(records) != len(expected_for_store):
        issues.append(f"record count mismatch: expected {len(expected_for_store)}, got {len(records)}")
    return {"status": "FAIL" if issues else "PASS", "checked": len(records), "expected": len(expected), "issues": issues}


def verify_snapshots(expected: list[dict[str, str]], snapshots: Any) -> dict[str, Any]:
    if not isinstance(snapshots, list) or len(snapshots) != 2:
        return {"status": "UNVERIFIABLE", "issues": ["both public and staff snapshots are required"]}
    results = [compare_snapshot(expected, snap) for snap in snapshots if isinstance(snap, dict)]
    if len(results) != 2:
        return {"status": "UNVERIFIABLE", "issues": ["malformed store snapshot"]}
    combined = {"status": "PASS", "stores": results}
    if any(r["status"] == "UNVERIFIABLE" for r in results):
        combined["status"] = "UNVERIFIABLE"
    elif any(r["status"] != "PASS" for r in results):
        combined["status"] = "FAIL"
    return combined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=Path, default=ROOT / "knowledge")
    parser.add_argument("--snapshot", type=Path, help="JSON containing exhaustive public and staff snapshots")
    parser.add_argument("--extract-live", action="store_true", help="Report whether native full-store extraction is supported")
    parser.add_argument("--check-sources", action="store_true", help="Read-only preflight; PASS applies only to source documents")
    args = parser.parse_args()
    if args.check_sources:
        result = check_sources(args.knowledge)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1
    expected = expected_chunks(args.knowledge)
    summary = {"expected": len(expected), "public": sum(r["access_level"] == "all" for r in expected),
               "staff": sum(r["access_level"] == "staff" for r in expected)}
    if args.extract_live:
        result = live_extraction_status()
        print(json.dumps({**summary, **result}, ensure_ascii=False, indent=2))
        return 2
    if not args.snapshot:
        print(json.dumps({**summary, **live_extraction_status()}, ensure_ascii=False, indent=2))
        return 2
    snapshots = json.loads(args.snapshot.read_text(encoding="utf-8"))
    result = verify_snapshots(expected, snapshots)
    print(json.dumps({**summary, **result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1 if result["status"] == "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
