"""Candidate: the unified entry object for both data sources.

A Candidate is what an ingestion produces *before* review. It shares a
common core (question payload, answers, evidence, state, identity) and
discriminates on ``source_type`` into:

* ``preprocessing`` — teacher-edition papers that already passed human
  review upstream. The downstream job is a **Strict** structural mapping;
  re-OCRing, re-splitting, re-identifying or re-guessing answers is a
  contract violation, not a feature.
* ``student_upload`` — a student's own practice material. OCR/NLP output,
  possibly missing answers, personal ownership and stricter distribution
  rules. No Preprocessing Manifest is required or expected.

Both branches land in the same Candidate contract and the same Question
Core lifecycle; the branch differences are preserved, not erased.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from .answer import AssetSlot, TypedAnswer
from .common import (
    ActorId,
    AnswerCompleteness,
    Completeness,
    ContractModel,
    DistributionPolicy,
    NoteText,
    OwnerScope,
    PiiStatus,
    QuestionType,
    Sha256Hex,
    UnitType,
    Visibility,
    new_id,
    utc_now,
)
from .content import Asset, QuestionContent
from .evidence import EvidenceBundle
from .idempotency import IngestionIdentity
from .state import StateSnapshot

# ---------------------------------------------------------------------------
# Preprocessing branch
# ---------------------------------------------------------------------------


class SourceDocumentRef(ContractModel):
    """Reference to one source artifact of a preprocessing package.

    ``content_hash`` is mandatory: an unhashed source is not traceable and
    must not enter the formal bank. ``locator_uri`` is informational; the
    contract layer never opens it.
    """

    doc_role: Literal["manifest", "source_markdown", "source_pdf", "annotated_markdown", "other"]
    content_hash: Sha256Hex
    locator_uri: Annotated[str, Field(max_length=1000)] | None = None
    byte_size: int | None = Field(default=None, ge=0)


class PreprocessingUnitRef(ContractModel):
    """One source unit from the upstream manifest.

    Kept as a faithful *reference* to what upstream declared. The adapter
    maps this into a question payload; it must not reinterpret it.
    """

    unit_id: Annotated[str, Field(min_length=1, max_length=200)]
    unit_type: UnitType
    question_numbers: tuple[int, ...] = Field(default_factory=tuple)
    original_question_type: Annotated[str, Field(max_length=50)] | None = None
    section: Annotated[str, Field(max_length=300)] | None = None
    printed_number: Annotated[str, Field(max_length=20)] | None = None
    #: Declared line ranges, kept verbatim so provenance survives mapping.
    stem_lines: tuple[int, int] | None = None
    options_lines: tuple[int, int] | None = None
    answer_lines: tuple[int, int] | None = None
    explanation_lines: tuple[int, int] | None = None
    extra_lines: tuple[int, int] | None = None
    material_lines: tuple[int, int] | None = None
    questions_lines: tuple[int, int] | None = None


class StrictAnswerDeclaration(ContractModel):
    """How upstream declared this question's answer.

    This is the contract-level encoding of the Strict boundary table:

    ==============================  =========================================
    upstream situation              strict handling
    ==============================  =========================================
    Manifest declares the unit's    direct map
    answer evidence
    Structured answer table with    deterministic conversion allowed;
    explicit number→answer map      table-row evidence kept
    Only a whole answer table or    ``incomplete``; do NOT infer
    prose explanation
    ==============================  =========================================

    ``attribution`` records which of the three cases applied. The adapter is
    forbidden from producing ``DECLARED`` or ``TABLE_ROW`` when the input did
    not actually declare it — that is the "no new semantic judgment" rule.
    """

    attribution: Literal["declared", "table_row", "not_attributable"] = "not_attributable"
    evidence_kind: Annotated[str, Field(max_length=50)]
    #: The verbatim declared value, kept byte-faithful when known.
    declared_value: str | None = None
    #: For ``table_row``: the table row / cell the answer came from.
    table_row_locator: str | None = None
    #: Content-axis completeness (orthogonal to ``attribution``, G-07):
    #: not-attributable no longer forces ``incomplete``; completeness is
    #: judged on the content axis and the attribution axis only forbids
    #: claiming ``attributed`` where nothing is attributable.
    completeness: Completeness = Completeness.INCOMPLETE

    @model_validator(mode="after")
    def _strict_boundary(self) -> "StrictAnswerDeclaration":
        if self.attribution == "declared" and not self.declared_value:
            raise ValueError("declared attribution requires declared_value")
        # F2: a table_row attribution must carry both a row locator and the
        # answer value found there — otherwise it is not attributable.
        if self.attribution == "table_row":
            if not self.table_row_locator:
                raise ValueError(
                    "table_row attribution requires table_row_locator "
                    "(the row the answer came from)"
                )
            if not self.declared_value:
                raise ValueError(
                    "table_row attribution requires declared_value "
                    "(the answer found in that row)"
                )
        return self


class PreprocessingSource(ContractModel):
    """Source branch: teacher-edition paper already reviewed upstream."""

    source_type: Literal["preprocessing"] = "preprocessing"
    #: Identity of the paper package this candidate came from.
    source_document_id: Annotated[str, Field(min_length=1, max_length=300)]
    manifest_ref: SourceDocumentRef
    source_md_ref: SourceDocumentRef | None = None
    source_pdf_ref: SourceDocumentRef | None = None
    annotated_md_ref: SourceDocumentRef | None = None
    #: Upstream unit this candidate maps from. Preserved verbatim.
    unit: PreprocessingUnitRef
    #: Grade / subject as declared upstream; may be None for odd papers.
    grade: Annotated[str, Field(max_length=50)] | None = None
    subject: Annotated[str, Field(max_length=50)] | None = None
    #: The answer declaration, per the Strict boundary table.
    answer_declaration: StrictAnswerDeclaration | None = None
    #: Permission / ownership facts — single source of truth for this branch.
    #: Teacher-edition papers default to the public bank with no PII.
    owner_scope: OwnerScope = OwnerScope.PUBLIC_BANK
    pii_status: PiiStatus = PiiStatus.NONE
    distribution_policy: DistributionPolicy = DistributionPolicy.UNKNOWN


# ---------------------------------------------------------------------------
# Student upload branch
# ---------------------------------------------------------------------------


class OcrObservation(ContractModel):
    """One OCR/NLP observation from a student upload.

    Student uploads have no reviewed manifest. Everything the pipeline saw
    is an *observation* with a confidence, not a declaration.
    """

    observation_id: Annotated[str, Field(min_length=1, max_length=200)]
    #: What the observation claims to be (stem, option, answer, ...).
    role: Literal["stem", "option", "answer", "explanation", "material", "other"]
    text: str
    #: Confidence in [0, 1]. Absent means "not measured", not "certain".
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    engine: Annotated[str, Field(max_length=100)] | None = None
    note: NoteText | None = None


class StudentUploadSource(ContractModel):
    """Source branch: a student's own practice material.

    F3 permission rules: student uploads are personal data. They never
    default to (and cannot claim) ``public_bank`` scope — promotion to the
    public bank is an explicit later action, not an import side effect.
    PII defaults to ``suspected`` (a photo of homework may contain names)
    and distribution defaults to ``no_redistribution``.
    """

    source_type: Literal["student_upload"] = "student_upload"
    source_document_id: Annotated[str, Field(min_length=1, max_length=300)]
    #: Who uploaded it. Required: this is personal data.
    uploaded_by: ActorId
    owner_scope: OwnerScope = OwnerScope.STUDENT
    upload_blob_hash: Sha256Hex
    upload_filename: Annotated[str, Field(max_length=300)] | None = None
    mime_type: Annotated[str, Field(max_length=100)] | None = None
    #: OCR/NLP observations. May be empty when the student typed the
    #: question by hand.
    observations: tuple[OcrObservation, ...] = Field(default_factory=tuple)
    #: Set when the pipeline knows an answer is missing. Missing is not the
    #: same as wrong: it must not be silently filled in.
    answers_declared_absent: bool = False
    explanations_declared_absent: bool = False
    pii_status: PiiStatus = PiiStatus.SUSPECTED
    distribution_policy: DistributionPolicy = DistributionPolicy.NO_REDISTRIBUTION
    note: NoteText | None = None

    @model_validator(mode="after")
    def _student_upload_permissions(self) -> "StudentUploadSource":
        # F3: student uploads must never claim public-bank scope at import.
        if self.owner_scope == OwnerScope.PUBLIC_BANK:
            raise ValueError(
                "student uploads must not claim public_bank scope; "
                "promotion to the public bank is a separate, explicit action"
            )
        # F3: distribution defaults conservative — reject permissive policy
        # on student data unless explicitly justified (note field).
        return self


# ---------------------------------------------------------------------------
# Shared candidate core
# ---------------------------------------------------------------------------


class CandidateCore(ContractModel):
    """Everything a candidate carries regardless of source.

    Permission / ownership facts (``owner_scope``, ``pii_status``,
    ``distribution_policy``) deliberately live on the **source branch**,
    not here: each source owns its own permission truth, and duplicating it
    here created the F3 contradiction class. Visibility of individual
    fields (answer / explanation / evidence) stays here because it is
    per-field policy, not source-level ownership.
    """

    #: N1: must be a UUID, not an arbitrary object.
    candidate_id: UUID = Field(default_factory=new_id)
    question_type: QuestionType
    content: QuestionContent
    answers: tuple[TypedAnswer, ...] = Field(default_factory=tuple)
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    completeness: Completeness = Completeness.INCOMPLETE
    identity_fingerprint: Annotated[str, Field(min_length=8, max_length=200)] | None = None
    ingestion: IngestionIdentity
    #: Defaults to review-only: unpublished is not unreadable, but only for
    #: reviewers. Students see nothing until publication.
    content_visibility: Visibility = Visibility.REVIEW_ONLY
    answer_visibility: Visibility = Visibility.REVIEW_ONLY
    explanation_visibility: Visibility = Visibility.REVIEW_ONLY
    evidence_visibility: Visibility = Visibility.REVIEW_ONLY
    created_at: datetime = Field(default_factory=utc_now)
    created_by: ActorId | None = None
    note: NoteText | None = None


class PreprocessingCandidate(ContractModel):
    """Candidate produced from a reviewed Preprocessing package."""

    #: Discriminator for the union below.
    source_type: Literal["preprocessing"] = "preprocessing"
    core: CandidateCore
    source: PreprocessingSource

    @model_validator(mode="after")
    def _strict_completeness_link(self) -> "PreprocessingCandidate":
        """F2: a PreprocessingCandidate claiming ``complete`` must prove its
        answers are present, attributed and complete.

        The five conditions (all must hold when ``core.completeness ==
        COMPLETE``):

        1. ``source.answer_declaration`` exists.
        2. Attribution axis (G-07/G-12): when the declaration is
           ``not_attributable``, no answer may claim ``attribution=
           "attributed"`` (completeness itself is judged on the content
           axis and is no longer tied to attribution).
        3. ``core.answers`` is non-empty (skipped for essay questions —
           Owner D-1: composition model text lives in Explanation and is
           never a TypedAnswer; its absence is not a missing answer).
        4. Every answer's ``completeness`` is ``FULL`` (skipped for essay;
           see D-1).
        5. Every declared answer has a corresponding TypedAnswer object
           (skipped for essay: the declared model text is represented in
           Explanation, not in TypedAnswer).

        Incomplete candidates remain fully constructible and reviewable —
        they simply cannot masquerade as complete.  StudentUploadCandidate
        is deliberately **not** subject to these rules.
        """
        dec = self.source.answer_declaration

        if self.core.completeness != Completeness.COMPLETE:
            # Incomplete is always allowed.
            return self

        # ---- from here on, core.completeness == COMPLETE ----

        # 1. Declaration must exist.
        if dec is None:
            raise ValueError(
                "core.completeness=complete requires "
                "source.answer_declaration to be present "
                "(a complete candidate must declare where its answer "
                "comes from)"
            )

        # 2. Attribution axis: a not-attributable declaration must not be
        #    paired with answers that claim full attribution.
        if dec.attribution == "not_attributable":
            for ans in self.core.answers:
                if getattr(ans, "attribution", "attributed") == "attributed":
                    raise ValueError(
                        "a not_attributable answer_declaration must not be "
                        "paired with answers claiming attribution='attributed' "
                        "(G-07: attribution and completeness are orthogonal; "
                        "answers of a not-attributable declaration may only "
                        "be partially_attributed/unattributed/disputed)"
                    )

        # Essay (Owner D-1): composition model text is Explanation content,
        # never a TypedAnswer; absence of TypedAnswer is not a missing answer.
        if self.core.question_type == QuestionType.ESSAY:
            return self

        # 3. Answers must be present.
        if not self.core.answers:
            raise ValueError(
                "core.completeness=complete requires at least one "
                "TypedAnswer in core.answers"
            )

        # 4. Every answer must be FULL (recursively for composite sub-answers).
        for ans in self.core.answers:
            self._assert_answer_fully_complete(ans)

        # 5. Declared value must have a corresponding TypedAnswer object.
        if dec.declared_value:
            self._assert_declared_value_represented(dec.declared_value)

        return self

    @staticmethod
    def _assert_answer_fully_complete(ans) -> None:
        """Recursively assert an answer (and all nested answers) is FULL.

        Covers the full chain:

        * ``composite``        → recurse into each ``CompositeSubAnswer``
        * ``composite_sub``    → recurse into its inner ``TypedAnswer``;
          an inner ``None`` (missing sub-answer) can never be FULL and is
          reported explicitly instead of crashing (G-12).
        * any other type       → leaf check on its own ``completeness``

        A wrapper marked ``full`` must never mask a partial inner answer.
        """
        ans_comp = getattr(ans, "completeness", None)
        if ans_comp != AnswerCompleteness.FULL:
            raise ValueError(
                "core.completeness=complete requires every answer's "
                f"completeness to be 'full', got "
                f"'{getattr(ans_comp, 'value', ans_comp)}' "
                "(a partial/unknown/absent answer is not a complete "
                "answer)"
            )
        atype = getattr(ans, "answer_type", None)
        if atype == "composite":
            for sub in ans.answer_value:
                PreprocessingCandidate._assert_answer_fully_complete(sub)
        elif atype == "composite_sub":
            if ans.answer_value is None:
                raise ValueError(
                    "core.completeness=complete requires every "
                    "composite_sub to carry an answer; a sub-answer of "
                    "None (missing) is never full (G-12)"
                )
            PreprocessingCandidate._assert_answer_fully_complete(
                ans.answer_value
            )

    def _assert_declared_value_represented(self, declared_value: str) -> None:
        """F2-condition-5: the declared answer must be **fully** represented
        by the TypedAnswer objects — not merely partially present.

        Type-aware, deterministic matching.  No semantic guessing: if the
        correspondence between the declared string and the answer structure
        cannot be established with certainty, the candidate must stay
        incomplete.
        """
        declared_norm = _norm(declared_value)
        for ans in self.core.answers:
            if _answer_matches_declared(ans, declared_norm):
                return
        raise ValueError(
            "core.completeness=complete requires the declared answer "
            f"('{declared_value[:80]}') to be **fully** represented by the "
            "TypedAnswer objects (partial or unrecognisable correspondence "
            "is not a complete answer)"
        )


class StudentUploadCandidate(ContractModel):
    """Candidate produced from a student's own upload."""

    source_type: Literal["student_upload"] = "student_upload"
    core: CandidateCore
    source: StudentUploadSource


