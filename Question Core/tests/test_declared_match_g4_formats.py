"""G4 阻断修复回归（G4-F1/F3）：declared↔TypedAnswer 匹配器格式覆盖。

背景：G4 dry-run 10 单元因 F2-condition-5 匹配器格式盲区 map_failed
（LaTeX 单空 / 未分段多空 / 无点括号复合 / 圈号槽位标记）。
本文件锁定修复后的确定性匹配语义（仍逐字符全等，无语义猜测）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

_HASH_A = "a" * 64


def _content():
    from question_core.contracts.v1 import QuestionContent, QuestionBody, TextBlock, QuestionType

    return QuestionContent(
        bodies=(
            QuestionBody(
                local_id="q1",
                question_type=QuestionType.SHORT_ANSWER,
                stem_blocks=(TextBlock(text="t"),),
            ),
        )
    )


def _mk(declared_value, answers, question_type="short_answer"):
    from question_core.contracts.v1 import (
        CandidateCore,
        IngestionIdentity,
        InputHashes,
        PreprocessingCandidate,
        PreprocessingSource,
        PreprocessingUnitRef,
        SourceDocumentRef,
        StrictAnswerDeclaration,
    )

    return PreprocessingCandidate(
        core=CandidateCore(
            question_type=question_type,
            content=_content(),
            answers=tuple(answers),
            completeness="complete",
            ingestion=IngestionIdentity(
                candidate_idempotency_key="k" * 20,
                adapter_version="a/1",
                input_hashes=InputHashes(manifest_hash=_HASH_A),
            ),
        ),
        source=PreprocessingSource(
            source_document_id="doc/1",
            manifest_ref=SourceDocumentRef(doc_role="manifest", content_hash=_HASH_A),
            unit=PreprocessingUnitRef(unit_id="Q1", unit_type="standalone_question"),
            answer_declaration=StrictAnswerDeclaration(
                attribution="declared",
                evidence_kind="answer_lines",
                declared_value=declared_value,
                completeness="complete",
            ),
        ),
    )


def _fill(blanks):
    from question_core.contracts.v1 import FillBlankAnswer

    return FillBlankAnswer(
        answer_value=list(blanks), evidence_kind="answer_lines", completeness="full"
    )


class TestG4FillBlankFormats:
    def test_latex_single_blank_exact(self):
        """S03 U12/U14 形态：LaTeX 单空，整串全等。"""
        for val in (r"\frac{\sqrt{66}}{6}", r"\sqrt[3]{\frac{3}{2}}", "[700,4900]"):
            cand = _mk(val, [_fill([val])], "fill_blank")
            assert cand.core.completeness.value == "complete"

    def test_unsegmented_two_blank_join_equality(self):
        """S04 U12/U14 形态：未分段 declared，按空格连接各空值后全等。"""
        blanks = ["-2", "9（答案不唯一，满足 $ 8 \\leq a_1 \\leq 10 $即可）"]
        declared = "-2 9（答案不唯一，满足 $ 8 \\leq a_1 \\leq 10 $即可）"
        cand = _mk(declared, [_fill(blanks)], "fill_blank")
        assert cand.core.completeness.value == "complete"

    def test_latex_two_blank_join_whitespace_collapse(self):
        blanks = ["$ \\sqrt{3} $", "$ \\frac{2\\sqrt{3}}{3} $"]
        declared = "$ \\sqrt{3} $  $ \\frac{2\\sqrt{3}}{3} $"  # 双空格
        cand = _mk(declared, [_fill(blanks)], "fill_blank")
        assert cand.core.completeness.value == "complete"

    def test_circled_marker_items(self):
        blanks = ["亦余心之所善兮", "离骚", "水澹澹兮生烟", "覆压三百余里", "隔离天日"]
        declared = "①. 亦余心之所善兮 ②. 离骚 ③. 水澹澹兮生烟 ④. 覆压三百余里 ⑤. 隔离天日"
        cand = _mk(declared, [_fill(blanks)], "fill_blank")
        assert cand.core.completeness.value == "complete"

    def test_decimal_not_marker(self):
        """小数不作印刷标记：1.5 应作为整值而非 '1.' 切分。"""
        cand = _mk("(1)1.5 (2)2.0", [_fill(["1.5", "2.0"])], "fill_blank")
        assert cand.core.completeness.value == "complete"

    def test_wrong_value_still_rejected(self):
        with pytest.raises(ValidationError, match="fully.*represented"):
            _mk(r"\frac{\sqrt{66}}{6}", [_fill([r"\frac{\sqrt{67}}{6}"])], "fill_blank")


class TestG4CompositeFormats:
    def _composite(self, subs):
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
            FillBlankAnswer,
        )

        children = []
        for label, kind, value in subs:
            if kind == "choice":
                inner = SingleChoiceAnswer(
                    answer_value=value, evidence_kind="answer_lines", completeness="full"
                )
            else:
                inner = FillBlankAnswer(
                    answer_value=list(value), evidence_kind="answer_lines", completeness="full"
                )
            children.append(
                CompositeSubAnswer(sub_label=label, answer_value=inner, completeness="full")
            )
        return CompositeAnswer(answer_value=children, evidence_kind="answer_lines", completeness="full")

    def test_paren_labels_without_dots(self):
        """S02 U2 形态：（1）A （2）D（标记无尾点）。"""
        comp = self._composite([("（1）", "choice", "A"), ("（2）", "choice", "D")])
        cand = _mk("（1）A （2）D", [comp])
        assert cand.core.completeness.value == "complete"

    def test_multi_token_latex_values(self):
        """S08 U13/U14 形态：子答案含空格的 LaTeX。"""
        comp = self._composite(
            [
                ("（1）", "blank", ["W"]),
                ("（2）", "blank", ["$ p = \\frac{V_{0}}{V} p_{0} $"]),
            ]
        )
        cand = _mk("（1）W （2）$ p = \\frac{V_{0}}{V} p_{0} $", [comp])
        assert cand.core.completeness.value == "complete"

    def test_flat_slot_fallback_circled_markers(self):
        """S02 U1 形态：declared ①-⑤ 是槽位标记，子问键为（1）-（3）。
        键位解析不齐时按叶子有序全等兜底。"""
        comp = self._composite(
            [
                ("（1）", "blank", ["亦余心之所善兮", "离骚"]),
                ("（2）", "blank", ["水澹澹兮生烟"]),
                ("（3）", "blank", ["覆压三百余里", "隔离天日"]),
            ]
        )
        declared = "①. 亦余心之所善兮 ②. 离骚 ③. 水澹澹兮生烟 ④. 覆压三百余里 ⑤. 隔离天日"
        cand = _mk(declared, [comp])
        assert cand.core.completeness.value == "complete"

    def test_flat_fallback_wrong_order_rejected(self):
        comp = self._composite(
            [
                ("（1）", "blank", ["离骚", "亦余心之所善兮"]),
                ("（2）", "blank", ["水澹澹兮生烟"]),
                ("（3）", "blank", ["覆压三百余里", "隔离天日"]),
            ]
        )
        declared = "①. 亦余心之所善兮 ②. 离骚 ③. 水澹澹兮生烟 ④. 覆压三百余里 ⑤. 隔离天日"
        with pytest.raises(ValidationError, match="fully.*represented"):
            _mk(declared, [comp])

    def test_missing_sub_still_rejected(self):
        comp = self._composite([("（1）", "choice", "A"), ("（2）", "choice", "D")])
        with pytest.raises(ValidationError, match="fully.*represented"):
            _mk("（1）A", [comp])
