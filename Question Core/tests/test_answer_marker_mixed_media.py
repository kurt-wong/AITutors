"""Regression tests for deterministic declared-answer parsing (2026-11-20).

Covers:
- A1: sub-question markers after Chinese/ASCII separators (;；,，。、)
- A2: circled marker with a trailing dot before a digit (①.4 → 4)
- A3: mixed image/text slots in a composite answer (U10)

No contract or Manifest change is involved; these are parser/matcher tests.
"""

from __future__ import annotations

from question_core.contracts.v1 import (
    AnswerAssetRef,
    AssetSlot,
    CompositeAnswer,
    CompositeSubAnswer,
    FillBlankAnswer,
    SlotBinding,
)
from question_core.contracts.v1 import candidate as C


def _asset_slot(asset_id: str):
    return AssetSlot(assets=(AnswerAssetRef(asset_id=asset_id),))


class TestMarkerBoundaries:
    def test_parenthesised_markers_after_separators(self):
        text = C._norm("（1）$ 0.04\\sqrt{2} $N；（2）0.016J")
        marks = C._find_markers(text)
        assert [m[2] for m in marks] == ["1", "2"]

    def test_three_markers_with_mixed_separators(self):
        text = C._norm("（1）$ a $；（2）$ b $,（3）c")
        assert [m[2] for m in C._find_markers(text)] == ["1", "2", "3"]

    def test_decimal_not_a_marker(self):
        assert C._find_markers(C._norm("1.5")) == []


class TestCircledMarkerDot:
    def test_dot_before_digit_is_marker_suffix(self):
        assert C._parse_blank_items("①.4 ②.加强 ③.向下", 3) == [
            "4",
            "加强",
            "向下",
        ]

    def test_dot_before_text_is_marker_suffix(self):
        assert C._parse_blank_items("①.加强 ②.4", 2) == ["加强", "4"]

    def test_plain_number_decimal_preserved_as_single_blank(self):
        assert C._parse_blank_items("1.5", 1) == ["1.5"]


class TestWhitespaceNormalisation:
    def test_math_interval_space_after_comma(self):
        answer = FillBlankAnswer(
            answer_value=("\\left(\\frac{1}{e}, 1\\right)",)
        )
        declared = C._norm("\\left(\\frac{1}{e},1\\right)")
        assert C._answer_matches_declared(answer, declared) is True

    def test_substantive_difference_still_fails(self):
        answer = FillBlankAnswer(
            answer_value=("\\left(\\frac{1}{e}, 1\\right)",)
        )
        declared = C._norm("\\left(\\frac{2}{e},1\\right)")
        assert C._answer_matches_declared(answer, declared) is False


class TestMixedMediaComposite:
    def _answer(self, *, bind_image: bool = True):
        image_fill = FillBlankAnswer(
            answer_value=(_asset_slot("img_in_image_box_182_646_504_922"),),
            slot_bindings=(
                (SlotBinding(slot_index=0, slot_id="(1)#1", sub_label="（1）"),)
                if bind_image
                else ()
            ),
        )
        sub1 = CompositeSubAnswer(
            sub_label="（1）", answer_value=image_fill
        )
        sub2 = CompositeSubAnswer(
            sub_label="（2）",
            answer_value=FillBlankAnswer(
                answer_value=("$ 10\\Omega $", "$ 75\\Omega $"),
                slot_bindings=(
                    SlotBinding(slot_index=0, slot_id="(2)#1"),
                    SlotBinding(slot_index=1, slot_id="(2)#2"),
                ),
            ),
        )
        sub3 = CompositeSubAnswer(
            sub_label="（3）",
            answer_value=FillBlankAnswer(
                answer_value=("2.30", "4.20", "548"),
                slot_bindings=(
                    SlotBinding(slot_index=0, slot_id="(3)#1"),
                    SlotBinding(slot_index=1, slot_id="(3)#2"),
                    SlotBinding(slot_index=2, slot_id="(3)#3"),
                ),
            ),
        )
        return CompositeAnswer(answer_value=(sub1, sub2, sub3))

    def test_declared_text_covers_text_slots_and_image_has_binding(self):
        declared = (
            "②. $ 10\\Omega $ ③. $ 75\\Omega $ "
            "④. 2.30 ⑤. 4.20 ⑥. 548"
        )
        ans = self._answer(bind_image=True)
        assert C._answer_matches_declared(ans, C._norm(declared)) is True

    def test_image_without_binding_is_not_complete(self):
        declared = (
            "②. $ 10\\Omega $ ③. $ 75\\Omega $ "
            "④. 2.30 ⑤. 4.20 ⑥. 548"
        )
        ans = self._answer(bind_image=False)
        assert C._answer_matches_declared(ans, C._norm(declared)) is False

    def test_text_value_mismatch_is_not_complete(self):
        declared = (
            "②. $ 10\\Omega $ ③. $ 75\\Omega $ "
            "④. 2.30 ⑤. 4.20 ⑥. 999"
        )
        ans = self._answer(bind_image=True)
        assert C._answer_matches_declared(ans, C._norm(declared)) is False
