# -*- coding: utf-8 -*-
"""图的跨单元归属守卫（AF3/Q14·Q19；Layer 2 起与 image_layout 证据配合）。

问题形态：相邻题的图片在 OCR 线性流里落进本单元的行区间（化学 Q14 stem 区含
Q13 选项 D 的结构图；U19 材料区含 U18/S5 的目标结构图），按行区间注入会
「多引入/配图错位」。

确定性判定（不依赖 LLM）：
  1. 图 bbox（stem 编码的 OCR 页像素）→ PDF pt 行带（页面优先取 Layer 1
     image_layout 的 placement.page，无布局证据时回退 MD 分页）；
  2. pypdfium2 取同页文本行（坐标+文本），找出与图行带**重叠**的文本行；
  3. 重叠文本行与各单元 MD 行做 5-gram 共享片段投票（≥2 片段）；
  4. ``decide_attribution`` 三态裁决：唯一决定性票 → cross_unit / same_unit；
     并列或差距不足 → ambiguous（显式未决，不得强行归属）；无候选 →
     no_evidence（保持既有 Unit 边界并记录证据不足）。

预解析（ctx 缓存）：按 manifest 全量 image_assets 一次算出跨单元登记，消除
单元处理顺序依赖（U18 先于 U19 处理也能拿到回填登记）。
"""
from __future__ import annotations

import re

__all__ = [
    "bbox_of",
    "decide_attribution",
    "pdf_error",
    "pdf_page_heights",
    "resolve_owner",
    "reattributed_map",
    "reset_cache",
    "stem_of",
]

_PAGE_BREAK = re.compile(r"^\s*---\s*$")
_LINE_RE = re.compile(r"_(?:image|chart|photo)_box_(\d+)_(\d+)_(\d+)_(\d+)(?:\.|$)")
_STEM_RE = re.compile(r"(img_in_\w+_box_[\d_]+)")
_PUNCT = re.compile(r"[\s　·、，,。.：:；;！!？?（）()\[\]【】\"'“”‘’—\-_=<>*/\\|~^$]")

_PDF_CACHE: dict = {}
_PAGE_CACHE: dict = {}
_PDF_ERRORS: dict = {}
_IDX_CACHE: dict = {}
_MAP_CACHE: dict = {}
OCR_H = 1684.0


def _norm(s: str) -> str:
    return _PUNCT.sub("", (s or "").lower())


def stem_of(asset_id: str) -> str:
    s = (asset_id or "").replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = _STEM_RE.search(s)
    return m.group(1) if m else s


def _bbox(asset_id: str):
    m = _LINE_RE.search(stem_of(asset_id))
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def bbox_of(asset_id: str):
    """asset stem 中编码的 OCR 页像素 bbox（无 bbox 编码时返回 None）。"""
    return _bbox(asset_id)


def pdf_text_lines(pdf_path: str) -> list:
    """[(page_index, y_bottom_pt, y_top_pt, norm_text)]，按 PDF 文本层聚合到行。"""
    key = str(pdf_path)
    if key in _PDF_CACHE:
        return _PDF_CACHE[key]
    rows: list = []
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_path)
        for pno in range(len(doc)):
            tp = doc[pno].get_textpage()
            buckets: dict = {}
            for i in range(tp.count_chars()):
                c = tp.get_text_range(i, 1)
                if not c.strip():
                    continue
                b = tp.get_charbox(i)
                keyb = round(b[1] / 5)
                rec = buckets.setdefault(keyb, [b[1], b[3], []])
                rec[0] = min(rec[0], b[1])
                rec[1] = max(rec[1], b[3])
                rec[2].append((b[0], c))
            for _k, (yb, yt, chars) in buckets.items():
                text = "".join(c for _, c in sorted(chars))
                rows.append((pno, yb, yt, _norm(text)))
    except Exception as exc:  # noqa: BLE001 — 无 PDF 文本层时放弃守卫（fail-open 保内容）
        _PDF_ERRORS[key] = type(exc).__name__
    _PDF_CACHE[key] = rows
    return rows


