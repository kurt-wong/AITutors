"""Synthetic contract fixtures for persistence tests.

Built from the contract models themselves (never from real exam data):
one revision covering every TypedAnswer kind, one rich revision covering
composite structure, materials, tables with merged cells, assets,
explanation blocks and evidence, plus candidate builders for both source
branches.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from question_core.contracts.v1 import (
    AnswerCompleteness,
    AnswerEvidenceKind,
    ApprovalRecord,
    Asset,
    BBox,
    CandidateCore,
    ChemicalAnswer,
    Completeness,
    CompositeAnswer,
    CompositeSubAnswer,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceRecord,
    ExpressionAnswer,
    FillBlankAnswer,
    ImageBlock,
    IngestionIdentity,
    InputHashes,
    Material,
    MaterialRef,
    MathBlock,
    MultiChoiceAnswer,
    MultiStepAnswer,
    NumericAnswer,
    OcrObservation,
    OptionItem,
    PreprocessingCandidate,
    PreprocessingSource,
    PreprocessingUnitRef,
    PublicationRecord,
    PublicationState,
    QuestionAggregate,
    QuestionBody,
    QuestionContent,
    QuestionIdentity,
    QuestionInstance,
    QuestionType,
    ReviewState,
    SingleChoiceAnswer,
    SourceDocumentRef,
    SourceLocator,
    SourceRef,
    SourceKind,
    StateSnapshot,
    StrictAnswerDeclaration,
    StudentUploadCandidate,
    StudentUploadSource,
    TableCell,
    TableBlock,
    TextBlock,
    UnitType,
    canonical_content_hash,
    derive_idempotency_key,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64

_FIXED_TIME = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Answers: every TypedAnswer kind
# ---------------------------------------------------------------------------


def make_all_answers() -> tuple:
    """One instance of every answer kind, incl. nested composite answers."""
    return (
        SingleChoiceAnswer(
            answer_value="B",
            completeness=AnswerCompleteness.FULL,
            evidence_kind=AnswerEvidenceKind.ANSWER_LINES,
        ),
        MultiChoiceAnswer(
            answer_value=("A", "C"),
            completeness=AnswerCompleteness.FULL,
            evidence_kind=AnswerEvidenceKind.ANSWER_TABLE_ROW,
        ),
        FillBlankAnswer(
            answer_value=("0.10", "2"),
            completeness=AnswerCompleteness.FULL,
        ),
        NumericAnswer(
            answer_value="0.10",
            unit="mol/L",
            tolerance=0.01,
            completeness=AnswerCompleteness.FULL,
        ),
        ExpressionAnswer(
            answer_value=r"\frac{1}{2}mv^2",
            notation="latex",
            completeness=AnswerCompleteness.FULL,
        ),
        ChemicalAnswer(
            answer_value="Fe-2e-=Fe2+",
            notation="plain",
            completeness=AnswerCompleteness.FULL,
        ),
        MultiStepAnswer(
            answer_value=("设未知数 x", "列方程 2x=4", "解得 x=2"),
            final_result="2",
            completeness=AnswerCompleteness.FULL,
        ),
        CompositeAnswer(
            answer_value=(
                CompositeSubAnswer(
                    sub_label="(1)",
                    answer_value=SingleChoiceAnswer(
                        answer_value="A",
                        completeness=AnswerCompleteness.FULL,
                    ),
                    completeness=AnswerCompleteness.FULL,
                ),
                CompositeSubAnswer(
                    sub_label="(2)",
                    answer_value=FillBlankAnswer(
                        answer_value=("x=2",),
                        completeness=AnswerCompleteness.FULL,
                    ),
                    completeness=AnswerCompleteness.FULL,
                ),
            ),
            completeness=AnswerCompleteness.FULL,
        ),
        CompositeSubAnswer(
            sub_label="(3)",
            answer_value=NumericAnswer(
                answer_value="7", completeness=AnswerCompleteness.FULL
            ),
            completeness=AnswerCompleteness.FULL,
        ),
    )


# ---------------------------------------------------------------------------
# Content: composite tree + material + merged-cell table + assets
# ---------------------------------------------------------------------------


def make_merged_table() -> TableBlock:
    """2x2 grid where the first cell spans both rows."""
    return TableBlock(
        table_id="tbl-1",
        n_rows=2,
        n_cols=2,
        caption="合并单元格表格",
        cells=(
            TableCell(row_index=0, col_index=0, content="左侧", rowspan=2, is_header=True),
            TableCell(row_index=0, col_index=1, content="右上"),
            TableCell(row_index=1, col_index=1, content="右下"),
        ),
    )


def make_rich_content() -> QuestionContent:
    asset = Asset(
        asset_id="fig-1",
        asset_role="figure",
        target_path="/bodies/0/stem_blocks/0",
        source_id="doc-1",
        page=3,
        bbox=BBox(x0=0.0, y0=0.0, x1=10.5, y1=20.0),
        storage_path="assets/fig-1.png",
        content_hash=_HASH_A,
        mime_type="image/png",
        width=640,
        height=480,
    )
    material = Material(
        material_id="mat-1",
        title="阅读材料",
        blocks=(
            TextBlock(text="这是共享材料。"),
            make_merged_table(),
        ),
        line_start=1,
        line_end=10,
    )
    parent = QuestionBody(
        local_id="q1",
        question_type=QuestionType.SHORT_ANSWER,
        printed_number="12",
        stem_blocks=(
            TextBlock(text="题干文本", line_start=11, line_end=12),
            MathBlock(latex="x^2+y^2=1", display=True),
            ImageBlock(asset_id="fig-1", alt_text="示意图"),
        ),
        material_ids=("mat-1",),
        sub_question_ids=("q1a", "q1b"),
        unit_type=UnitType.COMPOSITE_QUESTION,
    )
    sub1 = QuestionBody(
        local_id="q1a",
        question_type=QuestionType.SINGLE_CHOICE,
        printed_number="12(1)",
        stem_blocks=(TextBlock(text="子题一"),),
        options=(
            OptionItem(label="A", blocks=(TextBlock(text="选项甲"),)),
            OptionItem(label="B", blocks=(TextBlock(text="选项乙"),)),
        ),
        parent_question_ref="q1",
    )
    sub2 = QuestionBody(
        local_id="q1b",
        question_type=QuestionType.FILL_BLANK,
        printed_number="12(2)",
        stem_blocks=(
            MaterialRef(material_id="mat-1", label="材料一"),
            TextBlock(text="子题二"),
        ),
        parent_question_ref="q1",
    )
    return QuestionContent(
        bodies=(parent, sub1, sub2),
        materials=(material,),
        assets=(asset,),
    )


def make_rich_evidence() -> EvidenceBundle:
    rec1 = EvidenceRecord(
        evidence_id=UUID("00000000-0000-4000-8000-00000000e001"),
        target_path="/answers/0/answer_value",
        evidence_role="answer",
        source=SourceRef(
            source_id="md-1",
            source_kind=SourceKind.SOURCE_MARKDOWN,
            content_hash=_HASH_B,
            locator_uri="file://source.md",
        ),
        locators=(SourceLocator(kind="line_range", line_start=10, line_end=12),),
        raw_value="B",
        normalized_value="B",
    )
    rec2 = EvidenceRecord(
        evidence_id=UUID("00000000-0000-4000-8000-00000000e002"),
        target_path="/answers/0/answer_value",
        evidence_role="answer",
        source=SourceRef(
            source_id="table-1",
            source_kind=SourceKind.ANSWER_TABLE,
            content_hash=_HASH_C,
        ),
        locators=(
            SourceLocator(kind="table_cell", page=2, note="第2页答案表"),
        ),
        raw_value="B",
    )
    conflict = EvidenceConflict(
        conflict_id=UUID("00000000-0000-4000-8000-00000000e003"),
        target_path="/answers/0/answer_value",
        evidence_ids=(rec1.evidence_id, rec2.evidence_id),
        description="两个来源对同一字段的定位不一致",
        is_critical=True,
    )
    return EvidenceBundle(records=(rec1, rec2), conflicts=(conflict,))


# ---------------------------------------------------------------------------
# Revisions / aggregates
# ---------------------------------------------------------------------------


def make_single_answer_revision(
    question_id: UUID,
    *,
    revision_number: int = 1,
    answer: tuple | None = None,
    revision_id: UUID | None = None,
) -> "object":
    """A minimal revision whose answers tuple is ``answer`` (or one single
    choice).  Uses ``Revision.create`` so content_hash is derived."""
    from question_core.contracts.v1 import Revision

    content = QuestionContent(
        bodies=(
            QuestionBody(
                local_id="q1",
                question_type=QuestionType.SINGLE_CHOICE,
                stem_blocks=(TextBlock(text="题干"),),
            ),
        )
    )
    answers = answer or (
        SingleChoiceAnswer(
            answer_value="B", completeness=AnswerCompleteness.FULL
        ),
    )
    kwargs = {}
    if revision_id is not None:
        kwargs["revision_id"] = revision_id
    return Revision.create(
        question_id=question_id,
        revision_number=revision_number,
        question_type=QuestionType.SINGLE_CHOICE,
        content=content,
        answers=answers,
        **kwargs,
    )


def make_rich_revision(
    question_id: UUID,
    *,
    revision_number: int = 1,
    revision_id: UUID | None = None,
):
    """Rich revision: all answer kinds, composite content, table, assets,
    explanation blocks (the JSON-hydration path) and evidence with a
    critical conflict (state stays None, so F1 does not apply)."""
    from question_core.contracts.v1 import Revision

    rid = revision_id or UUID("00000000-0000-4000-8000-000000000066")
    content = make_rich_content()
    answers = make_all_answers()
    explanation_blocks = (
        TextBlock(text="解析：本题考查守恒。"),
        MathBlock(latex="E=mc^2", display=True),
        make_merged_table(),
    )
    content_hash = canonical_content_hash(
        content, *answers, *explanation_blocks
    )
    return Revision(
        revision_id=rid,
        question_id=question_id,
        revision_number=revision_number,
        question_type=QuestionType.SHORT_ANSWER,
        content=content,
        answers=answers,
        explanation_blocks=explanation_blocks,
        content_hash=content_hash,
        evidence=make_rich_evidence(),
        created_by="synthetic-builder",
        change_note="合成测试数据",
    )


def make_published_revision(
    question_id: UUID,
    *,
    revision_number: int = 1,
    revision_id: UUID | None = None,
):
    """A complete, approved and published revision (state round-trip)."""
    from question_core.contracts.v1 import Revision

    rid = revision_id or UUID("00000000-0000-4000-8000-000000000077")
    content = QuestionContent(
        bodies=(
            QuestionBody(
                local_id="q1",
                question_type=QuestionType.SHORT_ANSWER,
                stem_blocks=(TextBlock(text="简答题干"),),
            ),
        )
    )
    answers = (
        SingleChoiceAnswer(
            answer_value="A",
            completeness=AnswerCompleteness.FULL,
            evidence_kind=AnswerEvidenceKind.ANSWER_LINES,
        ),
    )
    content_hash = canonical_content_hash(content, *answers)
    approval = ApprovalRecord(
        approval_id=UUID("00000000-0000-4000-8000-0000000000a1"),
        revision_id=rid,
        content_hash=content_hash,
        approved_by="reviewer-1",
        approved_at=_FIXED_TIME,
        confirmed_fields=("content", "answer:0"),
        note="合成审批",
    )
    state = StateSnapshot(
        revision_id=rid,
        content_hash=content_hash,
        completeness=Completeness.COMPLETE,
        review=ReviewState.APPROVED,
        publication=PublicationState.PUBLISHED,
        approval=approval,
        publication_record=PublicationRecord(
            publication_id=UUID("00000000-0000-4000-8000-0000000000a2"),
            revision_id=rid,
            content_hash=content_hash,
            state=PublicationState.PUBLISHED,
            acted_by="publisher-1",
            acted_at=_FIXED_TIME,
        ),
    )
    return Revision(
        revision_id=rid,
        question_id=question_id,
        revision_number=revision_number,
        question_type=QuestionType.SHORT_ANSWER,
        content=content,
        answers=answers,
        content_hash=content_hash,
        state=state,
        created_by="synthetic-builder",
    )


def make_identity(question_id: UUID | None = None) -> QuestionIdentity:
    return QuestionIdentity(
        question_id=question_id
        or UUID("00000000-0000-4000-8000-000000000055"),
        identity_fingerprint="fp-synthetic-rich",
        embedding_ref=None,
        created_at=_FIXED_TIME,
    )


def make_instance(
    question_id: UUID,
    revision_id: UUID,
    *,
    instance_id: UUID | None = None,
    source_document_id: str = "synthetic_paper_2026",
    ordinal: int = 1,
) -> QuestionInstance:
    return QuestionInstance(
        instance_id=instance_id
        or UUID("00000000-0000-4000-8000-000000000088"),
        question_id=question_id,
        revision_id=revision_id,
        source_document_id=source_document_id,
        printed_number="12",
        question_numbers=(12,),
        section="第二部分",
        line_start=11,
        line_end=40,
        ordinal=ordinal,
    )


def make_rich_aggregate() -> QuestionAggregate:
    """Two revisions (rich + published) and two instances on two papers."""
    identity = make_identity()
    qid = identity.question_id
    rev1 = make_rich_revision(qid, revision_number=1)
    rev2 = make_published_revision(qid, revision_number=2)
    inst1 = make_instance(
        qid,
        rev1.revision_id,
        instance_id=UUID("00000000-0000-4000-8000-000000000088"),
        source_document_id="synthetic_paper_2026",
        ordinal=1,
    )
    inst2 = make_instance(
        qid,
        rev2.revision_id,
        instance_id=UUID("00000000-0000-4000-8000-000000000089"),
        source_document_id="synthetic_mock_2026",
        ordinal=1,
    )
    history = (rev2.state,)
    return QuestionAggregate(
        identity=identity,
        revisions=(rev1, rev2),
        instances=(inst1, inst2),
        state_history=history,
    )


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def _ingestion(
    source_type: str,
    doc_id: str,
    *,
    run_id: UUID | None = None,
    upload_hash: str | None = None,
) -> IngestionIdentity:
    hashes = InputHashes(
        manifest_hash=None if upload_hash else _HASH_A,
        source_md_hash=None if upload_hash else _HASH_B,
        source_pdf_hash=None if upload_hash else _HASH_C,
        upload_blob_hash=upload_hash,
    )
    kwargs = {}
    if run_id is not None:
        kwargs["ingestion_run_id"] = run_id
    return IngestionIdentity(
        candidate_idempotency_key=derive_idempotency_key(
            source_type=source_type,
            source_document_id=doc_id,
            input_hashes=hashes,
        ),
        adapter_version="strict-adapter/0.1.0",
        input_hashes=hashes,
        ingested_at=_FIXED_TIME,
        **kwargs,
    )


def make_preprocessing_candidate(
    *,
    candidate_id: UUID | None = None,
    doc_id: str = "synthetic_doc_pre",
) -> PreprocessingCandidate:
    """Complete preprocessing candidate carrying every answer kind."""
    core = CandidateCore(
        candidate_id=candidate_id
        or UUID("00000000-0000-4000-8000-0000000000c1"),
        question_type=QuestionType.SHORT_ANSWER,
        content=make_rich_content(),
        answers=make_all_answers(),
        evidence=make_rich_evidence(),
        completeness=Completeness.COMPLETE,
        ingestion=_ingestion("preprocessing", doc_id),
        created_at=_FIXED_TIME,
        created_by="synthetic-builder",
    )
    source = PreprocessingSource(
        source_document_id=doc_id,
        manifest_ref=SourceDocumentRef(
            doc_role="manifest", content_hash=_HASH_A, byte_size=1024
        ),
        source_md_ref=SourceDocumentRef(
            doc_role="source_markdown", content_hash=_HASH_B
        ),
        source_pdf_ref=SourceDocumentRef(
            doc_role="source_pdf", content_hash=_HASH_C
        ),
        unit=PreprocessingUnitRef(
            unit_id="unit-12",
            unit_type=UnitType.COMPOSITE_QUESTION,
            question_numbers=(12,),
            stem_lines=(11, 20),
            answer_lines=(80, 82),
        ),
        grade="高三",
        subject="化学",
        answer_declaration=StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="B",
            completeness=Completeness.COMPLETE,
        ),
    )
    return PreprocessingCandidate(core=core, source=source)


def make_student_upload_candidate(
    *,
    candidate_id: UUID | None = None,
    doc_id: str = "synthetic_doc_stu",
) -> StudentUploadCandidate:
    core = CandidateCore(
        candidate_id=candidate_id
        or UUID("00000000-0000-4000-8000-0000000000c2"),
        question_type=QuestionType.FILL_BLANK,
        content=QuestionContent(
            bodies=(
                QuestionBody(
                    local_id="q1",
                    question_type=QuestionType.FILL_BLANK,
                    stem_blocks=(TextBlock(text="学生上传的填空题"),),
                ),
            ),
            assets=(
                Asset(
                    asset_id="photo-1",
                    asset_role="photo",
                    storage_path="uploads/photo-1.jpg",
                    content_hash=_HASH_A,
                    mime_type="image/jpeg",
                ),
            ),
        ),
        answers=(
            FillBlankAnswer(
                answer_value=("3.14",),
                completeness=AnswerCompleteness.PARTIAL,
            ),
        ),
        evidence=make_rich_evidence(),
        completeness=Completeness.INCOMPLETE,
        ingestion=_ingestion(
            "student_upload", doc_id, upload_hash=_HASH_A
        ),
        created_at=_FIXED_TIME,
    )
    source = StudentUploadSource(
        source_document_id=doc_id,
        uploaded_by="student-42",
        upload_blob_hash=_HASH_A,
        upload_filename="photo.jpg",
        mime_type="image/jpeg",
        observations=(
            OcrObservation(
                observation_id="ocr-1",
                role="stem",
                text="学生上传的填空题",
                confidence=0.82,
                page=1,
                bbox=(10.0, 20.0, 300.0, 80.0),
                engine="paddleocr",
            ),
        ),
        answers_declared_absent=False,
    )
    return StudentUploadCandidate(core=core, source=source)
