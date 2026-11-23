# -*- coding: utf-8 -*-
"""Manifest ``annotation_meta.image_layout`` 的确定性消费层（Layer 2）。

范围（QCORE-OCR-EXTRACTION-FIDELITY-02）：只读消费 Preprocessing 已产出的
布局证据，供 Mapper 决定「图属哪个单元 / 落在文本哪一侧 / 是否同组」，
并把空间位置与显式风险带入 Question。**不生成、不改写**正文、图片、答案、
OCR 证据；缺失/畸形 ``image_layout`` 一律 fail-open 返回 None，Mapper 退回
既有「Manifest 行区间」行为，不据缺失证据推断。

证据来源（均由 Layer 1 写入 Manifest）：
- ``placements[]``：page / block_id / bbox(OCR 像素) / md_line / relation /
  text_line / echo / risks；
- ``risks[]``：``inline_image_after_text_in_md``、``math_echo_adjacent_image``、
  ``math_echo_without_image``、``md_image_without_json_image_block``、
  ``json_image_missing_in_md``；
- ``multi_image_groups[]``：同页同 y-band 的图片组（只作分组证据，禁止推断
  表格/选项组/固定网格）；
- ``digest``：布局证据指纹，用于把 Question 侧决策绑定到具体布局证据。
"""
from __future__ import annotations

from dataclasses import dataclass

from .figure_attribution import bbox_of, stem_of

__all__ = [
    "LayoutEvidence",
    "normalize_layout",
    "get_layout",
    "placement_for_stem",
    "group_of_stem",
    "risks_for_stem",
    "placements_for_unit",
    "unit_ranges",
]

RELATIONS = frozenset(
    {"inline", "block_before", "block_after", "block_unmapped"}
)
RISK_KINDS = frozenset(
    {
        "inline_image_after_text_in_md",
        "math_echo_adjacent_image",
        "math_echo_without_image",
        "md_image_without_json_image_block",
        "json_image_missing_in_md",
    }
)

_UNSET = object()


def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_page(value):
    n = _as_int(value)
    return n if n is not None and n >= 1 else None