def pdf_page_heights(pdf_path: str) -> list:
    """各页高度（pt）。用于校验 OCR 像素坐标的换算前提。"""
    key = str(pdf_path)
    if key in _PAGE_CACHE:
        return _PAGE_CACHE[key]
    heights: list = []
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_path)
        heights = [float(doc[pno].get_size()[1]) for pno in range(len(doc))]
    except Exception as exc:  # noqa: BLE001
        _PDF_ERRORS[key] = type(exc).__name__
    _PAGE_CACHE[key] = heights
    return heights


def pdf_error(pdf_path: str) -> str | None:
    """最近一次读取该 PDF 的错误类型（无错误/未读取为 None）。"""
    return _PDF_ERRORS.get(str(pdf_path))


def _page_map(lines: list) -> dict:
    page = 1
    m = {}
    for i, ln in enumerate(lines, 1):
        m[i] = page
        if _PAGE_BREAK.match(ln):
            page += 1
    return m


def _unit_index(manifest: dict, lines: list) -> list:
    """[(unit_id, ranges, shingles, sub_ranges)]"""
    key = id(manifest)
    if key in _IDX_CACHE:
        return _IDX_CACHE[key]
    idx = []
    for u in manifest.get("units") or []:
        uid = u.get("unit_id") or ""
        ranges = []
        for k in ("stem_lines", "questions_lines", "material_lines", "options_lines",
                  "extra_lines", "answer_lines", "explanation_lines"):
            r = u.get(k)
            if isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r):
                ranges.append((r[0], r[1]))
        for s in (u.get("sub_questions") or []):
            if s.get("line_start") is not None:
                ranges.append((int(s["line_start"]), int(s.get("line_end") or s["line_start"])))
        for mm in (u.get("materials") or []):
            if mm.get("line_start") is not None:
                ranges.append((int(mm["line_start"]), int(mm.get("line_end") or mm["line_start"])))
        shingles: set = set()
        for a, b in ranges:
            for ln in range(max(1, a), min(len(lines), b) + 1):
                n = _norm(lines[ln - 1])
                for i in range(max(0, len(n) - 4)):
                    shingles.add(n[i:i + 5])
        subs = [
            (s.get("sub_id"), int(s["line_start"]), int(s.get("line_end") or s["line_start"]))
            for s in (u.get("sub_questions") or [])
            if s.get("line_start") is not None
        ]
        idx.append((uid, ranges, shingles, subs))
    _IDX_CACHE[key] = idx
    return idx


def _decl_unit_for(line_no, unit_idx):
    for uid, ranges, _s, _subs in unit_idx:
        for a, b in ranges:
            if a <= line_no <= b:
                return uid
    return None


def decide_attribution(
    scores: dict,
    declaring_unit: str | None,
    *,
    threshold: int = 3,
    margin: int = 2,
) -> dict:
    """纯决策：5-gram 票数 → 归属三态（cross_unit / same_unit / ambiguous）。

    规则（确定性，不做空间距离/相邻顺序猜测）：
    - 任何单元的票数 < ``threshold`` 不构成候选（复核 F4：单行 2 票不得翻盘）；
    - 无候选 → ``no_evidence``（保持既有 Unit 边界，只记录证据不足）；
    - 最高票并列，或与第二名差距 < ``margin`` → ``ambiguous``（显式未决）；
    - 唯一最高票 == 声明单元 → ``same_unit``；否则 ``cross_unit``。
    """
    ranked = sorted(
        ((score, unit) for unit, score in (scores or {}).items() if score >= threshold),
        key=lambda pair: (-pair[0], str(pair[1])),
    )
    if not ranked:
        return {"status": "no_evidence", "owner": None, "ranked": []}
    top_score, top_unit = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if second_score == top_score:
        return {
            "status": "ambiguous",
            "owner": None,
            "ranked": [(u, s) for s, u in ranked],
            "reason": "tie",
        }
    if second_score and top_score - second_score < margin:
        return {
            "status": "ambiguous",
            "owner": None,
            "ranked": [(u, s) for s, u in ranked],
            "reason": "margin",
        }
    same = bool(
        declaring_unit and str(top_unit).lower() == str(declaring_unit).lower()
    )
    return {
        "status": "same_unit" if same else "cross_unit",
        "owner": top_unit,
        "ranked": [(u, s) for s, u in ranked],
    }


