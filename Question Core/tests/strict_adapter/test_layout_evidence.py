# -*- coding: utf-8 -*-
"""Layer 2 布局证据消费层单元测试（不依赖真实 PDF 的确定性规则）。

覆盖：
- Manifest image_layout 校验（缺失/畸形 fail-open；重复身份不用于裁决）；
- placement 索引、bbox 唯一回退、风险合并、分组证据；
- Mapper ``_ordered_stream`` 的 inline 邻接规则（block_before/after 不重排）；
- ``decide_attribution`` 三态裁决（tie / margin / no_evidence）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import ImageBlock, TextBlock  # noqa: E402
from strict_adapter import figure_attribution as fa  # noqa: E402
from strict_adapter import layout_evidence as le  # noqa: E402
from strict_adapter.mapper import _ordered_stream  # noqa: E402
from tests.strict_adapter import layer2_fixture as fx  # noqa: E402


def _placement(
    *,
    ref="imgs/img_in_image_box_10_10_20_20.jpg",
    page=1,
    bbox=(10, 10, 20, 20),
    md_line=3,
    relation="inline",
    text_line=1,
    risks=(),
    block_id=2,
):
    return {
        "page": page,
        "block_id": block_id,
        "block_order": None,
        "bbox": list(bbox),
        "md_line": md_line,
        "ref": ref,
        "relation": relation,
        "text_block_id": 1,
        "text_line": text_line,
        "echo": False,
        "risks": list(risks),
    }


def _manifest(placements, risks=(), groups=()):
    return {
        "annotation_meta": {
            "image_layout": {
                "digest": "d" * 64,
                "summary": {},
                "placements": list(placements),
                "risks": list(risks),
                "multi_image_groups": list(groups),
            }
        }
    }


# ---------------------------------------------------------------------------
# 1. 归一化 / fail-open
# ---------------------------------------------------------------------------


def test_missing_layout_is_fail_open():
    assert le.normalize_layout({}) is None
    assert le.normalize_layout({"annotation_meta": {}}) is None
    assert le.normalize_layout({"annotation_meta": {"image_layout": {"placements": None}}}) is None


def test_placement_without_page_bbox_or_relation_is_dropped():
    mad = _manifest(
        [
            _placement(page=None),
            _placement(relation="diagonal"),
        ]
    )
    layout = le.normalize_layout(mad)
    assert layout is not None
    assert layout.placements == ()
    assert any("missing_page_bbox_or_relation" in issue for issue in layout.issues)


def test_placement_without_md_anchor_keeps_spatial_evidence():
    mad = _manifest([{"page": 1, "bbox": [1, 2, 3, 4], "relation": "inline"}])
    layout = le.normalize_layout(mad)
    assert layout is not None
    assert len(layout.placements) == 1
    assert any("placement_without_md_anchor" in issue for issue in layout.issues)


def test_malformed_group_is_recorded_not_fatal():
    mad = _manifest(
        [_placement()],
        groups=[{"page": 1, "lines": [3], "y_band": "bad"}],
    )
    layout = le.normalize_layout(mad)
    assert layout is not None
    assert any("group_y_band_malformed" in issue for issue in layout.issues)
    assert le.group_of_stem(layout, "img_in_image_box_10_10_20_20") == 0


def test_group_indices_stay_aligned_when_malformed_groups_are_skipped():
    """复核 F1：畸形容器被跳过后，group 索引必须仍能安全索引 groups。"""
    mad = _manifest(
        [_placement(md_line=3)],
        groups=[
            {"page": 1, "lines": []},  # 被跳过：无行
            {"page": 1, "lines": [3], "y_band": [0, 10]},
        ],
    )
    layout = le.normalize_layout(mad)
    assert layout is not None
    assert len(layout.groups) == 1
    assert layout.groups[0]["source_index"] == 1
    assert layout.groups[0]["group_index"] == 0
    index = le.group_of_stem(layout, "img_in_image_box_10_10_20_20")
    assert index == 0
    assert layout.groups[index]["lines"] == (3,)
    # 直接调用 Mapper 的分组日志构造，确认不再 IndexError
    from strict_adapter.mapper import _layout_group_entries

    entries = _layout_group_entries(layout, list(layout.placements))
    assert entries and entries[0]["group_index"] == 0


# ---------------------------------------------------------------------------
# 2. 真实封存布局证据（Q14 / Q16 / 分组）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(bool(fx.REQUIRE_SEALED), reason=fx.REQUIRE_SEALED)
def test_real_layout_fixture_indexes_q14_and_q16():
    manifest = fx.load_manifest(with_layout=True)
    layout = le.normalize_layout(manifest)
    assert layout is not None
    assert layout.digest == fx.LAYOUT_DIGEST
    assert len(layout.placements) == 59
    assert len(layout.risks) == 16
    assert len(layout.groups) == 9

    q14 = le.placement_for_stem(layout, "img_in_image_box_703_1144_929_1250")
    assert q14 is not None
    assert q14["page"] == 4
    assert q14["md_line"] == 231
    assert q14["relation"] == "inline"
    assert tuple(q14["bbox"]) == (703, 1144, 929, 1250)

    q16 = le.placement_for_stem(layout, "img_in_image_box_240_1212_296_1283")
    assert q16 is not None
    assert q16["text_line"] == 264
    assert "inline_image_after_text_in_md" in le.risks_for_stem(
        layout, "img_in_image_box_240_1212_296_1283"
    )


@pytest.mark.skipif(bool(fx.REQUIRE_SEALED), reason=fx.REQUIRE_SEALED)
def test_real_layout_duplicate_stems_are_not_usable_for_identity():
    manifest = fx.load_manifest(with_layout=True)
    layout = le.normalize_layout(manifest)
    assert layout is not None
    # 页脚二维码变体：同名 stem 多页出现（bbox 相同）→ 不得用于 page/bbox 补全
    dup = "img_in_image_box_20_1548_147_1666"
    assert dup not in layout.by_stem
    assert le.placement_for_stem(layout, dup) is None
    assert any(issue.startswith("duplicate_placement_stem") for issue in layout.issues)


@pytest.mark.skipif(bool(fx.REQUIRE_SEALED), reason=fx.REQUIRE_SEALED)
def test_real_layout_q5_group_is_evidence_only():
    manifest = fx.load_manifest(with_layout=True)
    layout = le.normalize_layout(manifest)
    assert layout is not None
    members = [
        stem
        for stem, index in layout.group_of_stem.items()
        if index == 0
    ]
    assert len(members) == 6, members  # Q5 六仪器图同带
    # 分组只是证据：group 记录不产生任何表格/选项组语义
    assert tuple(layout.groups[0]["lines"]) == (55, 61, 67, 70, 79, 85)


# ---------------------------------------------------------------------------
# 3. 身份 / bbox 回退
# ---------------------------------------------------------------------------


def test_bbox_fallback_for_placement_without_md_ref():
    mad = _manifest([_placement(ref=None, md_line=None, bbox=(10, 10, 20, 20))])
    layout = le.normalize_layout(mad)
    assert layout is not None
    resolved = le.placement_for_stem(layout, "img_in_image_box_10_10_20_20")
    assert resolved is not None and resolved["page"] == 1


def test_ambiguous_bbox_fallback_is_refused():
    mad = _manifest(
        [
            _placement(page=1, bbox=(10, 10, 20, 20)),
            _placement(page=2, bbox=(10, 10, 20, 20)),
        ]
    )
    layout = le.normalize_layout(mad)
    assert layout is not None
    assert le.placement_for_stem(layout, "img_in_image_box_10_10_20_20") is None


# ---------------------------------------------------------------------------
# 4. 风险 / 单元过滤
# ---------------------------------------------------------------------------


def test_risks_for_stem_merges_placement_and_block_risks():
    mad = _manifest(
        [_placement(risks=("inline_image_after_text_in_md",))],
        risks=[
            {
                "kind": "math_echo_adjacent_image",
                "page": 1,
                "block_id": 2,
                "md_line": 3,
            }
        ],
    )
    layout = le.normalize_layout(mad)
    assert layout is not None
    risks = le.risks_for_stem(layout, "img_in_image_box_10_10_20_20")
    assert set(risks) == {"inline_image_after_text_in_md", "math_echo_adjacent_image"}


def test_placements_for_unit_uses_declared_ranges():
    mad = _manifest(
        [
            _placement(md_line=3),
            _placement(ref="imgs/img_in_image_box_30_30_40_40.jpg", md_line=9, bbox=(30, 30, 40, 40)),
        ]
    )
    layout = le.normalize_layout(mad)
    unit = {"stem_lines": [1, 4]}
    placed = le.placements_for_unit(layout, unit)
    assert [p["md_line"] for p in placed] == [3]


# ---------------------------------------------------------------------------
# 5. 顺序规则
# ---------------------------------------------------------------------------


def _ctx(manifest):
    return SimpleNamespace(manifest=manifest, lines=["a", "b", "c", "d"] * 5)


def test_inline_image_is_moved_after_its_text_block():
    manifest = _manifest([_placement(text_line=2, relation="inline")])
    ctx = _ctx(manifest)
    log: dict = {}
    text = TextBlock(text="hello", line_start=2, line_end=3)
    image = ImageBlock(asset_id="img_in_image_box_10_10_20_20")
    ordered = _ordered_stream([image, text], ctx, log, "u1/stem")
    assert [b.kind for b in ordered] == ["text", "image"]
    assert log["layout_order_moves"][0]["asset_id"] == "img_in_image_box_10_10_20_20"


def test_block_before_relation_does_not_reorder():
    manifest = _manifest([_placement(text_line=2, relation="block_before")])
    ctx = _ctx(manifest)
    log: dict = {}
    text = TextBlock(text="hello", line_start=2, line_end=3)
    image = ImageBlock(asset_id="img_in_image_box_10_10_20_20")
    ordered = _ordered_stream([text, image], ctx, log, "u1/stem")
    assert [b.kind for b in ordered] == ["text", "image"]
    assert "layout_order_moves" not in log


def test_inline_without_anchor_keeps_order():
    manifest = _manifest([_placement(text_line=99, relation="inline")])
    ctx = _ctx(manifest)
    log: dict = {}
    image = ImageBlock(asset_id="img_in_image_box_10_10_20_20")
    text = TextBlock(text="hello", line_start=2, line_end=3)
    ordered = _ordered_stream([image, text], ctx, log, "u1/stem")
    assert [b.kind for b in ordered] == ["image", "text"]
    assert "layout_order_moves" not in log


def test_no_layout_is_noop():
    ctx = _ctx({})
    blocks = [TextBlock(text="a", line_start=1, line_end=2)]
    assert _ordered_stream(blocks, ctx, {}, "u/stem") == tuple(blocks)


# ---------------------------------------------------------------------------
# 6. 归属三态
# ---------------------------------------------------------------------------


def test_decide_attribution_cross_unit():
    out = fa.decide_attribution({"U13": 3, "U19": 1}, "U14")
    assert out["status"] == "cross_unit" and out["owner"] == "U13"


def test_decide_attribution_same_unit():
    out = fa.decide_attribution({"U14": 7}, "U14")
    assert out["status"] == "same_unit" and out["owner"] == "U14"


def test_decide_attribution_tie_is_ambiguous():
    out = fa.decide_attribution({"U13": 3, "U14": 3}, "U14")
    assert out["status"] == "ambiguous" and out["owner"] is None
    assert out["reason"] == "tie"


def test_decide_attribution_margin_is_ambiguous():
    out = fa.decide_attribution({"U13": 4, "U14": 3}, "U14")
    assert out["status"] == "ambiguous" and out["reason"] == "margin"


def test_decide_attribution_no_candidate_is_no_evidence():
    out = fa.decide_attribution({"U13": 1}, "U14")
    assert out["status"] == "no_evidence" and out["owner"] is None


def test_decide_attribution_two_votes_cannot_flip_ownership():
    """复核 F4：单行 2 票不得推翻既有 Unit 边界（阈值缺失会误归属）。"""
    out = fa.decide_attribution({"U13": 2}, "U14")
    assert out["status"] == "no_evidence" and out["owner"] is None