def _as_bbox(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    out = []
    for x in value:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
        out.append(int(x) if float(x).is_integer() else float(x))
    x0, y0, x1, y1 = out
    if x1 < x0 or y1 < y0:
        return None
    return (x0, y0, x1, y1)


def _as_str_list(value):
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(x for x in value if isinstance(x, str) and x)


@dataclass(frozen=True)
class LayoutEvidence:
    """已校验的布局证据索引（只读）。"""

    digest: str
    summary: dict
    placements: tuple
    risks: tuple
    groups: tuple
    by_stem: dict
    by_md_line: dict
    by_block: dict
    group_of_stem: dict
    risks_by_block: dict
    issues: tuple

    def placement(self, stem: str):
        return self.by_stem.get(stem_of(stem))

    def group_index(self, stem: str):
        return self.group_of_stem.get(stem_of(stem))

    def placements_in_ranges(self, ranges) -> tuple:
        """MD 行区间命中的 placements（声明归属的既有证据）。"""
        out = []
        seen = set()
        for r in ranges or ():
            if not isinstance(r, (list, tuple)) or len(r) != 2:
                continue
            start, end = _as_int(r[0]), _as_int(r[1])
            if start is None or end is None:
                continue
            for line in range(max(1, start), end + 1):
                for p in self.by_md_line.get(line, ()):  # type: ignore[union-attr]
                    key = id(p)
                    if key not in seen:
                        seen.add(key)
                        out.append(p)
        return tuple(out)


def unit_ranges(unit: dict) -> tuple:
    """单元声明的全部 MD 行区间（stem/options/material/sub/…，1-based 闭区间）。"""
    ranges = []
    for key in (
        "stem_lines",
        "options_lines",
        "material_lines",
        "questions_lines",
        "extra_lines",
        "answer_lines",
        "explanation_lines",
    ):
        r = unit.get(key)
        if isinstance(r, (list, tuple)) and len(r) == 2:
            ranges.append((r[0], r[1]))
    for sub in unit.get("sub_questions") or ():
        if sub.get("line_start") is not None:
            ranges.append((sub["line_start"], sub.get("line_end") or sub["line_start"]))
    for mat in unit.get("materials") or ():
        if mat.get("line_start") is not None:
            ranges.append((mat["line_start"], mat.get("line_end") or mat["line_start"]))
    return tuple(ranges)


def normalize_layout(manifest: dict):
    """把 Manifest 的 ``annotation_meta.image_layout`` 校验成索引。

    返回 ``None`` 表示 Manifest 没有可消费的布局证据（缺字段/结构畸形）。
    """
    if not isinstance(manifest, dict):
        return None
    meta = manifest.get("annotation_meta")
    if not isinstance(meta, dict):
        return None
    raw = meta.get("image_layout")
    if not isinstance(raw, dict):
        return None
    raw_placements = raw.get("placements")
    if not isinstance(raw_placements, list):
        return None

    issues: list[str] = []
    placements: list[dict] = []
    by_stem: dict = {}
    by_md_line: dict = {}
    by_block: dict = {}

    for item in raw_placements:
        if not isinstance(item, dict):
            issues.append("placement_dropped:not_object")
            continue
        page = _as_page(item.get("page"))
        bbox = _as_bbox(item.get("bbox"))
        relation = item.get("relation")
        if page is None or bbox is None or relation not in RELATIONS:
            issues.append("placement_dropped:missing_page_bbox_or_relation")
            continue
        md_line = _as_int(item.get("md_line"))
        ref = item.get("ref") if isinstance(item.get("ref"), str) and item["ref"] else None
        stem = stem_of(ref) if ref else None
        if stem is None and md_line is None:
            # 无 MD 引用也无 MD 行：仍保留 page/bbox 证据（可用唯一 bbox 回退
            # 关联 asset）；只是不能作 MD 行索引。
            issues.append("placement_without_md_anchor")
        placement = {
            "page": page,
            "block_id": _as_int(item.get("block_id")),
            "block_order": item.get("block_order"),
            "bbox": bbox,
            "md_line": md_line,
            "ref": ref,
            "stem": stem,
            "relation": relation,
            "text_block_id": _as_int(item.get("text_block_id")),
            "text_line": _as_int(item.get("text_line")),
            "echo": bool(item.get("echo")),
            "risks": _as_str_list(item.get("risks")),
        }
        unknown = [r for r in placement["risks"] if r not in RISK_KINDS]
        if unknown:
            issues.append("unknown_risk_kind:" + ",".join(sorted(unknown)))
        placements.append(placement)
        if stem is not None:
            if stem in by_stem:
                issues.append("duplicate_placement_stem:" + stem)
            else:
                by_stem[stem] = placement
        if md_line is not None:
            by_md_line.setdefault(md_line, []).append(placement)
        if placement["block_id"] is not None:
            by_block[(page, placement["block_id"])] = placement

    # 身份不唯一的 stem（同页/跨页同名 bbox，如页脚二维码变体）不得用于
    # page/bbox 补全或归属裁决——没有唯一源元素身份就没有唯一空间位置。
    stem_counts: dict = {}
    for p in placements:
        if p.get("stem") is not None:
            stem_counts[p["stem"]] = stem_counts.get(p["stem"], 0) + 1
    ambiguous_stems = {s for s, n in stem_counts.items() if n > 1}
    for stem in sorted(ambiguous_stems):
        by_stem.pop(stem, None)

    risks: list[dict] = []
    raw_risks = raw.get("risks")
    if isinstance(raw_risks, list):
        for item in raw_risks:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if not isinstance(kind, str) or not kind:
                continue
            risk = {
                "kind": kind,
                "page": _as_page(item.get("page")),
                "block_id": _as_int(item.get("block_id")),
                "md_line": _as_int(item.get("md_line")),
                "text_line": _as_int(item.get("text_line")),
                "ref": item.get("ref") if isinstance(item.get("ref"), str) else None,
            }
            risks.append(risk)
            if kind not in RISK_KINDS:
                issues.append("unknown_risk_kind:" + kind)

    groups: list[dict] = []
    group_of_stem: dict = {}
    raw_groups = raw.get("multi_image_groups")
    if isinstance(raw_groups, list):
        for raw_index, item in enumerate(raw_groups):
            if not isinstance(item, dict):
                continue
            lines = tuple(
                sorted({n for n in (_as_int(x) for x in (item.get("lines") or ())) if n})
            )
            if not lines:
                issues.append("group_without_lines:%d" % raw_index)
                continue
            y_band = item.get("y_band")
            y_band_ok = (
                isinstance(y_band, (list, tuple))
                and len(y_band) == 2
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in y_band)
                and y_band[1] >= y_band[0]
            )
            if not y_band_ok:
                issues.append("group_y_band_malformed:%d" % raw_index)
                y_band = None
            # 存储下标必须与 groups 列表位置一致：畸形/被跳过的 group 会让
            # 原始 enumerate 下标与列表下标脱节（复核 F1）。
            stored_index = len(groups)
            groups.append(
                {
                    "group_index": stored_index,
                    "source_index": raw_index,
                    "page": _as_page(item.get("page")),
                    "lines": lines,
                    "y_band": tuple(y_band or ()),
                }
            )
            for line in lines:
                for p in by_md_line.get(line, ()):  # type: ignore[union-attr]
                    stem = p.get("stem")
                    if (
                        stem is not None
                        and stem not in ambiguous_stems
                        and stem not in group_of_stem
                    ):
                        group_of_stem[stem] = stored_index

    risks_by_block: dict = {}
    for risk in risks:
        page, block_id = risk.get("page"), risk.get("block_id")
        if page is not None and block_id is not None:
            risks_by_block.setdefault((page, block_id), []).append(risk["kind"])
        md_line = risk.get("md_line")
        if md_line is not None:
            for p in by_md_line.get(md_line, ()):  # type: ignore[union-attr]
                if p.get("block_id") is not None:
                    risks_by_block.setdefault(
                        (p["page"], p["block_id"]), []
                    ).append(risk["kind"])

    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    digest = raw.get("digest") if isinstance(raw.get("digest"), str) else ""
    deduped_issues = tuple(dict.fromkeys(issues))
    return LayoutEvidence(
        digest=digest,
        summary=dict(summary),
        placements=tuple(placements),
        risks=tuple(risks),
        groups=tuple(groups),
        by_stem=by_stem,
        by_md_line=by_md_line,
        by_block=by_block,
        group_of_stem=group_of_stem,
        risks_by_block=risks_by_block,
        issues=deduped_issues,
    )


