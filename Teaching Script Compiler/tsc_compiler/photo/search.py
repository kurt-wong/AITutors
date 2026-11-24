"""Photo → candidates decision layer.

The API contract is deliberately conservative:

* ``high_confidence`` — one candidate clearly matches; teaching may start;
* ``ambiguous`` — several plausible candidates; the user must choose;
* ``low_confidence`` — nothing convincing; the UI says "未找到可靠题目";
* ``no_match`` — no candidate above the floor.

OCR text is *evidence*; the returned candidates always reference QCore
``question_id`` / ``revision_id``. The response never includes answers or
explanations, so a student-facing search cannot leak them.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import Settings
from ..normalize import normalize_for_search, truncate_title
from ..qcore_source import load_catalog
from .index import SearchIndex
from .llm import judge_candidates

_INDEX_CACHE: dict[str, Any] = {"stamp": None, "index": None}

HIGH_SCORE = 0.68
HIGH_MARGIN = 0.08
AMBIGUOUS_FLOOR = 0.30
CANDIDATE_FLOOR = 0.12
LLM_CANDIDATES = 5


def clean_ocr_markdown(text: str) -> str:
    """Strip layout noise but keep every character of question content."""
    out = str(text or "")
    out = re.sub(r"<img\b[^>]*>", " [图] ", out, flags=re.I)
    out = re.sub(r"!\[[^\]]*\]\([^)]*\)", " [图] ", out)
    out = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " | ", out, flags=re.I)
    out = re.sub(r"<[^>]+>", " ", out)
    out = out.replace("&nbsp;", " ").replace("&amp;", "&")
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()


def ocr_features(text: str) -> dict[str, Any]:
    raw = str(text or "")
    return {
        "has_image": bool(re.search(r"<img|!\[", raw, re.I)),
        "has_table": bool(re.search(r"<table|\|\s*-{2,}", raw, re.I)),
        "has_math": "$" in raw or "\\frac" in raw,
        "text": clean_ocr_markdown(raw),
    }


def _index_for(settings: Settings) -> SearchIndex:
    catalog_path = settings.data_dir / "qcore" / "catalog.json"
    stamp = catalog_path.stat().st_mtime_ns if catalog_path.is_file() else 0
    if _INDEX_CACHE["index"] is None or _INDEX_CACHE["stamp"] != stamp:
        catalog = load_catalog(settings)
        _INDEX_CACHE["index"] = SearchIndex.from_catalog(catalog)
        _INDEX_CACHE["stamp"] = stamp
    return _INDEX_CACHE["index"]


def _evidence(matched: list[str], *, limit: int = 6) -> list[dict[str, str]]:
    numbers = [t[2:] for t in matched if t.startswith("n:")]
    cjk = [t[2:] for t in matched if t.startswith("z:")]
    commands = [t[2:] for t in matched if t.startswith("c:")]
    evidence: list[dict[str, str]] = []
    for value in numbers[:3]:
        evidence.append({"type": "number", "value": value})
    for value in cjk[:3]:
        evidence.append({"type": "text", "value": value})
    for value in commands[:2]:
        evidence.append({"type": "formula", "value": value})
    return evidence[:limit]


def _decide(candidates: list[dict[str, Any]], *, llm_enabled: bool, llm_error: str | None) -> dict[str, Any]:
    if not candidates:
        return {
            "decision": "no_match",
            "requires_confirmation": True,
            "may_teach": False,
            "reason": "no candidate above the matching floor",
        }
    top = candidates[0]
    margin = top["score"] - (candidates[1]["score"] if len(candidates) > 1 else 0.0)
    evidence_count = len(top["match_evidence"])
    llm_ok = True
    if llm_enabled:
        llm_entry = (top.get("llm") or {})
        llm_ok = llm_entry.get("verdict") == "match" and float(llm_entry.get("match") or 0) >= 0.7
    if (
        top["score"] >= HIGH_SCORE
        and margin >= HIGH_MARGIN
        and evidence_count >= 3
        and llm_ok
    ):
        return {
            "decision": "high_confidence",
            "requires_confirmation": False,
            "may_teach": True,
            "reason": f"top score {top['score']:.3f}, margin {margin:.3f}, evidence {evidence_count}",
        }
    if top["score"] >= AMBIGUOUS_FLOOR:
        reason = f"top score {top['score']:.3f}, margin {margin:.3f}"
        if llm_enabled and not llm_ok:
            reason += f", LLM not confident ({llm_error or 'verdict'})"
        return {
            "decision": "ambiguous",
            "requires_confirmation": True,
            "may_teach": False,
            "reason": reason,
        }
    return {
        "decision": "low_confidence",
        "requires_confirmation": True,
        "may_teach": False,
        "reason": f"top score {top['score']:.3f} below ambiguity floor",
    }


def search_text(
    settings: Settings,
    text: str,
    *,
    limit: int = 6,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    features = ocr_features(text)
    index = _index_for(settings)
    raw = index.query(
        features["text"],
        limit=max(limit, LLM_CANDIDATES),
        query_has_image=features["has_image"],
        query_has_table=features["has_table"],
        query_has_math=features["has_math"],
    )
    raw = [item for item in raw if item["score"] >= CANDIDATE_FLOOR]

    llm_enabled = settings.llm_rerank if use_llm is None else bool(use_llm)
    llm_error = None
    if llm_enabled and raw:
        judges, llm_error = judge_candidates(
            settings,
            features["text"],
            [item["entry"] for item in raw[:LLM_CANDIDATES]],
        )
        for item in raw:
            verdict = judges.get(item["question_id"])
            item["llm"] = verdict
            if verdict is not None:
                item["score"] = round(
                    0.75 * item["score"] + 0.25 * float(verdict["match"]), 4
                )
                item["score_parts"]["llm"] = verdict["match"]
        raw.sort(key=lambda item: item["score"], reverse=True)

    candidates: list[dict[str, Any]] = []
    for item in raw[:limit]:
        entry = item["entry"]
        candidates.append(
            {
                "question_id": item["question_id"],
                "revision_id": entry["revision_id"],
                "score": item["score"],
                "score_parts": item["score_parts"],
                "match_evidence": _evidence(item["matched_tokens"]),
                "source_document_id": entry.get("source_document_id"),
                "printed_number": entry.get("printed_number"),
                "question_type": entry.get("question_type"),
                "title": truncate_title(entry.get("stem_text") or "", 60),
                "has_image": entry.get("has_image"),
                "has_table": entry.get("has_table"),
                "llm": item.get("llm"),
                "needs_confirmation": True,
            }
        )
    decision = _decide(candidates, llm_enabled=llm_enabled, llm_error=llm_error)
    if decision["decision"] == "high_confidence" and candidates:
        candidates[0]["needs_confirmation"] = False
    return {
        "search_id": uuid.uuid4().hex[:16],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "query": {"text": features["text"], "features": features},
        "candidates": candidates,
        "decision": decision["decision"],
        "requires_confirmation": decision["requires_confirmation"],
        "may_teach": decision["may_teach"],
        "message": _message(decision["decision"]),
        "decision_reason": decision["reason"],
        "llm": {
            "enabled": llm_enabled,
            "status": "ok" if llm_enabled and not llm_error else ("error" if llm_error else "off"),
            "error": llm_error,
        },
    }


def _message(decision: str) -> str:
    return {
        "high_confidence": "已找到高置信题目，可直接进入讲题。",
        "ambiguous": "找到多个可能题目，请确认是哪一道。",
        "low_confidence": "未找到可靠的 QCore 题目，请重新拍摄或手动选择。",
        "no_match": "未找到可靠的 QCore 题目。",
    }[decision]


def persist_search(settings: Settings, result: dict[str, Any], *, ocr_text: str, image_path: Path | None = None) -> Path:
    directory = settings.data_dir / "photo" / result["search_id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ocr.md").write_text(ocr_text, encoding="utf-8")
    if image_path and image_path.is_file():
        (directory / "input").mkdir(exist_ok=True)
        (directory / "input" / image_path.name).write_bytes(image_path.read_bytes())
    (directory / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return directory
