# -*- coding: utf-8 -*-
"""G3-B B2 Mapper 消费改造测试（DSH B2 盯防主线②③）。

- 主线②：Mapper 彻底退出二次识别——split_sub_segments 不参与映射（audit-only）；
  旧 manifest 缺 sub_questions → 显式 input_contract_gap，无正则兜底。
- 主线③：答案身份——sub_ref 首选 / 完整标签（格式等价）回落；S03 U17 型
  (2)(i)/(2)(ii) 与 (2) 三级标签互不混淆，分绑正确。
另覆盖：sub_questions 树 → QuestionBody 父子；materials M:N 逐小问挂载；
uncertainty → hold_not_ready；_norm_label_key 数字前缀归一已废除。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.extract import load_source_lines  # noqa: E402
from strict_adapter.mapper import (  # noqa: E402
    MappingContext,
    _build_answers,
    _norm_label_key,
    map_unit,
)

# ---------------- 合成源文（含 U17 型 (2)/(2)(i)/(2)(ii) 三级） ----------------
LINES = [
    "# 合成卷",                            # 1
    "",                                    # 2
    "阅读下列材料，回答问题。",            # 3
    "材料内容甲乙丙。",                    # 4
    "2. 完成下列各题。",                   # 5
    "(2) 计算并证明。",                    # 6
    "(2)(i) 求值。",                       # 7
    "(2)(ii) 证明。",                      # 8
    "",                                    # 9
    "## 参考答案",                         # 10
    "【答案】(2)(i) 42",                   # 11
    "【答案】(2)(ii) 证明略",              # 12
]


def _unit():
    return {
        "unit_id": "U2",
        "unit_type": "composite_question",
        "question_numbers": [2],
        "original_question_type": "short_answer",
        "material_lines": [3, 4],
        "questions_lines": [5, 8],
        "answer_lines": [11, 12],
        "materials": [
            {"material_id": "M01", "label": "材料一", "line_start": 3, "line_end": 4},
        ],
        "sub_questions": [
            {"sub_id": "S0", "label": "(2)", "label_kind": "printed_number",
             "parent_sub_id": None, "order": 1,
             "line_start": 5, "line_end": 6,
             "materials_used": ["M01"], "answer_refs": [], "figure_refs": [],
             "answer_entry_count": 0, "uncertainty": None},
            {"sub_id": "S1", "label": "(2)(i)", "label_kind": "sub_label",
             "parent_sub_id": "S0", "order": 2,
             "line_start": 7, "line_end": 7,
             "materials_used": ["M01"], "answer_refs": ["(2)(i)#1"],
             "figure_refs": [], "answer_entry_count": 1, "uncertainty": None},
            {"sub_id": "S2", "label": "(2)(ii)", "label_kind": "sub_label",
             "parent_sub_id": "S0", "order": 3,
             "line_start": 8, "line_end": 8,
             "materials_used": [], "answer_refs": ["(2)(ii)#1"],
             "figure_refs": [], "answer_entry_count": 1, "uncertainty": None},
        ],
        "answers": [
            {"sub_ref": "S1", "sub_label": "(2)(i)", "slot_id": "(2)(i)#1",
             "value_text": "42", "form": "verbatim", "source_region": "answer_area",
             "evidence_lines": [11, 11], "status": "resolved",
             "missing_reason": None, "note": None},
            {"sub_ref": "S2", "sub_label": "(2)(ii)", "slot_id": "(2)(ii)#1",
             "value_text": "证明略", "form": "verbatim",
             "source_region": "answer_area", "evidence_lines": [12, 12],
             "status": "resolved", "missing_reason": None, "note": None},
        ],
        "answer_evidence": {"type": "answer_lines", "lines": [11, 12],
                            "value": None, "shared": False},
        "answer_completeness": "full",
    }


def _ctx(manifest, lines=None):
    lines = lines if lines is not None else list(LINES)
    return MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path="m.json",
        manifest_name="m.json",
        source_md_path="s.md",
        source_md_name="s.md",
        source_pdf_name="s.pdf",
        annotated_md_name="a.md",
        manifest_sha="1" * 64,
        source_md_sha="2" * 64,
        source_pdf_sha="3" * 64,
        annotated_md_sha="4" * 64,
        manifest_bytes=1,
        source_md_bytes=1,
        source_pdf_bytes=1,
        annotated_md_bytes=1,
        image_by_line={},
        paper_id="paper",
        subject="测试",
        run_id="g3b2-tests",
    )


class TestT1InputContractGap:
    def test_old_composite_without_sub_questions_fails_explicitly(self):
        old = _unit()
        del old["sub_questions"]
        del old["materials"]
        with pytest.raises(ValueError, match="input_contract_gap"):
            map_unit(old, _ctx({"units": [old]}))

    def test_unresolved_materials_used_fails(self):
        u = _unit()
        u["sub_questions"][0]["materials_used"] = ["MX"]
        with pytest.raises(ValueError, match="input_contract_gap"):
            map_unit(u, _ctx({"units": [u]}))

    def test_unresolved_parent_fails(self):
        u = _unit()
        u["sub_questions"][1]["parent_sub_id"] = "SX"
        with pytest.raises(ValueError, match="input_contract_gap"):
            map_unit(u, _ctx({"units": [u]}))

    def test_unresolved_sub_ref_fails(self):
        u = _unit()
        u["answers"][0]["sub_ref"] = "SX"
        with pytest.raises(ValueError, match="input_contract_gap"):
            map_unit(u, _ctx({"units": [u]}))


class TestT2TreeConsumption:
    def test_bodies_follow_manifest_tree(self):
        u = _unit()
        m = map_unit(u, _ctx({"units": [u]}))
        bodies = {b.local_id: b for b in m.candidate.core.content.bodies}
        assert set(bodies) == {"u2", "S0", "S1", "S2"}  # local_id = manifest sub_id
        assert bodies["u2"].parent_question_ref is None
        assert set(bodies["u2"].sub_question_ids) == {"S0"}
        assert bodies["S0"].parent_question_ref == "u2"
        assert set(bodies["S0"].sub_question_ids) == {"S1", "S2"}
        assert bodies["S1"].parent_question_ref == "S0"
        assert bodies["S2"].parent_question_ref == "S0"
        # 标签保留印刷形态
        assert bodies["S1"].printed_number == "(2)(i)"
        assert bodies["S2"].printed_number == "(2)(ii)"

    def test_no_regex_fallback_audit_only(self):
        u = _unit()
        m = map_unit(u, _ctx({"units": [u]}))
        audit = m.log.get("sub_segment_audit")
        assert audit and "audit-only" in audit["note"]
        # 映射结构来自声明而非正则
        assert [s["sub_id"] for s in audit["declared_segments"]] == ["S0", "S1", "S2"]

    def test_materials_used_per_sub_replaces_blanket_mount(self):
        u = _unit()
        m = map_unit(u, _ctx({"units": [u]}))
        bodies = {b.local_id: b for b in m.candidate.core.content.bodies}
        # S2 显式不依赖材料 → 不再统一挂载
        assert bodies["S1"].material_ids == ("M01",)
        assert bodies["S2"].material_ids == ()
        # parent 保留单元级材料并集
        assert bodies["u2"].material_ids == ("M01",)
        mats = m.candidate.core.content.materials
        assert [x.material_id for x in mats] == ["M01"]


class TestT3AnswerIdentityU17:
    """S03 U17 锚点：(2)(i)/(2)(ii) 分绑正确，不得同绑 (2)。"""

    def _bindings(self, m):
        ans = m.candidate.core.answers
        assert len(ans) == 1 and ans[0].answer_value  # CompositeAnswer
        subs = ans[0].answer_value
        out = {}
        for s in subs:
            out[s.sub_label] = s.sub_body_local_id
        return out

    def test_sub_ref_binding_distinct(self):
        u = _unit()
        m = map_unit(u, _ctx({"units": [u]}))
        b = self._bindings(m)
        assert b["(2)(i)"] == "S1"
        assert b["(2)(ii)"] == "S2"

    def test_full_label_fallback_distinct_without_sub_ref(self):
        u = _unit()
        for a in u["answers"]:
            a["sub_ref"] = None
        m = map_unit(u, _ctx({"units": [u]}))
        b = self._bindings(m)
        assert b["(2)(i)"] == "S1"
        assert b["(2)(ii)"] == "S2"

    def test_norm_label_key_no_numeric_collapse(self):
        assert _norm_label_key("(2)(i)") != _norm_label_key("(2)")
        assert _norm_label_key("(2)(i)") != _norm_label_key("(2)(ii)")
        assert _norm_label_key("(2)(ii)") != _norm_label_key("(2)")

    def test_norm_label_key_format_equivalence(self):
        assert _norm_label_key("（2）（ⅰ）") == _norm_label_key("(2)(i)")
        assert _norm_label_key("（１）") == _norm_label_key("(1)")

    def test_label_miss_is_explicitly_logged_not_guessed(self):
        u = _unit()
        for a in u["answers"]:
            a["sub_ref"] = None
        u["answers"][0]["sub_label"] = "(2)(iii)"  # 不存在的标签
        m = map_unit(u, _ctx({"units": [u]}))
        pending = m.log.get("unresolved_sub_bindings") or []
        assert any(p["sub_label"] == "(2)(iii)" for p in pending), pending

    def test_conflict_versions_keyed_full_label(self):
        u = _unit()
        u["answer_conflicts"] = [
            {"sub_label": "(2)(i)", "slot_id": "(2)(i)#1", "versions": [
                {"value_text": "42", "source_region": "answer_area",
                 "evidence_lines": [11, 11]},
                {"value_text": "43", "source_region": "explanation_area",
                 "evidence_lines": [12, 12]},
            ]},
            {"sub_label": "(2)(ii)", "slot_id": "(2)(ii)#1", "versions": [
                {"value_text": "x", "source_region": "answer_area",
                 "evidence_lines": [12, 12]},
            ]},
        ]
        m = map_unit(u, _ctx({"units": [u]}))
        # 冲突版本按完整标签归槽：(2)(i) 的冲突不得落到 (2)(ii)
        ans = m.candidate.core.answers[0].answer_value
        by = {s.sub_label: s for s in ans}
        texts_i = [st.value_text for st in by["(2)(i)"].answer_value.statements]
        texts_ii = [st.value_text for st in by["(2)(ii)"].answer_value.statements]
        assert "43" in texts_i and "x" not in texts_i, texts_i
        assert "x" in texts_ii and "43" not in texts_ii, texts_ii


class TestT4UncertaintyHold:
    def test_uncertainty_forces_hold_not_ready(self):
        u = _unit()
        u["uncertainty"] = [{"object": "小问边界", "reason": "印刷不清"}]
        m = map_unit(u, _ctx({"units": [u]}))
        assert m.state_plan == "hold_not_ready"
        assert m.log.get("uncertainty_hold") is True

    def test_without_uncertainty_completeness_decides(self):
        u = _unit()
        m = map_unit(u, _ctx({"units": [u]}))
        assert m.state_plan == "approve_publish"  # answers 全 full
