"""G4-R1 回归：表格内容完整性（B1/B3）与 sub_ref 答案归属（B2）。

背景：DSH G4 独立复核 FAIL 的三条阻断——
  B1 表格选项内容静默丢失（S09 U5 / S10 U8 / S12 U5）；
  B2 答案按印刷标签分组导致跨层错绑（S10 U15/U16/U18/U19、S12 U19）；
  B3 页脚串污染选项正文（S12 U5）。
本文件锁定修复后的确定性行为。
"""

from __future__ import annotations

from strict_adapter.extract import OptionSpec, extract_options, parse_html_table
from strict_adapter.mapper import (
    MappingContext,
    _build_answers,
    _norm_label_key,
    _table_content_missing,
)


def _opts(*labels):
    return [OptionSpec(label=lb, start=1, end=1) for lb in labels]


class TestB1LabelColumnTables:
    def test_label_column_rows_via_region(self):
        """S09 U5/S10 U8 形态：options[] 指向回声行，options_lines 覆盖表格。"""
        lines = [
            "5. 题干",
            "<table>"
            "<tr><td>选项</td><td>目的</td><td>小妙招</td></tr>"
            "<tr><td>A</td><td>锁住水分</td><td>涂油</td></tr>"
            "<tr><td>B</td><td>保鲜</td><td>蒸煮</td></tr>"
            "<tr><td>C</td><td>提味</td><td>料酒</td></tr>"
            "<tr><td>D</td><td>去污</td><td>苏打</td></tr>"
            "</table>",
            "",
            "A. A B. B C. C D. D",
        ]
        opts = [OptionSpec(label=l, start=4, end=4) for l in "ABCD"]
        out, tables = extract_options(lines, opts, region=(2, 4))
        assert len(tables) == 1
        assert [o["label"] for o in out] == ["A", "B", "C", "D"]
        texts = ["|".join(b["text"] for b in o["blocks"]) for o in out]
        assert texts[0] == "A|锁住水分|涂油"
        assert texts[3] == "D|去污|苏打"

    def test_expansion_multi_table_s12u5(self):
        """S12 U5 形态：声明仅 A；表格跨页拆两段（A-C 行 + D 行）+ 页脚串。"""
        lines = [
            "<table><tr><td>选项</td><td>实验名称</td></tr>"
            "<tr><td>A</td><td>检测还原糖</td></tr>"
            "<tr><td>B</td><td>观察质壁分离</td></tr>"
            "<tr><td>C</td><td>探究酶活性</td></tr></table>",
            "",
            '<div><img src="imgs/x.jpg"></div>',
            "",
            "第1页/共9页",
            "---",
            "<table><tr><td>D</td><td>模拟 pH 稳定</td></tr></table>",
        ]
        opts = [OptionSpec(label="A", start=5, end=5)]  # 声明指向页脚行（错误行）
        out, tables = extract_options(lines, opts, region=(1, 7))
        assert len(tables) == 2
        assert [o["label"] for o in out] == ["A", "B", "C", "D"]
        texts = ["|".join(b["text"] for b in o["blocks"]) for o in out]
        assert texts[0] == "A|检测还原糖"
        assert texts[3] == "D|模拟 pH 稳定"
        # 页脚不得进入任何选项
        assert all("第1页" not in str(o["blocks"]) for o in out)

    def test_footer_filter(self):
        lines = ["A. 选项甲 B. 选项乙"]
        opts = _opts("A", "B")
        out, _ = extract_options(lines, opts)
        assert [o["blocks"][0]["text"] for o in out] == ["选项甲", "选项乙"]

    def test_footer_only_option_fail_closed(self):
        lines = ["第2页/共23页"]
        opts = _opts("A", "B", "C", "D")
        import pytest

        with pytest.raises(ValueError):
            extract_options(lines, opts)