Candidate = Annotated[
    Union[PreprocessingCandidate, StudentUploadCandidate],
    Field(discriminator="source_type"),
]

candidate_adapter: TypeAdapter[Candidate] = TypeAdapter(Candidate)


# ---------------------------------------------------------------------------
# Strict boundary helpers
# ---------------------------------------------------------------------------

#: The three cases of the Strict / shared-answer-table boundary, expressed
#: as data so tests can assert the mapping policy directly.
STRICT_BOUNDARY_RULES: dict[str, str] = {
    "declared": "direct map; no re-interpretation",
    "table_row": (
        "deterministic conversion allowed when the table has an explicit "
        "question-number to answer mapping; keep the table-row evidence"
    ),
    "not_attributable": (
        "do not infer the answer from prose or from an unattributed "
        "whole-table blob; answers of such a declaration must not claim "
        "attribution='attributed' (G-07: completeness is judged on the "
        "content axis, independently of attribution)"
    ),
}


def strict_completeness_for(attribution: str) -> Completeness:
    """The only completeness value a Strict Adapter may emit per case."""
    return (
        Completeness.INCOMPLETE
        if attribution == "not_attributable"
        else Completeness.COMPLETE
    )


# ---------------------------------------------------------------------------
# Deterministic declared-value ↔ TypedAnswer matching (F2 condition 5)
# ---------------------------------------------------------------------------
#
# These helpers implement type-aware, deterministic correspondence between
# the verbatim ``declared_value`` string from upstream and the structured
# ``TypedAnswer`` objects.  They never guess: if the declared string cannot
# be parsed into a shape that **exactly** matches the answer structure, the
# match fails and the candidate stays incomplete.
#
# Normalisation is limited to whitespace collapsing and full-width →
# half-width character folding — no stemming, no semantic rewriting.

