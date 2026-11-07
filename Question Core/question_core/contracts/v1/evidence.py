"""Evidence: the formal record of *where* an answer, explanation, or other
field came from.

Design rules encoded here (from the project direction document):

* A field may carry **multiple** evidence records.
* Evidence from different sources may co-exist and may **conflict**.
* New evidence never overwrites old evidence; it is appended, and the old
  record is marked ``superseded`` only when a human says so.
* There is no built-in rule that human evidence always beats official
  evidence — precedence is an explicit adjudication, not a type ordering.
* A critical answer conflict that is still ``unresolved`` must block formal
  approval (enforced by the state machine in :mod:`.state`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    ActorId,
    ConflictResolution,
    ContractModel,
    EvidenceRole,
    EvidenceStatus,
    JsonPointer,
    NoteText,
    Sha256Hex,
    SourceKind,
    Visibility,
    new_id,
    utc_now,
)
from datetime import datetime as _dt
from uuid import UUID


class SourceLocator(ContractModel):
    """A position inside a source document.

    Line numbers are 1-based inclusive, matching the Preprocessing manifests.
    ``page`` is 1-based when the source is a PDF. ``bbox`` is
    ``[x0, y0, x1, y1]`` in the PDF's own coordinate space when known.
    """

    kind: Literal["line_range", "page_region", "json_pointer", "table_cell"] = (
        "line_range"
    )
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    pointer: JsonPointer | None = None
    note: NoteText | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "SourceLocator":
        if self.line_start is not None and self.line_end is not None:
            if self.line_end < self.line_start:
                raise ValueError("line_end must be >= line_start")
        if self.kind == "line_range" and self.line_start is None:
            raise ValueError("line_range locator requires line_start")
        return self


class SourceRef(ContractModel):
    """Identity of a source artifact an evidence record points into."""

    source_id: Annotated[str, Field(min_length=1, max_length=300)]
    source_kind: SourceKind
    content_hash: Sha256Hex | None = None
    #: Human-readable path or URI. Kept as data only; never dereferenced by
    #: the contract layer.
    locator_uri: Annotated[str, Field(max_length=1000)] | None = None


class EvidenceRecord(ContractModel):
    """One piece of evidence for one target field."""

    evidence_id: UUID = Field(default_factory=new_id)
    #: RFC 6901 JSON Pointer into the owning document (Candidate payload or
    #: Question Revision payload), e.g. ``/answers/0/answer_value``.
    target_path: JsonPointer
    evidence_role: EvidenceRole
    source: SourceRef
    locators: tuple[SourceLocator, ...] = Field(default_factory=tuple)
    #: The verbatim value as found in the source, before any normalization.
    raw_value: str | None = None
    #: Optional normalized value produced by a *deterministic* transform.
    normalized_value: str | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.ACTIVE
    visibility: Visibility = Visibility.REVIEW_ONLY
    collected_at: _dt = Field(default_factory=utc_now)
    collected_by: ActorId | None = None
    note: NoteText | None = None

    @model_validator(mode="after")
    def _check_locator_presence(self) -> "EvidenceRecord":
        if not self.locators and self.raw_value is None:
            raise ValueError(
                "evidence must carry at least one locator or a raw_value"
            )
        return self


class EvidenceConflict(ContractModel):
    """A recorded disagreement between evidence records.

    Conflicts are first-class: they are never silently dropped and never
    resolved by "latest write wins". The resolution field records *how* the
    disagreement was settled, and ``resolved_by`` must be present whenever
    the resolution is anything other than ``unresolved``.
    """

    conflict_id: UUID = Field(default_factory=new_id)
    target_path: JsonPointer
    #: The evidence records that disagree.
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=2)]
    description: NoteText | None = None
    #: True when the disagreement is about an answer field and therefore
    #: blocks formal approval while unresolved.
    is_critical: bool = False
    resolution: ConflictResolution = ConflictResolution.UNRESOLVED
    resolved_by: ActorId | None = None
    resolved_at: _dt | None = None
    resolution_note: NoteText | None = None
    #: When resolved, the evidence record the adjudicator accepted.
    winning_evidence_id: UUID | None = None

    @model_validator(mode="after")
    def _check_resolution(self) -> "EvidenceConflict":
        resolved = self.resolution != ConflictResolution.UNRESOLVED
        if resolved and self.resolved_by is None:
            raise ValueError("a resolved conflict requires resolved_by")
        if not resolved and (self.resolved_by is not None or self.winning_evidence_id):
            raise ValueError(
                "an unresolved conflict must not carry resolved_by/winning evidence"
            )
        if self.winning_evidence_id is not None and self.winning_evidence_id not in (
            set(self.evidence_ids)
        ):
            raise ValueError("winning_evidence_id must be one of evidence_ids")
        return self


class EvidenceBundle(ContractModel):
    """All evidence for one document, kept append-only."""

    records: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    conflicts: tuple[EvidenceConflict, ...] = Field(default_factory=tuple)

    def for_target(self, target_path: JsonPointer) -> list[EvidenceRecord]:
        return [r for r in self.records if r.target_path == target_path]

    def unresolved_critical(self) -> list[EvidenceConflict]:
        return [
            c
            for c in self.conflicts
            if c.is_critical and c.resolution == ConflictResolution.UNRESOLVED
        ]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "EvidenceBundle":
        ids = [r.evidence_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence_id in bundle")
        cids = [c.conflict_id for c in self.conflicts]
        if len(cids) != len(set(cids)):
            raise ValueError("duplicate conflict_id in bundle")
        # Every conflict must reference evidence that exists in the bundle.
        by_id = {r.evidence_id: r for r in self.records}
        for conflict in self.conflicts:
            missing = [e for e in conflict.evidence_ids if e not in by_id]
            if missing:
                raise ValueError(
                    f"conflict {conflict.conflict_id} references unknown "
                    f"evidence ids: {missing}"
                )
            # N7: the conflict's target_path must match every referenced
            # evidence record's target_path — otherwise the conflict is
            # about a different field and is meaningless.
            for eid in conflict.evidence_ids:
                rec = by_id[eid]
                if rec.target_path != conflict.target_path:
                    raise ValueError(
                        f"conflict {conflict.conflict_id} targets "
                        f"{conflict.target_path} but evidence {eid} targets "
                        f"{rec.target_path}; a conflict must reference "
                        f"evidence for the same field"
                    )
        return self


__all__ = [
    "EvidenceBundle",
    "EvidenceConflict",
    "EvidenceRecord",
    "SourceLocator",
    "SourceRef",
]
