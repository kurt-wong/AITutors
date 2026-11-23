# -*- coding: utf-8 -*-
"""asset_furniture 分类器全量核对 — QCORE-PRE-BULK-OWNER-ACCEPTANCE-01-AF1。

语料=qcore_prebulk_accept_01 全部 79 个资产 stem（4 卷真题）：
  12 个已知页脚机构码（微信二维码/小程序码，OCR 误标普通 image）→ 必须 decorative；
  其余 67 个真题图（结构式/装置图/统计图/表格截图）→ 必须 question_figure。
页尺寸 (1191, 1684) = OCR 页空间（ocr_raw.jsonl width/height 四卷一致）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\Project\AITutors\Question Core")))
sys.path.insert(0, str(Path(r"D:\Project\AITutors\Question Core\strict_adapter")))

from strict_adapter.asset_furniture import (  # noqa: E402
    ROLE_DECORATIVE,
    ROLE_QUESTION_FIGURE,
    classify_asset,
    discover_page_size,
    parse_bbox,
)

PAGE = (1191, 1684)

# 12 个已知页脚机构码（af1_db_decorative_scan.json 复核；左码 x≈20/右码 x≈1010）
DECORATIVE = [
    "img_in_image_box_1010_1531_1150_1672",
    "img_in_image_box_1010_1532_1150_1671",
    "img_in_image_box_1010_1532_1150_1672",
    "img_in_image_box_1010_1533_1150_1671",
    "img_in_image_box_1010_1534_1150_1671",
    "img_in_image_box_1011_1533_1150_1670",
    "img_in_image_box_1011_1533_1150_1671",
    "img_in_image_box_1011_1533_1150_1672",
    "img_in_image_box_19_1547_147_1666",
    "img_in_image_box_20_1548_147_1666",
    "img_in_image_box_20_1549_147_1666",
    "img_in_image_box_21_1548_147_1666",
]

# 67 个真题图（qcore_asset_refs 全量 minus 装饰 12）
REAL_FIGURES = [
    "img_in_chart_box_104_1214_617_1464",
    "img_in_chart_box_104_723_475_985",
    "img_in_chart_box_108_403_458_682",
    "img_in_chart_box_109_1187_680_1460",
    "img_in_chart_box_109_243_673_540",
    "img_in_image_box_103_1021_1096_1469",
    "img_in_image_box_103_226_864_366",
    "img_in_image_box_103_808_945_936",
    "img_in_image_box_103_899_933_1153",
    "img_in_image_box_103_90_773_215",
    "img_in_image_box_104_1320_849_1448",
    "img_in_image_box_105_103_653_353",
    "img_in_image_box_105_1189_933_1519",
    "img_in_image_box_105_1287_344_1454",
    "img_in_image_box_105_649_326_781",
    "img_in_image_box_105_95_745_277",
    "img_in_image_box_106_503_281_612",
    "img_in_image_box_107_606_507_918",
    "img_in_image_box_108_1085_361_1304",
    "img_in_image_box_108_1159_512_1525",
    "img_in_image_box_108_211_310_439",
    "img_in_image_box_108_740_659_1065",
    "img_in_image_box_108_797_796_980",
    "img_in_image_box_108_877_653_992",
    "img_in_image_box_109_106_398_321",
    "img_in_image_box_109_1290_328_1485",
    "img_in_image_box_110_1130_416_1376",
    "img_in_image_box_110_1231_338_1447",
    "img_in_image_box_110_877_415_1124",
    "img_in_image_box_112_388_354_602",
    "img_in_image_box_112_667_314_1132",
    "img_in_image_box_113_229_418_451",
    "img_in_image_box_114_1164_321_1295",
    "img_in_image_box_115_381_286_456",
    "img_in_image_box_115_591_322_745",
    "img_in_image_box_115_814_318_1053",
    "img_in_image_box_118_1047_510_1219",
    "img_in_image_box_118_783_934_955",
    "img_in_image_box_123_1409_139_1498",
    "img_in_image_box_136_215_336_423",
    "img_in_image_box_137_1315_647_1428",
    "img_in_image_box_160_398_220_476",
    "img_in_image_box_171_1345_233_1497",
    "img_in_image_box_210_922_345_1005",
    "img_in_image_box_240_1212_296_1283",
    "img_in_image_box_264_1423_358_1497",
    "img_in_image_box_368_383_491_452",
    "img_in_image_box_376_1085_620_1311",
    "img_in_image_box_377_274_576_370",
    "img_in_image_box_385_1351_446_1503",
    "img_in_image_box_397_912_559_982",
    "img_in_image_box_441_866_754_1110",
    "img_in_image_box_445_1125_750_1376",
    "img_in_image_box_469_465_674_588",
    "img_in_image_box_473_290_639_356",
    "img_in_image_box_476_1397_572_1500",
    "img_in_image_box_532_1048_685_1201",
    "img_in_image_box_593_153_949_311",
    "img_in_image_box_596_382_787_486",
    "img_in_image_box_605_1398_625_1504",
    "img_in_image_box_638_206_767_436",
    "img_in_image_box_682_1288_751_1329",
    "img_in_image_box_689_695_1084_855",
    "img_in_image_box_703_1144_929_1250",
    "img_in_image_box_830_244_1038_397",
    "img_in_image_box_841_364_1026_472",
    "img_in_image_box_841_492_1063_628",
]


def test_corpus_sizes():
    assert len(DECORATIVE) == 12
    assert len(REAL_FIGURES) == 67
    assert not set(DECORATIVE) & set(REAL_FIGURES)


def test_known_footer_codes_are_decorative():
    for stem in DECORATIVE:
        role = classify_asset(stem, page_size=PAGE)
        assert role == ROLE_DECORATIVE, (stem, role)


def test_real_figures_are_kept():
    for stem in REAL_FIGURES:
        role = classify_asset(stem, page_size=PAGE)
        assert role == ROLE_QUESTION_FIGURE, (stem, role)


def test_singleton_footer_code_still_flagged():
    # 语文卷页脚码各只出现 1 次（无跨页重复），靠紧角方形判据命中
    for stem in (
        "img_in_image_box_20_1549_147_1666",
        "img_in_image_box_1010_1534_1150_1671",
    ):
        assert classify_asset(stem, page_size=PAGE) == ROLE_DECORATIVE
        assert classify_asset(stem, page_size=PAGE, md_occurrence_count=1) == ROLE_DECORATIVE


def test_fail_safe_without_page_size():
    for stem in DECORATIVE + REAL_FIGURES:
        assert classify_asset(stem, page_size=None) == ROLE_QUESTION_FIGURE, stem


def test_no_bbox_kept():
    assert classify_asset("some_other_asset", page_size=PAGE) == ROLE_QUESTION_FIGURE
    assert parse_bbox("some_other_asset") is None


def test_repetition_helps_without_tightness():
    # 跨页水印重复（>=2 行）时，即使不在紧角也判装饰（页脚带内）
    stem = "img_in_image_box_20_1548_147_1666"
    assert classify_asset(stem, page_size=PAGE, md_occurrence_count=2) == ROLE_DECORATIVE


def test_discover_page_size_from_manifest_bbox():
    # 回退口径 = 全 bbox 的 (max x2, max y2) 上界估计（有页脚装饰时≈页）
    manifest = {"image_assets": [
        {"src": "imgs/img_in_image_box_100_100_200_200.jpg", "sha256": "a"},
        {"src": "imgs/img_in_image_box_20_1548_147_1666.jpg", "sha256": "b"},
    ]}
    assert discover_page_size(manifest=manifest) == (200, 1666)


def test_mapper_blocks_filter_drops_decorative():
    """集成：_blocks_from_raw 过滤装饰图块并留痕，真图保留。"""
    from strict_adapter.mapper import MappingContext, _blocks_from_raw

    ctx = MappingContext(
        lines=["![x](imgs/img_in_image_box_20_1548_147_1666.jpg)",
               "text", "![y](imgs/img_in_image_box_596_382_787_486.jpg)"],
        manifest={"image_assets": [
            {"src": "imgs/img_in_image_box_20_1548_147_1666.jpg", "sha256": "a",
             "artifact_path": "_imgs/img_in_image_box_20_1548_147_1666.jpg",
             "line_no": 1, "bytes": 1},
            {"src": "imgs/img_in_image_box_596_382_787_486.jpg", "sha256": "b",
             "artifact_path": "_imgs/img_in_image_box_596_382_787_486.jpg",
             "line_no": 3, "bytes": 1},
        ]},
        manifest_path="m.json", manifest_name="m.json",
        source_md_path="x.md", source_md_name="x.md",
        source_pdf_name="x.pdf", annotated_md_name="x.annotated.md",
        manifest_sha="0" * 64, source_md_sha="0" * 64,
        source_pdf_sha="0" * 64, annotated_md_sha="0" * 64,
        manifest_bytes=1, source_md_bytes=1, source_pdf_bytes=1,
        annotated_md_bytes=1,
    )
    raw = [
        {"kind": "image", "asset_id": "img_in_image_box_20_1548_147_1666", "alt_text": "Image"},
        {"kind": "text", "text": "正文"},
        {"kind": "image", "asset_id": "img_in_image_box_596_382_787_486", "alt_text": "Image"},
    ]
    sink: list = []
    log: dict = {}
    blocks = _blocks_from_raw(raw, sink, ctx, "t", log)
    ids = [b.asset_id for b in blocks if getattr(b, "kind", None) == "image"]
    assert ids == ["img_in_image_box_596_382_787_486"], ids
    assert [a["asset_id"] for a in sink] == ["img_in_image_box_596_382_787_486"]
    assert log["excluded_assets"] == [
        {"asset_id": "img_in_image_box_20_1548_147_1666", "where": "t",
         "reason": "footer_furniture"}
    ]