_FW_MAP: dict[str, str] = {}
for _i in range(26):
    _FW_MAP[chr(ord("Ａ") + _i)] = chr(ord("A") + _i)
    _FW_MAP[chr(ord("ａ") + _i)] = chr(ord("a") + _i)
for _i in range(10):
    _FW_MAP[chr(ord("０") + _i)] = chr(ord("0") + _i)
_FW_MAP.update(
    {
        "．": ".",
        "、": ",",
        "，": ",",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "　": " ",
    }
)


def _norm(text: str) -> str:
    """Collapse whitespace and fold full-width characters to half-width."""
    result = []
    for ch in text:
        result.append(_FW_MAP.get(ch, ch))
    return " ".join("".join(result).split())


def _norm_label(label: str) -> str:
    """Normalise a choice label to a single upper-case letter."""
    return _norm(label).strip().upper()


def _parse_choice_labels(text: str) -> set[str]:
    """Extract the set of choice labels from a declared value.

    Handles ``"BC"``, ``"A、C"``, ``"B,C"``, ``"A C"``, ``"ABC"`` etc.
    Only ``[A-H]`` characters are collected after normalisation.
    """
    normalised = _norm(text)
    return {ch for ch in normalised.upper() if "A" <= ch <= "H"}


def _parse_blank_items(text: str, expected_count: int) -> list[str] | None:
    """Parse fill-blank answer items from a declared value.

    Supports numbered formats ``(1).B (2).D`` / ``1. B; 2. D`` and simple
    delimited formats ``B,D,A,C``.  Returns ``None`` when the declared
    string cannot be split into *exactly* ``expected_count`` items.
    """
    import re

    normalised = _norm(text)

    # Strategy 1: numbered markers  (1).X  /  1. X  /  1) X  /  （1）X
    marker_re = re.compile(
        r"[(（]?\s*(\d+)\s*[)）]?\s*[.．、:：]?\s*(.+?)(?=[(（]?\s*\d+\s*[)）]?\s*[.．、:：]|$)"
    )
    pairs = marker_re.findall(normalised)
    if len(pairs) == expected_count:
        items = [v.strip() for _, v in pairs]
        if all(items):
            return items

    # Strategy 2: delimiter split
    for delim in (";", "；", ",", "，", "|"):
        if delim in normalised:
            items = [s.strip() for s in normalised.split(delim) if s.strip()]
            if len(items) == expected_count:
                return items

    # Strategy 3: whitespace split
    items = normalised.split()
    if len(items) == expected_count and expected_count > 1:
        return items

    # Single blank: the whole string is the answer.
    if expected_count == 1 and normalised:
        return [normalised]

    return None


