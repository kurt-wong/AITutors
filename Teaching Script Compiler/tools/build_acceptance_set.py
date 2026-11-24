# -*- coding: utf-8 -*-
"""Build the candidate 20-question acceptance list (ids only, no exam content).

The Owner has not yet confirmed the formal 20. This file is therefore written
with ``status = "candidate_pending_owner"`` and must not be reported as the
accepted acceptance set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tsc_compiler.config import load_settings  # noqa: E402
from tsc_compiler.qcore_source import load_catalog  # noqa: E402

# (question_id, category) — categories are about the photo input, not the type.
SELECTION = [
    ("ce2eb7f7-5310-4096-8963-4a7e0e91ae7c", "A_text"),
    ("bd84179d-a73e-4699-a469-9b2547287ea5", "A_text"),
    ("c6876803-507d-4c51-af69-3bf6de8a8cae", "B_formula"),
    ("0535c006-b324-45ff-a3b7-570d5843bc0a", "B_formula"),
    ("80d9e1d5-14e7-41a0-ac08-2679ad27afc0", "C_image"),
    ("9dd44bc6-25e9-42ed-ba6f-aca8cc825345", "A_text"),
    ("f3efbbb5-40db-4753-ade8-ac02b9dae5aa", "B_formula"),
    ("50e8cad3-952f-48b3-92f7-30b5516c4561", "A_text"),
    ("2a61081c-c596-41be-95ef-bdd28417b685", "B_formula"),
    ("23b89ff6-5adb-48ea-b7a2-d723389ddf29", "B_formula"),
    ("e9f1ee73-7422-4565-afbb-531d3aec85df", "A_text"),
    ("750c946d-85b0-46c5-b1aa-6ecb106ae64c", "B_formula"),
    ("84fff73d-4060-407e-bde4-9f512ae5da0c", "B_formula"),
    ("f39366b7-2538-45a2-814f-3b1339d90ae7", "B_formula"),
    ("67ce1be0-6c49-4f9d-938e-e927008d6c1b", "B_formula"),
    ("ec6930a0-9aa1-425e-aa4f-9c3a6a9f7310", "A_text"),
    ("9345cad9-c72d-4666-8535-71b0651b5310", "C_table"),
    ("a33323cc-1536-4c88-9e45-432eba348c4d", "A_text"),
    ("b8858d3f-6177-43fc-b96f-5588e4b93795", "B_formula"),
    ("808a03a4-c227-4a40-9c40-8c5853e55e07", "B_formula"),
]


def main() -> int:
    settings = load_settings()
    catalog = {entry["question_id"]: entry for entry in load_catalog(settings)}
    missing = [qid for qid, _ in SELECTION if qid not in catalog]
    if missing:
        raise SystemExit(f"questions missing from catalog: {missing}")
    items = []
    for index, (qid, category) in enumerate(SELECTION, start=1):
        entry = catalog[qid]
        items.append(
            {
                "seq": index,
                "question_id": qid,
                "revision_id": entry["revision_id"],
                "revision_number": entry["revision_number"],
                "category": category,
                "subject": entry["subject"],
                "source_document_id": entry["source_document_id"],
                "printed_number": entry["printed_number"],
                "question_type": entry["question_type"],
                "has_image": entry["has_image"],
                "has_table": entry["has_table"],
                "has_math": entry["has_math"],
            }
        )
    payload = {
        "title": "EULER-STYLE-INTERACTIVE-LESSON-PILOT-01 formal acceptance set",
        "status": "owner_confirmed",
        "confirmed_at": "2026-11-24T23:34:55+08:00",
        "confirmed_by": "Owner",
        "note": (
            "Owner 于 2026-11-24 确认该 20 题为正式验收清单；"
            "题目事实来源：QCore published Revision；此处只记录 id 与属性，不含题干/答案。"
        ),
        "count": len(items),
        "items": items,
    }
    out = ROOT / "docs" / "acceptance_20.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
    )
    print(f"wrote {out} with {len(items)} items")
    distribution: dict[str, int] = {}
    for item in items:
        distribution[item["category"]] = distribution.get(item["category"], 0) + 1
    print("categories", distribution)
    return 0


if __name__ == "__main__":
    sys.exit(main())
