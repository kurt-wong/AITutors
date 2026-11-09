"""Golden snapshot fixtures for the Question Core v1 contract.

These documents are produced *from* the Pydantic models. The test suite
validates them against the generated JSON Schema and asserts a stable
canonical-JSON digest. Any unintended contract change shows up as a digest
drift and must be reviewed before the snapshot is regenerated.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Question Core/
_ROOT = _PROJECT_ROOT / "question_core"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from question_core.contracts.v1 import (  # noqa: E402
    Asset,
    CandidateCore,
    EvidenceBundle,
    EvidenceRecord,
    FillBlankAnswer,
    IngestionIdentity,
    InputHashes,
    Material,
    NumericAnswer,
    OptionItem,
    PreprocessingCandidate,
    PreprocessingSource,
    PreprocessingUnitRef,
    QuestionBody,
    QuestionContent,
    QuestionIdentity,
    QuestionInstance,
    QuestionAggregate,
    QuestionType,
    Revision,
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
    OcrObservation,
    UnitType,
    Completeness,
    derive_idempotency_key,
    typed_answer_adapter,
)

GOLDEN_DIR = _ROOT / "golden" / "v1"

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64

#: Fixed UUIDs so the golden digest is deterministic across runs.
_UUID_CAND = "00000000-0000-4000-8000-000000000001"
_UUID_EVID = "00000000-0000-4000-8000-000000000002"
_UUID_RUN_PRE = "00000000-0000-4000-8000-000000000003"
_UUID_RUN_STU = "00000000-0000-4000-8000-000000000004"
_UUID_QID = "00000000-0000-4000-8000-000000000005"
_UUID_RID = "00000000-0000-4000-8000-000000000006"
_UUID_INST = "00000000-0000-4000-8000-000000000007"

#: Fixed timestamp so the golden digest is deterministic across runs.
from datetime import datetime, timezone  # noqa: E402

_FIXED_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ingestion(source_type: str, doc_id: str, hashes: InputHashes, run_id: str) -> IngestionIdentity:
    return IngestionIdentity(
        ingestion_run_id=run_id,
        candidate_idempotency_key=derive_idempotency_key(
            source_type=source_type,
            source_document_id=doc_id,
            input_hashes=hashes,
        ),
        adapter_version="strict-adapter/0.1.0",
        input_hashes=hashes,
        ingested_at=_FIXED_TIME,
    )


def build_preprocessing_candidate() -> PreprocessingCandidate:
    """A candidate shaped like a real single-choice unit from chem_2020_js."""
    hashes = InputHashes(
        manifest_hash=_HASH_A,
        source_md_hash=_HASH_B,
        source_pdf_hash=_HASH_C,
    )
    content = QuestionContent(
        bodies=[
            QuestionBody(
                local_id="q1",
                question_type=QuestionType.SINGLE_CHOICE,
                printed_number="1",
                stem_blocks=[TextBlock(text="下列说法正确的是", line_start=13, line_end=13)],
                options=[
                    OptionItem(
                        label="A",
                        blocks=[TextBlock(text="选项甲")],
                        line_start=15,
                        line_end=15,
                    ),
                    OptionItem(
                        label="B",
                        blocks=[TextBlock(text="选项乙")],
                        line_start=15,
                        line_end=15,
                    ),
                ],
                unit_type=UnitType.STANDALONE_QUESTION,
            )
        ],
        assets=[
            Asset(
                asset_id="img_203_1131",
                asset_role="figure",
                target_path="/bodies/0/stem_blocks/0",
                source_id="paper.manifest.json",
                page=1,
                storage_path="_imgs/img_in_image_box_203_1131_342_1327.jpg",
                content_hash=_HASH_D,
                mime_type="image/jpeg",
            )
        ],
    )
    core = CandidateCore(
        candidate_id=_UUID_CAND,
        question_type=QuestionType.SINGLE_CHOICE,
        content=content,
        answers=[
            SingleChoiceAnswer(
                answer_value="B",
                answer_display="B",
                evidence_kind="answer_lines",
                completeness="full",
            )
        ],
        evidence=EvidenceBundle(
            records=[
                EvidenceRecord(
                    evidence_id=_UUID_EVID,
                    target_path="/answers/0/answer_value",
                    evidence_role="answer",
                    source=SourceRef(
                        source_id="paper.md",
                        source_kind=SourceKind.SOURCE_MARKDOWN,
                        content_hash=_HASH_B,
                    ),
                    locators=[
                        SourceLocator(kind="line_range", line_start=388, line_end=388)
                    ],
                    raw_value="B",
                    collected_at=_FIXED_TIME,
                )
            ]
        ),
        completeness=Completeness.COMPLETE,
        identity_fingerprint="fp-chem-2020-js-q1",
        created_at=_FIXED_TIME,
        ingestion=_ingestion("preprocessing", "chem_2020_js/Q1", hashes, _UUID_RUN_PRE),
    )
    source = PreprocessingSource(
        source_document_id="chem_2020_js/Q1",
        manifest_ref=SourceDocumentRef(
            doc_role="manifest",
            content_hash=_HASH_A,
            locator_uri="package/paper.manifest.json",
        ),
        source_md_ref=SourceDocumentRef(
            doc_role="source_markdown",
            content_hash=_HASH_B,
            locator_uri="package/paper.md",
        ),
        source_pdf_ref=SourceDocumentRef(
            doc_role="source_pdf",
            content_hash=_HASH_C,
            locator_uri="package/paper.pdf",
        ),
        unit=PreprocessingUnitRef(
            unit_id="Q1",
            unit_type=UnitType.STANDALONE_QUESTION,
            question_numbers=[1],
            original_question_type="single_choice",
            section="单项选择题",
            printed_number="1",
            stem_lines=(13, 13),
            options_lines=(15, 15),
            answer_lines=(388, 388),
            explanation_lines=(390, 398),
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


def build_student_upload_candidate() -> StudentUploadCandidate:
    """A candidate shaped like a student's photo-upload with OCR output."""
    hashes = InputHashes(upload_blob_hash=_HASH_E)
    table = TableBlock(
        table_id="ph_table",
        n_rows=2,
        n_cols=3,
        cells=[
            TableCell(row_index=0, col_index=0, content="t/s", is_header=True),
            TableCell(row_index=0, col_index=1, content="pH", is_header=True),
            TableCell(row_index=0, col_index=2, content="c/(mol/L)", is_header=True),
            TableCell(row_index=1, col_index=0, content="0"),
            TableCell(row_index=1, col_index=1, content="1.0"),
            TableCell(row_index=1, col_index=2, content="0.10"),
        ],
    )
    content = QuestionContent(
        bodies=[
            QuestionBody(
                local_id="sub1",
                question_type=QuestionType.FILL_BLANK,
                printed_number="(1)",
                stem_blocks=[
                    TextBlock(text="由表求 c = "),
                    table,
                ],
                parent_question_ref="parent",
            ),
            QuestionBody(
                local_id="parent",
                question_type=QuestionType.FILL_BLANK,
                printed_number="21",
                stem_blocks=[TextBlock(text="某实验测得如下数据")],
                material_ids=["m1"],
                sub_question_ids=["sub1"],
                unit_type=UnitType.COMPOSITE_QUESTION,
            ),
        ],
        materials=[
            Material(
                material_id="m1",
                title="实验数据表",
                blocks=[table],
                line_start=1,
                line_end=12,
            )
        ],
    )
    core = CandidateCore(
        candidate_id=_UUID_CAND,
        question_type=QuestionType.FILL_BLANK,
        content=content,
        answers=[
            FillBlankAnswer(
                answer_value=["0.10"],
                evidence_kind="absent",
                completeness="unknown",
            )
        ],
        evidence=EvidenceBundle(),
        completeness=Completeness.INCOMPLETE,
        identity_fingerprint="fp-student-upload-001",
        created_at=_FIXED_TIME,
        ingestion=_ingestion("student_upload", "student_upload/2026-02-01/a1", hashes, _UUID_RUN_STU),
    )
    source = StudentUploadSource(
        source_document_id="student_upload/2026-02-01/a1",
        uploaded_by="student:Kurtw",
        upload_blob_hash=_HASH_E,
        upload_filename="week3_quiz.jpg",
        mime_type="image/jpeg",
        observations=[
            OcrObservation(
                observation_id="obs1",
                role="stem",
                text="某实验测得如下数据",
                confidence=0.82,
                page=1,
                engine="mineru/local",
            ),
            OcrObservation(
                observation_id="obs2",
                role="answer",
                text="",
                confidence=None,
                note="OCR could not read the answer line",
            ),
        ],
        answers_declared_absent=True,
        pii_status="suspected",
        distribution_policy="no_redistribution",
    )
    return StudentUploadCandidate(core=core, source=source)