def resolve_owner(asset_id: str, declaring_hint: str, ctx, *, page: int | None = None) -> dict | None:
    """PDF 文本行证据 → 图归属裁决（带证据；不再用 None 混淆"保持"与"无证据"）。

    返回 ``{"status","owner","sub","stem","evidence"}``：
    - ``cross_unit``：唯一最高票指向其它单元（应剔除并回填到 owner）；
    - ``same_unit``：唯一最高票就是声明单元（保持，证据在案）；
    - ``ambiguous``：票数并列/差距不足（显式未决，不得强行归属）；
    - ``no_evidence``：有 PDF 文本层但图行带内无可归属文本（保持既有边界）。

    返回 ``None`` 仅表示证据源不可用（无 bbox / 无 PDF / 无文本层 / 无法识别
    声明单元）——此时调用方不得据此改动归属。
    """
    box = _bbox(asset_id)
    if box is None or not getattr(ctx, "source_pdf_path", ""):
        return None
    x1, y1, x2, y2 = box
    lines = ctx.lines
    unit_idx = _unit_index(ctx.manifest, lines)
    rows = pdf_text_lines(ctx.source_pdf_path)
    pmap = _page_map(lines)
    stem = stem_of(asset_id)
    img_line = next((i for i, ln in enumerate(lines, 1) if stem in ln), None)
    if img_line is None:
        # 图不在 MD（如补裁的题干附件）→ 用 figures[] 证据行定页；无锚定即 fail-safe
        for fu in (ctx.manifest.get("units") or []):
            for fg in (fu.get("figures") or []):
                if stem_of(fg.get("asset_ref") or "") == stem:
                    ev = (fg.get("evidence") or {}).get("line_start")
                    if ev:
                        img_line = int(ev)
                        break
            if img_line:
                break
    if page is None:
        if img_line is None:
            return None
        img_page = pmap.get(img_line, 1) - 1
    else:
        img_page = int(page) - 1
    scale = 2.0
    yb_img = (OCR_H - y2) / scale
    yt_img = (OCR_H - y1) / scale

    error = pdf_error(ctx.source_pdf_path)
    if error:
        return {
            "status": "pdf_unavailable",
            "owner": None,
            "stem": stem,
            "evidence": {"page": img_page + 1, "bbox": list(box), "error": error},
        }
    heights = pdf_page_heights(ctx.source_pdf_path)
    if heights and img_page >= 0:
        if img_page >= len(heights):
            return {
                "status": "unsupported_page_geometry",
                "owner": None,
                "stem": stem,
                "evidence": {"page": img_page + 1, "bbox": list(box),
                             "reason": "page_out_of_range"},
            }
        # OCR 像素坐标按 2x、A4 1684px 高换算为 PDF pt；页高不符即拒绝裁决。
        if abs(heights[img_page] - OCR_H / scale) > 2.0:
            return {
                "status": "unsupported_page_geometry",
                "owner": None,
                "stem": stem,
                "evidence": {"page": img_page + 1, "bbox": list(box),
                             "reason": "page_height_mismatch",
                             "page_height_pt": round(heights[img_page], 2)},
            }
    if not rows:
        return None

    # 声明单元（target_hint "u14"/"u14-material"/"u18/S5"/"S5"）
    decl = (declaring_hint or "").split("/")[0].split("-")[0]
    decl_unit = next((uid for uid, _r, _s, _subs in unit_idx if uid.lower() == decl.lower()), None)
    if decl_unit is None:
        # 裸子问 hint（S5）在多单元下歧义（U17/U18/U19 都有 S5）→ 不可判定则保持
        for u in ctx.manifest.get("units") or []:
            subs_hit = [s for s in (u.get("sub_questions") or []) if s.get("sub_id") == decl]
            if len(subs_hit) == 1:
                decl_unit = u.get("unit_id")
                break
            if len(subs_hit) > 1:
                return None
    if decl_unit is None:
        # 声明单元不可识别（如 explanation_blocks 通道）→ 保持（fail-open）
        return None

    scores: dict = {}
    row_details: list = []
    for pno, yb, yt, norm in rows:
        if pno != img_page or len(norm) < 5:
            continue
        if not (yt >= yb_img - 4 and yb <= yt_img + 4):
            continue
        row_sh = {norm[i:i + 5] for i in range(max(0, len(norm) - 4))}
        row_scores = {}
        for uid, _ranges, shingles, _subs in unit_idx:
            shared = len(row_sh & shingles)
            if shared >= 2:
                row_scores[uid] = shared
                scores[uid] = scores.get(uid, 0) + shared
        if row_scores:
            # text 保留完整行（sub 区间投票需要完整 5-gram）；写日志时再截断
            row_details.append({"y": (round(yb, 1), round(yt, 1)), "text": norm, "votes": row_scores})

    decision = decide_attribution(scores, decl_unit)
    evidence = {
        "page": (page if page is not None else pmap.get(img_line, 1)),
        "bbox": list(box),
        "md_line": img_line,
        "declaring_unit": decl_unit,
        "rows": row_details,
        "scores": {u: s for u, s in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))},
    }
    sub = None
    if decision["status"] == "cross_unit" and decision.get("owner"):
        owner = decision["owner"]
        owner_subs = next(
            (subs for uid, _r, _s, subs in unit_idx if uid == owner), ()
        )
        best_sub, best_score = None, 0
        for sid, a, b in owner_subs:
            sub_sh = set()
            for ln in range(max(1, a), min(len(lines), b) + 1):
                n = _norm(lines[ln - 1])
                for i in range(max(0, len(n) - 4)):
                    sub_sh.add(n[i:i + 5])
            shared = 0
            for detail in row_details:
                row_sh = {detail["text"][i:i + 5] for i in range(max(0, len(detail["text"]) - 4))}
                shared += len(row_sh & sub_sh)
            if shared > best_score:
                best_sub, best_score = sid, shared
        if best_score >= 2:
            sub = best_sub
    return {
        "status": decision["status"],
        "owner": decision.get("owner"),
        "sub": sub,
        "stem": stem,
        "evidence": evidence,
        "ranked": decision.get("ranked", []),
        "reason": decision.get("reason"),
    }