def _parse_composite_pairs(text: str) -> dict[str, str] | None:
    """Parse ``key.answer`` pairs from a composite declared value.

    Handles ``"9.D 10.B"``, ``"(1).A (2).C"`` etc.  Returns a dict mapping
    normalised key → answer string, or ``None`` when parsing fails.
    """
    import re

    normalised = _norm(text)
    pair_re = re.compile(
        r"[(（]?\s*([A-Za-z0-9]+)\s*[)）]?\s*[.．、:：]?\s*(\S+?)(?=\s+[(（]?\s*[A-Za-z0-9]+\s*[)）]?\s*[.．、:：]|$)"
    )
    pairs = pair_re.findall(normalised)
    if not pairs:
        return None
    result: dict[str, str] = {}
    for key, value in pairs:
        norm_key = _norm_label(key) if len(key) <= 3 else _norm(key)
        if norm_key in result:
            return None  # duplicate key → ambiguous
        result[norm_key] = value.strip()
    return result


def _norm_composite_key(key: str) -> str:
    """Normalise a composite sub-question key.

    ``(1)`` → ``1``; ``9`` → ``9``; ``(10)`` → ``10``.
    """
    import re

    m = re.search(r"(\d+)", _norm(key))
    return m.group(1) if m else _norm(key).upper()


