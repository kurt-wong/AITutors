"""对真实封存 Manifest（Phase 2 修复后 2020 全国Ⅰ卷化学教师版，12 units）的映射断言。

只读：测试不修改任何封存产物。断言 Owner 裁决口径全部生效。

Phase 3（QCORE-ANSWER-FIDELITY-03）fixture 迁移（DSH Phase3 基线 §7）：
- 输入由旧封存 ``runs/qcore_e2e_01``（manifest_sha 585230ba…）切换为
  **Phase 2 封存 Manifest**（`Preprocessing/runs/qcore_answer_fidelity_02`，
  manifest_sha a0135baf…）；不得回流旧 Manifest。
- TestOwnerRulings 断言按 G-05/G-07/D-1/D-2 新口径**有意识改写**：
  Q3（inline_in_explanation）恢复 TypedAnswer；Q10/Q12（P-1/P-3）在
  disputed 归属下保留全部答案条目（不再是零答案）；Q12 图片答案落 AssetSlot。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    AnswerCompleteness,
    AssetSlot,
    Completeness,
    candidate_adapter,
)
from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import MappingContext, map_all  # noqa: E402

RUN_ROOT = Path(
    r"D:\Project\AITutors\Preprocessing\runs\qcore_answer_fidelity_02\chemistry"
)
SRC_MD = (
    RUN_ROOT
    / "ocr_output"
    / "高三"
    / "化学"
    / "2020全国I卷高考真题化学（教师版）(1).md"
)
MANIFEST = (
    RUN_ROOT / "manifest_output" / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
)
ANNOTATED = (
    RUN_ROOT
    / "manifest_output"
    / "2020全国I卷高考真题化学（教师版）(1).annotated.md"
)

#: Phase 2 封存 Manifest 终态哈希（DSH 复核在案）。
MANIFEST_SHA_PIN = (
    "a0135baf8729e2a035381e7085acc17b39e3d3c5e009f15e9d6fa50f85e122f4"
)
#: Phase 2 封存 OCR Markdown 哈希（DSH Phase3 基线 §1）。
SRC_MD_SHA_PIN = (
    "dee902ef16540079ed8eef3fef5a44443ecd58b48c801b229513aebe9524c1ef"
)

pytestmark = pytest.mark.skipif(
    not MANIFEST.is_file() or not SRC_MD.is_file(),
    reason="sealed Phase 2 manifest/OCR inputs not found",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def mappings():
    manifest_sha = _sha(MANIFEST)
    assert manifest_sha == MANIFEST_SHA_PIN, (
        f"sealed Phase 2 manifest changed: {manifest_sha}"
    )
    source_md_sha = _sha(SRC_MD)
    assert source_md_sha == SRC_MD_SHA_PIN, (
        f"sealed Phase 2 OCR markdown changed: {source_md_sha}"
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    lines = load_source_lines(str(SRC_MD))
    ctx = MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path=str(MANIFEST),
        manifest_name=MANIFEST.name,
        source_md_path=str(SRC_MD),
        source_md_name=SRC_MD.name,
        source_pdf_name="2020全国I卷高考真题化学（教师版）(1).pdf",
        annotated_md_name=ANNOTATED.name,
        manifest_sha=manifest_sha,
        source_md_sha=source_md_sha,
        source_pdf_sha="e" * 64,
        annotated_md_sha=_sha(ANNOTATED) if ANNOTATED.is_file() else "0" * 64,
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=SRC_MD.stat().st_size,
        source_pdf_bytes=1201552,
        annotated_md_bytes=ANNOTATED.stat().st_size if ANNOTATED.is_file() else 1,
        image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
        paper_id="2020全国I卷高考真题化学（教师版）(1)",
        subject="化学",
        run_id="qcore-answer-fidelity-03-tests",
    )
    return {m.unit_id: m for m in map_all(ctx)}


class TestAllUnits:
    def test_twelve_units_mapped(self, mappings):
        assert len(mappings) == 12

    @pytest.mark.parametrize(
        "unit_id", ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Q11", "Q12"]
    )
    def test_candidate_passes_contract_validation(self, mappings, unit_id):
        cand = mappings[unit_id].candidate
        # round-trip through the adapter re-runs every validator (F1/F2/…)
        candidate_adapter.validate_python(cand.model_dump(mode="json"))

    def test_subject_explicit_mapping(self, mappings):
        for m in mappings.values():
            assert m.candidate.source.subject == "化学"

    def test_all_ids_unique_and_idempotent_keys_differ(self, mappings):
        keys = [m.candidate.core.ingestion.candidate_idempotency_key for m in mappings.values()]
        assert len(set(keys)) == 12


class TestOwnerRulings:
    """Owner 裁决口径（Phase 3 期望；旧断言见 git 历史，按 G-05/G-07 改写）。"""

    def test_q1_q2_q4_q7_declared_complete(self, mappings):
        for uid in ("Q1", "Q2", "Q4", "Q5", "Q6", "Q7"):
            m = mappings[uid]
            dec = m.candidate.source.answer_declaration
            assert dec.attribution == "declared", uid
            assert m.candidate.core.completeness == Completeness.COMPLETE, uid
            assert len(m.candidate.core.answers) == 1, uid
            ans = m.candidate.core.answers[0]
            assert ans.answer_type == "single_choice", uid
            assert ans.completeness == AnswerCompleteness.FULL, uid

    def test_q1_q5_unit_level_conflicts_preserved(self, mappings):
        """D-2：单元级源内冲突两版本均保留、可区分来源，不选边、不阻断。"""
        for uid in ("Q1", "Q5"):
            m = mappings[uid]
            ans = m.candidate.core.answers[0]
            assert ans.answer_conflict == "source_conflict", uid
            stmts = [s for s in ans.statements if s.note and "source_conflict" in s.note]
            assert len(stmts) == 2, (uid, len(stmts))
            regions = {s.source_region for s in stmts}
            assert regions == {"stem_area", "answer_area"}, (uid, regions)
            conflicts = m.candidate.core.evidence.conflicts
            assert len(conflicts) == 1, uid
            assert conflicts[0].conflict_origin == "source_internal", uid
            assert conflicts[0].is_critical is True, uid
            # 源内冲突不阻断（G-08）：blocking 名单为空
            assert m.candidate.core.evidence.blocking_conflicts() == [], uid

    def test_q3_inline_answer_restored(self, mappings):
        """G-05：inline_in_explanation → 正式 SingleChoiceAnswer（旧口径丢答案）。"""
        m = mappings["Q3"]
        dec = m.candidate.source.answer_declaration
        assert dec.attribution == "declared"
        assert dec.declared_value == "A"
        assert m.candidate.core.completeness == Completeness.COMPLETE
        assert len(m.candidate.core.answers) == 1
        ans = m.candidate.core.answers[0]
        assert ans.answer_type == "single_choice"
        assert ans.answer_value == "A"
        assert ans.evidence_kind.value == "inline_in_explanation"
        assert ans.attribution == "attributed"
        stmt = ans.statements[0]
        assert stmt.source_region == "explanation_area"
        assert stmt.value_text == "A"
        assert stmt.locators[0].line_start == 338

    def test_q8_composite_sub_and_slot_attribution(self, mappings):
        """G-04/G-06：Q8 6 小问 8 空位逐归属（旧口径单串 '；' 切分）。"""
        m = mappings["Q8"]
        assert m.candidate.core.completeness == Completeness.INCOMPLETE
        assert len(m.candidate.core.answers) == 1
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        subs = comp.answer_value
        assert len(subs) == 6
        slot_counts = {
            sub.sub_label: len(sub.answer_value.slot_bindings) for sub in subs
        }
        assert slot_counts == {
            "(1)": 1,
            "(2)": 2,
            "(3)": 2,
            "(4)": 1,
            "(5)": 1,
            "(6)": 1,
        } or slot_counts == {
            "（1）": 1,
            "（2）": 2,
            "（3）": 2,
            "（4）": 1,
            "（5）": 1,
            "（6）": 1,
        }
        total_slots = sum(
            len(sub.answer_value.answer_value) for sub in subs
        )
        assert total_slots == 8

    def test_q9_disputed_slot_kept_with_versions(self, mappings):
        """D-2：Q9 (6)#1 争议空位 None + 全部冲突版本在案；Q9 (1) 单元级冲突保留。"""
        m = mappings["Q9"]
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        by_label = {sub.sub_label.strip("()（）"): sub for sub in comp.answer_value}
        sub6 = by_label["6"]
        inner = sub6.answer_value
        assert inner.answer_type == "fill_blank"
        assert inner.answer_value == (None,)
        assert inner.answer_conflict == "source_conflict"
        slot_stmts = [s for s in inner.statements if s.slot_index == 0]
        assert len(slot_stmts) == 2, [s.value_text for s in slot_stmts]
        assert sub6.attribution == "disputed"
        # 单元级冲突（(1) 的 0.110/0.10）也须保留两版本
        sub1 = by_label["1"]
        assert sub1.answer_conflict == "source_conflict"
        assert len(sub1.statements) == 2
        origins = {c.conflict_origin for c in m.candidate.core.evidence.conflicts}
        assert origins == {"source_internal"}

    def test_q10_p1_answers_kept_under_disputed(self, mappings):
        """DSH Phase3 基线 §3.4：P-1 ≠ 零答案——7 条全部保留，attribution=disputed。"""
        m = mappings["Q10"]
        dec = m.candidate.source.answer_declaration
        assert dec.attribution == "not_attributable"  # P-1 归属口径冻结
        assert m.candidate.core.completeness == Completeness.INCOMPLETE
        assert len(m.candidate.core.answers) == 1
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert comp.attribution == "disputed"
        total_slots = sum(
            len(sub.answer_value.answer_value) for sub in comp.answer_value
        )
        assert total_slots == 7
        for sub in comp.answer_value:
            assert sub.attribution == "disputed", sub.sub_label
        disputed = [
            r for r in m.candidate.core.evidence.records
            if r.evidence_status.value == "disputed"
        ]
        assert disputed, "P-1 manifest value must be retained as DISPUTED evidence"
        assert "P-1" in disputed[0].note

    def test_q12_p3_image_answers_and_disputed(self, mappings):
        """DSH Phase3 基线 §3.4/§5：Q12 7 条保留（含 2 图片槽），P-3 冻结
        attribution=disputed；图片答案落 AssetSlot + canonical asset_id。"""
        m = mappings["Q12"]
        dec = m.candidate.source.answer_declaration
        assert dec.attribution == "not_attributable"  # P-3 归属口径冻结
        assert len(m.candidate.core.answers) == 1
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        assert comp.attribution == "disputed"
        total_slots = sum(
            len(sub.answer_value.answer_value) for sub in comp.answer_value
        )
        assert total_slots == 7
        by_label = {sub.sub_label.strip("()（）"): sub for sub in comp.answer_value}
        inner5 = by_label["5"].answer_value
        assert inner5.answer_type == "fill_blank"
        assert isinstance(inner5.answer_value[0], AssetSlot)
        assert (
            inner5.answer_value[0].assets[0].asset_id
            == "img_in_image_box_150_396_396_557"
        )
        inner6 = by_label["6"].answer_value
        assert inner6.answer_type == "fill_blank"
        assert inner6.answer_value[0] == "6"
        assert isinstance(inner6.answer_value[1], AssetSlot)
        assert (
            inner6.answer_value[1].assets[0].asset_id
            == "img_in_image_box_534_397_602_549"
        )
        disputed = [
            r for r in m.candidate.core.evidence.records
            if r.evidence_status.value == "disputed"
        ]
        assert disputed, "P-3 manifest value must be retained as DISPUTED evidence"
        assert "P-3" in disputed[0].note
        # 图片语义描述不得伪装为源文答案证据：源文证据的 normalized_value 为空
        source_recs = [
            r for r in m.candidate.core.evidence.records
            if r.source.source_kind.value == "source_markdown"
        ]
        for r in source_recs:
            assert r.normalized_value is None
        # 答案图登记为 answer_image
        img_assets = {
            a.asset_id: a for a in m.candidate.core.content.assets
        }
        for stem in (
            "img_in_image_box_150_396_396_557",
            "img_in_image_box_534_397_602_549",
        ):
            assert stem in img_assets, stem
            assert img_assets[stem].asset_role == "answer_image", stem

    def test_q11_all_slots_mapped(self, mappings):
        """Q11 9 条 / 4 小问逐条映射（含 (2) 双空），不并单串。"""
        m = mappings["Q11"]
        comp = m.candidate.core.answers[0]
        assert comp.answer_type == "composite"
        subs = comp.answer_value
        assert len(subs) == 4
        total_slots = sum(len(sub.answer_value.answer_value) for sub in subs)
        assert total_slots == 9


