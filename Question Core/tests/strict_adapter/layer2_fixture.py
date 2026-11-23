# -*- coding: utf-8 -*-
"""Layer 2（QCORE-OCR-EXTRACTION-FIDELITY-02）测试夹具。

来源：封存 run ``qcore_prebulk_owner_acceptance_01`` 的 2026 山东高考化学
（教师版）——Manifest / OCR Markdown / 原始 PDF / Layer 1 ``image_layout``。
全部只读；源文件哈希固定，变化即失败（与 ``test_mapper_real_manifest`` 同口径）。

image_layout 夹具由 ``Preprocessing/scripts/ocr_layout.py build_layout_evidence``
在同一封存 MD + OCR JSONL 上生成，digest 见 ``fixtures/chem_2026sd_image_layout.json``；
本文件只消费，不重新生成。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from strict_adapter.extract import load_source_lines
from strict_adapter.mapper import MappingContext, map_all, map_unit

RUN_ROOT = Path(r"D:\Project\AITutors\runs\qcore_prebulk_owner_acceptance_01")
PRODUCTION = RUN_ROOT / "production"

MANIFEST = (
    PRODUCTION
    / "preprocessing"
    / "化学"
    / "化学_2026山东高考真题化学（教师版）(1).manifest.json"
)
SOURCE_MD = (
    PRODUCTION / "ocr" / "化学" / "化学_2026山东高考真题化学（教师版）(1).md"
)
SOURCE_JSONL = (
    PRODUCTION
    / "ocr"
    / "化学"
    / "化学_2026山东高考真题化学（教师版）(1).ocr_raw.jsonl"
)
SOURCE_PDF = (
    RUN_ROOT / "input" / "化学_2026山东高考真题化学（教师版）(1).pdf"
)
LAYOUT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "chem_2026sd_image_layout.json"

#: 封存输入哈希（只读基线；改动即说明输入被替换）
MANIFEST_SHA = "934ff0ed6c3b3a372aee392f6a66ea50742917e1487d97da3f236a11cb87cb01"
SOURCE_MD_SHA = "08399755ce7e9451d0c9870b72e683e6cd17a480ea5513fab027721a22a01b3f"
SOURCE_JSONL_SHA = "c76e1c3c5713afd57cd6703245c3a4d52e97cab4e61193db10880301db040d9f"
SOURCE_PDF_SHA = "d43a5828c71907e19061d7750485deba8a0b5d3d549f40bbf5990d7f65ec1ac8"
LAYOUT_DIGEST = "d83b9673019ffd27825352f346a264cbdcebc25e368cae50df7223a5a4093621"

PAPER_ID = "化学_2026山东高考真题化学（教师版）(1)"
SUBJECT = "化学"
_MISSING = [
    str(p)
    for p in (MANIFEST, SOURCE_MD, SOURCE_JSONL, SOURCE_PDF, LAYOUT_FIXTURE)
    if not p.is_file()
]
REQUIRE_SEALED = (
    f"sealed Layer 2 inputs not found: {_MISSING}" if _MISSING else ""
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(with_layout: bool) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if with_layout:
        fixture = json.loads(LAYOUT_FIXTURE.read_text(encoding="utf-8"))
        assert (
            fixture["image_layout"]["digest"] == LAYOUT_DIGEST
        ), "image_layout fixture digest changed"
        manifest.setdefault("annotation_meta", {})["image_layout"] = fixture[
            "image_layout"
        ]
    else:
        meta = manifest.get("annotation_meta") or {}
        meta.pop("image_layout", None)
        manifest["annotation_meta"] = meta
    return manifest


def build_ctx(with_layout: bool) -> MappingContext:
    manifest = load_manifest(with_layout)
    lines = load_source_lines(str(SOURCE_MD))
    return MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path=str(MANIFEST),
        manifest_name=MANIFEST.name,
        source_md_path=str(SOURCE_MD),
        source_md_name=SOURCE_MD.name,
        source_pdf_name=SOURCE_PDF.name,
        annotated_md_name="fixture",
        manifest_sha=sha256(MANIFEST),
        source_md_sha=sha256(SOURCE_MD),
        source_pdf_sha=sha256(SOURCE_PDF),
        annotated_md_sha="0" * 64,
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=SOURCE_MD.stat().st_size,
        source_pdf_bytes=SOURCE_PDF.stat().st_size,
        annotated_md_bytes=1,
        image_by_line={
            entry["line_no"]: entry
            for entry in manifest.get("image_assets", [])
        },
        paper_id=PAPER_ID,
        subject=SUBJECT,
        run_id="layer2-tests",
        source_pdf_path=str(SOURCE_PDF),
    )


def map_chem(with_layout: bool) -> dict:
    return {mapping.unit_id: mapping for mapping in map_all(build_ctx(with_layout))}


def map_one(unit_id: str, with_layout: bool):
    ctx = build_ctx(with_layout)
    unit = next(u for u in ctx.manifest["units"] if u.get("unit_id") == unit_id)
    return map_unit(unit, ctx)


def all_images(content) -> list:
    """content 中全部 image 块（stem / options / materials 顺序展开）。"""
    out = []
    for body in content.bodies:
        for block in body.stem_blocks:
            if getattr(block, "kind", "") == "image":
                out.append(("stem", body.local_id, block.asset_id))
        for option in body.options:
            for block in option.blocks:
                if getattr(block, "kind", "") == "image":
                    out.append(("option", f"{body.local_id}/{option.label}", block.asset_id))
    for material in content.materials:
        for block in material.blocks:
            if getattr(block, "kind", "") == "image":
                out.append(("material", material.material_id, block.asset_id))
    return out


def text_sequence(content) -> list:
    """去掉图块后的文本/表格序列（零回归口径：文本与结构不得变化）。"""
    out = []
    for body in content.bodies:
        for block in body.stem_blocks:
            if getattr(block, "kind", "") != "image":
                out.append((body.local_id, block.kind, getattr(block, "text", None)))
        for option in body.options:
            for block in option.blocks:
                if getattr(block, "kind", "") != "image":
                    out.append((f"{body.local_id}/{option.label}", block.kind, getattr(block, "text", None)))
    for material in content.materials:
        for block in material.blocks:
            if getattr(block, "kind", "") != "image":
                out.append((material.material_id, block.kind, getattr(block, "text", None)))
    return out