def get_layout(ctx):
    """按 ctx 缓存的布局证据；Manifest 未携带时返回 None（fail-open）。"""
    cached = getattr(ctx, "_layout_evidence", _UNSET)
    if cached is _UNSET:
        cached = normalize_layout(getattr(ctx, "manifest", None) or {})
        try:
            ctx._layout_evidence = cached
        except Exception:  # noqa: BLE001 — 非 dataclass ctx（测试替身）
            pass
    return cached


def placement_for_stem(layout, stem: str):
    """stem → placement；stem 无 MD 引用（``ref`` 缺失）时按唯一 bbox 回退。

    bbox 回退仅接受**唯一**命中：同页/跨页同 bbox 的多份证据（如页脚二维码
    变体）一律视为身份不唯一，不做位置补全，也不做归属裁决。
    """
    if layout is None or not stem:
        return None
    key = stem_of(stem)
    placement = layout.by_stem.get(key)
    if placement is not None:
        return placement
    box = bbox_of(key)
    if box is None:
        return None
    matches = [p for p in layout.placements if tuple(p["bbox"]) == tuple(box)]
    if len(matches) == 1:
        return matches[0]
    return None


def group_of_stem(layout, stem: str):
    if layout is None or not stem:
        return None
    return layout.group_of_stem.get(stem_of(stem))


def risks_for_stem(layout, stem: str) -> tuple:
    """该图自身的显式风险（placement risks + 同 block 的 risks[]）。"""
    if layout is None or not stem:
        return ()
    p = layout.by_stem.get(stem_of(stem))
    if p is None:
        return ()
    kinds = list(p.get("risks") or ())
    kinds.extend(layout.risks_by_block.get((p["page"], p.get("block_id")), ()))
    return tuple(dict.fromkeys(kinds))


def placements_for_unit(layout, unit: dict) -> tuple:
    """本单元声明行区间内出现的 placements（含无 MD 行但 figure 显式声明的图）。"""
    if layout is None:
        return ()
    found = list(layout.placements_in_ranges(unit_ranges(unit)))
    seen = {id(p) for p in found}
    for figure in unit.get("figures") or ():
        stem = stem_of(figure.get("asset_ref") or "")
        p = layout.by_stem.get(stem) if stem else None
        if p is not None and id(p) not in seen:
            seen.add(id(p))
            found.append(p)
    return tuple(found)
