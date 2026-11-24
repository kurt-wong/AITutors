# -*- coding: utf-8 -*-
"""Join the candidate acceptance list with compile, photo-audit and E2E results."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = Path(r"D:\Project\AITutors\_dsh\euler_lesson_01\e2e")


def load(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    acceptance = load(ROOT / "docs" / "acceptance_20.json")
    index = load(ROOT / "data" / "scripts" / "index.json") or []
    audit = load(ROOT / "data" / "reports" / "photo_audit20.json") or {"rows": []}
    e2e: dict[str, dict] = {}
    if E2E_DIR.is_dir():
        for path in E2E_DIR.glob("*_e2e.json"):
            payload = load(path) or {}
            e2e[payload.get("question_id", "")] = payload

    scripts = {row["question_id"]: row for row in index}
    photos = {row["question_id"]: row for row in audit.get("rows", [])}

    rows = []
    for item in acceptance["items"]:
        qid = item["question_id"]
        script = scripts.get(qid)
        photo = photos.get(qid)
        run = e2e.get(qid)
        rows.append(
            {
                "seq": item["seq"],
                "question_id": qid,
                "revision_id": item["revision_id"],
                "category": item["category"],
                "source_document_id": item["source_document_id"],
                "printed_number": item["printed_number"],
                "question_type": item["question_type"],
                "has_image": item["has_image"],
                "has_table": item["has_table"],
                "photo_input": bool(photo and photo.get("status") == "ok"),
                "photo_decision": (photo or {}).get("decision"),
                "top1_match": (photo or {}).get("top1_correct"),
                "top1_score": (photo or {}).get("top1_score"),
                "needs_confirmation": (photo or {}).get("decision") != "high_confidence",
                "photo_error": (photo or {}).get("error"),
                "teaching_script": bool(script and script.get("validation") == "pass"),
                "script_steps": (script or {}).get("steps"),
                "script_id": (script or {}).get("script_id"),
                "source_refs": "validated" if script and script.get("validation") == "pass" else None,
                "lesson_e2e": (run or {}).get("status"),
                "lesson_e2e_steps": [f"{s['name']}:{s['status']}" for s in (run or {}).get("steps", [])],
            }
        )

    summary = {
        "questions": len(rows),
        "scripts_pass": sum(1 for row in rows if row["teaching_script"]),
        "photo_ok": sum(1 for row in rows if row["photo_input"]),
        "photo_top1_correct": sum(1 for row in rows if row["top1_match"]),
        "high_confidence": sum(1 for row in rows if row["photo_decision"] == "high_confidence"),
        "lesson_e2e_pass": sum(1 for row in rows if row["lesson_e2e"] == "pass"),
    }
    payload = {
        "acceptance_status": acceptance.get("status"),
        "note": "候选 20 题，待 Owner 确认；不冒充正式验收集。",
        "summary": summary,
        "items": rows,
    }
    out = ROOT / "data" / "reports" / "acceptance20_full.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    header = "| # | 题 | 类型 | 图/表 | 拍照 | Top-1 | 置信决策 | 脚本 | E2E |"
    print(header)
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(
            f"| {row['seq']} | {row['printed_number']} | {row['question_type']} | "
            f"{'图' if row['has_image'] else ''}{'表' if row['has_table'] else ''} | "
            f"{'✓' if row['photo_input'] else '—'} | "
            f"{'✓' if row['top1_match'] else ('✗' if row['photo_input'] else '—')} | "
            f"{row['photo_decision'] or '—'} | "
            f"{'pass' if row['teaching_script'] else 'fail'} | "
            f"{row['lesson_e2e'] or '—'} |"
        )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
