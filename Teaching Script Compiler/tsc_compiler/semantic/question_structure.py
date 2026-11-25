"""Page-level question structure recovery with explicit uncertainty.

This module is deliberately conservative: it never invents a missing question
number or rewrites OCR text. It exposes numbered question units, leading
material / orphan text, and a reliability state that callers must honor before
building a retrieval query.
"""
from __future__ import annotations

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

    def query_for(self, indices: list[int], *, include_prefix: bool = True) -> str:
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
                    "preview": unit.text[:240],
                }
                for unit in self.units
            ],
        }


def analyze_page(text: str, *, min_chars: int = 20) -> PageStructure:
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

    prefix = value[: matches[0].start()].strip()
    units: list[QuestionUnit] = []
    for position, match in enumerate(matches):
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(value)
        body = value[start:end].strip()
        if len(body) >= min_chars:
            units.append(QuestionUnit(len(units), match.group(1), body, start, end))

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
        # A long unnumbered leading block with a single numbered unit is more
        # likely missing question number(s) than a complete material preamble.
        status = StructureStatus.INCOMPLETE
        reasons.append("PREFIX_WITHOUT_NUMBER")
    else:
        status = StructureStatus.RELIABLE

    return PageStructure(value, prefix, units, status, reasons, prefix_is_tail)
