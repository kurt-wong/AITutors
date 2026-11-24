# -*- coding: utf-8 -*-
"""Evaluate all real phone photos against the QCore candidate retriever."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\Project\AITutors\Teaching Script Compiler")

from tsc_compiler.config import load_settings  # noqa: E402
from tsc_compiler.photo.search import search_text  # noqa: E402

OCR = Path(r"D:\Project\AITutors\_dsh\euler_preprod_01\ocr")
OUT = Path(r"D:\Project\AITutors\_dsh\euler_preprod_01\photo_eval.json")

PRINTED = {"269", "IMG_7770", "IMG_7774", "IMG_8067", "IMG_8068", "IMG_8069", "IMG_8105"}


def main() -> int:
    settings = load_settings()
    rows = []
    for path in sorted(OCR.glob("*.md")):
        name = path.stem
        text = path.read_text(encoding="utf-8")
        started = time.time()
        result = search_text(settings, text, use_llm=True, limit=5)
        top = (result["candidates"] or [None])[0]
        rows.append(
            {
                "file": f"{name}.jpeg" if name.startswith("IMG_") else f"{name}.png",
                "kind": "printed_exam" if name in PRINTED else "handwritten_notes",
                "ocr_chars": len(text),
                "decision": result["decision"],
                "may_teach": result["may_teach"],
                "requires_confirmation": result["requires_confirmation"],
                "top1_question_id": top["question_id"] if top else None,
                "top1_printed_number": top["printed_number"] if top else None,
                "top1_source": top["source_document_id"] if top else None,
                "top1_score": top["score"] if top else None,
                "top2_score": result["candidates"][1]["score"] if len(result["candidates"]) > 1 else None,
                "llm_status": result["llm"]["status"],
                "elapsed_s": round(time.time() - started, 1),
            }
        )
        print(name, rows[-1]["decision"], rows[-1]["top1_score"], flush=True)

    summary = {
        "total": len(rows),
        "printed": sum(1 for r in rows if r["kind"] == "printed_exam"),
        "handwritten": sum(1 for r in rows if r["kind"] == "handwritten_notes"),
        "high_confidence": sum(1 for r in rows if r["decision"] == "high_confidence"),
        "high_confidence_ground_truth": "none: no QCore question text found in this photo set",
        "ambiguous": sum(1 for r in rows if r["decision"] == "ambiguous"),
        "low_confidence": sum(1 for r in rows if r["decision"] == "low_confidence"),
        "no_match": sum(1 for r in rows if r["decision"] == "no_match"),
        "ocr_failed_unrecovered": 0,
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
