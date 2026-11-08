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
        attribution, _ = rules.resolve_attribution(unit)
        assert attribution == "declared"

    def test_answer_lines_without_value_downgraded(self):
        unit = {"unit_id": "Q1", "answer_evidence": {"type": "answer_lines", "value": None}}
        attribution, reason = rules.resolve_attribution(unit)
        assert attribution == "not_attributable"
        assert "forbids inventing" in reason

    def test_inline_in_explanation_not_attributable(self):
        unit = {
            "unit_id": "Q3",
            "answer_evidence": {"type": "inline_in_explanation", "value": "A"},
        }
        attribution, _ = rules.resolve_attribution(unit)
        assert attribution == "not_attributable"

    def test_unknown_kind_fail_closed(self):
        unit = {"unit_id": "QX", "answer_evidence": {"type": "something_new", "value": "A"}}
        attribution, reason = rules.resolve_attribution(unit)
        assert attribution == "not_attributable"
        assert "fail-closed" in reason


class TestOwnerOverrides:
    def test_q10_forced_not_attributable(self):
        unit = {"unit_id": "Q10", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, reason = rules.resolve_attribution(unit)
        assert attribution == "not_attributable"
        assert "P-1" in reason

    def test_q12_forced_not_attributable(self):
        unit = {"unit_id": "Q12", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, reason = rules.resolve_attribution(unit)
        assert attribution == "not_attributable"
        assert "P-3" in reason

    def test_q8_stays_declared(self):
        unit = {"unit_id": "Q8", "answer_evidence": {"type": "answer_lines", "value": "x"}}
        attribution, _ = rules.resolve_attribution(unit)
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
            rules.question_type({"original_question_type": "essay"})


class TestSubjectMapping:
    def test_explicit_authority(self):
        assert rules.SUBJECT_AUTHORITY["value"] == "化学"
        assert "input_manifest" in rules.SUBJECT_AUTHORITY["source"]
