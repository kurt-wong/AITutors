"""Admission 初始状态绑定测试（QCORE-ADMISSION-01）。

核心断言：admit() 只绑定初始状态，绝不自动批准、绝不自动发布——
  complete   → complete   + pending_review + unpublished
  incomplete → incomplete + not_ready     + unpublished

使用真实封存 Manifest（2020 全国Ⅰ卷化学教师版，12 units）确定性映射，
只读；测试不修改任何封存产物。Q1 的 mapper state_plan 仍为遗留值
"approve_publish"——断言即便如此也不产生 approved/published。
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    Completeness,
    PublicationState,
    ReviewState,
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
def ctx() -> MappingContext:
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
        run_id="qcore-e2e-01-20261108-104211",
    )


@pytest.fixture(scope="module")
def mappings(ctx):
    return {m.unit_id: m for m in map_all(ctx)}


class TestNoAutoApproveOrPublish:
    """complete 不自动批准、不自动发布（Owner 硬约束）。"""

    def test_complete_unit_legacy_state_plan_is_approve_publish(self, mappings):
        # 前置事实：mapper 对 complete 仍产出遗留 state_plan="approve_publish"，
        # 旧 admit() 会据此自动 approve+publish。本测试组断言新行为不执行它。
        assert mappings["Q1"].state_plan == "approve_publish"

    def test_complete_unit_binds_pending_review_unpublished(self, mappings, ctx):
        res = admit(mappings["Q1"], ctx, ordinal=1)
        assert res.validated and res.admitted
        assert res.review_state == "pending_review"
        assert res.publication_state == "unpublished"

        snap = res.aggregate.state_history[-1]
        assert snap.completeness == Completeness.COMPLETE
        assert snap.review == ReviewState.PENDING_REVIEW
        assert snap.publication == PublicationState.UNPUBLISHED
        assert snap.approval is None
        assert snap.publication_record is None

    def test_complete_unit_history_has_no_approval_or_publication_events(
        self, mappings, ctx
    ):
        res = admit(mappings["Q1"], ctx, ordinal=1)
        history = res.aggregate.state_history
        assert len(history) == 1
        for snap in history:
            assert snap.approval is None
            assert snap.publication_record is None
        assert res.aggregate.published_revision() is None

    @pytest.mark.parametrize("unit_id", ["Q3", "Q8"])
    def test_incomplete_unit_binds_not_ready_unpublished(self, mappings, ctx, unit_id):
        # Q3 = not_attributable（无 TypedAnswer）；Q8 = declared 但 completeness=unknown
        assert mappings[unit_id].completeness == "incomplete"
        res = admit(mappings[unit_id], ctx, ordinal=1)
        assert res.validated and res.admitted
        assert res.review_state == "not_ready"
        assert res.publication_state == "unpublished"

        snap = res.aggregate.state_history[-1]
        assert snap.completeness == Completeness.INCOMPLETE
        assert snap.review == ReviewState.NOT_READY
        assert snap.publication == PublicationState.UNPUBLISHED
        assert snap.approval is None
        assert snap.publication_record is None

    def test_all_twelve_units_never_approved_or_published(self, mappings, ctx):
        for unit_id, mapping in sorted(mappings.items()):
            res = admit(mapping, ctx, ordinal=1)
            assert res.validated and res.admitted, unit_id
            assert res.review_state != "approved", unit_id
            assert res.publication_state == "unpublished", unit_id
            assert res.review_state in ("pending_review", "not_ready"), unit_id
            assert res.aggregate.published_revision() is None, unit_id
            for snap in res.aggregate.state_history:
                assert snap.approval is None, unit_id
                assert snap.publication_record is None, unit_id
            # 完整性与 mapper 声明一致（不硬编码 INCOMPLETE）
            expected = (
                Completeness.COMPLETE
                if mapping.completeness == "complete"
                else Completeness.INCOMPLETE
            )
            assert res.aggregate.state_history[-1].completeness == expected, unit_id

    def test_admission_log_flags_no_auto_actions(self, mappings, ctx):
        res = admit(mappings["Q1"], ctx, ordinal=1)
        state_log = res.log["state"]
        assert state_log["auto_approve"] is False
        assert state_log["auto_publish"] is False
        assert state_log["state_plan_not_executed"] == "approve_publish"
        assert state_log["history_len"] == 1


class TestContextAttribution:
    """created_by / note 取自当前上下文 ctx，不再硬编码化学卷。"""

    def test_created_by_and_note_from_ctx(self, mappings, ctx):
        test_ctx = dataclasses.replace(
            ctx,
            run_id="qcore-admission-01-test-run",
            paper_id="qcore-admission-01-test-paper",
            source_pdf_name="QCORE-ADMISSION-01-TEST-PAPER.pdf",
        )
        res = admit(mappings["Q1"], test_ctx, ordinal=1)
        revision = res.aggregate.revisions[0]
        instance = res.aggregate.instances[0]

        assert revision.created_by == "qcore-admission-01-test-run"
        assert revision.created_by != "qcore-e2e-01-phase-c"
        assert instance.note == "occurrence in QCORE-ADMISSION-01-TEST-PAPER.pdf"
        assert "2020 全国Ⅰ卷化学" not in (instance.note or "")
        assert instance.source_document_id == "qcore-admission-01-test-paper"

    def test_created_by_fallback_when_run_id_empty(self, mappings, ctx):
        test_ctx = dataclasses.replace(ctx, run_id="")
        res = admit(mappings["Q1"], test_ctx, ordinal=1)
        revision = res.aggregate.revisions[0]
        assert revision.created_by == "strict-adapter-admission"

    def test_default_fixture_ctx_run_id_used(self, mappings, ctx):
        res = admit(mappings["Q1"], ctx, ordinal=1)
        revision = res.aggregate.revisions[0]
        instance = res.aggregate.instances[0]
        assert revision.created_by == ctx.run_id
        assert instance.note == f"occurrence in {ctx.source_pdf_name}"
