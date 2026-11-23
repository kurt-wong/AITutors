# -*- coding: utf-8 -*-
"""Layer 2：image_layout 下游消费 + Q14 Unit-aware 归属（真实封存数据）。

口径（Owner 2026-11-19 裁定）：
- 只做 Mapper 消费 image_layout 与 Q14 Unit 归属；不展开 Q5/Q18 专项修复；
- 布局证据不得推翻既有 Unit 边界：仅当 Manifest 携带 image_layout 且
  PDF 文本行 5-gram 投票唯一决定时才 cross_unit；
- 证据并列/不足 → 显式 ``ownership_ambiguous``（不挂进学生可见内容）；
- 非目标题目的文本、答案、结构、图片引用不得发生非预期变化。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import candidate_adapter  # noqa: E402
from strict_adapter import figure_attribution as fa  # noqa: E402
from tests.strict_adapter import layer2_fixture as fx  # noqa: E402

pytestmark = pytest.mark.skipif(bool(fx.REQUIRE_SEALED), reason=fx.REQUIRE_SEALED)

_Q14_IMAGE = "img_in_image_box_703_1144_929_1250"


@pytest.fixture(scope="module")
def mapped():
    return fx.map_chem(with_layout=True)


@pytest.fixture(scope="module")
def mapped_no_layout():
    return fx.map_chem(with_layout=False)


def _images(mapping):
    return fx.all_images(mapping.candidate.core.content)


def _image_blocks(mapping):
    return [entry[2] for entry in _images(mapping)]


def _asset(mapping, asset_id):
    for asset in mapping.candidate.core.content.assets:
        if asset.asset_id == asset_id:
            return asset
    return None


def _layout_log(mapping):
    return mapping.log.get("image_layout") or {}


def _evidence_notes(mapping):
    return [(record.target_path, record.note or "") for record in mapping.candidate.core.evidence.records]


# ---------------------------------------------------------------------------
# 1. Q14 跨 Unit 归属（核心案例）
# ---------------------------------------------------------------------------


def test_q14_703_is_removed_from_u14(mapped):
    assert _Q14_IMAGE not in _image_blocks(mapped["U14"])
    assert _asset(mapped["U14"], _Q14_IMAGE) is None


def test_q14_703_is_owned_by_u13_with_traceable_evidence(mapped):
    u13 = mapped["U13"]
    assert _Q14_IMAGE in _image_blocks(u13)
    asset = _asset(u13, _Q14_IMAGE)
    assert asset is not None
    assert asset.page == 4
    assert asset.bbox is not None
    assert (asset.bbox.x0, asset.bbox.y0, asset.bbox.x1, asset.bbox.y1) == (703, 1144, 929, 1250)

    reattributed = u13.log.get("figure_reattributed_in") or []
    entry = next(item for item in reattributed if item["asset_id"] == _Q14_IMAGE)
    assert entry["owner"] == "U13"
    assert entry["evidence"]["scores"] == {"U13": 3}
    assert entry["evidence"]["declaring_unit"] == "U14"
    assert entry["evidence"]["page"] == 4

    notes = [
        note
        for target, note in _evidence_notes(u13)
        if "cross-unit figure attribution" in note and "asset_id" not in note
    ]
    assert notes, "owner unit must carry a review-only attribution evidence record"
    assert f"owner=U13" in notes[0]
    assert "declaring=U14" in notes[0]


def test_q14_declaring_unit_records_the_exclusion(mapped):
    notes = _evidence_notes(mapped["U14"])
    excluded = [note for target, note in notes if "figure excluded from this unit" in note]
    assert excluded, "declaring unit must record why the figure left"
    assert _Q14_IMAGE in excluded[0]
    assert "owner=U13" in excluded[0]


def test_q14_other_inline_images_stay_with_q14(mapped):
    u14 = mapped["U14"]
    assert "img_in_image_box_682_1288_751_1329" in _image_blocks(u14)
    assert "img_in_image_box_105_95_745_277" in _image_blocks(u14)
    assert _asset(u14, "img_in_image_box_682_1288_751_1329").page == 4
    assert _asset(u14, "img_in_image_box_105_95_745_277").page == 5


def test_q14_footer_furniture_never_enters_question(mapped):
    for mapping in mapped.values():
        assert "img_in_image_box_1011_1533_1150_1671" not in _image_blocks(mapping)
        assert _asset(mapping, "img_in_image_box_1011_1533_1150_1671") is None


# ---------------------------------------------------------------------------
# 2. 图文顺序（Q16）与风险保留
# ---------------------------------------------------------------------------


def test_q16_inline_image_position_enters_question_structure(mapped):
    u16 = mapped["U16"]
    material = u16.candidate.core.content.materials[0]
    blocks = list(material.blocks)
    image_ids = [getattr(b, "asset_id", None) for b in blocks if b.kind == "image"]
    assert "img_in_image_box_240_1212_296_1283" in image_ids

    text_index = next(
        i
        for i, block in enumerate(blocks)
        if block.kind == "text" and block.line_start == 264
    )
    image_index = next(
        i
        for i, block in enumerate(blocks)
        if block.kind == "image"
        and block.asset_id == "img_in_image_box_240_1212_296_1283"
    )
    assert image_index == text_index + 1, (
        "Q16 主题干行内图必须紧邻其文本块之后（布局证据已消费）"
    )

    asset = _asset(u16, "img_in_image_box_240_1212_296_1283")
    assert asset.page == 5
    placement = next(
        item
        for item in _layout_log(u16)["placements"]
        if item["asset_id"] == "img_in_image_box_240_1212_296_1283"
    )
    assert placement["relation"] == "inline"
    assert placement["text_line"] == 264
    assert "inline_image_after_text_in_md" in placement["risks"]


def test_q18_math_echo_without_image_is_explicit_and_fabrication_free(mapped):
    risks = _layout_log(mapped["U18"])["risks"]
    echo = [risk for risk in risks if risk["kind"] == "math_echo_without_image"]
    assert echo, "Q18 known-I math echo risk must stay visible"
    assert any(risk.get("page") == 7 for risk in echo)
    # 不合成资产：不存在以该 bbox 命名的 asset
    for mapping in mapped.values():
        for asset in mapping.candidate.core.content.assets:
            assert "106_1224_747_1297" not in asset.asset_id


def test_md_image_without_json_block_is_not_fabricated(mapped):
    """MD 有图引用但 OCR 无 image block → 保留 MD 身份，不补造 placement。"""
    risks = [
        risk
        for mapping in mapped.values()
        for risk in _layout_log(mapping)["risks"]
        if risk["kind"] == "md_image_without_json_image_block"
    ]
    assert risks, "explicit md-only risk must be retained"
    # 这些图仍按 MD 身份存在，但没有 page/bbox（不得凭 MD 推断空间位置）
    stems = {
        Path(risk["ref"]).stem
        for risk in risks
        if isinstance(risk.get("ref"), str)
    }
    seen = set()
    for mapping in mapped.values():
        for asset in mapping.candidate.core.content.assets:
            if asset.asset_id in stems:
                seen.add(asset.asset_id)
                assert asset.page is None
                assert asset.bbox is None
    assert seen, "MD-only image refs must not be dropped"


# ---------------------------------------------------------------------------
# 3. 多图分组（只作证据）与 Q19 同机制归属
# ---------------------------------------------------------------------------


def test_multi_image_group_is_evidence_only(mapped):
    u5 = mapped["U5"]
    groups = _layout_log(u5)["groups"]
    assert groups, "Q5 六仪器图分组证据必须随 Question 保留"
    assert all(
        group["policy"] == "group_evidence_only_no_table_inference"
        for group in groups
    )
    assert any(len(group["members"]) >= 2 for group in groups)
    # 分组不产生表格：六图仍是独立 image 资产
    image_ids = [asset_id for _, _, asset_id in _images(u5)]
    assert len(image_ids) == len(set(image_ids))
    assert len([x for x in image_ids if "img_in_image_box" in x]) >= 2


def test_q19_u18s5_is_same_mechanism_not_q14_scope(mapped):
    """U18/S5 目标结构图（原 U19 材料区）：同一确定性机制，证据在案。"""
    u18_images = _image_blocks(mapped["U18"])
    assert "img_in_image_box_596_382_787_486" in u18_images
    assert "img_in_image_box_596_382_787_486" not in _image_blocks(mapped["U19"])
    entry = next(
        item
        for item in mapped["U18"].log.get("figure_reattributed_in") or []
        if item["asset_id"] == "img_in_image_box_596_382_787_486"
    )
    assert entry["owner"] == "U18"
    assert entry["sub"] == "S5"
    assert entry["evidence"]["scores"] == {"U18": 26}
    assert entry["evidence"]["declaring_unit"] == "U19"


# ---------------------------------------------------------------------------
# 4. 反例：证据不足 → 显式未决（不强行归属）
# ---------------------------------------------------------------------------


def test_ambiguous_evidence_is_explicitly_unattributed(monkeypatch):
    real = fa.resolve_owner

    def fake(asset_id, hint, ctx, *, page=None):
        if fa.stem_of(asset_id) == _Q14_IMAGE:
            return {
                "status": "ambiguous",
                "owner": None,
                "sub": None,
                "stem": fa.stem_of(asset_id),
                "evidence": {
                    "page": 4,
                    "bbox": [703, 1144, 929, 1250],
                    "md_line": 231,
                    "declaring_unit": "U14",
                    "scores": {"U13": 3, "U14": 3},
                    "rows": [],
                },
                "ranked": [("U13", 3), ("U14", 3)],
                "reason": "tie",
            }
        return real(asset_id, hint, ctx, page=page)

    monkeypatch.setattr(fa, "resolve_owner", fake)
    mapping = fx.map_one("U14", with_layout=True)

    assert _Q14_IMAGE not in _image_blocks(mapping)
    asset = _asset(mapping, _Q14_IMAGE)
    assert asset is not None, "ambiguous figure must be retained as review-only asset"
    assert asset.target_path is None
    assert "OWNERSHIP-AMBIGUOUS" in (asset.note or "")

    unattributed = (mapping.log.get("image_layout") or {}).get("unattributed") or []
    assert any(item["asset_id"] == _Q14_IMAGE for item in unattributed)
    assert any(
        "ownership_ambiguous" in note for _, note in _evidence_notes(mapping)
    )


# ---------------------------------------------------------------------------
# 5. 零回归
# ---------------------------------------------------------------------------


def test_no_layout_keeps_existing_unit_boundary(mapped_no_layout):
    """无 image_layout → 不启用归属推翻/位置补全/证据改写。"""
    for unit_id, mapping in mapped_no_layout.items():
        assert mapping.log.get("image_layout") is None
        assert all(asset.page is None for asset in mapping.candidate.core.content.assets)
        notes = [note for _, note in _evidence_notes(mapping) if "cross-unit" in note]
        assert not notes
    assert _Q14_IMAGE in _image_blocks(mapped_no_layout["U14"])
    # 无布局证据时不启用 PDF 子问落位：保持 applies_to（S3/S4）
    assert ("stem", "S3", "img_in_image_box_160_398_220_476") in fx.all_images(
        mapped_no_layout["U16"].candidate.core.content
    )
    assert ("stem", "S4", "img_in_image_box_115_814_318_1053") in fx.all_images(
        mapped_no_layout["U16"].candidate.core.content
    )


def test_zero_regression_scope_is_exactly_four_units(mapped, mapped_no_layout):
    moved = {
        "U13": "img_in_image_box_703_1144_929_1250",
        "U14": "img_in_image_box_703_1144_929_1250",
        "U18": "img_in_image_box_596_382_787_486",
        "U19": "img_in_image_box_596_382_787_486",
    }
    changed = set()

    def _asset_identity(mapping):
        return [
            (asset.asset_id, asset.asset_role, asset.storage_path, asset.content_hash)
            for asset in mapping.candidate.core.content.assets
            if asset.asset_id != moved.get(mapping.unit_id)
        ]

    for unit_id, after in mapped.items():
        before = mapped_no_layout[unit_id]
        assert fx.text_sequence(after.candidate.core.content) == fx.text_sequence(
            before.candidate.core.content
        ), f"{unit_id}: text/structure changed"
        assert [
            answer.model_dump(mode="json") for answer in after.candidate.core.answers
        ] == [
            answer.model_dump(mode="json") for answer in before.candidate.core.answers
        ], f"{unit_id}: answers changed"
        # 图片身份/顺序（剔除跨单元移动的那一张）必须不变；page/bbox 补全除外
        assert _asset_identity(after) == _asset_identity(before), (
            f"{unit_id}: asset identity/order changed"
        )
        if fx.all_images(after.candidate.core.content) != fx.all_images(
            before.candidate.core.content
        ):
            changed.add(unit_id)

    assert changed == {"U13", "U14", "U16", "U18", "U19"}, changed
    assert set(_image_blocks(mapped["U13"])) - set(_image_blocks(mapped_no_layout["U13"])) == {_Q14_IMAGE}
    assert set(_image_blocks(mapped_no_layout["U14"])) - set(_image_blocks(mapped["U14"])) == {_Q14_IMAGE}
    # Q16（本轮验收案例）：子问行内图按 PDF 文本行证据回到 S2/S3（AF5 口径）
    assert ("stem", "S2", "img_in_image_box_160_398_220_476") in fx.all_images(
        mapped["U16"].candidate.core.content
    )
    assert ("stem", "S3", "img_in_image_box_115_814_318_1053") in fx.all_images(
        mapped["U16"].candidate.core.content
    )


def test_all_candidates_still_pass_contract_validation(mapped):
    for unit_id, mapping in mapped.items():
        candidate_adapter.validate_python(mapping.candidate.model_dump(mode="json"))


def test_layout_evidence_placements_are_logged_with_page_and_bbox(mapped):
    for mapping in mapped.values():
        layout_log = _layout_log(mapping)
        assert layout_log is not None
        assert layout_log["digest"] == fx.LAYOUT_DIGEST
        assert layout_log["policy"] == "layout_evidence_required"
        for placement in layout_log["placements"]:
            assert placement["page"] >= 1
            assert len(placement["bbox"]) == 4
