# -*- coding: utf-8 -*-
"""QCORE-MISSING-ANSWER-SLOT-01 定向测试：missing 答案槽位的契约表达与映射。

missing=答案槽位存在但无可确定性绑定的源文事实值；disputed=存在冲突版本。
两者语义与验证规则分离。伪造冲突版本不得让 missing 获得合法性；missing 不得
携带虚构答案值。schema_hash 硬约束：必须保持 1.1.0 基线值（validator-only）。
"""
from __future__ import annotations

import pytest

from question_core.contracts.v1 import (
    AnswerCompleteness,
    AnswerStatement,
    CompositeSubAnswer,
    FillBlankAnswer,
)
from question_core.contracts.v1.manifest import build_json_schema, compute_schema_hash

# QCORE-MISSING-ANSWER-SLOT-01 硬约束：validator-only 修复不得改变 JSON Schema
SCHEMA_HASH_FROZEN = (
    "b688da079adcb3ea82cc5a88bfab70d5f1c57c549d3840da46f4faa7f0484f83"
)


# ---------------------------------------------------------------------------
# 契约层：missing 与 disputed 的语义分离
# ---------------------------------------------------------------------------


def test_missing_blank_maps_legally():
    """missing + value=None + 无 asset → 合法映射（不需要冲突版本）。"""
    ans = FillBlankAnswer(
        answer_value=("0.975", None),
        completeness=AnswerCompleteness.PARTIAL,
        missing_reason="extraction_gap",
        attribution="partially_attributed",
    )
    assert ans.answer_value[1] is None
    assert ans.answer_conflict == "none"
    assert ans.missing_reason == "extraction_gap"


def test_missing_reason_preserved():
    ans = FillBlankAnswer(
        answer_value=(None,),
        completeness=AnswerCompleteness.ABSENT,
        missing_reason="source_not_provided",
        attribution="partially_attributed",
    )
    assert ans.missing_reason == "source_not_provided"


def test_missing_blank_full_completeness_rejected():
    # answer 级 _missing_reason_axis 或槽位级校验均须拒绝（full+missing 矛盾）
    with pytest.raises(Exception, match="completeness"):
        FillBlankAnswer(
            answer_value=(None,),
            completeness=AnswerCompleteness.FULL,
            missing_reason="extraction_gap",
            attribution="partially_attributed",
        )


def test_missing_blank_without_reason_rejected():
    with pytest.raises(Exception, match="requires missing_reason"):
        FillBlankAnswer(
            answer_value=(None,),
            completeness=AnswerCompleteness.PARTIAL,
            missing_reason=None,
            attribution="partially_attributed",
        )


def test_missing_blank_attributed_rejected():
    """防御：attributed 不得伪装 missing（漏映射≠缺失）。"""
    with pytest.raises(Exception, match="attribution != 'attributed'"):
        FillBlankAnswer(
            answer_value=(None,),
            completeness=AnswerCompleteness.PARTIAL,
            missing_reason="extraction_gap",
            attribution="attributed",
        )


def test_disputed_two_versions_ok():
    """disputed + 两冲突版本：原有行为不变。"""
    ans = FillBlankAnswer(
        answer_value=(None,),
        answer_conflict="source_conflict",
        statements=(
            AnswerStatement(statement_id="s1", value_text="甲", slot_index=0),
            AnswerStatement(statement_id="s2", value_text="乙", slot_index=0),
        ),
    )
    assert ans.answer_conflict == "source_conflict"
    assert len(ans.statements) == 2


def test_disputed_one_version_still_rejected():
    """disputed + 少于两版本：仍然拒绝（约束未放松）。"""
    with pytest.raises(Exception, match="two"):
        FillBlankAnswer(
            answer_value=(None,),
            answer_conflict="source_conflict",
            statements=(
                AnswerStatement(statement_id="s1", value_text="甲", slot_index=0),
            ),
        )


def test_bare_none_still_rejected():
    """裸 None（既非 missing 声明也非 disputed）仍然拒绝。"""
    with pytest.raises(Exception, match="None blank"):
        FillBlankAnswer(answer_value=("a", None))


def test_composite_nested_missing_ok():
    """composite 内嵌 fill_blank 的 missing 空位合法。"""
    inner = FillBlankAnswer(
        answer_value=(None,),
        completeness=AnswerCompleteness.ABSENT,
        missing_reason="extraction_gap",
        attribution="partially_attributed",
    )
    sub = CompositeSubAnswer(
        sub_label="（1）",
        answer_value=inner,
        completeness=AnswerCompleteness.PARTIAL,
        missing_reason="extraction_gap",
        attribution="partially_attributed",
    )
    assert sub.answer_value.answer_value[0] is None


def test_composite_nested_disputed_versions_required():
    """composite 声明 source_conflict 时嵌套 None 空位仍须 ≥2 冲突版本。"""
    inner_missing = FillBlankAnswer(
        answer_value=(None,),
        completeness=AnswerCompleteness.ABSENT,
        missing_reason="extraction_gap",
        attribution="partially_attributed",
    )
    # missing inner + sub 声明争议 → 版本不足必须拒绝
    with pytest.raises(Exception, match="two"):
        CompositeSubAnswer(
            sub_label="（1）",
            answer_value=inner_missing,
            answer_conflict="source_conflict",
            statements=(),
        )
    # 版本齐备（sub+inner 合计 ≥2）→ 合法
    sub = CompositeSubAnswer(
        sub_label="（1）",
        answer_value=inner_missing,
        answer_conflict="source_conflict",
        statements=(
            AnswerStatement(statement_id="s1", value_text="甲", slot_index=0),
            AnswerStatement(statement_id="s2", value_text="乙", slot_index=0),
        ),
    )
    assert sub.answer_value.answer_value[0] is None