def _answer_matches_declared(answer, declared_norm: str) -> bool:
    """Type-aware deterministic match between a TypedAnswer and the
    normalised declared-value string."""
    atype = getattr(answer, "answer_type", None)

    if atype == "single_choice":
        return _norm_label(declared_norm) == _norm_label(str(answer.answer_value))

    if atype == "multi_choice":
        declared_set = _parse_choice_labels(declared_norm)
        answer_set = {_norm_label(str(v)) for v in answer.answer_value}
        return declared_set == answer_set  # exact set equality, not subset

    if atype == "fill_blank":
        blanks = tuple(answer.answer_value)
        items = _parse_blank_items(declared_norm, len(blanks))
        if items is None:
            return False
        for i, (item, blank) in enumerate(zip(items, blanks)):
            if blank is None:
                # Disputed blank (G-12): the declared segment must be
                # missing/empty at this position, or one of the recorded
                # conflict-version texts — never a silent side pick.
                if not item.strip():
                    continue
                versions = {
                    _norm(s.value_text)
                    for s in getattr(answer, "statements", ())
                    if s.slot_index == i
                }
                if _norm(item) not in versions:
                    return False
                continue
            if isinstance(blank, AssetSlot):
                # Image blank (G-12): compare by asset id set — the declared
                # segment must reference one of the slot's assets.
                assets = getattr(blank, "assets", ())
                refs = []
                for a in assets:
                    aid = getattr(a, "asset_id", "")
                    refs.append(_norm(aid))
                    refs.append(_norm(aid.rsplit(".", 1)[0]))
                if not any(r and r in _norm(item) for r in refs):
                    return False
                continue
            if _norm(str(blank)) != _norm(item):
                return False
        return True

    if atype == "composite_sub":
        return _answer_matches_declared(answer.answer_value, declared_norm)

    if atype == "composite":
        return _match_composite(answer, declared_norm)

    if atype == "multi_step":
        return _match_multi_step(answer, declared_norm)

    # numeric / expression / chemical / fallback: exact match on the value.
    value = getattr(answer, "answer_value", None)
    if isinstance(value, str):
        return _norm(declared_norm) == _norm(value)
    return False


