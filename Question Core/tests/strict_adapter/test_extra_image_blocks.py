# -*- coding: utf-8 -*-
"""受控 extra_image_blocks 注入测试（QCORE-STUDENT-FIDELITY-IMAGE-REPAIR-01）。

- T1：Q2 句中切分（字节保全 + 位置 + line 区间不变 + 不生成额外文本）
- T2：U11 四图顺序（1→4、位于提示词块之后、不进 answer/explanation 结构）
- T3：未声明 Unit 零变化 + composite 声明 fail closed + 非法声明 fail closed

常量取自 R1 workspace 封存文本；offset 可审计：Q2=首个多勒符位置 9
（前缀 "2. 紫花前胡醇 "）；U11=提示词块文本流尾 101（len 73+11+17）。
"""
from __future__ import annotations

import pytest

from strict_adapter.mapper import (
    _apply_extra_image_blocks,
    _composite_bodies_and_materials,
)

Q2_TEXT = (
    "2. 紫花前胡醇 $ \\mathrm{HO} $ 可从中药材当归和白芷中提取得到，"
    "能提高人体免疫力。有关该化合物，下列叙述错误的是"
)
Q2_OFFSET = 9
Q2_ASSET = "img_in_image_box_217_754_454_834"

U11_TEXTS = [
    "假设你是红星中学高三学生李华。你们班上周组织了一次以“劳动最光荣”为主题的社会实践活动。请根据以下四幅图的先后顺序，写一篇英文周记，记述整个过程。",
    "注意：词数不少于60。",
    "提示词：西瓜 watermelon",
    "---",
    "---",
]
U11_OFFSET = 101  # len(73)+len(11)+len(17)
U11_LINES = [335, 337, 339, 341, 347]
U11_ASSETS = [
    "img_in_image_box_79_557_464_832",  # p8 连环画 1 号格（左上）
    "img_in_image_box_490_553_884_830",  # 2 号格（右上）
    "img_in_image_box_78_860_463_1137",  # 3 号格（左下）
    "img_in_image_box_490_859_885_1140",  # 4 号格（右下）
]


def _q2_raw():
    return [{"kind": "text", "text": Q2_TEXT, "line_start": 17, "line_end": 17}]


def _u11_raw():
    return [
        {"kind": "text", "text": t, "line_start": ln, "line_end": ln}
        for t, ln in zip(U11_TEXTS, U11_LINES)
    ]


class TestT1Q2MidSentenceSplit:
    def test_bytes_preserved_and_position(self):
        out = _apply_extra_image_blocks(
            _q2_raw(),
            [{"asset_id": Q2_ASSET, "anchor": "text", "offset": Q2_OFFSET}],
            "Q2",
        )
        assert [b["kind"] for b in out] == ["text", "image", "text"]
        # 前后文字字节拼接 == 修复前原文
        assert out[0]["text"] + out[2]["text"] == Q2_TEXT
        assert out[0]["text"] == Q2_TEXT[:Q2_OFFSET]
        assert out[2]["text"] == Q2_TEXT[Q2_OFFSET:]
        assert out[1]["asset_id"] == Q2_ASSET
        # line 区间沿用原块，不生成额外文本块
        assert sum(1 for b in out if b["kind"] == "text") == 2
        for b in out:
            assert b["line_start"] == 17 and b["line_end"] == 17


class TestT2U11FourOrder:
    def test_order_position_and_bytes(self):
        specs = [{"asset_id": a, "anchor": "text", "offset": U11_OFFSET} for a in U11_ASSETS]
        out = _apply_extra_image_blocks(_u11_raw(), specs, "U11")
        # 1→4 顺序
        img_ids = [b["asset_id"] for b in out if b["kind"] == "image"]
        assert img_ids == U11_ASSETS
        # 文字字节全保留且顺序不变
        assert "".join(b["text"] for b in out if b["kind"] == "text") == "".join(U11_TEXTS)
        # 图像位于提示词块之后、首个分页伪影 --- 之前
        idx_first_img = next(i for i, b in enumerate(out) if b["kind"] == "image")
        idx_dashes = next(
            i for i, b in enumerate(out) if b["kind"] == "text" and b["text"] == "---"
        )
        assert idx_first_img > 2  # 在前三个文本块之后
        assert idx_first_img < idx_dashes
        # 不进 answer/explanation：注入只作用于题面块列表本身
        # （explanation/answer 的装配在 _explanation_blocks / answers 路径，不经本函数）
        for b in out:
            if b["kind"] == "image":
                assert b["line_start"] == 339 and b["line_end"] == 339


class TestT3UndeclaredAndFailClosed:
    def test_empty_specs_identity(self):
        u11 = _u11_raw()
        assert _apply_extra_image_blocks(u11, [], "U11") == u11
        q2 = _q2_raw()
        assert _apply_extra_image_blocks(q2, [], "Q2") == q2

    def test_composite_declaration_fail_closed(self):
        with pytest.raises(ValueError, match="composite"):
            _composite_bodies_and_materials(
                {
                    "unit_id": "x",
                    "extra_image_blocks": [
                        {"asset_id": "a", "anchor": "text", "offset": 0}
                    ],
                },
                None,
                [],
                {},
            )

    @pytest.mark.parametrize(
        "spec",
        [
            {"asset_id": "a", "anchor": "image", "offset": 0},
            {"asset_id": "a", "anchor": "text", "offset": -1},
            {"asset_id": "a", "anchor": "text", "offset": 99999},
            {"asset_id": "a", "anchor": "text", "offset": 1.5},
            {"asset_id": "", "anchor": "text", "offset": 0},
        ],
    )
    def test_fail_closed_on_bad_spec(self, spec):
        with pytest.raises(ValueError):
            _apply_extra_image_blocks(_q2_raw(), [spec], "Q2")