def build_question_aggregate() -> QuestionAggregate:
    """A question with one revision, one instance and one approval-less state."""
    qid = _UUID_QID
    rid = _UUID_RID
    content = QuestionContent(
        bodies=[
            QuestionBody(
                local_id="q",
                question_type=QuestionType.NUMERIC,
                stem_blocks=[TextBlock(text="计算 c(NaOH)")],
            )
        ]
    )
    revision = Revision.create(
        revision_id=rid,
        question_id=qid,
        revision_number=1,
        question_type=QuestionType.NUMERIC,
        content=content,
        answers=(
            NumericAnswer(answer_value="0.10", unit="mol/L", tolerance=0.005),
        ),
        created_at=_FIXED_TIME,
    )
    state = StateSnapshot(revision_id=rid, content_hash=revision.content_hash)
    revision_data = revision.model_dump(mode="json")
    revision_data["state"] = state.model_dump(mode="json")
    revision = Revision.model_validate(revision_data)
    instance = QuestionInstance(
        instance_id=_UUID_INST,
        question_id=qid,
        revision_id=rid,
        source_document_id="chem_2020_js",
        printed_number="1",
        question_numbers=[1],
        line_start=13,
        line_end=15,
        created_at=_FIXED_TIME,
    )
    return QuestionAggregate(
        identity=QuestionIdentity(
            question_id=qid,
            identity_fingerprint="fp-numeric-c-naoh",
            created_at=_FIXED_TIME,
        ),
        revisions=[revision],
        instances=[instance],
    )


def canonical_digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_golden() -> dict[str, str]:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for name, builder in (
        ("preprocessing_candidate.json", build_preprocessing_candidate),
        ("student_upload_candidate.json", build_student_upload_candidate),
        ("question_aggregate.json", build_question_aggregate),
    ):
        doc = builder().model_dump(mode="json")
        path = GOLDEN_DIR / name
        path.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        out[name] = canonical_digest(doc)
    digests_path = GOLDEN_DIR / "golden_digests.json"
    digests_path.write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out


if __name__ == "__main__":
    print(json.dumps(write_golden(), indent=2, sort_keys=True))