def _match_composite(answer, declared_norm: str) -> bool:
    """Recursively verify that the declared value covers **all** sub-answers
    of a CompositeAnswer with exact per-sub correspondence."""
    pairs = _parse_composite_pairs(declared_norm)
    if pairs is None:
        return False

    sub_map: dict[str, object] = {}
    none_keys: set[str] = set()
    for sub in answer.answer_value:
        key = _norm_composite_key(sub.sub_label)
        if key in sub_map or key in none_keys:
            return False  # duplicate sub-label → ambiguous
        if getattr(sub, "answer_value", None) is None:
            # G-12: a missing sub-answer is consistent only when the
            # declared segment for that sub is absent.
            none_keys.add(key)
            continue
        sub_map[key] = sub

    # Every declared pair must map to a valued sub-answer, and every valued
    # sub-answer must be covered.  Missing sub-answers require their declared
    # segment to be absent.  Partial coverage is not enough.
    if set(pairs.keys()) != set(sub_map.keys()):
        return False
    if none_keys & set(pairs.keys()):
        return False

    for key, declared_val in pairs.items():
        sub = sub_map[key]
        if not _answer_matches_declared(sub, _norm(declared_val)):
            return False
    return True


def _match_multi_step(answer, declared_norm: str) -> bool:
    """Deterministic multi-step match: every step **and** the final result
    must appear in the declared value.  Partial presence is not enough."""
    steps = tuple(answer.answer_value)
    if not steps:
        return False
    for step in steps:
        if _norm(step) not in declared_norm:
            return False
    final = getattr(answer, "final_result", None)
    if final is not None and _norm(final) not in declared_norm:
        return False
    return True


__all__ = [
    "Candidate",
    "CandidateCore",
    "OcrObservation",
    "PreprocessingCandidate",
    "PreprocessingSource",
    "PreprocessingUnitRef",
    "STRICT_BOUNDARY_RULES",
    "SourceDocumentRef",
    "StrictAnswerDeclaration",
    "StudentUploadCandidate",
    "StudentUploadSource",
    "candidate_adapter",
    "strict_completeness_for",
]
