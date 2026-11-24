# -*- coding: utf-8 -*-
"""Real-phone-photo OCR batch for PREPROD-01 (serial, resumable)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\Project\AITutors\Teaching Script Compiler")

from tsc_compiler.config import load_settings  # noqa: E402
from tsc_compiler.photo.ocr_client import ocr_bytes  # noqa: E402

SRC = Path(r"D:\Project\AITutors\Interactive Lesson\tests\pic")
OUT = Path(r"D:\Project\AITutors\_dsh\euler_preprod_01\ocr")


def main() -> int:
    settings = load_settings()
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:] or None
    files = sorted(
        [p for p in SRC.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    )
    if only:
        files = [p for p in files if p.stem in only or p.name in only]
    results = []
    for path in files:
        target = OUT / f"{path.stem}.md"
        meta_path = OUT / f"{path.stem}.json"
        if target.is_file() and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            print(path.name, "cached", meta.get("status"), flush=True)
            results.append(meta)
            continue
        started = time.time()
        ocr = ocr_bytes(
            settings,
            path.read_bytes(),
            filename=path.name,
            payload_extra={
                "useDocOrientationClassify": True,
                "useDocUnwarping": False,
            },
            timeout_seconds=150,
        )
        meta = {
            "file": path.name,
            "status": ocr.get("status"),
            "pages": ocr.get("pages"),
            "duration_s": ocr.get("duration_s"),
            "error": ocr.get("error"),
            "chars": len(ocr.get("text") or ""),
            "elapsed_s": round(time.time() - started, 1),
        }
        if ocr.get("status") == "ok":
            target.write_text(ocr["text"], encoding="utf-8")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        results.append(meta)
        print(path.name, meta["status"], meta["chars"], f"{meta['elapsed_s']}s", flush=True)
        time.sleep(1)
    summary = {
        "count": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "failed": [r for r in results if r["status"] != "ok"],
        "chars": sum(r.get("chars") or 0 for r in results),
    }
    (OUT / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
