"""Typed answers: every kind, alternatives, round-trip, rejection of bad shape."""

from __future__ import annotations

import pytest

from pydantic import ValidationError


class TestChoiceAnswers:
    def test_single_choice(self, contract):
        ans = contract.SingleChoiceAnswer(answer_value="B")
        assert ans.answer_type == "single_choice"
        assert ans.answer_value == "B"
        assert ans.accepted_alternatives == ()

    def test_single_choice_alternatives(self, contract):
        ans = contract.SingleChoiceAnswer(
            answer_value="B", accepted_alternatives=["C"]
        )
        assert ans.accepted_alternatives == ("C",)

    def test_multi_choice_is_a_set(self, contract):
        ans = contract.MultiChoiceAnswer(answer_value=["A", "C", "D"])
        assert ans.grading_rule == "set"

    def test_multi_choice_rejects_duplicates(self, contract):
        with pytest.raises(ValidationError, match="must not repeat"):
            contract.MultiChoiceAnswer(answer_value=["A", "A"])


class TestFillAndNumeric:
    def test_fill_blank_keeps_blank_order(self, contract):
        ans = contract.FillBlankAnswer(answer_value=["0.10", "Fe3+"])
        assert ans.answer_value == ("0.10", "Fe3+")

    def test_numeric_keeps_trailing_zeros(self, contract):
        ans = contract.NumericAnswer(answer_value="0.10", unit="mol/L")
        assert ans.answer_value == "0.10", "trailing zero significance must survive"
        assert ans.unit == "mol/L"

    def test_numeric_rejects_non_number(self, contract):
        with pytest.raises(ValidationError):
            contract.NumericAnswer(answer_value="abc")

    def test_numeric_tolerance(self, contract):
        ans = contract.NumericAnswer(answer_value="0.10", tolerance=0.005)
        assert ans.tolerance == 0.005
        assert ans.grading_rule == "numeric_tolerance"


class TestExpressionAndChemical:
    def test_expression(self, contract):
        ans = contract.ExpressionAnswer(
            answer_value=r"\frac{1}{2}", notation="latex"
        )
        assert ans.notation == "latex"

    def test_chemical(self, contract):
        ans = contract.ChemicalAnswer(answer_value="VO2+", notation="plain")
        assert ans.answer_type == "chemical"


class TestMultiStepAndComposite:
    def test_multi_step(self, contract):
        ans = contract.MultiStepAnswer(
            answer_value=["设物质的量为 n", "n = cV = 0.010 mol"],
            final_result="0.010 mol",
        )
        assert len(ans.answer_value) == 2

    def test_composite_sub_answer(self, contract):
        sub = contract.CompositeSubAnswer(
            sub_label="(1)",
            answer_value=contract.SingleChoiceAnswer(answer_value="A"),
        )
        assert sub.answer_type == "composite_sub"
        assert sub.answer_value.answer_value == "A"

    def test_composite_answer_keyed_by_label(self, contract):
        comp = contract.CompositeAnswer(
            answer_value=[
                contract.CompositeSubAnswer(
                    sub_label="(1)",
                    answer_value=contract.SingleChoiceAnswer(answer_value="A"),
                ),
                contract.CompositeSubAnswer(
                    sub_label="(2)",
                    answer_value=contract.NumericAnswer(answer_value="0.10"),
                ),
            ]
        )
        assert [s.sub_label for s in comp.answer_value] == ["(1)", "(2)"]

    def test_composite_rejects_duplicate_labels(self, contract):
        with pytest.raises(ValidationError, match="sub-labels must be unique"):
            contract.CompositeAnswer(
                answer_value=[
                    contract.CompositeSubAnswer(
                        sub_label="(1)",
                        answer_value=contract.SingleChoiceAnswer(answer_value="A"),
                    ),
                    contract.CompositeSubAnswer(
                        sub_label="(1)",
                        answer_value=contract.SingleChoiceAnswer(answer_value="B"),
                    ),
                ]
            )


class TestDiscriminatedUnion:
    def test_union_dispatches_on_answer_type(self, contract):
        payload = {"answer_type": "numeric", "answer_value": "3.14"}
        ans = contract.typed_answer_adapter.validate_python(payload)
        assert isinstance(ans, contract.NumericAnswer)

    def test_union_rejects_unknown_kind(self, contract):
        with pytest.raises(ValidationError):
            contract.typed_answer_adapter.validate_python(
                {"answer_type": "telepathy", "answer_value": "x"}
            )

    def test_round_trip_preserves_kind(self, contract):
        for payload in (
            {"answer_type": "single_choice", "answer_value": "A"},
            {"answer_type": "multi_choice", "answer_value": ["A", "B"]},
            {"answer_type": "fill_blank", "answer_value": ["x", "y"]},
            {"answer_type": "numeric", "answer_value": "1", "unit": "s"},
            {"answer_type": "expression", "answer_value": "x^2"},
            {"answer_type": "chemical", "answer_value": "H2O"},
            {"answer_type": "multi_step", "answer_value": ["s1"]},
        ):
            ans = contract.typed_answer_adapter.validate_python(payload)
            dumped = ans.model_dump(mode="json")
            again = contract.typed_answer_adapter.validate_python(dumped)
            assert again.model_dump(mode="json") == dumped

    def test_composite_sub_round_trip(self, contract):
        payload = {
            "answer_type": "composite_sub",
            "sub_label": "(3)",
            "answer_value": {"answer_type": "fill_blank", "answer_value": ["NaCl"]},
        }
        ans = contract.typed_answer_adapter.validate_python(payload)
        dumped = ans.model_dump(mode="json")
        again = contract.typed_answer_adapter.validate_python(dumped)
        assert again.model_dump(mode="json") == dumped