# ---------------------------------------------------------------------------
# 映射层：missing_reason/completeness 传递 + 虚构值守卫 + 既有行为不变
# ---------------------------------------------------------------------------


def _mk_item(**kw):
    it = {
        "sub_label": kw.get("sub_label"),
        "slot_id": kw.get("slot_id", "ans#1"),
        "value_text": kw.get("value"),
        "asset_ref": None,
        "form": kw.get("form", "verbatim"),
        "source_region": "answer_area",
        "evidence_lines": kw.get("lines", [1, 1]),
        "status": kw.get("status", "resolved"),
        "missing_reason": kw.get("missing_reason"),
        "note": None,
    }
    return it


def _mk_unit(items, **kw):
    return {
        "unit_id": kw.get("unit_id", "QT"),
        "unit_type": kw.get("unit_type", "standalone_question"),
        "question_numbers": [1],
        "printed_number": "1",
        "original_question_type": "fill_in",
        "answer_completeness": kw.get("comp", "partial"),
        "answer_evidence": {"type": "answer_lines", "lines": [1, 1]},
        "answers": items,
        "answer_conflicts": kw.get("conflicts", []),
    }


def _build(unit, attribution="attributed"):
    from strict_adapter.mapper import _build_answers

    return _build_answers(unit, attribution, {})


def test_mapper_missing_passthrough():
    """missing+None+missing_reason → 合法映射并保留原因；不产伪造 statements。"""
    unit = _mk_unit([
        _mk_item(value="0.975", slot_id="ans#1"),
        _mk_item(value=None, status="missing", missing_reason="source_not_provided",
                 slot_id="ans#2"),
    ])
    outs = _build(unit)
    fb = outs[0]
    assert isinstance(fb, FillBlankAnswer)
    assert fb.answer_value[0] == "0.975"
    assert fb.answer_value[1] is None
    assert fb.missing_reason == "source_not_provided"
    assert fb.completeness == AnswerCompleteness.PARTIAL
    assert fb.attribution == "partially_attributed"
    assert fb.answer_conflict == "none"
    assert len(fb.statements) == 1        # 仅已验证条目产 statement


def test_mapper_all_missing_absent():
    unit = _mk_unit([
        _mk_item(value=None, status="missing", missing_reason="extraction_gap",
                 slot_id=f"ans#{i+1}") for i in range(2)
    ])
    outs = _build(unit)
    fb = outs[0]
    assert fb.completeness == AnswerCompleteness.ABSENT
    assert fb.missing_reason == "extraction_gap"
    assert fb.statements == ()


def test_mapper_fabricated_value_rejected():
    """missing 条目携带 value_text → 拒绝（虚构答案值不得静默接受）。"""
    unit = _mk_unit([
        _mk_item(value="编造的值", status="missing", missing_reason="extraction_gap"),
    ])
    with pytest.raises(ValueError, match="虚构"):
        _build(unit)


def test_mapper_missing_forges_no_versions():
    """missing 不通过伪造 conflict versions 获得合法性：不产版本、conflict=none。"""
    unit = _mk_unit([
        _mk_item(value=None, status="missing", missing_reason="extraction_gap",
                 slot_id="ans#1"),
    ])
    outs = _build(unit)
    fb = outs[0]
    assert fb.answer_conflict == "none"
    assert fb.statements == ()
    assert all(b.slot_id == "ans#1" for b in fb.slot_bindings)


def test_mapper_verified_unchanged():
    unit = _mk_unit([
        _mk_item(value="甲", slot_id="ans#1"),
        _mk_item(value="乙", slot_id="ans#2"),
    ])
    outs = _build(unit)
    fb = outs[0]
    assert fb.answer_value == ("甲", "乙")
    assert fb.answer_conflict == "none"
    assert fb.attribution == "attributed"
    assert fb.missing_reason is None
    assert fb.completeness == AnswerCompleteness.PARTIAL  # unit 声明的 comp


def test_mapper_unattributed_unchanged():
    unit = _mk_unit([_mk_item(value="甲")])
    outs = _build(unit, attribution="not_attributable")
    assert outs[0].attribution == "partially_attributed"


def test_mapper_composite_missing_sub():
    """composite 形态：missing 槽位经 CompositeSubAnswer 合法映射。"""
    unit = _mk_unit(
        [
            _mk_item(value="甲", sub_label="（1）", slot_id="(1)#1"),
            _mk_item(value=None, sub_label="（2）", slot_id="(2)#1",
                     status="missing", missing_reason="extraction_gap"),
        ],
        unit_type="composite_question",
    )
    outs = _build(unit)
    comp = outs[0]
    subs = {s.sub_label: s for s in comp.answer_value}
    assert subs["（2）"].answer_value.answer_value[0] is None
    assert subs["（2）"].answer_value.missing_reason == "extraction_gap"


# ---------------------------------------------------------------------------
# 硬约束：JSON Schema 不变（validator-only）
# ---------------------------------------------------------------------------


def test_schema_hash_unchanged():
    assert compute_schema_hash(build_json_schema()) == SCHEMA_HASH_FROZEN
