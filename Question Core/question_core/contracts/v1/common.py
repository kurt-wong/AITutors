"""Shared primitives for the Question Core v1 contract.

Every value object in this contract uses strict Pydantic v2 validation. The
enums here define the vocabulary shared across Candidate, Question, Evidence,
Answer and the three-dimensional state model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

# ---------------------------------------------------------------------------
# Contract identity
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "1.1.0"
CONTRACT_SCHEMA_ID = (
    "https://aitutor.example/schemas/question-core/contracts/v1"
)

# ---------------------------------------------------------------------------
# Generic constrained strings
# ---------------------------------------------------------------------------

#: A JSON Pointer (RFC 6901) addressing a field inside a document.
JsonPointer = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^(/([^/~]|~[01])*)*$"),
]

#: SHA-256 digest, lowercase hex.
Sha256Hex = Annotated[
    str,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]

#: A stable, non-secret identifier for a human or service actor.
ActorId = Annotated[str, StringConstraints(min_length=1, max_length=200)]

#: Free-form but bounded note text.
NoteText = Annotated[str, StringConstraints(max_length=4000)]


# ---------------------------------------------------------------------------
# Visibility / PII / distribution
# ---------------------------------------------------------------------------


class Visibility(str, Enum):
    """Who may read a field's content.

    ``review_only`` is what makes "unpublished is not unreadable" work:
    review staff see the full content while students see nothing until
    publication plus the per-field visibility policy allows it.
    """

    REVIEW_ONLY = "review_only"
    STUDENT_AFTER_SUBMIT = "student_after_submit"
    PUBLIC = "public"


class PiiStatus(str, Enum):
    NONE = "none"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class DistributionPolicy(str, Enum):
    """Redistribution policy for the *source material* (PDF, images).

    This is deliberately separate from question publication: publishing a
    question never grants the right to redistribute the teacher's PDF.
    """

    UNKNOWN = "unknown"
    NO_REDISTRIBUTION = "no_redistribution"
    INTERNAL_ONLY = "internal_only"
    REDISTRIBUTABLE = "redistributable"


class OwnerScope(str, Enum):
    """Ownership / tenancy boundary for a candidate or question."""

    PUBLIC_BANK = "public_bank"
    SCHOOL = "school"
    TEACHER = "teacher"
    STUDENT = "student"


class SourceKind(str, Enum):
    """Where a piece of evidence or content originated."""

    PREPROCESSING_MANIFEST = "preprocessing_manifest"
    SOURCE_MARKDOWN = "source_markdown"
    SOURCE_PDF = "source_pdf"
    ANSWER_TABLE = "answer_table"
    EXPLANATION_PROSE = "explanation_prose"
    STUDENT_UPLOAD = "student_upload"
    OCR_OUTPUT = "ocr_output"
    HUMAN_REVIEW = "human_review"
    DERIVED = "derived"


# ---------------------------------------------------------------------------
# Content / question taxonomy
# ---------------------------------------------------------------------------


class QuestionType(str, Enum):
    """Canonical question taxonomy.

    Covers the types observed across real Preprocessing manifests
    (single/multi choice, true/false, fill-in, short answer, cloze,
    grammar fill, reading, seven-to-five) plus the forms the direction
    document requires the model to hold (numeric, expression, chemical,
    multi-step).

    ``composite`` / ``standalone`` are **Unit Type** concepts (organizational
    structure), never Question Type (QCORE-DELIVERY-01-C-R5 cleanup): a
    composite Unit is ONE Question whose internal sub-questions live in the
    ``QuestionContent`` body tree (``parent_question_ref`` /
    ``sub_question_ids``), each keeping its own real answer-form type.
    """

    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"
    NUMERIC = "numeric"
    EXPRESSION = "expression"
    CHEMICAL = "chemical"
    MULTI_STEP = "multi_step"
    ESSAY = "essay"
    #: Observed in real English/Chinese papers; kept canonical so the
    #: adapter never has to degrade them to a catch-all.
    CLOZE = "cloze"
    GRAMMAR_FILL = "grammar_fill"
    READING = "reading"
    READING_EXPRESSION = "reading_expression"
    SEVEN_TO_FIVE = "seven_to_five"


class UnitType(str, Enum):
    """Structural role of a source unit in a paper."""

    STANDALONE_QUESTION = "standalone_question"
    COMPOSITE_QUESTION = "composite_question"
    MATERIAL = "material"
    SECTION = "section"


# ---------------------------------------------------------------------------
# Three-dimensional state model
# ---------------------------------------------------------------------------


class Completeness(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class ReviewState(str, Enum):
    NOT_READY = "not_ready"
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class PublicationState(str, Enum):
    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


# ---------------------------------------------------------------------------
# Evidence vocabulary
# ---------------------------------------------------------------------------


class EvidenceRole(str, Enum):
    """What the evidence is evidence *of*."""

    ANSWER = "answer"
    EXPLANATION = "explanation"
    STEM = "stem"
    OPTION = "option"
    MATERIAL = "material"
    TABLE = "table"
    ASSET = "asset"
    IDENTITY = "identity"
    OTHER = "other"


class EvidenceStatus(str, Enum):
    """Lifecycle of an individual evidence record."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    RESOLVED = "resolved"


