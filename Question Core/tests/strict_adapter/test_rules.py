"""Strict Adapter 规则层测试：契约 kind 映射 + Owner 裁决覆盖。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter import rules  # noqa: E402


class TestKindToAttribution:
    def test_contract_reference_pairs(self):
        """tests/test_strict_boundary.py:148-156 参数化对必须一致。"""
        assert rules.KIND_TO_ATTRIBUTION["answer_lines"] == "declared"
        assert rules.KIND_TO_ATTRIBUTION["answer_table_row"] == "table_row"
        assert rules.KIND_TO_ATTRIBUTION["inline_in_explanation"] == "not_attributable"
        assert rules.KIND_TO_ATTRIBUTION["range_string"] == "not_attributable"
        assert rules.KIND_TO_ATTRIBUTION["absent"] == "not_attributable"

    def test_answer_lines_with_value_declared(self):
        unit = {"unit_id": "Q1", "answer_evidence": {"type": "answer_lines", "value": "D"}}
        attribution, _ = rules.resolve_attribution(unit, "任意卷/Q1")
        assert attribution == "declared"

    def test_answer_lines_without_value_downgraded(self):
        unit = {"unit_id": "Q1", "answer_evidence": {"type": "answer_lines", "value": None}}
        attribution, reason = rules.resolve_attribution(unit, "任意卷/Q1")
        assert attribution == "not_attributable"
        assert "forbids inventing" in reason

    def test_inline_in_explanation_not_attributable(self):
        unit = {
            "unit_id": "Q3",
            "answer_evidence": {"type": "inline_in_explanation", "value": "A"},
        }
        attribution, _ = rules.resolve_attribution(unit, "任意卷/Q3")
        assert attribution == "not_attributable"

    def test_unknown_kind_fail_closed(self):
        unit = {"unit_id": "QX", "answer_evidence": {"type": "something_new", "value": "A"}}
        attribution, reason = rules.resolve_attribution(unit, "任意卷/QX")
        assert attribution == "not_attributable"
        assert "fail-closed" in reason


class TestOwnerOverrides:
    """M1：覆盖规则按 source_document_id（paper/unit）限定，不跨卷。"""

    CHEM = "2020全国I卷高考真题化学（教师版）(1)"
    CHN = "2019江苏高考真题语文（教师版）(1)"

    def test_chem_q10_forced_not_attributable(self):
        unit = {"unit_id": "Q10", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, reason = rules.resolve_attribution(unit, f"{self.CHEM}/Q10")
        assert attribution == "not_attributable"
        assert "P-1" in reason

    def test_chem_q12_forced_not_attributable(self):
        unit = {"unit_id": "Q12", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, reason = rules.resolve_attribution(unit, f"{self.CHEM}/Q12")
        assert attribution == "not_attributable"
        assert "P-3" in reason

    def test_chn_q10_NOT_hit_by_chem_override(self):
        """M1 定点验证：语文 Q10 不再误命中化学 P-1 覆盖。"""
        unit = {"unit_id": "Q10", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, reason = rules.resolve_attribution(unit, f"{self.CHN}/Q10")
        assert attribution == "declared"
        assert "P-1" not in reason

    def test_chn_q12_NOT_hit_by_chem_override(self):
        """M1 定点验证：语文 Q12 不再误命中化学 P-3 覆盖。"""
        unit = {"unit_id": "Q12", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, reason = rules.resolve_attribution(unit, f"{self.CHN}/Q12")
        assert attribution == "declared"
        assert "P-3" not in reason

    def test_chem_q8_stays_declared(self):
        unit = {"unit_id": "Q8", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, _ = rules.resolve_attribution(unit, f"{self.CHEM}/Q8")
        assert attribution == "declared"


class TestCompleteness:
    def test_transport_field_maps_verbatim(self):
        assert rules.answer_completeness({"answer_completeness": "unknown"}) == "unknown"
        assert rules.answer_completeness({"answer_completeness": "full"}) == "full"

    def test_semantic_field_never_read(self):
        unit = {
            "answer_completeness": "unknown",
            "answer_completeness_semantic": "full",
        }
        assert rules.answer_completeness(unit) == "unknown"

    def test_missing_defaults_unknown(self):
        assert rules.answer_completeness({}) == "unknown"

    def test_no_upgrade_order(self):
        assert rules.COMPLETENESS_ORDER["unknown"] < rules.COMPLETENESS_ORDER["full"]


class TestQuestionType:
    def test_known(self):
        assert rules.question_type({"original_question_type": "single_choice"}) == "single_choice"
        assert rules.question_type({"original_question_type": "short_answer"}) == "short_answer"

    def test_unknown_fail_closed(self):
        with pytest.raises(ValueError):
            rules.question_type({"original_question_type": "nonexistent_qtype"})


class TestSubjectMapping:
    """R1 B2：学科由 MappingContext 显式传递；无常量、无默认、fail-closed。"""

    def test_no_hardcoded_constant(self):
        assert not hasattr(rules, "SUBJECT_AUTHORITY")

    def test_subject_comes_from_context(self):
        from strict_adapter.mapper import MappingContext, map_unit

        unit = {
            "unit_id": "S1", "unit_type": "standalone_question",
            "question_numbers": [1], "printed_number": "1",
            "stem_lines": [1, 1], "original_question_type": "single_choice",
            "answer_evidence": {"type": "answer_lines", "lines": [2, 2],
                                "value": "A", "shared": False},
            "answer_completeness": "full",
            "options": [],
        }
        lines = ["1．题干", "【答案】A", "【解析】略"]
        for subject in ("化学", "语文", "英语"):
            ctx = MappingContext(
                lines=lines, manifest={"units": [unit], "grade": "高三",
                                       "image_assets": []},
                manifest_path="m.json", manifest_name="m.json",
                source_md_path="s.md", source_md_name="s.md",
                source_pdf_name="p.pdf", annotated_md_name="a.md",
                manifest_sha="0" * 64, source_md_sha="1" * 64,
                source_pdf_sha="2" * 64, annotated_md_sha="3" * 64,
                manifest_bytes=1, source_md_bytes=1, source_pdf_bytes=1,
                annotated_md_bytes=1, paper_id="paper-x", subject=subject,
                run_id="r1-test",
            )
            m = map_unit(unit, ctx)
            assert m.candidate.source.subject == subject

    def test_missing_subject_fail_closed(self):
        from strict_adapter.mapper import MappingContext, map_unit

        unit = {
            "unit_id": "S1", "unit_type": "standalone_question",
            "question_numbers": [1], "printed_number": "1",
            "stem_lines": [1, 1], "original_question_type": "single_choice",
            "answer_evidence": None, "answer_completeness": "full",
            "options": [],
        }
        ctx = MappingContext(
            lines=["x"], manifest={"units": [unit]},
            manifest_path="m.json", manifest_name="m.json",
            source_md_path="s.md", source_md_name="s.md",
            source_pdf_name="p.pdf", annotated_md_name="a.md",
            manifest_sha="0" * 64, source_md_sha="1" * 64,
            source_pdf_sha="2" * 64, annotated_md_sha="3" * 64,
            manifest_bytes=1, source_md_bytes=1, source_pdf_bytes=1,
            annotated_md_bytes=1, paper_id="paper-x",  # 无 subject
            run_id="r1-test",
        )
        with pytest.raises(ValueError, match="subject"):
            map_unit(unit, ctx)
