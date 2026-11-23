"""D9 identity resolution: map a source anchor onto an existing Question.

The anchor is ``(paper_segment_id, section_id, question_numbers)``; the source
PDF hash is part of the candidate key, not of this lookup.

Resolution is segment-scoped and deliberately conservative (D9 C2):

1. only occurrences of the **same source document and the same logical paper
   segment** are eligible;
2. exact ``(section_id, question_numbers)`` hit inside that segment — reuse;
3. no exact hit — ``question_numbers`` alone, but only when it matches exactly
   one Question *inside the same segment* (this absorbs section-label drift,
   which is real: the same paper's section text changed across five manifests
   on 2026-11-23);
4. zero or multiple matches — never guess (no positional fallback, no
   cross-segment match).

A legacy occurrence without a stored segment counts as the single-segment
default (its ``source_document_id``); it can therefore only match an incoming
anchor whose segment is that same paper id, never an arbitrary segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from question_core.contracts.v1 import (
    IdentityAnchorError,
    build_section_id,
    normalize_section_label,
)


class AmbiguousIdentityError(ValueError):
    """More than one Question matches the anchor (in the same segment)."""


@dataclass(frozen=True)
class InstanceSlot:
    """The occurrence facts resolution is allowed to use."""

    question_id: UUID
    paper_segment_id: str
    section: str | None
    question_numbers: tuple[int, ...]
    ordinal: int


@dataclass(frozen=True)
class ResolveResult:
    question_id: UUID | None
    matched_by: str  # "exact" | "question_numbers" | "none"
    section_drift: bool = False
    candidates: int = 0


def section_ids_for_slots(slots: Iterable[InstanceSlot]) -> dict[UUID, str]:
    """Contiguous-run section ids over occurrences, ordered by ``ordinal``.

    Mirrors ``strict_adapter.mapper.section_ids_for`` so the anchor computed
    from an incoming manifest and the anchor reconstructed from stored
    instances agree.
    """
    ordered = sorted(slots, key=lambda s: s.ordinal)
    seen: dict[str, int] = {}
    out: dict[UUID, str] = {}
    prev: str | None = None
    ordinal = 0
    for slot in ordered:
        label = normalize_section_label(slot.section)
        if label != prev:
            seen[label] = seen.get(label, 0) + 1
            ordinal = seen[label]
            prev = label
        out[slot.question_id] = build_section_id(slot.section, ordinal)
    return out


def resolve_identity(
    slots: Iterable[InstanceSlot],
    *,
    paper_segment_id: str,
    section_id: str,
    question_numbers: tuple[int, ...],
) -> ResolveResult:
    """Resolve an anchor inside one logical paper segment.

    ``paper_segment_id`` is mandatory: an empty value fails closed rather than
    scanning the whole PDF (a double-paper PDF would otherwise let segment B
    reuse segment A's question with the same number).
    """
    segment = (paper_segment_id or "").strip()
    if not segment:
        raise IdentityAnchorError(
            "resolve_identity requires paper_segment_id; a missing segment "
            "must fail closed instead of scanning the whole document"
        )
    if not question_numbers:
        raise IdentityAnchorError(
            "resolve_identity requires question_numbers; a unit without "
            "printed numbers has no stable anchor"
        )

    # Defence in depth: the repository already filters by segment, but the
    # resolver must never accept a slot from another segment even if handed a
    # wider list.
    slots = [s for s in slots if s.paper_segment_id == segment]
    if not slots:
        return ResolveResult(None, "none", False, 0)

    by_id = section_ids_for_slots(slots)
    exact = [
        s
        for s in slots
        if by_id.get(s.question_id) == section_id
        and tuple(s.question_numbers) == question_numbers
    ]
    exact_ids = {s.question_id for s in exact}
    if len(exact_ids) == 1:
        return ResolveResult(next(iter(exact_ids)), "exact")
    if len(exact_ids) > 1:
        raise AmbiguousIdentityError(
            "identity anchor is ambiguous in segment "
            f"{segment!r}: {len(exact_ids)} questions share "
            f"section_id={section_id!r} and question_numbers="
            f"{list(question_numbers)}"
        )

    loose_ids = {
        s.question_id
        for s in slots
        if tuple(s.question_numbers) == question_numbers
    }
    if len(loose_ids) == 1:
        # Section text drifted between rounds — reuse only because the match
        # is unique inside this segment.
        return ResolveResult(
            next(iter(loose_ids)), "question_numbers", section_drift=True
        )
    if len(loose_ids) > 1:
        raise AmbiguousIdentityError(
            "identity anchor is ambiguous in segment "
            f"{segment!r}: section drift left {len(loose_ids)} questions with "
            f"question_numbers={list(question_numbers)}"
        )
    return ResolveResult(None, "none", False, 0)


__all__ = [
    "AmbiguousIdentityError",
    "InstanceSlot",
    "ResolveResult",
    "resolve_identity",
    "section_ids_for_slots",
]
