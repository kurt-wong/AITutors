# -*- coding: utf-8 -*-
"""Photo-input audit over the candidate acceptance set.

For each question: crop a photo-style image from the sealed PDF, OCR it, run
candidate retrieval (with the configured LLM rerank), and record whether the
Top-1 candidate is the correct published revision. Every raw OCR text and the
full candidate list are kept under ``data/photo/audit20`` for review.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tsc_compiler.config import load_settings  # noqa: E402
from tsc_compiler.photo.fixtures import render_question_image, stem_hint  # noqa: E402
from tsc_compiler.photo.ocr_client import ocr_bytes  # noqa: E402
from tsc_compiler.photo.search import search_text  # noqa: E402
from tsc_compiler.qcore_source import load_catalog  # noqa: E402

INPUT_DIR = Path(r"D:\Project\AITutors\runs\qcore_six_subject_accept_01\input")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=999)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    settings = load_settings()
    acceptance = json.loads(
        (ROOT / "docs" / "acceptance_20.json").read_text(encoding="utf-8")
    )
    catalog = {entry["question_id"]: entry for entry in load_catalog(settings)}
    out_dir = settings.data_dir / "photo" / "audit20"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for item in acceptance["items"]:
        seq = item["seq"]
        if seq < args.start or seq > args.end:
            continue
        qid = item["question_id"]
        entry = catalog[qid]
        pdf = INPUT_DIR / f"{entry['source_document_id']}.pdf"
        row = {
            "seq": seq,
            "question_id": qid,
            "revision_id": entry["revision_id"],
            "category": item["category"],
            "printed_number": entry["printed_number"],
            "source_document_id": entry["source_document_id"],
        }
        if not pdf.is_file():
            row.update({"status": "pdf_missing", "pdf": str(pdf)})
            results.append(row)
            continue
        image_path = out_dir / f"{seq:02d}_q{entry['printed_number']}.jpg"
        search_path = out_dir / f"{seq:02d}_q{entry['printed_number']}.search.json"
        if search_path.is_file():
            search = json.loads(search_path.read_text(encoding="utf-8"))
            top = (search["candidates"] or [None])[0]
            row.update(
                {
                    "status": "ok",
                    "decision": search["decision"],
                    "decision_reason": search.get("decision_reason"),
                    "llm": search.get("llm"),
                    "top1_correct": bool(top and top["question_id"] == qid),
                    "top1_question_id": top["question_id"] if top else None,
                    "top1_printed_number": top["printed_number"] if top else None,
                    "top1_source": top["source_document_id"] if top else None,
                    "top1_score": top["score"] if top else None,
                    "top2_score": search["candidates"][1]["score"] if len(search["candidates"]) > 1 else None,
                    "top1_evidence": top["match_evidence"] if top else [],
                    "search_id": search["search_id"],
                    "resumed": True,
                }
            )
            results.append(row)
            print(seq, "resumed", row.get("top1_correct"), flush=True)
            continue
        print("start", seq, entry["printed_number"], flush=True)
        try:
            render = render_question_image(
                pdf,
                printed_number=str(entry["printed_number"]),
                hint=stem_hint(entry["stem_text"]),
                out_path=image_path,
                rotate_degrees=1.2,
                jpeg_quality=86,
            )
            row["image"] = {k: render[k] for k in ("method", "width", "height", "segments")}
            ocr_started = time.time()
            ocr = ocr_bytes(
                settings,
                image_path.read_bytes(),
                filename=image_path.name,
                timeout_seconds=args.timeout,
            )
            row["ocr"] = {
                "status": ocr.get("status"),
                "pages": ocr.get("pages"),
                "duration_s": ocr.get("duration_s"),
                "error": ocr.get("error"),
                "chars": len(ocr.get("text") or ""),
            }
            if ocr.get("status") != "ok":
                row["status"] = "ocr_failed"
                results.append(row)
                continue
            (out_dir / f"{seq:02d}_q{entry['printed_number']}.ocr.md").write_text(
                ocr["text"], encoding="utf-8"
            )
            search = search_text(settings, ocr["text"], limit=6, use_llm=True)
            top = (search["candidates"] or [None])[0]
            row.update(
                {
                    "status": "ok",
                    "decision": search["decision"],
                    "decision_reason": search["decision_reason"],
                    "llm": search["llm"],
                    "top1_correct": bool(top and top["question_id"] == qid),
                    "top1_question_id": top["question_id"] if top else None,
                    "top1_printed_number": top["printed_number"] if top else None,
                    "top1_source": top["source_document_id"] if top else None,
                    "top1_score": top["score"] if top else None,
                    "top2_score": search["candidates"][1]["score"] if len(search["candidates"]) > 1 else None,
                    "top1_evidence": top["match_evidence"] if top else [],
                    "search_id": search["search_id"],
                    "elapsed_s": round(time.time() - ocr_started, 1),
                }
            )
            (out_dir / f"{seq:02d}_q{entry['printed_number']}.search.json").write_text(
                json.dumps(search, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - audit records the failure
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        results.append(row)
        print(
            seq,
            row.get("status"),
            row.get("top1_correct"),
            row.get("decision"),
            row.get("top1_score"),
            flush=True,
        )
        time.sleep(1)

    report_path = settings.data_dir / "reports" / "photo_audit20.json"
    merged: dict[int, dict] = {}
    if report_path.is_file():
        try:
            for previous in json.loads(report_path.read_text(encoding="utf-8")).get("rows", []):
                merged[int(previous["seq"])] = previous
        except (json.JSONDecodeError, KeyError, TypeError):
            merged = {}
    for result in results:
        merged[int(result["seq"])] = result
    ordered = [merged[key] for key in sorted(merged)]
    report = {
        "input": str(INPUT_DIR),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(ordered),
        "ok": sum(1 for r in ordered if r["status"] == "ok"),
        "top1_correct": sum(1 for r in ordered if r.get("top1_correct")),
        "high_confidence": sum(1 for r in ordered if r.get("decision") == "high_confidence"),
        "rows": ordered,
    }
    (settings.data_dir / "reports").mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: report[k] for k in ("count", "ok", "top1_correct", "high_confidence")},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
