# -*- coding: utf-8 -*-
"""页脚装饰图（机构二维码/水印）分类 — QCORE-PRE-BULK-OWNER-ACCEPTANCE-01-AF1。

OCR 版面模型把页脚二维码标成普通 image（markdown_ignore_labels 只滤
footer/footer_image），装饰图因此随题面行区间流入 figure assets。本模块在
资产层做确定性分类（不改 PDF/正文、不物理删除源图）：

  decorative = small
               AND (extreme_left OR extreme_right)
               AND bottom_band
               AND (repeated OR tight_bottom_square)

其中（页像素坐标来自 stem `img_in_*_box_x1_y1_x2_y2`）：
  small               面积 < 5% 页面积
  extreme_left        x1 <= 15% 页宽（左页边）
  extreme_right       x2 >= 85% 页宽（右页边）
  bottom_band         y1 >= 87% 页高（页脚装饰带）
  repeated            同 stem 源 MD 出现 >=2 行，或 manifest 同 sha 引用 >=2
  tight_bottom_square y1 >= 90% 页高 且 0.5 <= 纵横比 <= 2.0

页尺寸来源（按序）：调用方显式 → 源 MD 同名 *.ocr_raw.jsonl 的 width/height
（OCR 权威）→ manifest 全 bbox 的 max(x2)/max(y2)（有页脚装饰时≈页）。
缺页尺寸 → 一律 question_figure（fail-safe：没有依据就不判装饰）。

真题图（结构式/装置图/统计图）不满足全部条件；对 4 卷 83 个资产的全量核对见
tests/strict_adapter/test_asset_furniture.py。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = [
    "ROLE_DECORATIVE",
    "ROLE_QUESTION_FIGURE",
    "AssetRole",
    "classify_asset",
    "discover_page_size",
    "parse_bbox",
    "stem_of",
]

AssetRole = str
ROLE_DECORATIVE: AssetRole = "decorative"
ROLE_QUESTION_FIGURE: AssetRole = "question_figure"

_BOX_RE = re.compile(r"_(?:image|chart|photo)_box_(\d+)_(\d+)_(\d+)_(\d+)(?:\.|$)")
_STEM_RE = re.compile(r"(img_in_\w+_box_[\d_]+)")


def stem_of(asset_id: str) -> str:
    """asset 标识 → 无扩展名 stem（与 manifest image_assets src stem 同口径）。"""
    s = (asset_id or "").replace("\\", "/").rsplit("/", 1)[-1]
    s = s.rsplit(".", 1)[0]
    m = _STEM_RE.search(s)
    return m.group(1) if m else s


def parse_bbox(asset_id: str) -> tuple[int, int, int, int] | None:
    """从 stem 解析 OCR 页像素坐标 (x1, y1, x2, y2)。"""
    m = _BOX_RE.search(stem_of(asset_id))
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def discover_page_size(
    source_md_path: str | Path | None = None,
    manifest: dict | None = None,
    image_assets: list | None = None,
) -> tuple[int, int] | None:
    """页尺寸发现 (width, height)：OCR jsonl → manifest bbox 上界；无据为 None。"""
    if source_md_path:
        p = Path(source_md_path)
        cand = p.parent / (p.stem + ".ocr_raw.jsonl")
        if cand.is_file():
            try:
                with open(cand, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        rec = json.loads(line)
                        for res in (rec.get("result") or {}).get("layoutParsingResults") or []:
                            pr = res.get("prunedResult") or {}
                            w, h = pr.get("width"), pr.get("height")
                            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                                return w, h
            except (OSError, ValueError):
                pass
    assets = image_assets
    if assets is None and manifest is not None:
        assets = manifest.get("image_assets") or []
    max_x2 = max_y2 = 0
    for a in assets or []:
        src = a.get("src") or a.get("asset_id") or a.get("artifact_path") or ""
        box = parse_bbox(src)
        if box:
            max_x2 = max(max_x2, box[2])
            max_y2 = max(max_y2, box[3])
    if max_x2 > 0 and max_y2 > 0:
        return max_x2, max_y2
    return None


def classify_asset(
    asset_id: str,
    *,
    page_size: tuple[int, int] | None = None,
    md_occurrence_count: int = 1,
    same_sha_count: int = 1,
) -> AssetRole:
    """装饰图分类（纯函数、确定性）。证据不足一律 question_figure。"""
    box = parse_bbox(asset_id)
    if box is None or not page_size:
        return ROLE_QUESTION_FIGURE
    pw, ph = page_size
    if pw <= 0 or ph <= 0:
        return ROLE_QUESTION_FIGURE
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    aspect = (w / h) if h else 0.0
    small = (w * h) < 0.05 * (pw * ph)
    extreme = x1 <= 0.15 * pw or x2 >= 0.85 * pw
    bottom = y1 >= 0.87 * ph
    repeated = md_occurrence_count >= 2 or same_sha_count >= 2
    tight_square = y1 >= 0.90 * ph and 0.5 <= aspect <= 2.0
    if small and extreme and bottom and (repeated or tight_square):
        return ROLE_DECORATIVE
    return ROLE_QUESTION_FIGURE
