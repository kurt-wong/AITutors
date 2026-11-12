"""Typed answers.

An answer is a structured domain object, never just a string. The concrete
payload is selected by ``answer_type``. This round defines representation,
structural validation and serialization only — there is no grading engine.

Supported kinds (direction document §4.3):

* single / multi choice
* fill-in blank
* numeric (with unit and tolerance)
* mathematical expression
* chemical formula / equation
* multi-step worked solution
* composite sub-question answer
* multiple accepted alternatives (on every kind)
"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from .common import (
    AnswerCompleteness,
    AnswerEvidenceKind,
    ContractModel,
    NoteText,
    Visibility,
)
from .evidence import SourceLocator

#: A single choice label such as ``A`` or ``Ａ`` (full-width is normalized at
#: import time, not by the contract).
ChoiceLabel = Annotated[str, Field(min_length=1, max_length=4)]

#: Source regions an answer statement / evidence record may come from.
#: Mirrors the Manifest region vocabulary.  ``option_area`` is deliberately
#: absent: option-area text lives in OptionItem blocks and its conflicts are
#: recorded as statements/evidence (CONTRACT_EXPRESSION_GAP, Phase 2 06/07).
SourceRegion = Literal[
    "answer_area",
    "answer_table",
    "explanation_area",
    "stem_area",
    "material",
    "unknown",
]

#: Verbatim vs derived text form.  ``compressed``/``combined``/``descriptive``
#: statements must never masquerade as source verbatim.
ValueForm = Literal["verbatim", "compressed", "combined", "descriptive"]


class AnswerStatement(ContractModel):
    """One source-anchored answer statement (the Answer Item carrier).

    ``value_text`` is what the source actually wrote (verbatim) or a
    labelled derivation (``compressed``/``combined``/``descriptive``);
    ``form`` makes the difference explicit.  Conflict versions each get
    their own statement so no source wording is lost or adjudicated.
    """

    statement_id: Annotated[str, Field(min_length=1, max_length=200)]
    value_text: Annotated[str, Field(min_length=1, max_length=4000)]
    form: ValueForm = "verbatim"
    source_region: SourceRegion = "unknown"
    sub_label: Annotated[str, Field(max_length=20)] | None = None
    #: Points at the ``answer_value`` tuple index this statement belongs to
    #: (fill-blank slot position).  ``None`` for whole-answer statements.
    slot_index: int | None = Field(default=None, ge=0)
    evidence_ref: UUID | None = None
    locators: tuple[SourceLocator, ...] = Field(default_factory=tuple)
    note: NoteText | None = None


class SlotBinding(ContractModel):
    """Blank identity: binds ``answer_value[i]`` to a printed blank slot."""

    #: 0-based index into the owning answer's ``answer_value`` tuple.
    slot_index: int = Field(ge=0)
    #: Print-anchored slot id, e.g. ``(2)#1`` = blank 1 of sub-question (2).
    slot_id: Annotated[str, Field(min_length=1, max_length=50)]
    sub_label: Annotated[str, Field(max_length=20)] | None = None
    sub_body_local_id: Annotated[str, Field(max_length=100)] | None = None


class AnswerAssetRef(ContractModel):
    """Reference to one image asset taking part in an answer."""

    asset_id: Annotated[str, Field(min_length=1, max_length=200)]
    #: ``answer_value``: the image *is* the answer content;
    #: ``answer_evidence``: corroborating answer-area figure;
    #: ``illustration``: ordinary stem illustration.
    role: Literal["answer_value", "answer_evidence", "illustration"] = "answer_value"


class AssetSlot(ContractModel):
    """One blank slot whose answer value is one or more images."""

    assets: Annotated[tuple[AnswerAssetRef, ...], Field(min_length=1)]


#: Fill-blank slot value union: text blank / image blank / disputed blank.
#: ``None`` is legal only for a disputed blank (``answer_conflict`` =
#: ``source_conflict`` whose statements hold every conflict version) —
#: the adapter must never silently pick one side.
SlotValue = Union[str, "AssetSlot", None]


class AnswerBase(ContractModel):
    """Fields shared by every answer kind."""

    #: Free-text rendering used for display. Kept separate from the typed
    #: value so a display form never silently changes grading semantics.
    answer_display: str | None = None
    accepted_alternatives: tuple[str, ...] = Field(default_factory=tuple)
    grading_rule: Literal["exact", "normalized", "numeric_tolerance", "set", "manual"] = (
        "exact"
    )
    #: Provenance of this answer, as declared upstream. Drives the Strict
    #: boundary: only ``ANSWER_LINES`` and ``ANSWER_TABLE_ROW`` are directly
    #: attributable; the rest must land as incomplete when attribution is
    #: not decidable.
    evidence_kind: AnswerEvidenceKind = AnswerEvidenceKind.ABSENT
    completeness: AnswerCompleteness = AnswerCompleteness.UNKNOWN
    visibility: Visibility = Visibility.REVIEW_ONLY
    note: NoteText | None = None
    #: Attribution axis (orthogonal to ``completeness``).  Default
    #: ``attributed`` only means "not declared otherwise", never "verified".
    attribution: Literal[
        "attributed", "partially_attributed", "unattributed", "disputed"
    ] = "attributed"
    #: ``source_conflict``: the source document gives inconsistent content
    #: for this answer across regions.  All versions live in ``statements``;
    #: the adapter never picks a winner.
    answer_conflict: Literal["none", "source_conflict"] = "none"
    #: Why content is missing when ``completeness`` is not ``full``:
    #: extraction gap vs source omission vs policy freeze.
    missing_reason: Literal[
        "extraction_gap", "source_not_provided", "policy_withheld"
    ] | None = None
    #: Source-anchored statement layer: verbatim/conflict/compressed text
    #: with per-statement region + locators.
    statements: tuple[AnswerStatement, ...] = Field(default_factory=tuple)
    #: Blank identity for multi-slot answers.
    slot_bindings: tuple[SlotBinding, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _missing_reason_axis(self) -> "AnswerBase":
        if self.missing_reason is not None and self.completeness == (
            AnswerCompleteness.FULL
        ):
            raise ValueError(
                "missing_reason must not accompany completeness='full'"
            )
        return self


class SingleChoiceAnswer(AnswerBase):
    answer_type: Literal["single_choice"] = "single_choice"
    answer_value: ChoiceLabel
    accepted_alternatives: tuple[ChoiceLabel, ...] = Field(default_factory=tuple)


class MultiChoiceAnswer(AnswerBase):
    answer_type: Literal["multi_choice"] = "multi_choice"
    #: Selected labels. Order-insensitive; stored sorted at validation time
    #: is *not* done automatically so that upstream order survives.
    answer_value: Annotated[tuple[ChoiceLabel, ...], Field(min_length=1)]
    grading_rule: Literal["set"] = "set"

    @model_validator(mode="after")
    def _no_dupes(self) -> "MultiChoiceAnswer":
        if len(self.answer_value) != len(set(self.answer_value)):
            raise ValueError("multi_choice answer_value must not repeat labels")
        return self


class FillBlankAnswer(AnswerBase):
    answer_type: Literal["fill_blank"] = "fill_blank"
    #: One entry per blank, in blank order.  Elements are ``SlotValue``:
    #: text (``str``), image blank (``AssetSlot``) or disputed blank
    #: (``None``, legal only under a source conflict — see validator).
    answer_value: Annotated[tuple[SlotValue, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _slot_values_valid(self) -> "FillBlankAnswer":
        none_idx = [i for i, v in enumerate(self.answer_value) if v is None]
        if not none_idx:
            return self
        if self.answer_conflict == "source_conflict":
            # D1 (Owner-confirmed): a disputed blank's statements hold every
            # conflict version — the adapter never silently picks one side.
            for i in none_idx:
                versions = [s for s in self.statements if s.slot_index == i]
                if len(versions) < 2:
                    raise ValueError(
                        f"disputed blank at slot_index={i} requires at least two "
                        "conflict-version statements for that slot (the statements "
                        "must hold every source version)"
                    )
            return self
        # QCORE-MISSING-ANSWER-SLOT-01: a missing blank = the slot exists but
        # no source-verified value can be bound (not a dispute).
        if self.completeness == AnswerCompleteness.FULL:
            raise ValueError(
                "None blank (non-disputed) requires completeness != 'full' "
                "(missing blank is a fact, not a complete answer)"
            )
        if self.missing_reason is None:
            raise ValueError(
                "None blank (non-disputed) requires missing_reason "
                "(extraction_gap / source_not_provided / policy_withheld)"
            )
        if self.attribution == "attributed":
            raise ValueError(
                "None blank (non-disputed) requires attribution != 'attributed' "
                "(missing must not pose as a silently skipped mapping)"
            )
        return self


class NumericAnswer(AnswerBase):
    answer_type: Literal["numeric"] = "numeric"
    #: Canonical decimal string, e.g. ``"0.10"`` or ``"-3.5e2"``. Kept as a
    #: string so trailing-zero significance ("0.10" vs "0.1") survives
    #: round-trips without float noise.
    answer_value: Annotated[str, Field(pattern=r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")]
    unit: Annotated[str, Field(max_length=50)] | None = None
    tolerance: float | None = Field(default=None, ge=0)
    grading_rule: Literal["numeric_tolerance", "exact"] = "numeric_tolerance"


class ExpressionAnswer(AnswerBase):
    """Mathematical expression or formula. Not evaluated by the contract."""

    answer_type: Literal["expression"] = "expression"
    answer_value: Annotated[str, Field(min_length=1, max_length=2000)]
    #: The notation the string is written in, so a future renderer does not
    #: have to guess.
    notation: Literal["latex", "asciimath", "plain"] = "latex"


class ChemicalAnswer(AnswerBase):
    """Chemical formula or equation, e.g. ``VO2+`` or ``Fe-2e-=Fe2+``."""

    answer_type: Literal["chemical"] = "chemical"
    answer_value: Annotated[str, Field(min_length=1, max_length=2000)]
    notation: Literal["plain", "latex"] = "plain"


class MultiStepAnswer(AnswerBase):
    """A worked solution with ordered steps."""

    answer_type: Literal["multi_step"] = "multi_step"
    answer_value: Annotated[tuple[str, ...], Field(min_length=1)]
    #: Final result(s) extracted from the steps, when the source states them
    #: explicitly. Optional; absence is not a defect.
    final_result: str | None = None


class CompositeSubAnswer(AnswerBase):
    """Answer belonging to one sub-question of a composite parent."""

    answer_type: Literal["composite_sub"] = "composite_sub"
    #: Sub-question label as printed, e.g. ``(1)`` or ``(5)``. The label is
    #: the stable key: sub-question *numbering* across papers is unreliable.
    sub_label: Annotated[str, Field(min_length=1, max_length=20)]
    #: Direct pointer to the QuestionBody of this sub-question (stable id);
    #: removes label ↔ body string guessing.  Optional for legacy data.
    sub_body_local_id: Annotated[str, Field(max_length=100)] | None = None
    #: The concrete answer of this sub-question, as one of the other kinds.
    #: ``None`` is legal for a sub-question whose answer the source omits
    #: (never fabricate one to "complete" the structure).
    answer_value: "TypedAnswer | None" = None

    @model_validator(mode="after")
    def _sub_answer_valid(self) -> "CompositeSubAnswer":
        if self.answer_value is None:
            # A missing sub-answer is a fact, but it must never pose as full.
            if self.completeness == AnswerCompleteness.FULL:
                raise ValueError(
                    "composite_sub with answer_value=None must not claim "
                    "completeness='full' (missing sub-answer is a fact, not a "
                    "complete answer)"
                )
            if (
                self.completeness == AnswerCompleteness.ABSENT
                and self.missing_reason is None
            ):
                raise ValueError(
                    "composite_sub with completeness='absent' requires "
                    "missing_reason (extraction_gap / source_not_provided / "
                    "policy_withheld)"
                )
            return self
        inner = self.answer_value
        if getattr(inner, "answer_type", None) == "fill_blank":
            none_idx = [
                i for i, v in enumerate(inner.answer_value) if v is None
            ]
            if none_idx:
                disputed = (
                    self.answer_conflict == "source_conflict"
                    or inner.answer_conflict == "source_conflict"
                )
                if disputed:
                    for i in none_idx:
                        versions = [
                            s
                            for s in tuple(self.statements) + tuple(inner.statements)
                            if s.slot_index == i
                        ]
                        if len(versions) < 2:
                            raise ValueError(
                                f"disputed blank at slot_index={i} requires at least "
                                "two conflict-version statements (on the sub-answer "
                                "or the fill-blank answer) for that slot"
                            )
                # 非 disputed 的 None 空位 = missing（QCORE-MISSING-ANSWER-SLOT-01）：
                # inner 的 _slot_values_valid 已强制 completeness != full +
                # missing_reason + attribution != attributed，此处不再重复拒绝。
        return self


class CompositeAnswer(AnswerBase):
    """Answers of a composite question, keyed by sub-question label.

    Parent-level answers must not be flattened into one string: each
    sub-question keeps its own typed answer and its own evidence.
    """

    answer_type: Literal["composite"] = "composite"
    answer_value: Annotated[tuple[CompositeSubAnswer, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_labels(self) -> "CompositeAnswer":
        labels = [s.sub_label for s in self.answer_value]
        if len(labels) != len(set(labels)):
            raise ValueError("composite sub-labels must be unique")
        return self


TypedAnswer = Annotated[
    Union[
        SingleChoiceAnswer,
        MultiChoiceAnswer,
        FillBlankAnswer,
        NumericAnswer,
        ExpressionAnswer,
        ChemicalAnswer,
        MultiStepAnswer,
        CompositeAnswer,
        CompositeSubAnswer,
    ],
    Field(discriminator="answer_type"),
]

#: Module-level adapter for parsing raw dicts into the right answer kind.
typed_answer_adapter: TypeAdapter[TypedAnswer] = TypeAdapter(TypedAnswer)

# Rebuild CompositeSubAnswer now that TypedAnswer exists.
CompositeSubAnswer.model_rebuild()


__all__ = [
    "AnswerAssetRef",
    "AnswerStatement",
    "AssetSlot",
    "ChemicalAnswer",
    "CompositeAnswer",
    "CompositeSubAnswer",
    "ExpressionAnswer",
    "FillBlankAnswer",
    "MultiChoiceAnswer",
    "MultiStepAnswer",
    "NumericAnswer",
    "SingleChoiceAnswer",
    "SlotBinding",
    "SlotValue",
    "TypedAnswer",
    "typed_answer_adapter",
]