def _layout_page(ctx, stem: str):
    """Layer 2：优先用 Manifest image_layout 的 placement.page（与单图裁决同源）。"""
    try:
        from . import layout_evidence

        layout = layout_evidence.get_layout(ctx)
        placement = layout_evidence.placement_for_stem(layout, stem)
        return placement.get("page") if placement else None
    except Exception:  # noqa: BLE001 — 布局层不可用时退回 MD 分页
        return None


def reattributed_map(ctx) -> dict:
    """预解析：manifest 全量 image_assets 的跨单元归属登记 {stem: {owner, sub}}。

    只登记 ``cross_unit``（有唯一决定性证据）的结果；``ambiguous`` 不进本表，
    由 Mapper 另行显式未决（不得自动归属）。页来源与单图裁决一致
    （优先 placement.page），避免同图两次裁决落在不同页（复核 F7）。
    """
    key = (id(ctx.manifest), getattr(ctx, "source_pdf_path", ""))
    if key in _MAP_CACHE:
        return _MAP_CACHE[key]
    out: dict = {}
    for a in (ctx.manifest.get("image_assets") or []):
        stem = stem_of(a.get("src") or "")
        if not stem:
            continue
        line_no = a.get("line_no")
        decl = _decl_unit_for(line_no, _unit_index(ctx.manifest, ctx.lines)) if line_no else None
        hint = (decl or "").lower()
        res = resolve_owner(stem, hint, ctx, page=_layout_page(ctx, stem))
        if res and res.get("status") == "cross_unit" and res.get("owner"):
            out[stem] = res
    _MAP_CACHE[key] = out
    return out


