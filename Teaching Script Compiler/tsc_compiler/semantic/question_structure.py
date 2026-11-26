"""Page-level question structure recovery with explicit uncertainty.

This module is deliberately conservative: it never invents a missing question
number or rewrites OCR text. It exposes numbered question units, leading
material / orphan text, and a reliability state that callers must honor before
building a retrieval query.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

_NUMBERED = re.compile(r"(?m)^\s*(?:#+\s*)?(\d{1,3})\s*[.、．]\s*")
_SUBQUESTION = re.compile(r"^\s*[（(]\s*\d{1,3}\s*[）)]")
_MATERIAL_HINT = re.compile(r"(阅读下面|阅读材料|材料[一二三四五六七八九十\d]|据此完成|完成下面小题|根据材料)")


class StructureStatus(str, Enum):
    RELIABLE = "reliable"
    AMBIGUOUS = "ambiguous"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


@dataclass(frozen=True)
class QuestionUnit:
    index: int
    number: str
    text: str
    start: int
    end: int
    context: str = ""


@dataclass
class PageStructure:
    text: str
    prefix: str
    units: list[QuestionUnit]
    status: StructureStatus
    reasons: list[str] = field(default_factory=list)
    prefix_is_tail: bool = False

    @property
    def requires_selection(self) -> bool:
        return self.status != StructureStatus.RELIABLE

    def query_for(
        self,
        indices: list[int],
        *,
        include_prefix: bool = True,
        include_context: bool = True,
    ) -> str:
        chosen = []
        for index in sorted(set(indices)):
            if index < 0 or index >= len(self.units):
                raise ValueError(f"question index out of range: {index}")
            chosen.append(self.units[index])
        if not chosen:
            raise ValueError("no target question selected")
        parts = []
        if include_prefix and self.prefix and not self.prefix_is_tail:
            parts.append(self.prefix)
        if include_context:
            contexts = []
            for unit in chosen:
                if unit.context and unit.context not in contexts:
                    contexts.append(unit.context)
            parts.extend(contexts)
        parts.extend(unit.text for unit in chosen)
        return "\n".join(part.strip() for part in parts if part.strip())

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "requires_selection": self.requires_selection,
            "reasons": list(self.reasons),
            "prefix_chars": len(self.prefix),
            "prefix_is_tail": self.prefix_is_tail,
            "prefix": self.prefix,
            "prefix_preview": self.prefix[:240],
            "units": [
                {
                    "index": unit.index,
                    "number": unit.number,
                    "chars": len(unit.text),
                    "start": unit.start,
                    "end": unit.end,
                    "text": unit.text,
                    "context": unit.context,
                    "preview": unit.text[:240],
                }
                for unit in self.units
            ],
        }


def _raw_contexts(raw_jsonl: str | None) -> dict[str, str]:
    """Map OCR material blocks to the numbered questions that follow them.

    llama.cpp/PaddleOCR raw JSONL is untrusted layout data; this only uses the
    ordered ``parsing_res_list`` text blocks to attach an explicit material
    block. It never rewrites the OCR text.
    """
    if not raw_jsonl:
        return {}
    contexts: dict[str, str] = {}
    try:
        payload = json.loads(raw_jsonl.splitlines()[0])
        pages = payload.get("result", {}).get("layoutParsingResults") or []
    except (ValueError, AttributeError, IndexError):
        return {}
    pending = ""
    for page in pages:
        blocks = page.get("prunedResult", {}).get("parsing_res_list") or []
        for block in blocks:
            content = str(block.get("block_content") or "").strip()
            if not content:
                continue
            match = _NUMBERED.match(content)
            if match:
                if pending:
                    contexts[match.group(1)] = pending
                continue
            if _SUBQUESTION.match(content):
                # A leading sub-question marker is the previous question's tail,
                # not shared material for the next question.
                pending = ""
                continue
            if _MATERIAL_HINT.search(content) and len(content) >= 20:
                pending = content
    return contexts


def analyze_page(text: str, *, min_chars: int = 20, raw_jsonl: str | None = None) -> PageStructure:
    value = (text or "").strip()
    if not value:
        return PageStructure(value, "", [], StructureStatus.INCOMPLETE, ["EMPTY_OCR"])

    matches = list(_NUMBERED.finditer(value))
    if not matches:
        return PageStructure(
            value,
            value,
            [],
            StructureStatus.INCOMPLETE,
            ["NO_QUESTION_NUMBER"],
        )

    contexts = _raw_contexts(raw_jsonl)
    prefix = value[: matches[0].start()].strip()
    units: list[QuestionUnit] = []
    for position, match in enumerate(matches):
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(value)
        body = value[start:end].strip()
        if len(body) >= min_chars:
            number = match.group(1)
            units.append(
                QuestionUnit(
                    len(units),
                    number,
                    body,
                    start,
                    end,
                    contexts.get(number, ""),
                )
            )

    if not units:
        return PageStructure(value, prefix, [], StructureStatus.INCOMPLETE, ["NO_VALID_UNIT"])

    reasons: list[str] = []
    prefix_is_tail = bool(prefix and _SUBQUESTION.match(prefix))
    if prefix_is_tail:
        reasons.append("QUESTION_TAIL_CONTAMINATION")

    if len(units) > 1:
        status = StructureStatus.AMBIGUOUS
        reasons.append("MULTIPLE_QUESTIONS")
        if prefix and not prefix_is_tail:
            reasons.append("LEADING_CONTEXT")
        if _MATERIAL_HINT.search(value):
            reasons.append("SHARED_MATERIAL_PRESENT")
    elif prefix_is_tail:
        status = StructureStatus.AMBIGUOUS
    elif prefix and len(prefix) > 40 and not _MATERIAL_HINT.search(prefix):
        # A long unnumbered leading block with a single numbered unit is most
        # likely a missing number or the previous question's tail. Both need
        # explicit user selection; do not guess it as part of this question.
        status = StructureStatus.AMBIGUOUS
        reasons.append("PREFIX_WITHOUT_NUMBER")
    else:
        status = StructureStatus.RELIABLE

    return PageStructure(value, prefix, units, status, reasons, prefix_is_tail)