class TestCompositeStructure:
    @pytest.mark.parametrize("unit_id", ["Q8", "Q9", "Q10", "Q11", "Q12"])
    def test_composite_tree_present(self, mappings, unit_id):
        m = mappings[unit_id]
        content = m.candidate.core.content
        tree = content.tree()
        assert tree, f"{unit_id} must expose parent→subs tree"
        for parent, subs in tree.items():
            assert len(subs) >= 2, (unit_id, parent, subs)
            by_id = {b.local_id: b for b in content.bodies}
            for s in subs:
                assert by_id[s].parent_question_ref == parent

    @pytest.mark.parametrize("unit_id", ["Q8", "Q9", "Q10", "Q11", "Q12"])
    def test_composite_single_question_candidate(self, mappings, unit_id):
        """综合题 1 个 Question Candidate：1 个顶层答案对象（CompositeAnswer）。"""
        assert len(mappings[unit_id].candidate.core.answers) == 1, unit_id

    @pytest.mark.parametrize("unit_id", ["Q8", "Q9", "Q10", "Q11", "Q12"])
    def test_materials_attached(self, mappings, unit_id):
        content = mappings[unit_id].candidate.core.content
        assert len(content.materials) == 1, unit_id
        parent = [b for b in content.bodies if b.parent_question_ref is None][0]
        assert content.materials[0].material_id in parent.material_ids

    @pytest.mark.parametrize("unit_id", ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"])
    def test_standalone_single_body(self, mappings, unit_id):
        content = mappings[unit_id].candidate.core.content
        assert len(content.bodies) == 1, unit_id
        assert content.bodies[0].parent_question_ref is None


class TestContentFidelity:
    def test_q3_shared_option_table_captured(self, mappings):
        body = mappings["Q3"].candidate.core.content.bodies[0]
        assert len(body.options) == 4
        labels = [o.label for o in body.options]
        assert labels == ["A", "B", "C", "D"]
        # 整表网格保留在 stem_blocks
        assert any(getattr(b, "kind", "") == "table" for b in body.stem_blocks)

    def test_explanation_blocks_kept(self, mappings):
        for uid, m in mappings.items():
            assert len(m.explanation_blocks) >= 1, uid

    def test_images_registered_as_assets(self, mappings):
        total_assets = sum(
            len(m.candidate.core.content.assets) for m in mappings.values()
        )
        assert total_assets >= 10, total_assets
        for m in mappings.values():
            for a in m.candidate.core.content.assets:
                assert len(a.content_hash) == 64, a.asset_id
                assert a.storage_path.startswith("_imgs/"), a.asset_id

    def test_no_cross_paper_override_leak(self, mappings):
        """F 作用域：同名 Q10/Q12 不得因裸 unit_id 命中化学 P-1/P-3 覆盖。"""
        from strict_adapter.rules import owner_override_reason

        chem = "2020全国I卷高考真题化学（教师版）(1)"
        chn = "2019江苏高考真题语文（教师版）(1)"
        assert owner_override_reason(f"{chem}/Q10") is not None
        assert owner_override_reason(f"{chem}/Q12") is not None
        assert owner_override_reason(f"{chn}/Q10") is None
        assert owner_override_reason(f"{chn}/Q12") is None
        # Q1/Q2/Q4–Q9/Q11 不受影响
        for uid in ("Q1", "Q5", "Q8", "Q9", "Q11"):
            assert owner_override_reason(f"{chem}/{uid}") is None, uid
