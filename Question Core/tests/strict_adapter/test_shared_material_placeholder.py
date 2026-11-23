"""Shared-material placeholder mechanism (Owner DELIVERY-04 closure).

Covers the generic rule: text that belongs to a shared material must be rendered
once by the material; a sub-question whose whole body is the material keeps a
structural empty placeholder instead of duplicating it.
"""
from strict_adapter.content_audit import audit_unit
from strict_adapter.mapper import _dedupe_identical_blocks
from question_core.contracts.v1.content import Material, QuestionBody, TextBlock


def _body(local_id, texts, parent=None):
    return QuestionBody(
        local_id=local_id,
        question_type="short_answer",
        stem_blocks=tuple(
            TextBlock(text=t, line_start=i + 1, line_end=i + 1) for i, t in enumerate(texts)
        ),
        parent_question_ref=parent,
    )


def _material(mid, texts):
    return Material(
        material_id=mid,
        blocks=tuple(
            TextBlock(text=t, line_start=i + 1, line_end=i + 1) for i, t in enumerate(texts)
        ),
    )


def test_identical_stem_blocks_are_deduplicated_but_structure_kept():
    text = "这是一段在多个小问里重复出现的共享材料正文内容，长度足够触发去重规则"
    bodies = [_body("u1", [text]), _body("S1", [text], parent="u1")]
    log = {}
    nb, _ = _dedupe_identical_blocks(bodies, [], log)
    assert len(nb) == 2
    # 全部被去重时保留原块，避免制造空题面（空题面由结构化占位单独处理）
    assert [len(b.stem_blocks) for b in nb] == [1, 1]
    assert log.get("identical_source_blocks_deduped")


def test_distinct_text_is_not_touched():
    bodies = [_body("u1", ["第一段"]), _body("S1", ["第二段不同内容"], parent="u1")]
    nb, _ = _dedupe_identical_blocks(bodies, [], {})
    assert [b.stem_blocks[0].text for b in nb] == ["第一段", "第二段不同内容"]


def test_dedupe_never_deletes_the_only_copy():
    shared = "共享材料段落内容，足够长以便触发去重判定，出现在材料和小问题面里"
    bodies = [_body("S1", [shared], parent="u1")]
    mats = [_material("M01", [shared])]
    nb, nm = _dedupe_identical_blocks(bodies, mats, {})
    total = sum(1 for b in nb for blk in b.stem_blocks if blk.text == shared)
    total += sum(1 for m in nm for blk in m.blocks if blk.text == shared)
    # 两个容器各保留一次（去重只删除"重复项"，不删除唯一载体；真正的单次渲染由
    # map_unit 的 shared_material_sub_placeholders 负责）
    assert total == 2


def test_structural_empty_sub_body_is_exempt_but_real_missing_is_not():
    base = {
        "unit_id": "U6",
        "source_lines": ["材料一行", "材料二行"],
        "source_line_count": 2,
        "manifest_option_lines": [],
        "options": [],
        "options_shape": "stem_text",
        "material_blocks": [{"text": "材料一行", "line_start": 1, "line_end": 1}],
        "explanation_blocks": [],
        "is_composite_parent_placeholder": False,
    }
    ok = dict(
        base,
        stem_blocks=[{"text": "", "line_start": 2, "line_end": 2}],
        structural_empty_lines={2},
    )
    assert audit_unit(ok)["status"] == "ok"
    bad = dict(ok, structural_empty_lines=set())
    assert audit_unit(bad)["status"] != "ok"
