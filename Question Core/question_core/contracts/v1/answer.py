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

from pydantic import Field, TypeAdapter, model_validator

from .common import (
    AnswerCompleteness,
    AnswerEvidenceKind,
    ContractModel,
    NoteText,
    Visibility,
)

#: A single choice label such as ``A`` or ``Ａ`` (full-width is normalized at
#: import time, not by the contract).
ChoiceLabel = Annotated[str, Field(min_length=1, max_length=4)]


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
    #: One entry per blank, in blank order.
    answer_value: Annotated[tuple[str, ...], Field(min_length=1)]


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
    #: The concrete answer of this sub-question, as one of the other kinds.
    answer_value: "TypedAnswer"


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
    "ChemicalAnswer",
    "CompositeAnswer",
    "CompositeSubAnswer",
    "ExpressionAnswer",
    "FillBlankAnswer",
    "MultiChoiceAnswer",
    "MultiStepAnswer",
    "NumericAnswer",
    "SingleChoiceAnswer",
    "TypedAnswer",
    "typed_answer_adapter",
]