class ConflictResolution(str, Enum):
    """How a conflict among evidence records was (or was not) settled."""

    UNRESOLVED = "unresolved"
    HUMAN_ADJUDICATED = "human_adjudicated"
    SOURCE_PRECEDENCE = "source_precedence"
    WITHDRAWN = "withdrawn"


class AnswerEvidenceKind(str, Enum):
    """How the answer evidence was declared upstream.

    Mirrors the real Preprocessing ``answer_evidence.type`` values so a
    Strict Adapter can map without re-interpreting semantics. The three
    cases in the Strict boundary table are:

    * ``ANSWER_LINES``        — declared, direct map.
    * ``ANSWER_TABLE_ROW``    — structured answer table with explicit
                                 question-number → answer mapping; allowed
                                 deterministic conversion, row evidence kept.
    * ``INLINE_IN_EXPLANATION`` / ``RANGE_STRING`` / ``ABSENT`` — no
                                 reliable per-question attribution outside
                                 the declared lines; anything the adapter
                                 cannot attribute becomes ``incomplete``.
    """

    ANSWER_LINES = "answer_lines"
    ANSWER_TABLE_ROW = "answer_table_row"
    INLINE_IN_EXPLANATION = "inline_in_explanation"
    RANGE_STRING = "range_string"
    ABSENT = "absent"


class AnswerCompleteness(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ABSENT = "absent"


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class UnsafeModelCopyError(Exception):
    """Raised when ``model_copy(update=...)`` is used on a contract model.

    Contract objects are immutable domain facts.  ``model_copy(update=…)``
    bypasses Pydantic validation and would allow unverified content — a
    changed ``content_hash``, an approved state without an approval record,
    a rewritten ``question_id``.  Legitimate state transitions must go
    through factory functions (``approve_revision``, ``publish_revision``,
    ``Revision.create``, …) that re-validate the full object.
    """


class ContractModel(BaseModel):
    """Base for every contract model: strict, extra-forbid, **deeply
    immutable**.

    ``frozen=True`` blocks attribute reassignment. Collection fields are
    declared as ``tuple`` (not ``list``) throughout the contract so nested
    containers cannot be mutated in place either. This is what makes the
    approval binding meaningful: once a Revision exists, neither its
    content, nor its identity, nor its approval record can be altered.

    .. warning::

       ``model_construct`` is Pydantic's low-level unchecked constructor.
       It is **not** part of the normal contract-object creation path and
       must never be called from business code.  Use ``model_validate`` or
       the dedicated factory class-methods instead.  (This round does not
       attempt to block ``model_construct`` itself — that is a broader
       Pydantic-API hardening exercise deferred to a later phase.)
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        str_strip_whitespace=True,
        use_enum_values=False,
        arbitrary_types_allowed=False,
    )

    def model_copy(
        self,
        *,
        update: dict | None = None,
        deep: bool = False,
    ) -> "ContractModel":
        """Copy the model, optionally with ``update``.

        ``update=None`` (or ``{}``) returns a faithful copy.
        A **non-empty** ``update`` is rejected with
        :class:`UnsafeModelCopyError` because it would bypass validation.

        Use a factory (e.g. ``Revision.create``, ``approve_revision``) or
        ``Model.model_validate(merged_dict)`` when a new object with
        changed fields is needed.
        """
        if update:
            raise UnsafeModelCopyError(
                f"{type(self).__name__}.model_copy(update=…) is forbidden: "
                "it bypasses validation and would produce a contract object "
                "whose hash, state and identity bindings are unverified. "
                "Use model_validate() or a dedicated factory method instead."
            )
        # Delegate to the base implementation for the plain-copy case.
        return super().model_copy(update=update, deep=deep)


# ---------------------------------------------------------------------------
# Content hashing (provisional algorithm)
# ---------------------------------------------------------------------------


def canonical_content_hash(*models: "ContractModel") -> str:
    """Canonical SHA-256 of one or more contract models' JSON forms.

    Algorithm (provisional, must be finalized before QCORE-02 — see N4):

    1. ``model_dump(mode="json")`` for each model — enums become values,
       tuples become arrays.
    2. ``json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
       over the combined list of dumps.
    3. UTF-8 encode, SHA-256, lowercase hex.

    The same content therefore always yields the same hash, and any content
    change yields a different one. ``Revision`` validates that its stored
    ``content_hash`` equals ``canonical_content_hash(content, answers,
    explanation_blocks)`` so the approval/publication binding is verifiable,
    not decorative.
    """
    import hashlib
    import json as _json

    if not models:
        raise ValueError("canonical_content_hash requires at least one model")
    payload = [m.model_dump(mode="json") for m in models]
    blob = _json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> UUID:
    return uuid4()


__all__ = [
    "CONTRACT_VERSION",
    "CONTRACT_SCHEMA_ID",
    "ActorId",
    "AnswerCompleteness",
    "AnswerEvidenceKind",
    "Completeness",
    "ConflictResolution",
    "ContractModel",
    "DistributionPolicy",
    "EvidenceRole",
    "EvidenceStatus",
    "JsonPointer",
    "NoteText",
    "OwnerScope",
    "PiiStatus",
    "PublicationState",
    "QuestionType",
    "ReviewState",
    "Sha256Hex",
    "SourceKind",
    "UnitType",
    "Visibility",
    "UnsafeModelCopyError",
    "canonical_content_hash",
    "new_id",
    "utc_now",
]