def reset_cache() -> None:
    _PDF_CACHE.clear()
    _PAGE_CACHE.clear()
    _PDF_ERRORS.clear()
    _IDX_CACHE.clear()
    _MAP_CACHE.clear()


_REF_RE = re.compile(r"如图|下图|图示|如图所示")


def resolve_sub_target(asset_id: str, unit: dict, ctx) -> str | None:
    """AF5/Q16：figure→子问落位纠正（行序权威，applies_to 仅兜底）。

    规则（确定性）：
      1. 图行带与某子问文本行**重叠**（≥2 个 5-gram 共享）→ 该子问；
      2. 否则：≤120pt 内含图引用（如图/图示/下图）的子问文本行 → 该子问；
      3. 否则 applies_to 首项；再无 → None（父级/材料）。
    """
    subs = [
        (s.get("sub_id"), int(s["line_start"]), int(s.get("line_end") or s["line_start"]))
        for s in (unit.get("sub_questions") or [])
        if s.get("line_start") is not None
    ]
    applies = None
    for f in (unit.get("figures") or []):
        if stem_of(f.get("asset_ref") or "") == stem_of(asset_id):
            applies = (f.get("applies_to") or [None])[0]
            break
    box = _bbox(asset_id)
    if box is None or not getattr(ctx, "source_pdf_path", "") or not subs:
        return applies
    lines = ctx.lines
    rows = pdf_text_lines(ctx.source_pdf_path)
    if not rows:
        return applies
    pmap = _page_map(lines)
    stem = stem_of(asset_id)
    img_line = next((i for i, ln in enumerate(lines, 1) if stem in ln), None)
    if img_line is None:
        # 图不在 MD（如补裁的题干附件）→ 用 figures[] 证据行定页；无锚定即 fail-safe
        for fu in (ctx.manifest.get("units") or []):
            for fg in (fu.get("figures") or []):
                if stem_of(fg.get("asset_ref") or "") == stem:
                    ev = (fg.get("evidence") or {}).get("line_start")
                    if ev:
                        img_line = int(ev)
                        break
            if img_line:
                break
    if img_line is None:
        return None
    img_page = pmap.get(img_line, 1) - 1
    # 与 resolve_owner 同一几何前提：OCR 像素 2x/A4；不符则不使用 PDF 证据。
    if pdf_error(ctx.source_pdf_path):
        return applies
    heights = pdf_page_heights(ctx.source_pdf_path)
    if heights and (
        img_page >= len(heights)
        or abs(heights[img_page] - OCR_H / 2.0) > 2.0
    ):
        return applies
    yb_i = (OCR_H - box[3]) / 2.0
    yt_i = (OCR_H - box[1]) / 2.0

    sub_sh = {}
    for sid, a, b in subs:
        sh = set()
        for ln in range(max(1, a), min(len(lines), b) + 1):
            n = _norm(lines[ln - 1])
            for i in range(max(0, len(n) - 4)):
                sh.add(n[i:i + 5])
        sub_sh[sid] = sh

    overlap = {}
    refhit = {}
    for pno, yb, yt, norm in rows:
        if img_page is not None and pno != img_page or len(norm) < 5:
            continue
        dist = max(yb_i - yt, yb - yt_i, 0)
        row_sh = {norm[i:i + 5] for i in range(max(0, len(norm) - 4))}
        for sid, sh in sub_sh.items():
            sc = len(row_sh & sh)
            if sc >= 2:
                if dist == 0:
                    overlap[sid] = overlap.get(sid, 0) + sc
                elif dist <= 120 and _REF_RE.search(norm):
                    prev = refhit.get(sid, (999, 0))
                    refhit[sid] = (dist, prev[1] + sc)
    if overlap:
        return max(overlap.items(), key=lambda kv: kv[1])[0]
    if refhit:
        return min(refhit.items(), key=lambda kv: (kv[1][0], -kv[1][1]))[0]
    return applies