class TestB2SubRefBinding:
    def _unit(self, answers):
        return {
            "unit_id": "U19",
            "unit_type": "composite_question",
            "original_question_type": "short_answer",
            "answer_completeness": "full",
            "answer_evidence": {"type": "answer_lines", "value": "…"},
            "answers": answers,
        }

    def test_duplicate_printed_labels_bind_by_sub_ref(self):
        """S10 U19 形态：三个 ① 分属 S1_1/S2_1/S3_1，不得合并错绑。"""
        answers = [
            {"sub_ref": "S1_1", "sub_label": "①", "slot_id": "(1)①#1",
             "value_text": None, "status": "missing"},
            {"sub_ref": "S1_2", "sub_label": "②", "slot_id": "(1)②#1",
             "value_text": "增强", "status": "resolved"},
            {"sub_ref": "S2_1", "sub_label": "①", "slot_id": "(2)①#1",
             "value_text": None, "status": "missing"},
            {"sub_ref": "S3_1", "sub_label": "①", "slot_id": "(3)①#1",
             "value_text": None, "status": "missing"},
            {"sub_ref": "S3_2", "sub_label": "②", "slot_id": "(3)②#1",
             "value_text": "5000a%", "status": "resolved"},
        ]
        sub_id_map = {
            "S1_1": "S1_1", "S1_2": "S1_2", "S2_1": "S2_1",
            "S3_1": "S3_1", "S3_2": "S3_2",
            _norm_label_key("①"): "S3_1",  # 标签键故意指向最后出现者（旧 bug 现场）
            _norm_label_key("②"): "S3_2",
        }
        log: dict = {}
        out = _build_answers(self._unit(answers), "attributed", log, sub_id_map=sub_id_map)
        comp = out[0]
        subs = list(comp.answer_value)
        # 5 个答案节点按 sub_ref 分立（三个 ① 共存）
        assert len(subs) == 5
        by_body = {s.sub_body_local_id: s for s in subs}
        assert set(by_body) == {"S1_1", "S1_2", "S2_1", "S3_1", "S3_2"}
        # 印刷标签保留原文
        assert by_body["S3_1"].sub_label == "①"
        assert by_body["S2_1"].sub_label == "①"
        # 错绑现场值 5000a% 归属 S3_2
        s32 = by_body["S3_2"]
        flat = s32.answer_value
        texts = [st.value_text for st in (getattr(flat, "statements", ()))]
        assert "5000a%" in texts or getattr(flat, "answer_value", None) in ("5000a%", ["5000a%"])

    def test_same_sub_ref_slots_stay_grouped(self):
        """同 sub_ref 多槽仍归同一节点（S12 U19 的 S3a 两槽）。"""
        answers = [
            {"sub_ref": "S3a", "sub_label": "①", "slot_id": "(3)①#1",
             "value_text": "aabb", "status": "resolved"},
            {"sub_ref": "S3a", "sub_label": "①", "slot_id": "(3)①#2",
             "value_text": "两对等位基因", "status": "resolved"},
        ]
        sub_id_map = {"S3a": "S3a"}
        out = _build_answers(self._unit(answers), "attributed", {}, sub_id_map=sub_id_map)
        subs = list(out[0].answer_value)
        assert len(subs) == 1
        assert subs[0].sub_body_local_id == "S3a"


class TestB2ContractIdentityUniqueness:
    def test_duplicate_labels_allowed_per_body(self):
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        def sub(label, body):
            return CompositeSubAnswer(
                sub_label=label, sub_body_local_id=body,
                answer_value=SingleChoiceAnswer(
                    answer_value="A", evidence_kind="answer_lines", completeness="full"
                ),
                completeness="full",
            )

        comp = CompositeAnswer(
            answer_value=[sub("①", "S2_1"), sub("①", "S3_1")],
            evidence_kind="answer_lines", completeness="full",
        )
        assert len(comp.answer_value) == 2

    def test_duplicate_labels_same_body_rejected(self):
        import pytest
        from pydantic import ValidationError
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        def sub(label, body):
            return CompositeSubAnswer(
                sub_label=label, sub_body_local_id=body,
                answer_value=SingleChoiceAnswer(
                    answer_value="A", evidence_kind="answer_lines", completeness="full"
                ),
                completeness="full",
            )

        with pytest.raises(ValidationError):
            CompositeAnswer(
                answer_value=[sub("①", "S3_1"), sub("①", "S3_1")],
                evidence_kind="answer_lines", completeness="full",
            )


class TestR103TableCoverageGate:
    def test_missing_cells_reported(self):
        lines = [
            "<table><tr><td>A</td><td>内容甲</td></tr>"
            "<tr><td>B</td><td>内容乙</td></tr></table>",
        ]
        ctx = MappingContext(
            lines=lines, manifest={"units": []}, manifest_path="m", manifest_name="m",
            source_md_path="s", source_md_name="s", source_pdf_name="p",
            annotated_md_name="a", manifest_sha="0" * 64, source_md_sha="0" * 64,
            source_pdf_sha="0" * 64, annotated_md_sha="0" * 64,
            manifest_bytes=1, source_md_bytes=1, source_pdf_bytes=1, annotated_md_bytes=1,
            image_by_line={}, paper_id="p", subject="x", run_id="r",
        )
        unit = {"unit_id": "U1", "stem_lines": [1, 1], "options": []}

        class B:
            kind = "text"
            text = "A 内容甲 B 内容乙"

        class Body:
            stem_blocks = [B()]
            options = []

        missing = _table_content_missing(unit, ctx, [Body()], [], {})
        assert missing == []

        class B2:
            kind = "text"
            text = "A 内容甲"

        class Body2:
            stem_blocks = [B2()]
            options = []

        missing2 = _table_content_missing(unit, ctx, [Body2()], [], {})
        assert missing2 and missing2[0]["cell"].startswith("B")

    def test_no_table_units_unaffected(self):
        lines = ["1. 纯文本题干"]
        ctx = MappingContext(
            lines=lines, manifest={"units": []}, manifest_path="m", manifest_name="m",
            source_md_path="s", source_md_name="s", source_pdf_name="p",
            annotated_md_name="a", manifest_sha="0" * 64, source_md_sha="0" * 64,
            source_pdf_sha="0" * 64, annotated_md_sha="0" * 64,
            manifest_bytes=1, source_md_bytes=1, source_pdf_bytes=1, annotated_md_bytes=1,
            image_by_line={}, paper_id="p", subject="x", run_id="r",
        )
        unit = {"unit_id": "U1", "stem_lines": [1, 1], "options": []}

        class B:
            kind = "text"
            text = "1. 纯文本题干"

        class Body:
            stem_blocks = [B()]
            options = []

        assert _table_content_missing(unit, ctx, [Body()], [], {}) == []
