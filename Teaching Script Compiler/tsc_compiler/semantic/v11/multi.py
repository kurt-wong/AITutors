"""Multi-question candidate layer for full-page photos (V1.1 candidate only).

The layer never returns a single automatic Exact decision. It splits the OCR
page into question blocks, retrieves candidates for each block, and returns a
de-duplicated candidate list that requires an explicit user selection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_QUESTION_START = re.compile(r"(?m)^\s*(?:#+\s*)?(\d{1,3})\s*[.、．]\s*")


@dataclass(frozen=True)
class QuestionSegment:
    index: int
    number: str
    text: str


def split_questions(text: str, *, min_chars: int = 20) -> list[QuestionSegment]:
    value = (text or "").strip()
    if not value:
        return []
    matches = list(_QUESTION_START.finditer(value))
    if len(matches) <= 1:
        return [QuestionSegment(index=0, number=matches[0].group(1) if matches else "", text=value)]
    segments: list[QuestionSegment] = []
    for position, match in enumerate(matches):
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(value)
        body = value[start:end].strip()
        if len(body) >= min_chars:
            segments.append(QuestionSegment(index=len(segments), number=match.group(1), text=body))
    return segments or [QuestionSegment(index=0, number="", text=value)]


class MultiCandidateIndex:
    """Wrap an existing SemanticIndex; add page segmentation and candidate union."""

    def __init__(self, index: Any):
        self.index = index

    def search(
        self,
        page_text: str,
        *,
        per_segment: int = 5,
        whole_page: int = 10,
        max_candidates: int = 20,
    ) -> dict:
        segments = split_questions(page_text)
        found: dict[str, dict] = {}

        def add_candidate(candidate: dict, segment: QuestionSegment | None, relation: str) -> None:
            qid = candidate.get("question_id")
            if not qid:
                return
            item = found.get(qid)
            if item is None:
                item = {
                    "question_id": qid,
                    "score": float(candidate.get("score") or 0.0),
                    "dense": candidate.get("dense"),
                    "lexical": candidate.get("lexical"),
                    "relation": relation,
                    "segments": [],
                }
                found[qid] = item
            else:
                item["score"] = max(item["score"], float(candidate.get("score") or 0.0))
                if relation == "exact_candidate":
                    item["relation"] = "exact_candidate"
                elif relation == "similar_candidate" and item["relation"] == "weak_candidate":
                    item["relation"] = "similar_candidate"
            if segment is not None and segment.index not in item["segments"]:
                item["segments"].append(segment.index)

        for segment in segments:
            result = self.index.search(segment.text, top_k=max(per_segment, 10))
            raw = result.get("candidates") or []
            exact = (result.get("exact") or {}).get("question_id")
            similar_ids = {
                c.get("question_id") for c in (result.get("similar") or []) if c.get("question_id")
            }
            for candidate in raw[:per_segment]:
                qid = candidate.get("question_id")
                if qid == exact:
                    relation = "exact_candidate"
                elif qid in similar_ids:
                    relation = "similar_candidate"
                else:
                    relation = "weak_candidate"
                add_candidate(candidate, segment, relation)

        # Whole-page retrieval is a safety net for a segment that was split badly.
        whole = self.index.search(page_text, top_k=max(whole_page, 10))
        for candidate in (whole.get("candidates") or [])[:whole_page]:
            add_candidate(candidate, None, "weak_candidate")

        ordered = sorted(found.values(), key=lambda item: item["score"], reverse=True)[:max_candidates]
        for rank, item in enumerate(ordered, 1):
            item["rank"] = rank
            item["requires_user_selection"] = True

        return {
            "status": "needs_user_selection" if ordered else "no_candidate",
            "auto_exact": None,
            "requires_user_selection": True,
            "segments": [
                {"index": s.index, "number": s.number, "chars": len(s.text), "text": s.text[:200]}
                for s in segments
            ],
            "candidates": ordered,
        }
