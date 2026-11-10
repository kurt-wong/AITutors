"""Question, Revision and QuestionInstance.

Three distinct concepts (direction document §4.1):

* **Question** — the logical identity of a question. A stable UUID that is
  *not* derived from content.
* **Revision** — one concrete content version of that question. Content
  changes create a new Revision; they never mutate an existing one.
* **QuestionInstance** — one occurrence of the question in one specific
  paper (2020 national paper, a provincial mock, a school quiz, ...).

``question_id`` / ``identity_fingerprint`` / ``content_hash`` are three
different things: identity for addressing, fingerprint for candidate
matching, content hash for integrity of one revision. Embeddings may be
used for similarity recall but are never a merge authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from .answer import TypedAnswer
from .common import (
    ActorId,
    ContractModel,
    NoteText,
    PublicationState,
    QuestionType,
    ReviewState,
    Sha256Hex,
    Visibility,
    canonical_content_hash,
    new_id,
    utc_now,
)
from .content import QuestionContent
from .evidence import EvidenceBundle
from .state import ApprovalRecord, PublicationRecord, StateSnapshot


class QuestionIdentity(ContractModel):
    """Stable identity of a logical question."""

    question_id: UUID = Field(default_factory=new_id)
    #: Matching/dedup feature. Deterministic from normalized content but
    #: **never** used as the primary key. Two questions with equal
    #: fingerprints are only merge *candidates*.
    identity_fingerprint: Annotated[str, Field(min_length=8, max_length=200)] | None = None
    #: Optional similarity hint (e.g. an embedding id). Advisory only.
    embedding_ref: Annotated[str, Field(max_length=200)] | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Revision(ContractModel):
    """One immutable content version of a question."""

    revision_id: UUID = Field(default_factory=new_id)
    question_id: UUID
    #: Monotonic within the question; 1-based.
    revision_number: int = Field(ge=1)
    content_hash: Sha256Hex
    question_type: QuestionType
    content: QuestionContent
    answers: tuple[TypedAnswer, ...] = Field(default_factory=tuple)
    explanation_blocks: tuple = Field(default_factory=tuple)
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    #: Visibility of the answer/explanation *content* for this revision.
    answer_visibility: Visibility = Visibility.REVIEW_ONLY
    explanation_visibility: Visibility = Visibility.REVIEW_ONLY
    state: StateSnapshot | None = None
    created_at: datetime = Field(default_factory=utc_now)
    created_by: ActorId | None = None
    change_note: NoteText | None = None

    @model_validator(mode="after")
    def _state_binding(self) -> "Revision":
        # F4: content_hash must be verifiable — it is the canonical hash of
        # the revision's substantive content (question body + answers +
        # explanation), not an arbitrary string someone happened to store.
        expected = canonical_content_hash(
            self.content, *self.answers, *self.explanation_blocks
        )
        if self.content_hash != expected:
            raise ValueError(
                "content_hash must equal canonical_content_hash(content, "
                "answers, explanation_blocks); the approval binding depends "
                "on this being verifiable"
            )
        if self.state is not None:
            if self.state.revision_id != self.revision_id:
                raise ValueError("state.revision_id must equal revision.revision_id")
            if self.state.content_hash != self.content_hash:
                raise ValueError("state.content_hash must equal revision.content_hash")
            # F1: an unresolved critical evidence conflict must block both
            # approval and publication — except source-internal conflicts
            # (the source document contradicts itself: preserved as fact,
            # never an approval/publication blocker — Owner D-2 / G-08).
            if self.state.review in (
                ReviewState.APPROVED,
            ) or self.state.publication == PublicationState.PUBLISHED:
                blocking = self.evidence.blocking_conflicts()
                if blocking:
                    targets = ", ".join(c.target_path for c in blocking)
                    raise ValueError(
                        "unresolved critical evidence conflict blocks "
                        f"approval/publication: {targets}"
                    )
        return self

    @classmethod
    def create(
        cls,
        *,
        question_id: UUID,
        revision_number: int,
        question_type: QuestionType,
        content: QuestionContent,
        answers: tuple = (),
        explanation_blocks: tuple = (),
        **kwargs,
    ) -> "Revision":
        """Build a Revision with the content hash computed from its content.

        This is the correct-by-construction entry point: the hash is
        derived, not hand-supplied, so it can never drift from the content.
        """
        content_hash = canonical_content_hash(
            content, *answers, *explanation_blocks
        )
        return cls(
            question_id=question_id,
            revision_number=revision_number,
            question_type=question_type,
            content=content,
            answers=answers,
            explanation_blocks=explanation_blocks,
            content_hash=content_hash,
            **kwargs,
        )


class QuestionInstance(ContractModel):
    """One occurrence of a question inside one paper."""

    instance_id: UUID = Field(default_factory=new_id)
    question_id: UUID
    #: The revision this occurrence was taken from at ingestion time.
    revision_id: UUID
    #: Identity of the paper / upload this occurrence belongs to.
    source_document_id: Annotated[str, Field(min_length=1, max_length=300)]
    printed_number: Annotated[str, Field(max_length=20)] | None = None
    question_numbers: tuple[int, ...] = Field(default_factory=tuple)
    section: Annotated[str, Field(max_length=300)] | None = None
    #: Source line range in the paper's markdown, when known.
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    ordinal: int = Field(default=1, ge=1)
    note: NoteText | None = None
    created_at: datetime = Field(default_factory=utc_now)


class QuestionAggregate(ContractModel):
    """The full record of one logical question.

    ``revisions`` is append-only. ``instances`` lists every known
    occurrence. ``state_history`` preserves every approval/publication event
    so rule 9 (history preserved) is structural, not a convention.
    """

    identity: QuestionIdentity
    revisions: Annotated[tuple[Revision, ...], Field(min_length=1)]
    instances: tuple[QuestionInstance, ...] = Field(default_factory=tuple)
    state_history: tuple[StateSnapshot, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _check_consistency(self) -> "QuestionAggregate":
        qid = self.identity.question_id
        numbers = [r.revision_number for r in self.revisions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("revision_number must be unique within a question")
        for rev in self.revisions:
            if rev.question_id != qid:
                raise ValueError("revision.question_id must match identity")
        for inst in self.instances:
            if inst.question_id != qid:
                raise ValueError("instance.question_id must match identity")
            if not any(r.revision_id == inst.revision_id for r in self.revisions):
                raise ValueError("instance references unknown revision")
        # At most one currently published revision (rule 8).
        from .state import PublicationState, check_single_published

        current = [
            r.state for r in self.revisions if r.state is not None
        ]
        if current:
            check_single_published(current)
        return self

    def current_revision(self) -> Revision:
        return max(self.revisions, key=lambda r: r.revision_number)

    def published_revision(self) -> Revision | None:
        from .state import PublicationState

        for rev in self.revisions:
            if rev.state is not None and rev.state.publication == PublicationState.PUBLISHED:
                return rev
        return None


__all__ = [
    "QuestionAggregate",
    "QuestionIdentity",
    "QuestionInstance",
    "Revision",
]
