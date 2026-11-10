"""QCORE-ADMISSION-01：隔离测试库验证 admit() 状态绑定。

只写 qcore_dev_test（安全检查见 safety.verify_test_target），
绝不连接 qcore_delivery_01c。断言：
  complete   → complete   + pending_review + unpublished 持久化并回读一致；
  incomplete → incomplete + not_ready     + unpublished 持久化并回读一致；
  不产生 ApprovalRecord / PublicationRecord，不出现已发布 Revision。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # Question Core/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from question_core.contracts.v1 import (  # noqa: E402
    Completeness,
    PublicationState,
    ReviewState,
)
from question_core.persistence import (  # noqa: E402
    QuestionCoreRepository,
    session_scope,
)
from strict_adapter.admission import admit  # noqa: E402
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext, map_all  # noqa: E402

RUN_ROOT = Path(r"D:\Project\AITutors\runs\qcore_e2e_01\qcore-e2e-01-20261108-104211")
OCR_DIR = RUN_ROOT / "02_PREPROCESSING" / "artifacts" / "ocr" / "高考真题" / "化学"
RESLICE_DIR = RUN_ROOT / "02_PREPROCESSING" / "artifacts" / "reslice"
SRC_MD = OCR_DIR / "2020全国I卷高考真题化学（教师版）(1).md"
MANIFEST = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
ANNOTATED = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).annotated.md"

pytestmark = pytest.mark.skipif(
    not MANIFEST.is_file(), reason="sealed Phase-B manifest not found"
)


@pytest.fixture(scope="module")
def chem_ctx() -> MappingContext:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lines = load_source_lines(str(SRC_MD))
    return MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path=str(MANIFEST),
        manifest_name=MANIFEST.name,
        source_md_path=str(SRC_MD),
        source_md_name=SRC_MD.name,
        source_pdf_name="2020全国I卷高考真题化学（教师版）(1).pdf",
        annotated_md_name=ANNOTATED.name,
        manifest_sha="585230ba63148b2e5714c31d0d6dd0b38c26cdb7b1456f65ba11296fc47f5d18",
        source_md_sha="dee902ef16540079ed8eef3fef5a44443ecd58b48c801b229513aebe9524c1ef",
        source_pdf_sha="e58e921daca6b049214e87d0c2284ca91cc04e62745348ec4b7037b0059ba2be",
        annotated_md_sha="0" * 64,
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=SRC_MD.stat().st_size,
        source_pdf_bytes=1201552,
        annotated_md_bytes=ANNOTATED.stat().st_size,
        image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
        paper_id="2020全国I卷高考真题化学（教师版）(1)",
        subject="化学",
        run_id="qcore-admission-01-pytest",
    )


@pytest.fixture(scope="module")
def chem_mappings(chem_ctx):
    return {m.unit_id: m for m in map_all(chem_ctx)}


def _persist_and_readback(engine, mapping, res):
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(mapping.candidate, res.aggregate)
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        return repo.get_question_aggregate(uuid.UUID(res.question_id))


class TestAdmissionStateBindingInDb:
    def test_complete_question_persists_pending_review_unpublished(
        self, engine, clean_db, chem_ctx, chem_mappings
    ):
        mapping = chem_mappings["Q1"]
        assert mapping.completeness == "complete"
        res = admit(mapping, chem_ctx, ordinal=1)
        assert res.validated and res.admitted
        assert res.review_state == "pending_review"
        assert res.publication_state == "unpublished"

        agg = _persist_and_readback(engine, mapping, res)

        rev = agg.revisions[0]
        assert rev.state.completeness == Completeness.COMPLETE
        assert rev.state.review == ReviewState.PENDING_REVIEW
        assert rev.state.publication == PublicationState.UNPUBLISHED
        assert rev.state.approval is None
        assert rev.state.publication_record is None
        assert rev.created_by == chem_ctx.run_id
        assert rev.content_hash == res.content_hash

        assert agg.published_revision() is None
        assert len(agg.state_history) == 1
        assert agg.state_history[0].approval is None
        assert agg.state_history[0].publication_record is None

    def test_incomplete_question_persists_not_ready_unpublished(
        self, engine, clean_db, chem_ctx, chem_mappings
    ):
        mapping = chem_mappings["Q3"]
        assert mapping.completeness == "incomplete"
        res = admit(mapping, chem_ctx, ordinal=1)
        assert res.validated and res.admitted
        assert res.review_state == "not_ready"
        assert res.publication_state == "unpublished"

        agg = _persist_and_readback(engine, mapping, res)

        rev = agg.revisions[0]
        assert rev.state.completeness == Completeness.INCOMPLETE
        assert rev.state.review == ReviewState.NOT_READY
        assert rev.state.publication == PublicationState.UNPUBLISHED
        assert rev.state.approval is None
        assert rev.state.publication_record is None
        assert agg.published_revision() is None
        assert len(agg.state_history) == 1

    def test_twelve_questions_roundtrip_no_auto_actions(
        self, engine, clean_db, chem_ctx, chem_mappings
    ):
        results = []
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            for unit_id in sorted(chem_mappings):
                mapping = chem_mappings[unit_id]
                res = admit(mapping, chem_ctx, ordinal=len(results) + 1)
                assert res.validated and res.admitted, unit_id
                repo.save_candidate_with_question(mapping.candidate, res.aggregate)
                results.append((unit_id, res))

        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            approved = published = 0
            for unit_id, res in results:
                agg = repo.get_question_aggregate(uuid.UUID(res.question_id))
                rev = agg.revisions[0]
                assert rev.state.approval is None, unit_id
                assert rev.state.publication_record is None, unit_id
                assert agg.published_revision() is None, unit_id
                if rev.state.review == ReviewState.APPROVED:
                    approved += 1
                if rev.state.publication == PublicationState.PUBLISHED:
                    published += 1
                expected_review = (
                    ReviewState.PENDING_REVIEW
                    if rev.state.completeness == Completeness.COMPLETE
                    else ReviewState.NOT_READY
                )
                assert rev.state.review == expected_review, unit_id
                assert rev.state.publication == PublicationState.UNPUBLISHED, unit_id
            assert approved == 0
            assert published == 0
