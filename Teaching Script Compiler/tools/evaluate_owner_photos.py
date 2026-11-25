# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.path.insert(0, r"D:\Project\AITutors\Teaching Script Compiler")

from tsc_compiler.config import load_settings
from tsc_compiler.photo.search import search_text

DATASET = {
    "test1": {
        "paper": "2022全国乙卷 数学（理）",
        "expected": {
            "9673bd10-b644-4258-bbd3-cd0012ba593d": "4",
            "0535c006-b324-45ff-a3b7-570d5843bc0a": "5",
            "80d9e1d5-14e7-41a0-ac08-2679ad27afc0": "6",
        },
    },
    "test2": {
        "paper": "2022全国乙卷 数学（理）",
        "expected": {
            "ce2eb7f7-5310-4096-8963-4a7e0e91ae7c": "1",
            "bd84179d-a73e-4699-a469-9b2547287ea5": "2",
            "c6876803-507d-4c51-af69-3bf6de8a8cae": "3",
            "9673bd10-b644-4258-bbd3-cd0012ba593d": "4",
        },
    },
}

settings = load_settings()
ocr_dir = Path(r"D:\Project\AITutors\_dsh\euler_preprod_01\ocr")
rows = []
for name, meta in DATASET.items():
    text = (ocr_dir / f"{name}.md").read_text(encoding="utf-8")
    result = search_text(settings, text, use_llm=True, limit=6)
    candidates = result["candidates"]
    top = candidates[0] if candidates else None
    print(f"== {name} ({meta['paper']}) decision={result['decision']} reason={result['decision_reason']}")
    for candidate in candidates:
        mark = "EXPECTED" if candidate["question_id"] in meta["expected"] else ""
        print(
            " ",
            round(candidate["score"], 4),
            candidate["printed_number"],
            candidate["source_document_id"][:24],
            mark,
        )
    rows.append(
        {
            "file": f"{name}.jpg",
            "paper": meta["paper"],
            "expected_question_ids": list(meta["expected"]),
            "expected_printed_numbers": list(meta["expected"].values()),
            "decision": result["decision"],
            "may_teach": result["may_teach"],
            "requires_confirmation": result["requires_confirmation"],
            "top1_question_id": top["question_id"] if top else None,
            "top1_printed_number": top["printed_number"] if top else None,
            "top1_score": top["score"] if top else None,
            "top1_expected": bool(top and top["question_id"] in meta["expected"]),
            "expected_in_candidates": sum(1 for c in candidates if c["question_id"] in meta["expected"]),
            "candidates": [
                {
                    "question_id": c["question_id"],
                    "printed_number": c["printed_number"],
                    "score": c["score"],
                    "expected": c["question_id"] in meta["expected"],
                }
                for c in candidates
            ],
            "llm_status": result["llm"]["status"],
            "ocr_chars": len(text),
        }
    )

summary = {
    "photos": len(rows),
    "top1_expected": sum(1 for r in rows if r["top1_expected"]),
    "high_confidence": sum(1 for r in rows if r["decision"] == "high_confidence"),
    "ambiguous": sum(1 for r in rows if r["decision"] == "ambiguous"),
    "low_confidence": sum(1 for r in rows if r["decision"] == "low_confidence"),
    "rows": rows,
}
out = Path(r"D:\Project\AITutors\_dsh\euler_preprod_01\owner_positive_photos.json")
out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
