"""对真实封存 Manifest（2020 全国Ⅰ卷化学教师版，12 units）的映射断言。

只读：测试不修改任何封存产物。断言 Owner 裁决口径全部生效。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    AnswerCompleteness,
    Completeness,
    candidate_adapter,
)
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
def mappings():
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
        run_id="qcore-e2e-01-20261108-104211",
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
    def test_q1_q2_q4_q7_declared_complete(self, mappings):
        for uid in ("Q1", "Q2", "Q4", "Q5", "Q6", "Q7"):
            m = mappings[uid]
            dec = m.candidate.source.answer_declaration
            assert dec.attribution == "declared", uid
            assert dec.completeness == Completeness.COMPLETE, uid
            assert m.candidate.core.completeness == Completeness.COMPLETE, uid
            assert len(m.candidate.core.answers) == 1, uid
            ans = m.candidate.core.answers[0]
            assert ans.completeness == AnswerCompleteness.FULL, uid

    def test_q3_inline_in_explanation_not_attributable(self, mappings):
        m = mappings["Q3"]
        dec = m.candidate.source.answer_declaration
        assert dec.attribution == "not_attributable"
        assert dec.declared_value is None
        assert dec.completeness == Completeness.INCOMPLETE
        assert m.candidate.core.completeness == Completeness.INCOMPLETE
        assert m.candidate.core.answers == ()
        # 证据保留（不得丢弃）
        assert any(r.raw_value for r in m.candidate.core.evidence.records)

    def test_q8_q9_q11_declared_but_unknown_completeness(self, mappings):
        for uid in ("Q8", "Q9", "Q11"):
            m = mappings[uid]
            dec = m.candidate.source.answer_declaration
            assert dec.attribution == "declared", uid
            assert len(m.candidate.core.answers) == 1, uid
            ans = m.candidate.core.answers[0]
            assert ans.completeness == AnswerCompleteness.UNKNOWN, uid
            # 不得转 complete
            assert m.candidate.core.completeness == Completeness.INCOMPLETE, uid

    def test_q10_p1_not_attributable(self, mappings):
        m = mappings["Q10"]
        dec = m.candidate.source.answer_declaration
        assert dec.attribution == "not_attributable"
        assert dec.completeness == Completeness.INCOMPLETE
        assert m.candidate.core.answers == ()
        # manifest value 保留为 DISPUTED 证据
        disputed = [
            r for r in m.candidate.core.evidence.records
            if r.evidence_status.value == "disputed"
        ]
        assert disputed, "P-1 manifest value must be retained as DISPUTED evidence"
        assert "P-1" in disputed[0].note

    def test_q12_p3_not_attributable(self, mappings):
        m = mappings["Q12"]
        dec = m.candidate.source.answer_declaration
        assert dec.attribution == "not_attributable"
        assert dec.completeness == Completeness.INCOMPLETE
        assert m.candidate.core.answers == ()
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
