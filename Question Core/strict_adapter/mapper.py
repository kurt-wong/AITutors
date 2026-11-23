"""Deterministic unit → PreprocessingCandidate mapping.

每一步都可回溯到 Manifest 已声明的行区 / 已裁决口径（`rules.py`）。
禁止：重新识别结构、猜测答案、语义补全、修改 Manifest。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from uuid import UUID

from question_core.contracts.v1 import (
    AnswerCompleteness,
    AnswerEvidenceKind,
    AnswerAssetRef,
    AnswerStatement,
    Asset,
    AssetSlot,
    CandidateCore,
    ChemicalBlock,
    Completeness,
    CompositeAnswer,
    CompositeSubAnswer,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceRecord,
    EvidenceRole,
    EvidenceStatus,
    FillBlankAnswer,
    ImageBlock,
    IngestionIdentity,
    InputHashes,
    Material,
    MaterialRef,
    MathBlock,
    MultiChoiceAnswer,
    OptionItem,
    PreprocessingCandidate,
    PreprocessingSource,
    PreprocessingUnitRef,
    QuestionBody,
    QuestionContent,
    QuestionType,
    SingleChoiceAnswer,
    SlotBinding,
    SourceDocumentRef,
    SourceKind,
    SourceLocator,
    SourceRef,
    StrictAnswerDeclaration,
    TableBlock,
    TableCell,
    TextBlock,
    UnitType,
    Visibility,
    canonical_content_hash,
    derive_idempotency_key,
    new_id,
)

from . import ADAPTER_VERSION, asset_furniture
from . import content_audit
from . import layout_evidence as layout_ev
from .extract import (
    RawTable,
    extract_options,
    extract_range,
    load_source_lines,
    parse_html_table,
    split_sub_segments,
)
from .rules import (
    answer_completeness,
    owner_override_reason,
    question_type,
    resolve_attribution,
)

# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------


@dataclass
class MappingContext:
    lines: list[str]
    manifest: dict
    manifest_path: str
    manifest_name: str
    source_md_path: str
    source_md_name: str
    source_pdf_name: str
    annotated_md_name: str
    manifest_sha: str
    source_md_sha: str
    source_pdf_sha: str
    annotated_md_sha: str
    manifest_bytes: int
    source_md_bytes: int
    source_pdf_bytes: int
    annotated_md_bytes: int
    image_by_line: dict = field(default_factory=dict)
    paper_id: str = ""
    subject: str = ""  # 试卷级显式学科（R1 B2）：缺失即 fail-closed
    run_id: str = ""
    source_pdf_path: str = ""  # AF3/Q14：跨单元图归属守卫需要 PDF 文本层坐标
    ingestion_run_id: UUID = field(default_factory=new_id)
    log_records: list = field(default_factory=list)


@dataclass
class UnitMapping:
    unit_id: str
    candidate: PreprocessingCandidate
    explanation_blocks: tuple
    content_hash: str
    completeness: str
    instance_fields: dict
    state_plan: str  # "approve_publish" | "hold_not_ready"
    log: dict


# ---------------------------------------------------------------------------
# 块原料 → 契约 ContentBlock
# ---------------------------------------------------------------------------


def _furniture_index(ctx: MappingContext) -> dict:
    """装饰图分类上下文（页尺寸 + stem 行内出现数 + sha 重复数），按 ctx 缓存。"""
    idx = getattr(ctx, "_furniture_index", None)
    if idx is None:
        page_size = asset_furniture.discover_page_size(
            source_md_path=ctx.source_md_path, manifest=ctx.manifest
        )
        stem_occ: dict = {}
        for ln in ctx.lines:
            for m in re.finditer(r"img_in_\w+_box_[\d_]+", ln):
                stem = asset_furniture.stem_of(m.group(0))
                stem_occ[stem] = stem_occ.get(stem, 0) + 1
        sha_count: dict = {}
        stem_of_sha: dict = {}
        for a in ctx.manifest.get("image_assets") or []:
            sha = a.get("sha256")
            if sha:
                sha_count[sha] = sha_count.get(sha, 0) + 1
            stem_of_sha[asset_furniture.stem_of(a.get("src") or "")] = sha
        idx = {
            "page_size": page_size,
            "stem_occ": stem_occ,
            "sha_count": sha_count,
            "stem_sha": stem_of_sha,
        }
        ctx._furniture_index = idx
    return idx


def _is_decorative(asset_id: str, ctx: MappingContext) -> bool:
    """页脚装饰图（机构二维码/水印）→ True（AF1 规则；证据不足一律 False）。"""
    idx = _furniture_index(ctx)
    stem = asset_furniture.stem_of(asset_id)
    sha = idx["stem_sha"].get(stem)
    role = asset_furniture.classify_asset(
        stem,
        page_size=idx["page_size"],
        md_occurrence_count=idx["stem_occ"].get(stem, 1),
        same_sha_count=idx["sha_count"].get(sha, 1) if sha else 1,
    )
    return role == asset_furniture.ROLE_DECORATIVE


def _exclude(log: dict | None, asset_id: str, where: str, reason: str) -> None:
    if log is not None:
        log.setdefault("excluded_assets", []).append(
            {"asset_id": asset_id, "where": where, "reason": reason}
        )


_BARE_LATEX_SAFE_RE = re.compile(
    r"\\(?:mathrm|text|mathbf|mathit|frac|sqrt|times|cdot|pi|alpha|beta|gamma|sigma|mu|nu|lambda)"
    r"\s*(?:\{[^{}]*\})?"
    r"(?:\s*[_^]\s*(?:\{[^{}]*\}|[A-Za-z0-9]))?"
    r"(?:\s*[_^]\s*(?:\{[^{}]*\}|[A-Za-z0-9]))?"
)


def _wrap_bare_latex(text: str) -> str:
    """把表格单元格里未包定界符的常见 LaTeX 命令包成 `$...$`。

    Owner QCORE-175：PDF 表格里的 `\\mathrm{Cl}_{2}`、`\\times 10^{-8}` 被 OCR
    写成裸 LaTeX，DT 按普通文本显示原始命令。只包装**已有数学区间之外**的
    白名单命令；`\\chemfig` 等渲染器不支持的命令不包装（避免把错误变成 KaTeX 报错）。
    """
    s = text or ""
    if not s or "\\" not in s:
        return s
    parts = re.split(r"(\$[^$]*\$)", s)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # 已是数学区间
            out.append(part)
            continue
        buf = []
        pos = 0
        for m in _BARE_LATEX_SAFE_RE.finditer(part):
            if m.start() < pos:
                continue
            buf.append(part[pos : m.start()])
            buf.append("$" + m.group(0).strip() + "$")
            pos = m.end()
        buf.append(part[pos:])
        out.append("".join(buf))
    return "".join(out)


def _normalize_bare_latex(text: str) -> str:
    """文本块的 LaTeX 规范化：去公式尾部多余反斜杠 + 包装裸白名单命令。"""
    if not text or "\\" not in text:
        return text
    # `$ 2.5\times 10^{-8}\ $` → 去掉闭区间前孤立反斜杠（OCR 痕迹）。
    s = re.sub(r"(\$[^$\n]*?)\\+\s*(\$)", r"\1\2", text)
    return _wrap_bare_latex(s)


def _raw_table_to_table_block(rt: RawTable, line_start: int, line_end: int) -> TableBlock:
    from .extract import _asset_id_from_src

    def _cell_content(c: dict) -> str:
        text = (
            (c["content"] + " " if c.get("content") else "")
            + " ".join(f"![]({_asset_id_from_src(s)})" for s in (c.get("image_srcs") or []))
        ).strip() or c["content"]
        # Owner QCORE-ADAPTER-MATH-CONTENT-FIX-01：HTML 表格单元格里的 `&gt;` 等实体
        # 必须在解析阶段解码；否则数学区间 `$ … \mathrm{Cl}_{2} &gt; … $` 里的
        # `&` 会让 KaTeX 解析失败并把源码显示给学生（化学 p4 已证）。
        if "&" in text:
            import html

            text = html.unescape(text)
        return text

    cells = tuple(
        TableCell(
            row_index=c["row_index"],
            col_index=c["col_index"],
            # AF3/Q6：表格图片单元格不得丢——以 ![](asset_id) 确定性标记保留在
            # content（展示层解析为图；文本单元格不受影响）。
            content=_cell_content(c),
            rowspan=c["rowspan"],
            colspan=c["colspan"],
            is_header=c["is_header"],
        )
        for c in rt.cells
    )
    return TableBlock(n_rows=rt.n_rows, n_cols=rt.n_cols, cells=cells)


def _is_figure_label(text: str) -> bool:
    """图内标签行（AF3/Q20）：可见文本仅单个 A-H 字母（反应式/装置图内标注）。"""
    lines_ = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    return bool(lines_) and all(re.fullmatch(r"[A-H]", ln) for ln in lines_)


def _attribution_decision(
    asset_id: str,
    target_hint: str,
    ctx: MappingContext,
    log: dict | None = None,
) -> dict | None:
    """Layer 2：布局证据在场的跨单元归属裁决（三态，带证据）。

    契约：**Manifest 没有 image_layout 时不启用 PDF 归属推翻**——既有 Unit
    边界保持不变（零回归）；布局证据在场时才允许用 PDF 文本行证据做
    cross_unit / same_unit / ambiguous 裁决。返回 None 表示无可执行证据。

    证据源不可用（PDF 路径缺失/不存在、页高不支持、解析异常）必须写入
    ``log["layout_attribution_unavailable"]``/``errors``，不得静默退回。
    """
    layout = layout_ev.get_layout(ctx)
    if layout is None:
        return None
    placement = layout_ev.placement_for_stem(layout, asset_id)
    if placement is None:
        # 没有该图的布局 placement（例如仅 MD 引用、OCR 无 image block）：
        # 不拿 PDF 证据单独推翻既有 Unit 边界；显式记入风险，保持原归属。
        if log is not None:
            log.setdefault("layout_attribution_unavailable", []).append(
                {"asset_id": asset_id, "where": target_hint,
                 "reason": "no_layout_placement"}
            )
        return None
    if log is not None and (
        not getattr(ctx, "source_pdf_path", "")
        or not os.path.isfile(ctx.source_pdf_path)
    ):
        log.setdefault("layout_attribution_unavailable", []).append(
            {"asset_id": asset_id, "where": target_hint,
             "reason": "source_pdf_missing"}
        )
        return None
    try:
        from .figure_attribution import resolve_owner

        return resolve_owner(
            asset_id, target_hint, ctx, page=placement.get("page")
        )
    except Exception as exc:  # noqa: BLE001 — 守卫失败不阻断映射（fail-open 保内容）
        if log is not None:
            log.setdefault("layout_attribution_errors", []).append(
                {"asset_id": asset_id, "where": target_hint,
                 "error": type(exc).__name__}
            )
        return None


def _blocks_from_raw(
    raw_blocks: list,
    asset_sink: list,
    ctx: MappingContext,
    target_hint: str,
    log: dict | None = None,
):
    """raw block dicts → contract ContentBlocks；图片同时登记 Asset。

    AF1 装饰图过滤：页脚机构二维码/水印（asset_furniture 判定 decorative）
    不进题面内容块、不登记 figure asset，仅记 log["excluded_assets"]（源图
    文件保留，不物理删除）。
    AF3 追加：图内标签行过滤（Q20）；跨单元图归属守卫（Q14，按页面行位
    判定相邻题的图不得进入本单元）。
    """
    # Empty text placeholders are not content; drop them before contract
    # validation (image-only bodies keep their image block).
    raw_blocks = [
        rb for rb in raw_blocks
        if not (rb.get("kind") == "text" and not (rb.get("text") or "").strip())
    ]
    img_line_flat = {
        n
        for rb in raw_blocks
        if rb.get("kind") == "image"
        for n in (rb.get("line_start"), rb.get("line_end"))
        if isinstance(n, int)
    }

    def _near_image(ls, le):
        return any(
            isinstance(n, int) and any(abs(n - m) <= 6 for m in img_line_flat)
            for n in (ls, le)
        )

    out = []
    for rb in raw_blocks:
        kind = rb["kind"]
        if kind == "text":
            from .extract import _FOOTER_RE

            raw_text = rb["text"] or ""
            raw_lines = raw_text.split("\n")
            kept = [ln for ln in raw_lines if not _FOOTER_RE.match(ln.strip())]
            if len(kept) < len(raw_lines):
                # AF2-E：页脚装饰行（第N页/共M页 / 更多资料 / 交互课程径课堂）
                # 不进正文——与页脚二维码同层过滤，保留审计。
                _exclude(log, f"text-line@{rb.get('line_start')}", target_hint, "footer_text")
            text = "\n".join(kept).strip()
            if not text:
                continue
            if _is_figure_label(text) and _near_image(rb.get("line_start"), rb.get("line_end")):
                # AF3/Q20：反应式/装置图内标签（E/D/B 等）被 OCR 多余识别为正文
                _exclude(log, f"text-line@{rb.get('line_start')}", target_hint, "figure_label")
                continue
            out.append(
                TextBlock(
                    text=text,
                    line_start=rb.get("line_start"),
                    line_end=rb.get("line_end"),
                )
            )
        elif kind == "image":
            if _is_decorative(rb["asset_id"], ctx):
                _exclude(log, rb["asset_id"], target_hint, "footer_furniture")
                continue
            decision = _attribution_decision(rb["asset_id"], target_hint, ctx, log)
            status = (decision or {}).get("status")
            if status == "cross_unit":
                # Layer 2/Q14：布局证据 + PDF 文本行唯一决定性票指向其它单元
                _exclude(log, rb["asset_id"], target_hint, f"cross_unit:{decision['owner']}")
                log.setdefault("figure_reattributed_out", []).append(
                    {
                        "asset_id": rb["asset_id"],
                        "where": target_hint,
                        "owner": decision.get("owner"),
                        "sub": decision.get("sub"),
                        "evidence": _decision_evidence(decision),
                    }
                )
                continue
            if status == "ambiguous":
                # Layer 2：证据并列/不足 → 显式未决，不挂进任何题目内容
                _register_unattributed(
                    rb["asset_id"], asset_sink, ctx, target_hint, log, decision
                )
                continue
            if status in ("same_unit", "no_evidence"):
                log.setdefault("image_attribution", []).append(
                    {
                        "asset_id": rb["asset_id"],
                        "where": target_hint,
                        "status": status,
                        "scores": (decision.get("evidence") or {}).get("scores"),
                        "page": (decision.get("evidence") or {}).get("page"),
                    }
                )
            elif status in ("pdf_unavailable", "unsupported_page_geometry"):
                # 证据源不可用/几何不匹配：不推翻既有边界，但必须显式记录
                log.setdefault("layout_attribution_unavailable", []).append(
                    {
                        "asset_id": rb["asset_id"],
                        "where": target_hint,
                        "status": status,
                        "evidence": _decision_evidence(decision),
                    }
                )
            out.append(
                ImageBlock(
                    asset_id=rb["asset_id"],
                    alt_text=rb.get("alt_text"),
                )
            )
            _register_asset(rb["asset_id"], asset_sink, ctx, target_hint)
        elif kind == "table":
            out.append(
                _raw_table_to_table_block(
                    rb["table"], rb.get("line_start"), rb.get("line_end")
                )
            )
    return out


def _layout_note(placement: dict | None, layout) -> str:
    """Asset.note 中追加布局证据（只记录，不改内容）。"""
    if placement is None:
        return ""
    parts = [
        f"layout={placement['relation']}",
        f"page={placement['page']}",
        f"md_line={placement['md_line']}",
        f"text_line={placement['text_line']}",
        f"bbox={list(placement['bbox'])}",
        "bbox_space=ocr_px",
    ]
    group = layout_ev.group_of_stem(layout, placement.get("stem") or "")
    if group is not None:
        parts.append(f"layout_group={group}")
    risks = layout_ev.risks_for_stem(layout, placement.get("stem") or "")
    if risks:
        parts.append("layout_risks=" + ",".join(risks))
    return "; " + "; ".join(parts)


def _register_asset(
    asset_id: str,
    asset_sink: list,
    ctx: MappingContext,
    target_hint: str,
    *,
    review_only_note: str | None = None,
) -> None:
    if any(a["asset_id"] == asset_id for a in asset_sink):
        return
    if _is_decorative(asset_id, ctx):
        # 防御性：装饰图不应到达登记点（上游 _blocks_from_raw 已过滤）。
        raise ValueError(
            f"decorative asset {asset_id!r} must not be registered as figure "
            f"(target_hint={target_hint!r}); AF1 footer-furniture filter missed it"
        )
    meta = None
    for _, m in ctx.image_by_line.items():
        src_name = m["src"].rsplit("/", 1)[-1]
        if src_name.rsplit(".", 1)[0] == asset_id:
            meta = m
            break
    if meta is None:
        # 行号索引对同行多图只留一席（dict 后写覆盖）；回退全表检索（G4-F2）
        for m in (ctx.manifest.get("image_assets") or []):
            src_name = m["src"].rsplit("/", 1)[-1]
            if src_name.rsplit(".", 1)[0] == asset_id:
                meta = m
                break
    if meta is None:
        raise ValueError(f"image asset {asset_id!r} not found in manifest.image_assets")
    layout = layout_ev.get_layout(ctx)
    placement = layout_ev.placement_for_stem(layout, asset_id) if layout else None
    note = f"src={meta['src']}; line_no={meta['line_no']}; bytes={meta['bytes']}"
    note += _layout_note(placement, layout)
    if review_only_note:
        note += "; " + review_only_note
    asset_sink.append(
        {
            "asset_id": asset_id,
            "asset_role": "figure",
            "storage_path": meta["artifact_path"],
            "content_hash": meta["sha256"],
            "mime_type": "image/jpeg",
            "source_id": ctx.source_md_name,
            "page": placement["page"] if placement else None,
            "bbox": (
                {
                    "x0": placement["bbox"][0],
                    "y0": placement["bbox"][1],
                    "x1": placement["bbox"][2],
                    "y1": placement["bbox"][3],
                }
                if placement
                else None
            ),
            "width": None,
            "height": None,
            "note": note,
        }
    )


def _decision_evidence(decision: dict | None) -> dict:
    """归属裁决的可审计证据（写入 Mapper log / Question evidence）。"""
    if not decision:
        return {}
    ev = decision.get("evidence") or {}
    return {
        "page": ev.get("page"),
        "bbox": ev.get("bbox"),
        "md_line": ev.get("md_line"),
        "declaring_unit": ev.get("declaring_unit"),
        "scores": ev.get("scores") or {},
        "rows": [
            {
                "y": row.get("y"),
                "text": (row.get("text") or "")[:160],
                "votes": row.get("votes"),
            }
            for row in (ev.get("rows") or [])
        ],
        "ranked": decision.get("ranked") or [],
        "reason": decision.get("reason"),
    }


def _register_unattributed(
    asset_id: str,
    asset_sink: list,
    ctx: MappingContext,
    target_hint: str,
    log: dict,
    decision: dict | None,
) -> None:
    """证据不足/并列 → 显式未决：登记审核专用 Asset，不进学生可见内容。

    不删除源图、不猜测归属；Asset.target_path 保持 None，note 标记
    ``OWNERSHIP-AMBIGUOUS``，并写入 log["unattributed_images"] 供人工/复核。
    """
    evidence = _decision_evidence(decision)
    note = (
        "OWNERSHIP-AMBIGUOUS (layout evidence contested/insufficient; "
        f"votes={evidence.get('scores')}; page={evidence.get('page')}; "
        f"bbox={evidence.get('bbox')}); review-only asset, NOT student-visible content"
    )
    before = len(asset_sink)
    _register_asset(asset_id, asset_sink, ctx, target_hint, review_only_note=note)
    if len(asset_sink) > before:
        # 仅对本次新登记的审核资产清空 target_path；已存在的资产不改其归属。
        asset_sink[-1]["target_path"] = None
    else:
        # 同 unit/同 stem 已被其它块登记：早退分支无法把 note 变成"不可见"，
        # 必须显式记录冲突，供复核判断是否泄露（复核 F5）。
        log.setdefault("unattributed_already_registered", []).append(
            {"asset_id": asset_id, "where": target_hint}
        )
    log.setdefault("unattributed_images", []).append(
        {
            "asset_id": asset_id,
            "where": target_hint,
            "status": (decision or {}).get("status"),
            "reason": (decision or {}).get("reason"),
            "evidence": evidence,
        }
    )


def _ordered_stream(blocks, ctx: MappingContext, log: dict, where: str) -> tuple:
    """Layer 2：按 image_layout 的 ``inline`` 关系保持图块与文本的相邻顺序。

    只处理 ``inline``：图必须在命中 ``text_line`` 的文本块之后（OCR 的
    行内图在 MD 中被线性化到段落之后，保持该邻接即为正确阅读顺序）。

    ``block_before`` / ``block_after`` 只作证据记录、**不调整顺序**：
    Layer 1 的 relation 由垂直重叠 + 水平包含判定，无法区分“图在文本上方”
    与“图与文本左右并排（图注/标签在左）”；据此重排会推翻正确的阅读顺序。
    找不到锚定文本块或 ``text_line`` 缺失 → 保持原顺序（不猜测）。
    """
    layout = layout_ev.get_layout(ctx)
    if layout is None or not blocks:
        return tuple(blocks)
    items = list(blocks)
    moves: list = []
    for img in [b for b in items if getattr(b, "kind", "") == "image"]:
        placement = layout_ev.placement_for_stem(layout, getattr(img, "asset_id", ""))
        if not placement or placement.get("text_line") is None:
            continue
        if placement.get("relation") != "inline":
            continue
        text_line = int(placement["text_line"])
        anchor = None
        for cand in items:
            if getattr(cand, "kind", "") != "text":
                continue
            start = getattr(cand, "line_start", None)
            end = getattr(cand, "line_end", None)
            if start is None or end is None:
                continue
            if start <= text_line <= end:
                anchor = cand
                break
        if anchor is None:
            continue
        cur, anc = items.index(img), items.index(anchor)
        if cur >= anc:
            continue
        items.pop(cur)
        items.insert(anc, img)
        moves.append({"where": where, "asset_id": img.asset_id, "relation": "inline",
                      "from": cur, "to": anc, "text_line": text_line})
    if moves:
        log.setdefault("layout_order_moves", []).extend(moves)
    return tuple(items)


def _apply_layout_order(
    bodies, materials, ctx: MappingContext, log: dict, unit_id: str
):
    """对 body/options/materials 的块流套用布局顺序（仅布局证据在场时）。"""
    if layout_ev.get_layout(ctx) is None:
        return bodies, materials
    prefix = (unit_id or "").lower()
    new_bodies = []
    for body in bodies:
        stem_blocks = _ordered_stream(
            body.stem_blocks, ctx, log, f"{prefix}/{body.local_id}/stem"
        )
        options = tuple(
            _rebuild(
                option,
                blocks=_ordered_stream(
                    option.blocks,
                    ctx,
                    log,
                    f"{prefix}/{body.local_id}/option:{option.label}",
                ),
            )
            for option in body.options
        )
        new_bodies.append(
            _rebuild(body, stem_blocks=stem_blocks, options=options)
        )
    new_materials = tuple(
        _rebuild(
            material,
            blocks=_ordered_stream(
                material.blocks,
                ctx,
                log,
                f"{prefix}/material:{material.material_id}",
            ),
        )
        for material in materials
    )
    return tuple(new_bodies), new_materials


def _unit_risk_entries(layout, unit: dict, placements) -> list:
    """该单元的显式风险（只登记，不修复）。

    归属规则（确定性）：
    - risk 有 ``md_line`` → 落在单元声明行区间即归本单元；
    - risk 无 ``md_line``（如 Q18 math_echo_without_image）→ 落在本单元
      某个 placement 的同一页即归本单元（页级证据，只作 review-only 记录）。
    """
    ranges = layout_ev.unit_ranges(unit)
    lines = set()
    for start, end in ranges:
        if isinstance(start, int) and isinstance(end, int):
            lines.update(range(max(1, start), end + 1))
    pages = {p["page"] for p in placements if p.get("page")}
    out = []
    for risk in layout.risks:
        md_line = risk.get("md_line")
        if md_line is not None:
            if md_line in lines:
                out.append(dict(risk))
            continue
        if risk.get("page") in pages:
            out.append(dict(risk))
    return out


def _layout_group_entries(layout, placements) -> list:
    """本单元图涉及的 multi_image_groups（只作分组证据，不生成表格/选项组）。"""
    entries = []
    seen = set()
    for placement in placements:
        stem = placement.get("stem")
        index = layout_ev.group_of_stem(layout, stem) if stem else None
        if index is None or index in seen:
            continue
        if not (0 <= index < len(layout.groups)):
            # 防御：索引越界（畸形 group）时不得让整个 unit 映射失败
            seen.add(index)
            continue
        seen.add(index)
        group = layout.groups[index]
        members = [
            p.get("stem")
            for p in layout.placements
            if p.get("stem") and layout_ev.group_of_stem(layout, p.get("stem")) == index
        ]
        entries.append(
            {
                "group_index": index,
                "page": group.get("page"),
                "lines": list(group.get("lines") or ()),
                "y_band": list(group.get("y_band") or ()),
                "members": members,
                "policy": "group_evidence_only_no_table_inference",
            }
        )
    return entries


def _attach_layout_log(unit: dict, ctx: MappingContext, content, log: dict) -> None:
    """把本单元的布局消费结果写入 Mapper log（可审计，不改内容）。"""
    layout = layout_ev.get_layout(ctx)
    if layout is None:
        log["image_layout"] = None
        return
    placements = layout_ev.placements_for_unit(layout, unit)
    asset_ids = {asset.asset_id for asset in content.assets}
    used = []
    for placement in placements:
        stem = placement.get("stem")
        used.append(
            {
                "asset_id": stem,
                "page": placement["page"],
                "relation": placement["relation"],
                "md_line": placement["md_line"],
                "text_line": placement["text_line"],
                "bbox": list(placement["bbox"]),
                "risks": list(layout_ev.risks_for_stem(layout, stem)),
                "group_index": layout_ev.group_of_stem(layout, stem),
                "in_assets": stem in asset_ids,
            }
        )
    log["image_layout"] = {
        "digest": layout.digest,
        "summary": layout.summary,
        "policy": "layout_evidence_required",
        "placements": used,
        "risks": _unit_risk_entries(layout, unit, placements),
        "groups": _layout_group_entries(layout, placements),
        "reattributed_in": log.get("figure_reattributed_in", []),
        "reattributed_out": log.get("figure_reattributed_out", []),
        "unattributed": log.get("unattributed_images", []),
        "order_moves": [
            m
            for m in log.get("layout_order_moves", [])
            if m.get("where", "").startswith(
                (unit.get("unit_id", "") or "").lower() + "/"
            )
        ],
        "issues": list(layout.issues),
    }


def _layout_evidence_records(unit: dict, ctx: MappingContext, content, log: dict) -> list:
    """布局证据驱动的归属决策 → Question 侧 review-only 证据记录。"""
    layout = layout_ev.get_layout(ctx)
    if layout is None:
        return []
    asset_index = {asset.asset_id: i for i, asset in enumerate(content.assets)}
    recs: list = []

    def _record(entry: dict, note: str, region: str) -> None:
        stem = entry.get("asset_id")
        index = asset_index.get(stem)
        if index is None:
            return
        evidence = entry.get("evidence") or {}
        locators = []
        if evidence.get("page"):
            locators.append(
                SourceLocator(
                    kind="page_region",
                    page=int(evidence["page"]),
                    bbox=tuple(evidence["bbox"]) if evidence.get("bbox") else None,
                    note=f"image_layout page={evidence.get('page')} bbox={evidence.get('bbox')}",
                )
            )
        md_line = evidence.get("md_line")
        if md_line:
            locators.append(
                SourceLocator(kind="line_range", line_start=int(md_line), line_end=int(md_line))
            )
        if not locators:
            return
        recs.append(
            EvidenceRecord(
                target_path=f"/content/assets/{index}",
                evidence_role=EvidenceRole.ASSET,
                source=SourceRef(
                    source_id=ctx.source_pdf_name,
                    source_kind=SourceKind.SOURCE_PDF,
                    content_hash=ctx.source_pdf_sha,
                    locator_uri=ctx.source_pdf_path,
                ),
                locators=tuple(locators),
                value_form="descriptive",
                source_region=region,
                visibility=Visibility.REVIEW_ONLY,
                note=note,
            )
        )

    for entry in log.get("figure_reattributed_in") or []:
        evidence = entry.get("evidence") or {}
        _record(
            entry,
            (
                "cross-unit figure attribution (image_layout + PDF text rows); "
                f"declaring={evidence.get('declaring_unit')} owner={entry.get('owner')} "
                f"sub={entry.get('sub')} votes={evidence.get('scores')} "
                f"md_line={evidence.get('md_line')}"
            ),
            "stem_area",
        )
    for entry in log.get("figure_reattributed_out") or []:
        evidence = entry.get("evidence") or {}
        if not evidence.get("page"):
            continue
        recs.append(
            EvidenceRecord(
                target_path="/content",
                evidence_role=EvidenceRole.ASSET,
                source=SourceRef(
                    source_id=ctx.source_pdf_name,
                    source_kind=SourceKind.SOURCE_PDF,
                    content_hash=ctx.source_pdf_sha,
                    locator_uri=ctx.source_pdf_path,
                ),
                locators=(
                    SourceLocator(
                        kind="page_region",
                        page=int(evidence["page"]),
                        bbox=tuple(evidence["bbox"]) if evidence.get("bbox") else None,
                        note=f"image_layout page={evidence.get('page')} bbox={evidence.get('bbox')}",
                    ),
                ),
                value_form="descriptive",
                source_region="stem_area",
                visibility=Visibility.REVIEW_ONLY,
                note=(
                    "figure excluded from this unit: cross-unit attribution "
                    f"asset_id={entry.get('asset_id')} declaring="
                    f"{evidence.get('declaring_unit')} owner={entry.get('owner')} "
                    f"votes={evidence.get('scores')} md_line={evidence.get('md_line')}"
                ),
            )
        )
    for entry in log.get("unattributed_images") or []:
        evidence = entry.get("evidence") or {}
        _record(
            entry,
            (
                "ownership_ambiguous: layout/PDF evidence contested or insufficient; "
                f"votes={evidence.get('scores')} reason={entry.get('reason')} "
                "asset kept review-only (NOT student-visible content)"
            ),
            "unknown",
        )
    return recs


def _norm_cov(text: str) -> str:
    return "".join((text or "").split())


def _strip_label_marker(text: str) -> str:
    return re.sub(r"^\s*[A-H]\s*[.．、:：]\s*", "", text or "").strip()


def _table_content_missing(
    unit: dict, ctx: MappingContext, bodies, materials, log: dict
) -> list[dict]:
    """G4-R1 R1-03：题面表格内容完整性检查（确定性，fail-closed）。

    口径（Owner：不得整表 MD 总数盲比）：
      1. Manifest 声明的题面表格范围 = stem_lines / options_lines / materials 行区；
      2. 逐行解析其中的 HTML 表格 → 非空单元格清单；
      3. Mapper 输出中对应载体 = 各 body 的 stem_blocks / options blocks /
         materials blocks（text 与 table cells）；
      4. 逐单元格做规范化包含核对（整格文本，或去掉标签前缀后的余文）。
    返回缺失清单（空 = 完整）。
    """
    ranges: list[tuple[int, int]] = []
    for key in ("stem_lines", "options_lines"):
        r = unit.get(key)
        if r and r[0] is not None:
            s = int(r[0])
            e = int(r[1]) if len(r) > 1 and r[1] is not None else s
            ranges.append((s, e))
    for m in unit.get("materials") or []:
        if m.get("line_start") is not None:
            s = int(m["line_start"])
            e = int(m.get("line_end") or s)
            ranges.append((s, e))
    md_cells: list[tuple[int, str]] = []
    for s, e in ranges:
        for ln in range(s, e + 1):
            line = ctx.lines[ln - 1] if 0 < ln <= len(ctx.lines) else ""
            if "<table" not in line:
                continue
            try:
                rt = parse_html_table(line)
            except ValueError:
                continue
            for c in rt.cells:
                txt = (c.get("content") or "").strip()
                if txt:
                    md_cells.append((ln, txt))
    if not md_cells:
        return []

    parts: list[str] = []

    def _collect(b) -> None:
        kind = getattr(b, "kind", "")
        if kind == "text":
            parts.append(getattr(b, "text", "") or "")
        elif kind == "table":
            for cell in b.cells:
                parts.append(cell.content or "")
        elif kind == "chemical":
            parts.append(getattr(b, "formula", "") or "")
        elif kind == "math":
            parts.append(getattr(b, "latex", "") or "")

    for body in bodies:
        for b in body.stem_blocks:
            _collect(b)
        for o in body.options:
            for b in o.blocks:
                _collect(b)
    for mat in materials:
        for b in mat.blocks:
            _collect(b)
    blob = _norm_cov("\n".join(parts))

    missing = []
    for ln, txt in md_cells:
        # Owner QCORE-ADAPTER-MATH-CONTENT-FIX-01：内容侧已按 HTML 解析规则解码
        # 实体（`&gt;`→`>`），源侧比对必须用同一口径，否则会把已正确映射的
        # 单元格误判为"表格内容丢失"（化学 p4）。
        import html as _html

        txt_cmp = _html.unescape(txt)
        n = _norm_cov(txt_cmp)
        if n and n in blob:
            continue
        n2 = _norm_cov(_strip_label_marker(txt_cmp))
        if n2 and n2 in blob:
            continue
        missing.append({"line": ln, "cell": txt[:60]})
    return missing


def _register_answer_asset(asset_ref: str, asset_sink: list, ctx: MappingContext) -> str:
    """答案图片槽位的 canonical asset_id 解析（DSH Phase3 基线 §0.2）。

    `asset_ref` 是无扩展名 stem；唯一命中 manifest.image_assets 的 src stem。
    已登记资产只提升 role 为 answer_image（查询便利），不重复登记。
    """
    stem = asset_ref.rsplit(".", 1)[0]
    # 唯一命中校验（全表检索：行号索引对同行多图只留一席，G4-F2）
    hits = [
        m
        for m in (ctx.manifest.get("image_assets") or [])
        if (m["src"].rsplit("/", 1)[-1]).rsplit(".", 1)[0] == stem
    ]
    if len(hits) != 1:
        raise ValueError(
            f"answer asset_ref {asset_ref!r}: expected exactly one "
            f"image_assets hit for stem {stem!r}, got {len(hits)}"
        )
    for a in asset_sink:
        if a["asset_id"] == stem:
            a["asset_role"] = "answer_image"
            return stem
    _register_asset(stem, asset_sink, ctx, "/answers")
    for a in asset_sink:
        if a["asset_id"] == stem:
            a["asset_role"] = "answer_image"
            a["target_path"] = "/answers"
            a["note"] = (
                (a.get("note") or "")
                + "; ANSWER-VALUE image (AssetSlot slot value; canonical "
                "asset_id = manifest image_assets stem)"
            )
    return stem


# Owner 2026-11-22（D11）：图片答案占位语，不得作为 statement 文本写入。
_ANSWER_PLACEHOLDER_TEXT_RE = re.compile(r"(图片答案|结构简式图片答案|答案图片|见解析|无答案|略)")


def _place_unreferenced_assets(bodies, materials, assets, log: dict):
    """Owner 2026-11-22（P1）：登记了资产但内容里没有 image block → 该题在 DT 上无图。

    仅按证据放置：资产 note 里的 ``line_no=NN`` 必须落在某个 body/material 的
    文本行区间内，才把 ImageBlock 插到该行之前最近的位置。找不到区间则不动
    （登记待复核），不猜测归属。
    """
    placed = set()
    for body in bodies:
        for blk in body.stem_blocks:
            if getattr(blk, "kind", "") == "image":
                placed.add(getattr(blk, "asset_id", None))
        for opt in body.options:
            for blk in opt.blocks:
                if getattr(blk, "kind", "") == "image":
                    placed.add(getattr(blk, "asset_id", None))
    for mat in materials:
        for blk in mat.blocks:
            if getattr(blk, "kind", "") == "image":
                placed.add(getattr(blk, "asset_id", None))
    unplaced = [a for a in assets if getattr(a, "asset_id", None) not in placed]
    if not unplaced:
        return bodies, materials

    def _line_of(asset):
        m = re.search(r"line_no=(\d+)", getattr(asset, "note", "") or "")
        return int(m.group(1)) if m else None

    def _range(blocks):
        starts = [getattr(b, "line_start", None) for b in blocks if getattr(b, "line_start", None)]
        ends = [getattr(b, "line_end", None) or getattr(b, "line_start", None) for b in blocks]
        ends = [e for e in ends if e]
        return (min(starts), max(ends)) if starts and ends else None

    inserted = []
    new_bodies = list(bodies)
    new_materials = list(materials)
    for asset in unplaced:
        ln = _line_of(asset)
        if ln is None:
            continue
        for idx, body in enumerate(new_bodies):
            rng = _range(list(body.stem_blocks) + [b for o in body.options for b in o.blocks])
            if rng and rng[0] <= ln <= rng[1]:
                blocks = list(body.stem_blocks)
                pos = 0
                for i, b in enumerate(blocks):
                    ls = getattr(b, "line_start", None)
                    if ls is not None and ls <= ln:
                        pos = i + 1
                blocks.insert(pos, ImageBlock(asset_id=asset.asset_id, alt_text=None))
                new_bodies[idx] = _rebuild(body, stem_blocks=tuple(blocks))
                inserted.append({"asset": asset.asset_id, "where": f"body:{body.local_id}", "line": ln})
                break
        else:
            for idx, mat in enumerate(new_materials):
                rng = _range(list(mat.blocks))
                if rng and rng[0] <= ln <= rng[1]:
                    blocks = list(mat.blocks)
                    pos = 0
                    for i, b in enumerate(blocks):
                        ls = getattr(b, "line_start", None)
                        if ls is not None and ls <= ln:
                            pos = i + 1
                    blocks.insert(pos, ImageBlock(asset_id=asset.asset_id, alt_text=None))
                    new_materials[idx] = _rebuild(mat, blocks=tuple(blocks))
                    inserted.append({"asset": asset.asset_id, "where": f"material:{mat.material_id}", "line": ln})
                    break
    if inserted:
        log["unreferenced_assets_placed"] = inserted
    missing = [a.asset_id for a in unplaced if a.asset_id not in {i["asset"] for i in inserted}]
    if missing:
        log["unreferenced_assets_unplaced"] = missing
    return tuple(new_bodies), tuple(new_materials)


def _dedupe_identical_blocks(bodies, materials, log: dict):
    """Owner 2026-11-22：同一 Question 内"同源行 + 同文本"的块只保留一次。

    只去重完全相同的 (归一化文本, line_start, line_end)，因此：
      - 不删除 PDF 中本来重复出现的不同源行（同一文本在不同行不算重复）；
      - 不改变内容，只消除同一源行被父体/子体/材料重复消费造成的渲染重复。
    保留文档顺序中的第一次出现。
    """
    seen: set[tuple] = set()
    dropped = []

    def _keep(block) -> bool:
        if getattr(block, "kind", "") != "text":
            return True
        text = (getattr(block, "text", "") or "").strip()
        if not text:
            return True
        key = (re.sub(r"\s+", "", text),)
        if len(key[0]) < 20:
            return True
        if getattr(block, "line_start", None) is None:
            return True
        if key in seen:
            dropped.append(
                {
                    "text": text[:80],
                    "line_start": getattr(block, "line_start", None),
                    "line_end": getattr(block, "line_end", None),
                }
            )
            return False
        seen.add(key)
        return True

    new_bodies = []
    for body in bodies:
        stem_src = tuple(body.stem_blocks)
        stem = tuple(b for b in stem_src if _keep(b))
        # 不得把题面清空：全部被去重时保留原块（交审核，而不是制造空题面）
        if not stem and stem_src:
            stem = stem_src
        # 选项块不参与去重：选项是题目结构的一部分，删除会导致
        # 「manifest option lines not covered」并使选项丢失。
        new_bodies.append(_rebuild(body, stem_blocks=stem))
    new_materials = []
    for mat in materials:
        src = tuple(mat.blocks)
        blocks = tuple(b for b in src if _keep(b))
        if not blocks and src:
            blocks = src
        new_materials.append(_rebuild(mat, blocks=blocks))
    if dropped:
        log["identical_source_blocks_deduped"] = dropped[:20]
    return tuple(new_bodies), tuple(new_materials)


def _essay_content_complete(unit: dict, log: dict) -> bool:
    """Owner 2026-11-22：中英文作文题不要求标准答案/范文。

    判定只看"题目本身是否完整"：题干与写作要求/材料是否存在且有实质内容。
    范文、例文、立意是附加学习材料——存在则照常提取，不存在不得阻断发布。
    """
    texts = []
    for key in ("stem_lines", "material_lines", "questions_lines"):
        rng = unit.get(key)
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            texts.append(str(rng))
    # 题干正文由 mapper 的 stem 抽取负责；此处以"是否有可抽取的题目内容"为准
    blocks = unit.get("stem_text")
    if isinstance(blocks, str) and len(blocks.strip()) >= 20:
        return True
    # Manifest 未内联题干文本时，退化为：存在题目行区或材料行区
    ok = bool(texts)
    log["essay_content_complete"] = ok
    return ok


def _essay_model_text_covered(unit: dict, log: dict) -> bool:
    """Owner D-1 / C2：作文范文条目须被解析区行区覆盖，才算作答参考已保留。

    2026-11-22 修正（Owner C2）：旧实现在 ``answers`` 为空时**空真通过**，
    导致"没有任何可定位答案"的作文被判 complete 并发布。现要求至少存在一个
    带 ``evidence_lines`` 的答案条目，否则视为未覆盖（fail-closed）。
    """
    expl = unit.get("explanation_lines")
    extra = unit.get("extra_lines")
    ranges = [r for r in (expl, extra) if r]
    if not ranges:
        return False
    seen = False
    for item in unit.get("answers") or []:
        lines = item.get("evidence_lines")
        if not lines or lines[0] is None:
            continue
        seen = True
        start = int(lines[0])
        end = int(lines[1]) if len(lines) > 1 and lines[1] is not None else start
        ok = any(r[0] <= start and end <= r[1] for r in ranges)
        if not ok:
            log.setdefault("essay_uncovered_items", []).append(
                {
                    "slot_id": item.get("slot_id"),
                    "evidence_lines": item.get("evidence_lines"),
                }
            )
            return False
    if not seen:
        log["essay_no_located_answer"] = True
        return False
    return True


# ---------------------------------------------------------------------------
# 答案对象（Manifest answers[] 逐条消费；G-04/G-05/G-06）
# ---------------------------------------------------------------------------


def _rebuild(obj, **updates):
    """契约安全重建：ContractModel 禁止 model_copy(update=)，须
    ``Model.model_validate(merged_dict)``（frozen + extra=forbid）。"""
    merged = {**obj.model_dump(mode="json")}
    for k, v in updates.items():
        if isinstance(v, tuple):
            merged[k] = [
                (x.model_dump(mode="json") if hasattr(x, "model_dump") else x)
                for x in v
            ]
        elif hasattr(v, "model_dump"):
            merged[k] = v.model_dump(mode="json")
        else:
            merged[k] = v
    return type(obj).model_validate(merged)


def _norm_label_key(label: str | None) -> str:
    """印刷标签**格式**归一（G3-B B2-3 / P-04）：NFKC 全半角等价 + 去空白。

    保留层级身份：``（2）（ⅰ）``/``(2)(i)`` 与 ``（2）`` 是不同标签，绝不做数字
    前缀跨级归一（旧数字前缀正则把 (2)(i)/(2)(ii) 全撞成 "2"，
    S03 U17 实证错绑）。匹配失败走显式未绑定/失败路径，不猜。"""
    import unicodedata

    if not label:
        return ""
    s = unicodedata.normalize("NFKC", str(label))
    return "".join(s.split())


def _derive_slot_id(item: dict, fallback_index: int, sub_label: str | None) -> str:
    """槽位印刷锚定 id：manifest `slot_id` 优先，否则按约定派生（不猜内容）。"""
    sid = (item.get("slot_id") or "").strip()
    if sid:
        return sid
    if sub_label:
        return f"{sub_label}#1"
    return f"ans#{fallback_index + 1}"


def _item_statement(
    item: dict,
    *,
    statement_id: str,
    sub_label: str | None,
    slot_index: int | None,
    value_text: str,
    locators: tuple,
) -> AnswerStatement:
    form = item.get("form") or "verbatim"
    if form not in ("verbatim", "compressed", "combined", "descriptive"):
        form = "verbatim"
    region = item.get("source_region") or "unknown"
    if region not in (
        "answer_area",
        "answer_table",
        "explanation_area",
        "stem_area",
        "material",
        "unknown",
    ):
        region = "unknown"
    return AnswerStatement(
        statement_id=statement_id,
        value_text=value_text,
        form=form,
        source_region=region,
        sub_label=sub_label,
        slot_index=slot_index,
        locators=locators,
    )


def _item_locators(item: dict) -> tuple:
    lines = item.get("evidence_lines")
    if not lines or lines[0] is None:
        return ()
    return (
        SourceLocator(
            kind="line_range",
            line_start=int(lines[0]),
            line_end=int(lines[1]) if len(lines) > 1 and lines[1] is not None else int(lines[0]),
        ),
    )


def _item_slot_value(
    item: dict,
    asset_resolver,
    trace: dict,
) -> tuple[object, int | None]:
    """answers[] 条目 → 槽位值（str / AssetSlot / None）。返回 (值, 槽位号提示)。"""
    asset_ref = item.get("asset_ref")
    value_text = item.get("value_text")
    if asset_ref:
        asset_id = asset_resolver(asset_ref)
        trace["disposition"] = "image_asset_ref"
        return (
            AssetSlot(
                assets=(
                    AnswerAssetRef(asset_id=asset_id, role="answer_value"),
                )
            ),
            None,
        )
    if value_text is None:
        # 争议空位（D-1 定则）：值=None，全部冲突版本在 statements，不选边。
        trace["disposition"] = "conflict_preserved"
        return (None, None)
    trace["disposition"] = "candidate_answer"
    return (value_text, None)


def _value_target_base(inner_type: str, base: str, j: int) -> str:
    """按 inner 实际类型生成可解析的 JSON Pointer（DSH B1）。

    - fill_blank / multi_step：answer_value 为逐槽元组 → 指向 ``/{j}``；
    - single_choice / multi_choice / numeric / expression / chemical：
      一整值（标量或标签元组）→ 指向值字段本身，不带下标
      （MultiChoice 下标只会指到首个标签，属不精确）。
    """
    if inner_type in ("fill_blank", "multi_step"):
        return f"{base}/{j}"
    return base


def _build_sub_inner(
    sub_items: list[dict],
    qtype: str,
    *,
    answer_stem: str,
    asset_resolver,
    comp_enum: AnswerCompleteness,
    evidence_kind: AnswerEvidenceKind,
    attribution: str,
    override_reason: str | None,
    statements: list,
    slot_bindings: list,
    traces: list,
    unit_id: str,
):
    """一个子问/一个独立题位的 inner TypedAnswer（类型按题型+值形确定性判定）。"""
    notes = []
    if override_reason:
        notes.append(f"owner override (attribution frozen): {override_reason}")
    # QCORE-MISSING-ANSWER-SLOT-01：missing 槽位传递——
    # ① 虚构值守卫：status=missing 条目不得携带 value_text（拒绝静默接受）；
    # ② missing_reason 传递（Contract 非 disputed None 槽的必要条件）；
    # ③ completeness 降档（missing 与 full 矛盾，_missing_reason_axis 亦拒绝）。
    missing_items = []
    for i in sub_items:
        if i.get("status") == "missing" and i.get("value_text") is not None:
            raise ValueError(
                "missing 答案条目不得携带 value_text（虚构答案值不得静默接受）"
            )
        if (i.get("value_text") is None and not i.get("asset_ref")
                and i.get("status") == "missing"):
            missing_items.append(i)
    missing_reason = None
    if missing_items:
        mr = missing_items[0].get("missing_reason")
        missing_reason = (
            mr if mr in ("extraction_gap", "source_not_provided", "policy_withheld")
            else "extraction_gap"
        )
        comp_enum = (
            AnswerCompleteness.ABSENT
            if len(missing_items) == len(sub_items)
            else AnswerCompleteness.PARTIAL
        )
    # 单值多选（题型明确；空值/missing 不进此分支，落 fill_blank）
    if (qtype in ("multi_choice", "multiple_choice") and len(sub_items) == 1
            and (sub_items[0].get("value_text") or "").strip()):
        raw = (sub_items[0].get("value_text") or "").strip()
        labels = tuple(
            ch for ch in raw.upper() if "A" <= ch <= "H"
        ) or (raw,)
        ans = MultiChoiceAnswer(
            answer_value=labels,
            answer_display=raw,
            evidence_kind=evidence_kind,
            completeness=comp_enum,
            grading_rule="set",
            attribution=attribution,
            statements=tuple(statements),
            slot_bindings=tuple(slot_bindings),
            note="; ".join(notes) or None,
        )
        return ans
    # 单值单选（值形 = 单个 A–H 标签；空值/missing 不进此分支，落 fill_blank）
    if len(sub_items) == 1:
        raw = (sub_items[0].get("value_text") or "").strip()
        if raw and (qtype == "single_choice" or (
            len(raw) == 1 and "A" <= raw.upper() <= "H"
        )):
            ans = SingleChoiceAnswer(
                answer_value=raw.upper() if len(raw) == 1 else raw,
                answer_display=raw,
                evidence_kind=evidence_kind,
                completeness=comp_enum,
                grading_rule="exact",
                attribution=attribution,
                statements=tuple(statements),
                slot_bindings=tuple(slot_bindings),
                note="; ".join(notes) or None,
            )
            return ans
    # 多槽/文本 → fill_blank 槽位联合（str | AssetSlot | None）
    values = []
    for idx, item in enumerate(sub_items):
        trace = traces[sub_items[idx]["_trace_idx"]]
        val, _ = _item_slot_value(item, asset_resolver, trace)
        values.append(val)
    fb_statements = tuple(
        s
        for s in statements
        if s.slot_index is not None or len(sub_items) > 1
    ) or tuple(statements)
    ans = FillBlankAnswer(
        answer_value=tuple(values),
        answer_display=None,
        evidence_kind=evidence_kind,
        completeness=comp_enum,
        grading_rule="manual",
        attribution=attribution,
        answer_conflict=(
            "source_conflict"
            # QCORE-MISSING-ANSWER-SLOT-01：仅非 missing 的无值槽触发争议语义；
            # missing 槽位保持 answer_conflict=none（缺失≠争议）。
            if any(v is None and sub_items[idx].get("status") != "missing"
                   for idx, v in enumerate(values))
            else "none"
        ),
        missing_reason=missing_reason,
        statements=fb_statements,
        slot_bindings=tuple(slot_bindings),
        note="; ".join(notes) or None,
    )
    return ans


_INNER_MARK_RE = re.compile(
    r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]"
    r"|(?<!\w)\(\s*(?:i{1,3}|iv|v|vi{0,3})\s*\)"
)
_TOP_LINE_RE = re.compile(
    r"^\s*(?:[（(]\s*(?P<par>\d{1,2})\s*[）)]|(?P<num>\d{1,3})\s*[.．、])"
)


def _split_by(regex, text: str) -> list[str]:
    """按标记切分，丢弃标记本身；返回非空片段（保持原文）。"""
    out = []
    for part in regex.split(text or ""):
        p = (part or "").strip()
        if p:
            out.append(p)
    return out


_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _canon_mark(label: str) -> str:
    """`（１）`/`(1)`/`16.` → 纯 ASCII 数字串（用于标记对齐，不用于展示）。"""
    s = (label or "").strip().translate(_FW_DIGITS)
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"[.．、:：]\s*$", "", s)
    m = re.search(r"[0-9]{1,3}", s)
    return m.group(0) if m else ""


_TOP_MARK_RE2 = re.compile(
    r"(?m)^[ \t]*\d{1,3}[.．、]|[（(]\s*\d{1,2}\s*[）)]"
)


def _parse_answer_region(text: str) -> dict[str, list[str]]:
    """把答案区解析成 {顶层题号: [层内片段...]}。

    顶层标记 = 行首 `16.` 或任意位置的 `（1）/(3)`（答案区实际形态）；
    行内小数（`0.04`）不会命中。层内标记 = `①` / `(i)`。
    """
    marks = list(_TOP_MARK_RE2.finditer(text or ""))
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for i, m in enumerate(marks):
        key = _canon_mark(m.group(0))
        if not key:
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = (text[m.end() : end] or "").strip()
        if not body:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        inner = _split_by(_INNER_MARK_RE, body) or [body]
        groups[key].extend(inner)
    return groups


def _slot_top(slot_id: str) -> str:
    """`(3)(i)#1` / `(1)#2` / `10#1` → 顶层题号（"3"/"1"/"10"）。"""
    sid = (slot_id or "").strip()
    m = re.match(r"[（(]\s*(\d{1,2})\s*[）)]", sid.replace("（", "(").replace("）", ")"))
    if m:
        return m.group(1)
    m = re.match(r"(\d{1,2})", sid)
    return m.group(1) if m else ""


def _slot_index(slot_id: str) -> int:
    m = re.search(r"#(\d{1,2})$", (slot_id or "").strip())
    return int(m.group(1)) if m else 1


def _backfill_answer_values(unit: dict, prepared: list, source_lines, log: dict) -> bool:
    """把答案区原文按**顶层题号 + 组内印刷顺序**绑定到答案槽（纯复制，不推断）。

    与"全局位置绑定"不同：每个槽位先用 `slot_id` 顶层题号定位到答案区的对应
    题号组，再在**组内**按印刷顺序绑定；只有组内片段数与组内槽位数相等（或槽位
    自身序号在片段数内）时才绑定。跨组串位因此不会发生。数量不匹配即保持原状。
    """
    empties = [
        it
        for it in prepared
        if not (it.get("value_text") or "").strip()
        and not it.get("asset_ref")
        # 争议槽（disputed/conflict）不得被回填覆盖：保留冲突版本，交冲突机制处理。
        and (it.get("status") in (None, "missing", "resolved"))
    ]
    if not empties:
        return False
    ev = (unit.get("answer_evidence") or {}).get("value")
    r = unit.get("answer_lines") or ((unit.get("answer_evidence") or {}).get("lines"))
    text = ""
    if r and source_lines:
        try:
            text = "\n".join(source_lines[int(r[0]) - 1 : int(r[1])])
        except (TypeError, ValueError, IndexError):
            text = ""
    if not text and isinstance(ev, str):
        text = ev
    text = (text or "").replace("【答案】", "").replace("【解析】", "").strip()
    if not text:
        return False

    groups = _parse_answer_region(text)
    if not groups:
        log.setdefault("answer_region_backfill_skipped", []).append({"reason": "no_markers"})
        return False

    # 按顶层题号分槽；组内顺序 = 槽位在 prepared 中的先后（同一小问的印刷顺序）。
    by_top: dict[str, list[dict]] = {}
    for it in prepared:
        top = _slot_top(str(it.get("slot_id") or ""))
        if top:
            by_top.setdefault(top, []).append(it)

    filled = 0
    restored = 0
    mismatched = []
    for top, slots in by_top.items():
        segs = groups.get(top) or []
        if not segs:
            continue
        if len(segs) != len(slots):
            # 组内片段数与槽位数不一致 → 该组不做位置绑定（fail-closed）。
            mismatched.append({"top": top, "slots": len(slots), "segments": len(segs)})
            continue
        for it, seg in zip(slots, segs):
            if (it.get("value_text") or "").strip() or it.get("asset_ref"):
                continue
            value = re.sub(r"^\d{1,3}\s*[.．、]\s*", "", seg).strip()
            value = re.sub(r"^[.．、:：]\s*", "", value).strip()
            if not value:
                continue
            # 回填值必须是答案区原文的可溯源子串（去空白比较），否则不写入。
            if re.sub(r"\s+", "", value) not in re.sub(r"\s+", "", text):
                log.setdefault("answer_backfill_ungrounded_skipped", []).append(value[:40])
                continue
            it["value_text"] = value
            if it.get("status") == "missing":
                it["status"] = "resolved"
                it["missing_reason"] = None
                restored += 1
            filled += 1
    if mismatched:
        log.setdefault("answer_region_backfill_skipped", []).extend(mismatched)
    if filled:
        log.setdefault("answer_region_backfill", []).append(
            {
                "filled": filled,
                "restored_missing": restored,
                "source": "answer_lines" if r else "answer_evidence.value",
                "policy": "top-marker group + within-group printed order (segment count must equal slot count)",
            }
        )
    return filled > 0


def _build_answers(
    unit: dict,
    attribution: str,
    log: dict,
    *,
    sub_id_map: dict | None = None,
    asset_resolver=None,
    override_reason: str | None = None,
    source_lines: list | None = None,
) -> tuple:
    # sub_id_map 语义（G3-B B2-3 / P-04）：同时含 sub_id→local_id（sub_ref 首选）
    # 与完整标签格式键→local_id（回落）；数字前缀归一已废除。
    """Manifest `answers[]` → TypedAnswer（G-04/G-05/G-06，Phase 3）。

    - composite_unit → 1 个 CompositeAnswer（每 sub_label 一个 CompositeSubAnswer）
    - standalone → 1 个答案对象（单选/多选/按槽位 fill_blank）
    - essay（Owner D-1）→ 不产 TypedAnswer；范文进 Explanation
    - 争议空位 value=None 仅在 answer_conflict=source_conflict 且
      statements 持有全部冲突版本时合法（契约 FillBlankAnswer 校验）
    """
    unit_id = unit["unit_id"]
    qtype = question_type(unit)
    comp = AnswerCompleteness(answer_completeness(unit))
    kind = (unit.get("answer_evidence") or {}).get("type") or "absent"
    try:
        evidence_kind = AnswerEvidenceKind(kind)
    except ValueError:
        evidence_kind = AnswerEvidenceKind.ABSENT
    items = unit.get("answers") or []
    traces: list = []
    log.setdefault("answers_trace", [])

    # ---- essay（D-1：范文仅作 Explanation，不作 TypedAnswer，不判缺答案）----
    if qtype == "essay":
        for idx, item in enumerate(items):
            log["answers_trace"].append(
                {
                    "item_index": idx,
                    "sub_label": item.get("sub_label"),
                    "slot_id": item.get("slot_id"),
                    "value_text": item.get("value_text"),
                    "asset_ref": item.get("asset_ref"),
                    "disposition": "explanation_per_owner_d1",
                    "target": "Explanation(model text) + Evidence",
                }
            )
        log["answers"] = []
        log["answers_policy"] = (
            "essay (Owner D-1): model text kept in Explanation with source "
            "regions/evidence; no TypedAnswer; NOT treated as a missing answer"
        )
        return ()

    if not items:
        # 旧形态 manifest（无 answers[]）：内容不丢、不伪造槽位（G-04）。
        value = (unit.get("answer_evidence") or {}).get("value")
        if not value or attribution == "not_attributable":
            log["answers"] = []
            log["answers_policy"] = (
                "no manifest answers[] and no declared value: no TypedAnswer"
            )
            return ()
        pseudo_item = {
            "value_text": value,
            "form": "combined",
            "source_region": "unknown",
            "_trace_idx": 0,
        }
        stmt = _item_statement(
            pseudo_item,
            statement_id=f"{unit_id.lower()}-st1",
            sub_label=None,
            slot_index=None,
            value_text=value,
            locators=(),
        )
        inner = _build_sub_inner(
            [pseudo_item],
            qtype,
            answer_stem=unit_id,
            asset_resolver=lambda ref: ref,
            comp_enum=comp,
            evidence_kind=evidence_kind,
            # 单值题整值即该题答案（归属确定）；多空整串无法逐空绑定时
            # 保守标 partially_attributed（G-07 归属轴，不冒充已核实）。
            attribution=(
                "attributed"
                if qtype in ("single_choice", "multi_choice", "multiple_choice")
                else "partially_attributed"
            ),
            override_reason=override_reason,
            statements=[stmt],
            slot_bindings=(),
            traces=[{"disposition": "candidate_answer"}],
            unit_id=unit_id,
        )
        log["answers"] = [
            {
                "answer_type": inner.answer_type,
                "completeness": comp.value,
            }
        ]
        log["answers_policy"] = (
            "legacy manifest without answers[]: declared value preserved as "
            "one slot/choice (no '；' split, no fabricated per-blank claims)"
        )
        log["answers_trace"].append(
            {
                "item_index": 0,
                "sub_label": None,
                "slot_id": "ans#1",
                "value_text": value,
                "disposition": "candidate_answer",
                "target": _value_target_base(
                    inner.answer_type, "/answers/0/answer_value", 0
                ),
            }
        )
        return (inner,)

    # ---- 逐条预处理：statements / 槽位值 / trace ----
    prepared: list[dict] = []
    for idx, item in enumerate(items):
        trace = {
            "item_index": idx,
            "sub_label": item.get("sub_label"),
            "slot_id": item.get("slot_id"),
            "value_text": item.get("value_text"),
            "asset_ref": item.get("asset_ref"),
            "form": item.get("form"),
            "source_region": item.get("source_region"),
            "evidence_lines": item.get("evidence_lines"),
            "status": item.get("status"),
        }
        traces.append(trace)
        prepared.append({**item, "_trace_idx": idx})

    # Owner 2026-11-22（答案证据）：Manifest 的 `answers[].value` 常为空，真实答案
    # 只存在于答案区文本（answer_lines / answer_evidence.value）。按印刷标记把
    # 答案区原文逐段绑定到空槽——纯复制，不推断、不补写；无法等量对齐则不填。
    _backfilled = _backfill_answer_values(unit, prepared, source_lines, log)
    _has_missing = any(it.get("status") == "missing" for it in prepared)
    _has_disputed = any(it.get("status") not in (None, "missing", "resolved") for it in prepared)
    _all_valued = all(
        (it.get("value_text") or "").strip() or it.get("asset_ref") for it in prepared
    )
    _PROOF_MARKS = ("见解析", "证明见解析", "答案见解析", "证明过程见解析")
    _has_proof_answer = any(
        any(mark in (it.get("value_text") or "") for mark in _PROOF_MARKS) for it in prepared
    )
    # Owner 2026-11-19/§6.9：答案 note 显式记录 OCR 失真的单元属于 OCR_SOURCE_ERROR，
    # 不得被任何"答案已齐"规则自动升为 complete（Admission 保持 pending）。
    _ocr_flagged = any(
        "ocr" in str(it.get("note") or "").lower() for it in prepared
    )
    # 升级条件（均要求无缺失/无争议槽、且未被 OCR 失真标记）：
    #   1) 本轮从答案区逐字补到了值；
    #   2) 答案是"见解析/证明见解析"（Owner 裁决：这就是合法答案）；
    #   3) Manifest 全部槽位已 resolved 且有值 —— 答案文本已由 Manifest 给出。
    if (
        (
            _backfilled
            or _has_proof_answer
            # Manifest 自身说 unknown（无法判定）且槽位已全部 resolved 有值 → 可判定为完整；
            # Manifest 明确说 partial 的单元不在此列（那是它的正向判断）。
            or (comp == AnswerCompleteness.UNKNOWN and _all_valued)
        )
        and _all_valued
        and not _has_missing
        and not _has_disputed
        and not _ocr_flagged
        and comp != AnswerCompleteness.FULL
    ):
        comp = AnswerCompleteness.FULL
        log["answer_completeness_backfilled"] = {
            "from": (
                "answer_region_verbatim"
                if _backfilled
                else ("proof_marker_owner_ruling" if _has_proof_answer else "all_slots_resolved")
            ),
            "slots": len(prepared),
        }

    # ---- 分组：composite 按唯一小问身份（answers[].sub_ref）；无 sub_ref 时
    # 回落完整标签（格式键）；standalone 为单对象。印刷标签（sub_label）仅作
    # 展示，不得作绑定主键——同题不同层级可有相同印刷标签（G4-R1 R1-04）。
    is_composite = (unit.get("unit_type") == "composite_question")
    groups: list[tuple[str | None, list[dict]]] = []
    seen: dict[str, int] = {}
    for it in prepared:
        key = it.get("sub_ref") or it.get("sub_label")
        if key in seen:
            groups[seen[key]][1].append(it)
        else:
            seen[key] = len(groups)
            groups.append((key, [it]))

    asset_resolver = asset_resolver or (lambda ref: ref)

    # 槽位级冲突版本预取：构造 FillBlank 时即挂上（契约 None 槽位合法性
    # 要求"该空位的 statements 持有全部冲突版本"，校验发生在构造期）。
    conflict_versions: dict[tuple[str, str], list[dict]] = {}
    conflict_versions_total = 0
    for c in unit.get("answer_conflicts") or []:
        sid = (c.get("slot_id") or "").strip()
        if not sid:
            continue
        vs = [
            v
            for v in (c.get("versions") or [])
            if (v.get("value_text") or "").strip()
        ]
        if vs:
            conflict_versions[(_norm_label_key(c.get("sub_label")), sid)] = vs
            conflict_versions_total += 1

    def _conflict_version_statement(
        v: dict, vi: int, total: int, sub_label, slot_index: int, unit_id: str
    ) -> AnswerStatement:
        lines = v.get("evidence_lines")
        locators = ()
        if lines and lines[0] is not None:
            locators = (
                SourceLocator(
                    kind="line_range",
                    line_start=int(lines[0]),
                    line_end=int(lines[1])
                    if len(lines) > 1 and lines[1] is not None
                    else int(lines[0]),
                ),
            )
        region = v.get("source_region") or "unknown"
        return AnswerStatement(
            statement_id=f"{unit_id.lower()}-cf-s{slot_index}v{vi + 1}",
            value_text=(v.get("value_text") or "").strip(),
            form="verbatim",
            source_region=region
            if region
            in (
                "answer_area",
                "answer_table",
                "explanation_area",
                "stem_area",
                "material",
                "unknown",
            )
            else "unknown",
            sub_label=sub_label,
            slot_index=slot_index,
            locators=locators,
            note=(
                f"source_conflict version {vi + 1}/{total} (not adjudicated)"
            ),
        )

    def _attribution_for(sub_items: list[dict]) -> str:
        if override_reason:
            return "disputed"
        if any((i.get("status") == "disputed") for i in sub_items):
            return "disputed"
        if any(
            i.get("value_text") is None and not i.get("asset_ref")
            and i.get("status") != "missing"
            for i in sub_items
        ):
            return "disputed"
        # QCORE-MISSING-ANSWER-SLOT-01：status=missing 的无值槽位不是争议，
        # 落 partially_attributed（"存在未定槽位"硬信号）。
        if any(
            i.get("value_text") is None and not i.get("asset_ref")
            and i.get("status") == "missing"
            for i in sub_items
        ):
            return "partially_attributed"
        if attribution == "not_attributable":
            return "partially_attributed"
        return "attributed"

    answers_out = []
    if is_composite:
        subs = []
        for sub_index, (sub_key, sub_items) in enumerate(groups):
            # 展示标签 = 印刷标签（保留原文）；绑定身份 = sub_key（sub_ref 优先）
            sub_label = next(
                (i.get("sub_label") for i in sub_items if i.get("sub_label")), sub_key
            )
            # P-04 身份顺序：① answers[].sub_ref ② 完整标签（格式等价）③ 显式未绑定
            _sub_ref = next(
                (i.get("sub_ref") for i in sub_items if i.get("sub_ref")), None
            )
            if _sub_ref:
                _body_id = (sub_id_map or {}).get(_sub_ref)
                if _body_id is None:
                    raise ValueError(
                        f"{unit_id}: input_contract_gap — answers[].sub_ref {_sub_ref!r} "
                        "unresolved (explicit id; no fallback)"
                    )
            elif sub_label:
                _body_id = (sub_id_map or {}).get(_norm_label_key(sub_label))
                if _body_id is None:
                    log.setdefault("unresolved_sub_bindings", []).append(
                        {"sub_label": sub_label, "reason": "full-label match miss after "
                         "format-only norm (no numeric-prefix collapse); pending"}
                    )
            else:
                _body_id = None
            sub_statements = []
            slot_bindings = []
            for j, it in enumerate(sub_items):
                slot_id = _derive_slot_id(it, j, sub_label)
                stmt_value = it.get("value_text")
                # Owner 2026-11-22（D11）：图片答案由 AssetSlot 表达；不得把
                # 「图片答案 / 结构简式图片答案」这类占位语写进 statement。
                if it.get("asset_ref") and (
                    stmt_value is None
                    or _ANSWER_PLACEHOLDER_TEXT_RE.search((stmt_value or "").strip() or "")
                ):
                    stmt_value = None
                elif stmt_value is None and it.get("asset_ref"):
                    stmt_value = it.get("note")
                if stmt_value is not None:
                    sub_statements.append(
                        _item_statement(
                            it,
                            statement_id=f"{unit_id.lower()}-st{it['_trace_idx'] + 1}",
                            sub_label=sub_label,
                            slot_index=j,
                            value_text=stmt_value,
                            locators=_item_locators(it),
                        )
                    )
                ckey = (
                    _norm_label_key(sub_label),
                    (slot_id or "").strip(),
                )
                if ckey[1] and ckey in conflict_versions:
                    vs = conflict_versions[ckey]
                    for vi, v in enumerate(vs):
                        sub_statements.append(
                            _conflict_version_statement(
                                v, vi, len(vs), sub_label, j, unit_id
                            )
                        )
                slot_bindings.append(
                    SlotBinding(
                        slot_index=j,
                        slot_id=slot_id,
                        sub_label=sub_label,
                        sub_body_local_id=_body_id,
                    )
                )
            sub_attr = _attribution_for(sub_items)
            inner = _build_sub_inner(
                sub_items,
                qtype,
                answer_stem=unit_id,
                asset_resolver=asset_resolver,
                comp_enum=comp,
                evidence_kind=evidence_kind,
                attribution=sub_attr,
                override_reason=override_reason,
                statements=sub_statements,
                slot_bindings=slot_bindings,
                traces=traces,
                unit_id=unit_id,
            )
            for j, it in enumerate(sub_items):
                t = traces[it["_trace_idx"]]
                if "target" not in t:
                    t["target"] = _value_target_base(
                        inner.answer_type,
                        f"/answers/0/answer_value/{sub_index}"
                        f"/answer_value/answer_value",
                        j,
                    )
                if "disposition" not in t:
                    t["disposition"] = (
                        "composite_sub_slot"
                        if sub_label
                        else "candidate_answer"
                    )
            subs.append(
                CompositeSubAnswer(
                    sub_label=sub_label or "ans",
                    sub_body_local_id=_body_id,
                    answer_value=inner,
                    evidence_kind=evidence_kind,
                    completeness=comp,
                    attribution=sub_attr,
                    note=(
                        f"owner override (attribution frozen): {override_reason}"
                        if override_reason
                        else None
                    ),
                )
            )
        composite = CompositeAnswer(
            answer_value=tuple(subs),
            evidence_kind=evidence_kind,
            completeness=comp,
            attribution=_attribution_for(prepared),
            note=(
                "CompositeAnswer: one sub-answer per manifest sub_label; "
                "slot identity from answers[].slot_id (G-04/G-06)"
                + (
                    f"; owner override (attribution frozen): {override_reason}"
                    if override_reason
                    else ""
                )
            ),
        )
        answers_out = [composite]
    else:
        # standalone：1 个答案对象；多条目按槽位展开（Q7/Q14 形态）
        statements = []
        slot_bindings = []
        for j, it in enumerate(prepared):
            slot_id = _derive_slot_id(it, j, it.get("sub_label"))
            stmt_value = it.get("value_text")
            if stmt_value is None and it.get("asset_ref"):
                stmt_value = (
                    it.get("note") or f"（图片答案：{it.get('asset_ref')}）"
                )
            if stmt_value is not None:
                statements.append(
                    _item_statement(
                        it,
                        statement_id=f"{unit_id.lower()}-st{j + 1}",
                        sub_label=it.get("sub_label"),
                        slot_index=j if len(prepared) > 1 or qtype not in (
                            "single_choice", "multi_choice", "multiple_choice"
                        ) else None,
                        value_text=stmt_value,
                        locators=_item_locators(it),
                    )
                )
            ckey = (
                _norm_label_key(it.get("sub_label")),
                (slot_id or "").strip(),
            )
            if ckey[1] and ckey in conflict_versions:
                vs = conflict_versions[ckey]
                for vi, v in enumerate(vs):
                    statements.append(
                        _conflict_version_statement(
                            v,
                            vi,
                            len(vs),
                            it.get("sub_label"),
                            j,
                            unit_id,
                        )
                    )
            slot_bindings.append(
                SlotBinding(
                    slot_index=j,
                    slot_id=slot_id,
                    sub_label=it.get("sub_label"),
                )
            )
        attr = _attribution_for(prepared)
        if qtype == "single_choice" and len(prepared) == 1:
            inner = _build_sub_inner(
                prepared,
                qtype,
                answer_stem=unit_id,
                asset_resolver=asset_resolver,
                comp_enum=comp,
                evidence_kind=evidence_kind,
                attribution=attr,
                override_reason=override_reason,
                statements=statements,
                slot_bindings=slot_bindings,
                traces=traces,
                unit_id=unit_id,
            )
            # 单值题不需要槽位绑定
            if isinstance(inner, SingleChoiceAnswer):
                inner = _rebuild(inner, slot_bindings=())
            if isinstance(inner, MultiChoiceAnswer):
                inner = _rebuild(inner, slot_bindings=())
            answers_out = [inner]
        else:
            inner = _build_sub_inner(
                prepared,
                qtype,
                answer_stem=unit_id,
                asset_resolver=asset_resolver,
                comp_enum=comp,
                evidence_kind=evidence_kind,
                attribution=attr,
                override_reason=override_reason,
                statements=statements,
                slot_bindings=slot_bindings,
                traces=traces,
                unit_id=unit_id,
            )
            answers_out = [inner]
        for j, it in enumerate(prepared):
            t = traces[it["_trace_idx"]]
            if "target" not in t:
                t["target"] = _value_target_base(
                    inner.answer_type, "/answers/0/answer_value", j
                )
            if "disposition" not in t:
                t["disposition"] = (
                    "candidate_answer"
                    if len(prepared) == 1
                    else "answer_slot"
                )

    for t in traces:
        log["answers_trace"].append(t)
    log["answers"] = [
        {
            "answer_type": a.answer_type,
            "attribution": a.attribution,
            "completeness": a.completeness.value,
        }
        for a in answers_out
    ]
    log["answers_policy"] = (
        "manifest answers[] consumed item-by-item (G-04): slot identity from "
        "slot_id/sub_label; statements carry verbatim/source_region; "
        "disputed blanks keep None + all conflict versions (no side pick)"
    )
    return tuple(answers_out)


# ---------------------------------------------------------------------------
# 证据
# ---------------------------------------------------------------------------


def _verbatim(lines: list[str], start: int | None, end: int | None) -> str:
    if start is None or end is None:
        return ""
    return "\n".join(
        lines[i - 1] if i - 1 < len(lines) else "" for i in range(start, end + 1)
    )


def manifest_answer_value_pointer(unit: dict, ctx: MappingContext) -> str:
    """本 Unit 的 Manifest `answer_evidence.value` 的 JSON Pointer（RFC 6901）。"""
    idx = None
    for i, u in enumerate(ctx.manifest.get("units", [])):
        if u.get("unit_id") == unit.get("unit_id"):
            idx = i
            break
    if idx is None:
        raise ValueError(f"unit {unit.get('unit_id')!r} not found in manifest units")
    return f"/units/{idx}/answer_evidence/value"


def _answer_region_images(
    unit: dict, ctx: MappingContext, asset_sink: list, log: dict
) -> list:
    """答案区图片（C-CLOSURE C1）：注册为审核专用 Asset + ASSET 证据记录。

    这些图片属答案证据（P-3 区），不是题干配图：不放入任何学生可见内容块；
    Asset.target_path=/answers 表明答案归属；证据 visibility=review_only。
    """
    recs: list = []
    ar = unit.get("answer_lines")
    if not ar:
        log["answer_region_images"] = []
        return recs
    res = extract_range(ctx.lines, ar[0], ar[1])
    for img in res.images:
        if _is_decorative(img.asset_id, ctx):
            _exclude(log, img.asset_id, "/answers", "footer_furniture")
            continue
        _register_asset(img.asset_id, asset_sink, ctx, "/answers")
        for a in asset_sink:
            if a["asset_id"] == img.asset_id:
                a["target_path"] = "/answers"
                a["note"] = (
                    (a.get("note") or "")
                    + "; ANSWER-AREA figure (answer evidence, review-only; "
                    "NOT student-visible content)"
                )
                break
        raw_line = (
            ctx.lines[img.line_no - 1] if img.line_no - 1 < len(ctx.lines) else ""
        )
        recs.append(
            EvidenceRecord(
                target_path="/answers",
                evidence_role=EvidenceRole.ASSET,
                source=SourceRef(
                    source_id=ctx.source_md_name,
                    source_kind=SourceKind.SOURCE_MARKDOWN,
                    content_hash=ctx.source_md_sha,
                    locator_uri=ctx.source_md_path,
                ),
                locators=(
                    SourceLocator(
                        kind="line_range",
                        line_start=img.line_no,
                        line_end=img.line_no,
                    ),
                ),
                raw_value=raw_line,
                evidence_status=EvidenceStatus.ACTIVE,
                visibility=Visibility.REVIEW_ONLY,
                note=(
                    f"answer figure of {unit['unit_id']} (answer_lines region "
                    f"L{img.line_no}); review-only evidence asset "
                    f"asset_id={img.asset_id}; associated to /answers "
                    "(C-CLOSURE C1)"
                ),
            )
        )
    log["answer_region_images"] = [
        {
            "asset_id": r.note.split("asset_id=")[1].split(";")[0]
            if "asset_id=" in (r.note or "")
            else None,
            "line_start": r.locators[0].line_start,
            "raw_value_len": len(r.raw_value or ""),
            "visibility": r.visibility.value,
            "evidence_role": r.evidence_role.value,
            "target_path": r.target_path,
        }
        for r in recs
    ]
    return recs


def _annotate_conflicts(
    answers: tuple,
    unit: dict,
    unit_id: str,
    log: dict,
) -> tuple[tuple, list[dict]]:
    """answer_conflicts[] → 冲突语句 + source_conflict 标记（D-2：不选边）。

    槽位级冲突的版本语句挂在承载该槽位的 FillBlankAnswer 上（契约
    None 槽位合法性校验要求）；子问级/单元级冲突挂在对应子问/顶层答案上。
    返回 (更新后的 answers, 冲突规格列表[供证据登记])。
    """
    import re as _re

    conflicts = unit.get("answer_conflicts") or []
    if not conflicts:
        return answers, []

    def _key(label):
        if not label:
            return ""
        m = _re.search(r"(\d+)", str(label))
        return m.group(1) if m else str(label).strip().upper()

    specs: list[dict] = []
    # 按 (顶层答案, 子问标签) 定位 owner；用 model_copy 回写。
    mutable = list(answers)

    def _patch_top(update):
        if len(mutable) == 1:
            mutable[0] = _rebuild(mutable[0], **update)

    def _find_sub(ans, sub_label):
        if getattr(ans, "answer_type", None) != "composite":
            return None
        for i, sub in enumerate(ans.answer_value):
            if _key(sub.sub_label) == _key(sub_label):
                return i, sub
        return None

    for c in conflicts:
        sub_label = c.get("sub_label")
        slot_id = c.get("slot_id")
        versions = c.get("versions") or []
        stmts = []
        for vi, v in enumerate(versions):
            vtext = (v.get("value_text") or "").strip()
            if not vtext:
                log.setdefault("conflicts_skipped_versions", []).append(
                    {"sub_label": sub_label, "slot_id": slot_id, "version": vi + 1}
                )
                continue
            lines = v.get("evidence_lines")
            locators = ()
            if lines and lines[0] is not None:
                locators = (
                    SourceLocator(
                        kind="line_range",
                        line_start=int(lines[0]),
                        line_end=int(lines[1])
                        if len(lines) > 1 and lines[1] is not None
                        else int(lines[0]),
                    ),
                )
            region = v.get("source_region") or "unknown"
            stmts.append(
                AnswerStatement(
                    statement_id=f"{unit_id.lower()}-cf{len(specs) + 1}v{vi + 1}",
                    value_text=v.get("value_text") or "",
                    form="verbatim",
                    source_region=region
                    if region
                    in (
                        "answer_area",
                        "answer_table",
                        "explanation_area",
                        "stem_area",
                        "material",
                        "unknown",
                    )
                    else "unknown",
                    sub_label=sub_label,
                    locators=locators,
                    note=f"source_conflict version {vi + 1}/{len(versions)} (not adjudicated)",
                )
            )

        target = "/answers/0"
        owner_kind = "top"
        slot_index = None
        found = None
        if sub_label is not None and len(mutable) == 1:
            found = _find_sub(mutable[0], sub_label)
            if found is not None:
                si, sub = found
                target = f"/answers/0/answer_value/{si}"
                owner_kind = "sub"
                if slot_id:
                    inner = sub.answer_value
                    if getattr(inner, "answer_type", None) == "fill_blank":
                        for b in inner.slot_bindings:
                            if b.slot_id == slot_id:
                                slot_index = b.slot_index
                                break
                        if slot_index is not None:
                            target = (
                                f"/answers/0/answer_value/{si}"
                                f"/answer_value/answer_value/{slot_index}"
                            )
                            owner_kind = "slot"
        # 语句挂载 + 标记
        if owner_kind == "slot" and slot_index is not None and found is not None:
            si, sub = found
            inner = sub.answer_value
            # 槽位级冲突语句已在 _build_answers 构造期挂到对应槽位
            # （None 槽位合法性要求构造时在案）；此处只补标记。
            new_inner = _rebuild(
                inner,
                answer_conflict="source_conflict",
            )
            new_sub = _rebuild(
                sub,
                answer_value=new_inner,
                answer_conflict="source_conflict",
            )
            top = mutable[0]
            subs = list(top.answer_value)
            subs[si] = new_sub
            mutable[0] = _rebuild(
                top,
                answer_value=tuple(subs),
                answer_conflict="source_conflict",
            )
        elif owner_kind == "sub" and found is not None:
            si, sub = found
            new_sub = _rebuild(
                sub,
                statements=tuple(sub.statements) + tuple(stmts),
                answer_conflict="source_conflict",
            )
            top = mutable[0]
            subs = list(top.answer_value)
            subs[si] = new_sub
            mutable[0] = _rebuild(
                top,
                answer_value=tuple(subs),
                answer_conflict="source_conflict",
            )
        else:
            top = mutable[0]
            _patch_top(
                {
                    "statements": tuple(top.statements) + tuple(stmts),
                    "answer_conflict": "source_conflict",
                }
            )

        specs.append(
            {
                "target_path": target,
                "statements": stmts,
                "versions": versions,
                "sub_label": sub_label,
                "slot_id": slot_id,
                "owner_kind": owner_kind,
            }
        )
        log.setdefault("conflicts", []).append(
            {
                "sub_label": sub_label,
                "slot_id": slot_id,
                "versions": [
                    {
                        "value_text": v.get("value_text"),
                        "source_region": v.get("source_region"),
                        "evidence_lines": v.get("evidence_lines"),
                    }
                    for v in versions
                ],
                "target": target,
                "origin": "source_internal",
            }
        )
    return tuple(mutable), specs


def _build_evidence(
    unit: dict,
    answers: tuple,
    ctx: MappingContext,
    attribution: str,
    log: dict,
    extra_records: tuple = (),
    *,
    conflict_specs: list | None = None,
    override_reason: str | None = None,
) -> EvidenceBundle:
    ev = unit.get("answer_evidence") or {}
    ev_lines = ev.get("lines") or unit.get("answer_lines")
    value = ev.get("value")
    recs = list(extra_records)
    conflicts_out: list[EvidenceConflict] = []

    target = "/answers/0/answer_value" if answers else "/answers"
    note_parts = [f"attribution={attribution}"]
    normalized = None
    if attribution != "not_attributable":
        normalized = value
    elif value and override_reason is None:
        # 值在源文中可见，但按契约 kind 映射不可声明为正式答案。
        normalized = value
        note_parts.append(
            "value observed in source/manifest but not declared as answer "
            "per contract kind_to_attribution"
        )

    if ev_lines:
        recs.append(
            EvidenceRecord(
                target_path=target,
                evidence_role=EvidenceRole.ANSWER,
                source=SourceRef(
                    source_id=ctx.source_md_name,
                    source_kind=SourceKind.SOURCE_MARKDOWN,
                    content_hash=ctx.source_md_sha,
                    locator_uri=ctx.source_md_path,
                ),
                locators=(
                    SourceLocator(
                        kind="line_range",
                        line_start=ev_lines[0],
                        line_end=ev_lines[1],
                    ),
                ),
                raw_value=_verbatim(ctx.lines, ev_lines[0], ev_lines[1]),
                normalized_value=normalized,
                value_form="verbatim",
                source_region="answer_area"
                if (unit.get("answer_evidence") or {}).get("type") != "inline_in_explanation"
                else "explanation_area",
                evidence_status=EvidenceStatus.ACTIVE,
                note="; ".join(note_parts),
            )
        )

    # P-1/P-3：Manifest value 保留为独立 DISPUTED 记录，不得伪装为源文证据。
    # C-CLOSURE C2：source_kind=preprocessing_manifest 的记录必须用 Manifest
    # JSON Pointer 定位。纸卷作用域（Phase 3 G-05/F）：仅命中 override 的
    # paper_id/unit_id 生效，禁止裸 unit_id 跨卷误伤（语文 Q10/Q12 同名）。
    if override_reason and value:
        recs.append(
            EvidenceRecord(
                target_path=target,
                evidence_role=EvidenceRole.ANSWER,
                source=SourceRef(
                    source_id=ctx.manifest_name,
                    source_kind=SourceKind.PREPROCESSING_MANIFEST,
                    content_hash=ctx.manifest_sha,
                    locator_uri=ctx.manifest_path,
                ),
                locators=(
                    SourceLocator(
                        kind="json_pointer",
                        pointer=manifest_answer_value_pointer(unit, ctx),
                    ),
                ),
                raw_value=value,
                value_form="compressed",
                source_region="answer_area",
                evidence_status=EvidenceStatus.DISPUTED,
                note=(
                    "manifest declared_value retained for audit but DISPUTED: "
                    + override_reason
                    + "; locator = manifest JSON Pointer (C-CLOSURE C2)"
                ),
            )
        )

    # 源内冲突版本：每版本一条 ACTIVE 记录（两造并存，不裁定），登记
    # EvidenceConflict(conflict_origin="source_internal")——按 G-08 不阻断。
    for spec in conflict_specs or []:
        version_ids = []
        for vi, v in enumerate(spec["versions"]):
            lines = v.get("evidence_lines")
            locators = ()
            if lines and lines[0] is not None:
                locators = (
                    SourceLocator(
                        kind="line_range",
                        line_start=int(lines[0]),
                        line_end=int(lines[1])
                        if len(lines) > 1 and lines[1] is not None
                        else int(lines[0]),
                    ),
                )
            region = v.get("source_region") or "unknown"
            rec = EvidenceRecord(
                target_path=spec["target_path"],
                evidence_role=EvidenceRole.ANSWER,
                source=SourceRef(
                    source_id=ctx.source_md_name,
                    source_kind=SourceKind.SOURCE_MARKDOWN,
                    content_hash=ctx.source_md_sha,
                    locator_uri=ctx.source_md_path,
                ),
                locators=locators,
                raw_value=v.get("value_text") or "",
                value_form="verbatim",
                source_region=region
                if region
                in (
                    "answer_area",
                    "answer_table",
                    "explanation_area",
                    "stem_area",
                    "material",
                    "unknown",
                )
                else "unknown",
                evidence_status=EvidenceStatus.ACTIVE,
                note=(
                    f"source_conflict version {vi + 1}/{len(spec['versions'])}; "
                    f"sub={spec['sub_label']} slot={spec['slot_id']}; "
                    "both/all versions preserved, never adjudicated (D-2)"
                ),
            )
            recs.append(rec)
            version_ids.append(rec.evidence_id)
        if len(version_ids) >= 2:
            conflicts_out.append(
                EvidenceConflict(
                    target_path=spec["target_path"],
                    evidence_ids=tuple(version_ids),
                    description=(
                        f"source-internal answer conflict at sub="
                        f"{spec['sub_label']} slot={spec['slot_id']} "
                        f"({len(version_ids)} versions with own regions/lines)"
                    ),
                    is_critical=True,
                    conflict_origin="source_internal",
                )
            )

    expl = unit.get("explanation_lines")
    if expl:
        recs.append(
            EvidenceRecord(
                target_path="/explanation_blocks",
                evidence_role=EvidenceRole.EXPLANATION,
                source=SourceRef(
                    source_id=ctx.source_md_name,
                    source_kind=SourceKind.SOURCE_MARKDOWN,
                    content_hash=ctx.source_md_sha,
                    locator_uri=ctx.source_md_path,
                ),
                locators=(
                    SourceLocator(
                        kind="line_range", line_start=expl[0], line_end=expl[1]
                    ),
                ),
                value_form="verbatim",
                source_region="explanation_area",
                evidence_status=EvidenceStatus.ACTIVE,
                note="explanation region (content preserved in Revision.explanation_blocks)",
            )
        )

    log["evidence"] = [
        {
            "role": r.evidence_role.value,
            "source_kind": r.source.source_kind.value,
            "locators": [
                {"line_start": l.line_start, "line_end": l.line_end} for l in r.locators
            ],
            "raw_value_len": len(r.raw_value or ""),
            "normalized_value": r.normalized_value,
            "value_form": r.value_form,
            "source_region": r.source_region,
            "status": r.evidence_status.value,
            "note": r.note,
        }
        for r in recs
    ]
    log["conflicts_registered"] = [
        {
            "target_path": c.target_path,
            "origin": c.conflict_origin,
            "versions": len(c.evidence_ids),
        }
        for c in conflicts_out
    ]
    return EvidenceBundle(records=tuple(recs), conflicts=tuple(conflicts_out))


# ---------------------------------------------------------------------------
# 内容（bodies / materials / assets）
# ---------------------------------------------------------------------------


def _dedupe_option_text(
    opt_raw: list, log: dict, where: str, lines: list | None = None, region=None
) -> list:
    """同一源行被两个选项声明同时认领时的通用保护。

    分两种情况，以**源行里是否真有该标签标记**为准：
    - 源行中没有该标签标记 → Manifest 多声明了一个选项（幻想项），丢弃该声明，
      还原 PDF 真实选项集；
    - 源行中确有该标签（映射错位）→ 保留声明但置空文本（fail-closed），
      由内容审计判缺失，避免把同一行展示两次。
    """
    seen: dict[tuple, str] = {}
    out: list = []
    dropped: list = []
    for o in opt_raw:
        if not isinstance(o, dict):
            out.append(o)
            continue
        text = o.get("text")
        if not isinstance(text, str):
            text = "".join(
                (b.get("text") or "") for b in (o.get("blocks") or []) if isinstance(b, dict)
            )
        text = text.strip()
        key = (o.get("line_start"), re.sub(r"\s+", "", text))
        if text and len(key[1]) >= 8 and key in seen:
            label = str(o.get("label") or "")
            marker_in_source = False
            has_region = bool(lines) and bool(region) and len(region or ()) == 2
            if has_region:
                _pat = re.compile(rf"^\s*{re.escape(label)}\s*[.．、:：]") if label else None
                if _pat:
                    for _ln in range(max(1, int(region[0])), min(len(lines), int(region[1])) + 1):
                        if _pat.match(lines[_ln - 1]):
                            marker_in_source = True
                            break
            dropped.append(
                {
                    "label": o.get("label"),
                    "same_as": seen[key],
                    "line": o.get("line_start"),
                    "marker_in_source": marker_in_source,
                    "region_evidence": has_region,
                }
            )
            if not has_region:
                # 没有可核验的选项区证据：不改动内容（保留原声明，重复由门禁拦截）。
                out.append(o)
                continue
            if not marker_in_source:
                # 源文档中不存在该选项标记：Manifest 幻想项，丢弃声明。
                continue
            _ln = o.get("line_start")
            o = dict(
                o,
                text="",
                blocks=[{"kind": "text", "text": "", "line_start": _ln, "line_end": _ln}],
                shared_tables=o.get("shared_tables") or [],
            )
        elif text:
            seen[key] = str(o.get("label"))
        out.append(o)
    if dropped:
        log.setdefault("option_duplicate_text_dropped", []).extend(
            [dict(d, where=where) for d in dropped]
        )
    return out


def _gap_ranges(qrange: tuple[int, int], covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """行区间差集：qrange 去掉 covered 后的有序间隙（AF2-C 父子去重复用）。"""
    covered = sorted(covered)
    lead: list[tuple[int, int]] = []
    cur = qrange[0]
    for s, e in covered:
        s2, e2 = max(s, qrange[0]), min(e, qrange[1])
        if e2 < cur:
            continue
        if s2 > cur:
            lead.append((cur, s2 - 1))
        cur = max(cur, e2 + 1)
    if cur <= qrange[1]:
        lead.append((cur, qrange[1]))
    return lead


def _composite_bodies_and_materials(
    unit: dict, ctx: MappingContext, asset_sink: list, log: dict
):
    """composite 内容构建（G3-B B2-2 / P-07）：只消费 Manifest 结构。

    - 结构来源 = ``sub_questions[]`` 树（实体/层级/区间/归属），直接构建
      QuestionBody 父子（parent_question_ref/sub_question_ids）；
    - ``materials[]`` 材料实体逐条消费，小问按 ``materials_used[]`` 逐小问挂载
      （替换旧「统一挂载」）；``material_lines`` 只是兼容投影，不作消费源；
    - 旧 manifest 缺 ``sub_questions`` → 显式 ``input_contract_gap`` 失败，
      **不启用正则兜底**（split_sub_segments 已降 audit-only）。
    """
    unit_id = unit["unit_id"]
    base = unit_id.lower()
    if unit.get("extra_image_blocks"):
        # 本能力仅支持 standalone 题面定点注入；composite 形态 fail closed，
        # 不静默忽略声明（QCORE-STUDENT-FIDELITY-IMAGE-REPAIR-01）。
        raise ValueError(
            f"extra_image_blocks not supported on composite units (unit {unit_id!r})"
        )
    qrange = unit.get("questions_lines")
    if not qrange:
        raise ValueError(f"{unit_id}: composite unit without questions_lines")

    subs_decl = unit.get("sub_questions")
    if not subs_decl:
        raise ValueError(
            f"{unit_id}: input_contract_gap — composite unit without "
            "sub_questions (G3 new-structure contract; regex fallback retired)"
        )

    # ---- materials[]（M:N 实体）----
    # M1/M2: material ranges may overlap sub-question ranges in the frozen
    # manifest.  A sub-question line is owned by that sub-question, never by
    # the shared material; trim only the overlapping source ranges.
    _decl_sub_ranges = [
        (int(sq["line_start"]), int(sq["line_end"]))
        for sq in (subs_decl or [])
        if isinstance(sq.get("line_start"), int) and isinstance(sq.get("line_end"), int)
    ]
    materials = []
    mat_by_id = {}
    for mi, m in enumerate(unit.get("materials") or []):
        if not isinstance(m, dict):
            raise ValueError(f"{unit_id}: materials[{mi}] not an object (input_contract_gap)")
        mid = (m.get("material_id") or f"{base}-m{mi + 1}")
        if mid in mat_by_id:
            raise ValueError(f"{unit_id}: duplicate material_id {mid!r} (input_contract_gap)")
        s, e = m.get("line_start"), m.get("line_end")
        if not (isinstance(s, int) and isinstance(e, int) and not isinstance(s, bool)
                and not isinstance(e, bool) and 1 <= s <= e):
            raise ValueError(
                f"{unit_id}: material {mid!r} illegal lines {s!r},{e!r} (input_contract_gap)"
            )
        if _decl_sub_ranges:
            _mraw_blocks = []
            for _a, _b in _gap_ranges((s, e), _decl_sub_ranges):
                _mraw_blocks.extend(extract_range(ctx.lines, _a, _b).blocks)
            if _mraw_blocks != list(extract_range(ctx.lines, s, e).blocks):
                log.setdefault("material_sub_overlap_trimmed", []).append(
                    {"material_id": mid, "line_start": s, "line_end": e}
                )
            # A material whose whole range is covered by sub-question point
            # ranges (e.g. cloze passage) must not become empty; keep the
            # original material in that case rather than dropping the passage.
            mres_blocks = _mraw_blocks or extract_range(ctx.lines, s, e).blocks
            # Owner 2026-11-22（40 未发布根因）：材料块流曾把区间外内容也带进来
            # （M01 声明 93-95 却含 98/103/108），导致同一题注在多个材料里重复。
            # 归属边界以声明区间为准：区间外块由父级/其他材料负责，不在此复制。
            _before = len(mres_blocks)
            mres_blocks = [
                b
                for b in mres_blocks
                if not isinstance(b.get("line_start"), int)
                or s <= int(b["line_start"]) <= e
            ]
            if len(mres_blocks) != _before:
                log.setdefault("material_blocks_clamped", []).append(
                    {"material_id": mid, "line_start": s, "line_end": e,
                     "dropped": _before - len(mres_blocks)}
                )
        else:
            mres_blocks = extract_range(ctx.lines, s, e).blocks
        mres = type("_MR", (), {"blocks": mres_blocks})()
        mraw = _merge_extras_and_figures(
            unit, ctx, mres.blocks, log=log, where=f"material:{mid}", target=f"{base}-material"
        )
        mblocks = _blocks_from_raw(mraw, asset_sink, ctx, f"{base}-material", log)
        mat = Material(
            material_id=mid,
            title=m.get("label"),
            blocks=tuple(mblocks),
            line_start=s,
            line_end=e,
            note="material entity from manifest.materials[] (verbatim; M:N via materials_used)",
        )
        materials.append(mat)
        mat_by_id[mid] = mat

    # ---- M3: composite options_lines -> an explicit options body ----
    # Manifest already declares the option region.  Keep the region out of the
    # parent stem, parse labels deterministically, and emit the options once in
    # a body sorted at the option region's source line.
    _opt_region = unit.get("options_lines")
    _opt_raw = []
    _opt_specs = []
    if (ctx.subject or "").strip() == "英语" and _opt_region and len(_opt_region) == 2:
        from .extract import OptionSpec, extract_options
        _os, _oe = int(_opt_region[0]), int(_opt_region[1])
        _found = {}
        for _ln in range(max(1, _os), min(len(ctx.lines), _oe) + 1):
            _m = re.match(r"\s*([A-H])\s*[.．、:：]", ctx.lines[_ln - 1])
            if _m and _m.group(1) not in _found:
                _found[_m.group(1)] = _ln
        _labels = sorted(_found)
        if _labels:
            _starts = sorted(_found.values())
            for _lb in _labels:
                _st = _found[_lb]
                _nxt = min((x for x in _starts if x > _st), default=_oe + 1)
                _opt_specs.append(OptionSpec(label=_lb, start=_st, end=_nxt - 1))
            # Owner 2026-11-22（D2）：最后一个选项不得延伸到下一小问/下一题的
            # 标记行；否则选项会把后续小问的题干与选项一起吞进来（学生端可见重复）。
            _clamped = _clamp_option_spans(
                [{"label": s.label, "start": s.start, "end": s.end} for s in _opt_specs],
                ctx.lines,
                log,
                unit.get("unit_id"),
            )
            _opt_specs = [
                OptionSpec(label=c["label"], start=c["start"], end=c["end"]) for c in _clamped
            ]
            _opt_raw, _shared_tables = extract_options(ctx.lines, _opt_specs, region=(_os, _oe))
            _opt_raw = _dedupe_option_text(_opt_raw, log, unit.get("unit_id"), ctx.lines, unit.get("options_lines"))
            if _opt_raw:
                _covered = set()
                for _o in _opt_raw:
                    _a = _o.get("line_start") or _os
                    _b = _o.get("line_end") or _a
                    _covered.update(range(int(_a), int(_b) + 1))
                _expected = set()
                for _sp in _opt_specs:
                    _expected.update(range(int(_sp.start), int(_sp.end) + 1))
                if not _expected.issubset(_covered):
                    # Not all declared option lines are covered by parsed
                    # options; keep the original parent-stem behaviour rather
                    # than dropping source lines (fail-open for content).
                    log["composite_option_mode"] = "fallback_parent_stem"
                    _opt_raw = []
                else:
                    log["composite_option_mode"] = "options_body"
            else:
                log["composite_option_mode"] = "none"

    # ---- sub_questions 树 → 实体/层级 ----
    sub_by_id: dict[str, dict] = {}
    sub_order: list[str] = []
    for si, sq in enumerate(subs_decl):
        if not isinstance(sq, dict):
            raise ValueError(f"{unit_id}: sub_questions[{si}] not an object (input_contract_gap)")
        sid = sq.get("sub_id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{unit_id}: sub_questions[{si}] missing sub_id (input_contract_gap)")
        if sid in sub_by_id:
            raise ValueError(f"{unit_id}: duplicate sub_id {sid!r} (input_contract_gap)")
        s, e = sq.get("line_start"), sq.get("line_end")
        if not (isinstance(s, int) and isinstance(e, int) and not isinstance(s, bool)
                and not isinstance(e, bool) and 1 <= s <= e):
            raise ValueError(
                f"{unit_id}/{sid}: illegal sub lines {s!r},{e!r} (input_contract_gap)"
            )
        sub_by_id[sid] = sq
        sub_order.append(sid)

    children: dict[str, list[str]] = {sid: [] for sid in sub_order}
    roots: list[str] = []
    for sid in sub_order:
        par = sub_by_id[sid].get("parent_sub_id")
        if par is None:
            roots.append(sid)
        elif par not in sub_by_id:
            raise ValueError(
                f"{unit_id}/{sid}: parent_sub_id {par!r} unresolved (input_contract_gap)"
            )
        else:
            children[par].append(sid)

    # ---- 父体 stem = questions_lines −（小问区 ∪ 材料区）的最大间隙 ----
    covered = [(sub_by_id[s]["line_start"], sub_by_id[s]["line_end"]) for s in sub_order]
    covered += [(m.line_start, m.line_end) for m in materials]
    if _opt_raw and _opt_region and len(_opt_region) == 2:
        covered += [(int(_opt_region[0]), int(_opt_region[1]))]
    lead = _gap_ranges((qrange[0], qrange[1]), covered)

    parent_blocks = []
    lead_raw: list = []
    for a, b in lead:
        r = extract_range(ctx.lines, a, b)
        lead_raw.extend(r.blocks)
    # M1: consume only source lines actually assigned to parent/material/sub.
    _consumed_lines = set()
    for _b in lead_raw:
        _a = _b.get("line_start")
        _z = _b.get("line_end") or _a
        if isinstance(_a, int):
            _consumed_lines.update(range(_a, (int(_z) if isinstance(_z, int) else _a) + 1))
    for _m in materials:
        _consumed_lines.update(range(int(_m.line_start), int(_m.line_end) + 1))
    for _s, _e in _decl_sub_ranges:
        _consumed_lines.update(range(int(_s), int(_e) + 1))
    lead_raw = _merge_extras_and_figures(
        unit, ctx, lead_raw, log=log, where="root", target=f"{base}",
        extra_text_dedup=True, extra_text_cutoff=qrange[1],
        consumed_lines=_consumed_lines,
    )
    parent_blocks = _blocks_from_raw(lead_raw, asset_sink, ctx, f"{base}", log)
    if not parent_blocks:
        parent_blocks = [TextBlock(text="", line_start=qrange[0], line_end=qrange[0])]

    # ---- audit-only：正则切点 vs 声明切点（不参与任何映射/兜底）----
    try:
        _segs, _leads = split_sub_segments(ctx.lines, qrange[0], qrange[1], [])
        log["sub_segment_audit"] = {
            "note": "audit-only (P-07): regex cut points vs manifest declarations; "
                    "NOT used for mapping",
            "regex_segments": [
                {"label": lb, "line_start": s, "line_end": e} for lb, s, e in _segs
            ],
            "declared_segments": [
                {"sub_id": sid,
                 "line_start": sub_by_id[sid]["line_start"],
                 "line_end": sub_by_id[sid]["line_end"]}
                for sid in sub_order
            ],
        }
    except Exception as exc:  # 审计失败不影响映射
        log["sub_segment_audit"] = {"note": "audit-only failed", "error": str(exc)}

    parent = QuestionBody(
        local_id=base,
        question_type=QuestionType(question_type(unit)),
        printed_number=unit.get("printed_number"),
        stem_blocks=tuple(parent_blocks),
        options=(),
        material_ids=tuple(m.material_id for m in materials),
        parent_question_ref=None,
        sub_question_ids=tuple(roots),
        unit_type=UnitType(unit.get("unit_type") or "composite_question"),
        note="composite parent; structure from manifest.sub_questions tree (verbatim)",
    )

    bodies = [parent]
    for sid in sub_order:
        sq = sub_by_id[sid]
        s, e = sq["line_start"], sq["line_end"]
        # AF2-C 父子去重：带子问的节点只保留「自身行区 − 子问行区」的间隙，
        # 子文本由子 body 各自渲染一次（此前父级吞子行区导致重复渲染）。
        kid_ranges = [
            (sub_by_id[k]["line_start"], sub_by_id[k]["line_end"])
            for k in children.get(sid, ())
        ]
        # 共享材料与选项由各自载体渲染一次；小问题面不得重复消费这些源行
        # （否则完形/语法填空的整段passage会在每个小问里重复，学生端可见重复）。
        excl_ranges = list(kid_ranges) + [
            (int(m.line_start), int(m.line_end)) for m in materials
        ]
        if _opt_raw and _opt_region and len(_opt_region) == 2:
            excl_ranges.append((int(_opt_region[0]), int(_opt_region[1])))
        if excl_ranges:
            raw_r: list = []
            for a, b in _gap_ranges((s, e), excl_ranges):
                raw_r.extend(extract_range(ctx.lines, a, b).blocks)
            # 排除共享材料/选项后若小问题面为空，说明该小问只有共享内容；
            # 退回未排除抽取（fail-open），避免制造空题面。
            if not any((x.get("text") or "").strip() for x in raw_r):
                if children.get(sid):
                    # 父小问的区间被其子问完全覆盖（202-204 = 202 ∪ 204）：
                    # 父级只保留结构占位，正文由子问渲染一次，避免父子重复。
                    raw_r = [{"kind": "text", "text": "", "line_start": s, "line_end": s}]
                    log.setdefault("child_parent_placeholders", []).append(sid)
                else:
                    raw_r = extract_range(ctx.lines, s, e).blocks
        else:
            raw_r = extract_range(ctx.lines, s, e).blocks
        sraw = _merge_extras_and_figures(
            unit, ctx, raw_r, log=log, where=sid, target=sid
        )
        sraw = _inject_reattributed(unit, ctx, sraw, log=log, where=sid, target=sid)
        # Owner 2026-11-22（DELIVERY-04 · 共享材料）：小问若完全落在共享材料内，
        # 其正文就是材料本身——正文只由 material 渲染一次，小问保留结构占位，
        # 否则完形/语法填空的整段 passage 会在每个小问里重复。
        if materials:
            _mat_text = "".join(
                "".join((getattr(b, "text", "") or "") for b in (m.blocks or []))
                for m in materials
            )
            _sub_text = "".join((b.get("text") or "") for b in sraw)
            _norm_mat = re.sub(r"\s+", "", _mat_text)
            _norm_sub = re.sub(r"\s+", "", _sub_text)
            if _norm_sub and _norm_sub in _norm_mat:
                sraw = [{"kind": "text", "text": "", "line_start": s, "line_end": s}]
                log.setdefault("shared_material_sub_placeholders", []).append(sid)
        if _opt_raw:
            # 选项在同一 unit 内单独声明：小问题面里不得重复保留这些行。
            sraw = _drop_option_line_blocks(
                sraw,
                [(o.get("line_start"), o.get("line_end")) for o in _opt_raw],
                log,
                f"{base}/{sid}/stem",
            )
        blocks = _blocks_from_raw(sraw, asset_sink, ctx, f"{base}/{sid}", log)
        if not blocks:
            blocks = [TextBlock(text="", line_start=s, line_end=e)]
        used = []
        for mref in sq.get("materials_used") or []:
            if mref not in mat_by_id:
                raise ValueError(
                    f"{unit_id}/{sid}: materials_used {mref!r} unresolved (input_contract_gap)"
                )
            used.append(mref)
        par = sq.get("parent_sub_id")
        bodies.append(
            QuestionBody(
                local_id=sid,
                question_type=QuestionType(question_type(unit)),
                printed_number=sq.get("label"),
                stem_blocks=tuple(blocks),
                options=(),
                material_ids=tuple(used),
                parent_question_ref=(par if par is not None else base),
                sub_question_ids=tuple(children.get(sid, ())),
                unit_type=UnitType(unit.get("unit_type") or "composite_question"),
                note=(
                    f"sub-question from manifest.sub_questions {sid!r} (L{s}-L{e}); "
                    f"label={sq.get('label')!r}; materials_used={used}"
                ),
            )
        )
    if _opt_raw:
        def _option_blocks(o):
            _bl = list(_blocks_from_raw(o["blocks"], asset_sink, ctx, f"{base}-options", log))
            if _bl and getattr(_bl[0], "kind", "") == "text":
                _txt = getattr(_bl[0], "text", "") or ""
                _pref = re.match(r"^\s*[A-H]\s*[.．、:：]\s*", _txt)
                if _pref:
                    _bl[0] = TextBlock(
                        text=_txt[_pref.end():],
                        line_start=getattr(_bl[0], "line_start", None),
                        line_end=getattr(_bl[0], "line_end", None),
                    )
            return tuple(_bl)

        _opt_blocks = tuple(
            OptionItem(
                label=o["label"],
                blocks=_option_blocks(o),
                line_start=o.get("line_start"),
                line_end=o.get("line_end"),
            )
            for o in _opt_raw
        )
        # Attach the shared options to the last sub-question body.  This keeps
        # a non-empty stem (content audit requires it) and places the options
        # after the passage in source order; options are rendered once.
        if bodies:
            _last = bodies[-1]
            bodies[-1] = _rebuild(_last, options=_opt_blocks)

    log["g3_structure"] = {
        "sub_ids": sub_order,
        "roots": roots,
        "materials": [m.material_id for m in materials],
        "grouping_statements": unit.get("grouping_statements") or [],
        "classification": unit.get("classification"),
        "uncertainty": unit.get("uncertainty"),
    }
    return bodies, materials


def _apply_extra_image_blocks(raw_blocks: list, specs: list, unit_id: str) -> list:
    """受控题面图片注入（QCORE-STUDENT-FIDELITY-IMAGE-REPAIR-01）。

    仅对 unit.extra_image_blocks 显式声明生效：按声明顺序在文本流 offset 处
    切分文本并插入 ImageBlock(asset_id)。文字字节保持不变；line_start/line_end
    沿用被切分文本块的原区间。offset 以「该 unit 题面 text 块的拼接文本」为
    坐标系（单块时即块内 offset）。未声明（specs 为空）时原样返回；anchor 非
    "text"、offset 越界/非整数、asset_id 缺失时 fail closed，不作任何猜测。
    """
    if not specs:
        return raw_blocks
    ordered = sorted(
        enumerate(specs),
        key=lambda t: (t[1].get("offset") if isinstance(t[1].get("offset"), int) and not isinstance(t[1].get("offset"), bool) else -1, t[0]),
    )
    total = sum(len(b.get("text", "")) for b in raw_blocks if b.get("kind") == "text")
    for _, spec in ordered:
        if spec.get("anchor") != "text":
            raise ValueError(
                f"extra_image_blocks: unsupported anchor {spec.get('anchor')!r} (unit {unit_id!r})"
            )
        off = spec.get("offset")
        if not isinstance(off, int) or isinstance(off, bool) or off < 0 or off > total:
            raise ValueError(
                f"extra_image_blocks: offset {off!r} out of [0,{total}] (unit {unit_id!r})"
            )
        if not spec.get("asset_id"):
            raise ValueError(f"extra_image_blocks: asset_id required (unit {unit_id!r})")
    out = []
    cursor = 0
    spec_iter = iter(ordered)
    pending = next(spec_iter, None)
    for b in raw_blocks:
        if b.get("kind") != "text":
            out.append(b)
            continue
        text = b.get("text", "")
        start = cursor
        end = cursor + len(text)
        pos = start
        while pending is not None:
            _, spec = pending
            off = spec["offset"]
            if off < pos:
                raise ValueError(
                    f"extra_image_blocks: offset {off} already passed (unit {unit_id!r})"
                )
            if off > end:
                break
            if off > pos:
                out.append({**b, "text": text[pos - start:off - start]})
            out.append(
                {
                    "kind": "image",
                    "asset_id": spec["asset_id"],
                    "alt_text": spec.get("alt_text"),
                    "line_start": b.get("line_start"),
                    "line_end": b.get("line_end"),
                }
            )
            pos = off
            pending = next(spec_iter, None)
        if end > pos:
            out.append({**b, "text": text[pos - start:]})
        elif start == end:
            out.append(b)
        cursor = end
    if pending is not None:
        raise ValueError(f"extra_image_blocks: unresolved spec (unit {unit_id!r})")
    return out


def _merge_extras_and_figures(
    unit: dict, ctx: MappingContext, raw: list, *, log: dict, where: str, target: str,
    extra_present: set | None = None,
    declared_asset_ids: set | None = None,
    extra_text_dedup: bool = False,
    extra_text_cutoff: int | None = None,
    consumed_lines: set | None = None,
) -> list:
    """AF2-B：题面图落位（Q8/Q14/Q16）。

    - ``extra_lines``（题面补图/题注区）并入题面流，不再进解析区（review-only）；
    - ``figures[]`` 声明但未被行区提取到的插图，按 evidence 行号插回对应
      body/material 的块流（子 asset 块，禁止只登记 asset 不落块）；
    - 已存在的图块不重复注入（含兄弟流 extra_present，如选项区表内图）；
      页脚装饰图由 _blocks_from_raw 过滤层剔除。
    """
    present = {b.get("asset_id") for b in raw if b.get("kind") == "image"}
    if extra_present:
        present |= {x for x in extra_present if x}
    placed: dict = log.setdefault("placed_image_ids", {})
    for b in raw:
        if b.get("kind") == "image" and b.get("asset_id"):
            placed.setdefault(b["asset_id"], target)
    present |= set(placed)

    if where in ("stem", "root"):
        # AF3/Q16：figures[] 显式指派给子问（applies_to 非空）的图，即使其行号
        # 落在父级间隙，也不得滞留父级——由对应子问的合并按 applies_to 落位。
        assigned = {
            asset_furniture.stem_of(f.get("asset_ref") or "")
            for f in (unit.get("figures") or [])
            if (f.get("applies_to") or [])
        }
        if assigned:
            kept = []
            for b in raw:
                if b.get("kind") == "image" and b.get("asset_id") in assigned:
                    _exclude(log, b.get("asset_id"), target, "assigned_to_sub")
                    present.discard(b.get("asset_id"))
                    placed.pop(b.get("asset_id"), None)
                    continue
                kept.append(b)
            raw = kept
    add: list = []

    ex = unit.get("extra_lines")
    if ex and where in ("stem", "root"):
        res = extract_range(ctx.lines, ex[0], ex[1])
        declared = declared_asset_ids if declared_asset_ids is not None else {
            asset_furniture.stem_of(f.get("asset_ref") or "")
            for f in (unit.get("figures") or [])
            if f.get("asset_ref")
        }
        for b in res.blocks:
            if b.get("kind") == "image":
                aid = b.get("asset_id")
                # M2: extra_lines images are only admissible when the Manifest
                # declares the asset (figures[]).  Answer/explanation page
                # images found only via extra_lines are not question assets.
                if not aid or aid in present or aid not in declared:
                    log.setdefault("extra_image_skipped", []).append(
                        {"where": where, "asset_id": aid, "reason": "not_declared_in_figures"}
                    )
                    continue
                present.add(aid)
            elif extra_text_dedup and b.get("kind") in ("text", "table"):
                _ls, _le = b.get("line_start"), b.get("line_end")
                if extra_text_cutoff is not None and isinstance(_ls, int) and _ls > extra_text_cutoff:
                    # extra_lines outside the declared question range is not a
                    # parent-content owner; keep it out of the parent body.
                    log.setdefault("extra_text_suppressed", []).append(
                        {"where": where, "line_start": _ls, "line_end": _le,
                         "reason": "outside_questions_range"}
                    )
                    continue
                if isinstance(_ls, int) and consumed_lines:
                    _le2 = _le if isinstance(_le, int) else _ls
                    if all(_ln in consumed_lines for _ln in range(_ls, _le2 + 1)):
                        log.setdefault("extra_text_suppressed", []).append(
                            {"where": where, "line_start": _ls, "line_end": _le,
                             "reason": "same_source_line_already_consumed"}
                        )
                        continue
            add.append(b)

    for f in unit.get("figures") or []:
        ref = f.get("asset_ref") or ""
        stem = asset_furniture.stem_of(ref)
        if not stem or stem in present:
            continue
        ev = f.get("evidence") or {}
        ls = ev.get("line_start")
        le = ev.get("line_end") or ls
        applies = f.get("applies_to") or []

        def _in(mid_line_ranges):
            return any(
                isinstance(s, int) and isinstance(e, int) and ls and s <= ls <= e
                for s, e in mid_line_ranges
            )

        sub_ranges = [
            (s.get("line_start"), s.get("line_end"))
            for s in (unit.get("sub_questions") or [])
        ]
        mat_ranges = [
            (m.get("line_start"), m.get("line_end"))
            for m in (unit.get("materials") or [])
        ]
        if where.startswith("material:"):
            mid = where.split(":", 1)[1]
            mat = next(
                (m for m in (unit.get("materials") or []) if (m.get("material_id") or "") == mid),
                None,
            )
            want = mat is not None and _in([(mat.get("line_start"), mat.get("line_end"))])
        else:
            # AF5/Q16：子问落位以行序权威（resolve_sub_target：行重叠>如图引用>applies_to）；
            # 多子问共享图（applies_to 多目标）仍归父级一次（AF2-B/Q15）。
            # Layer 2 契约：PDF 证据驱动的子问落位同样以布局证据在场为前提；
            # 无 image_layout 时退回 applies_to，保证既有输出不变（零回归）。
            if len(applies) > 1 and not _in(mat_ranges):
                want = where in ("stem", "root")
            else:
                if layout_ev.get_layout(ctx) is None:
                    target_sub = applies[0] if applies else None
                else:
                    from .figure_attribution import resolve_sub_target

                    target_sub = resolve_sub_target(stem, unit, ctx)
                if target_sub is not None:
                    want = target_sub == where
                else:
                    want = (
                        where in ("stem", "root")
                        and not _in(sub_ranges)
                        and not _in(mat_ranges)
                    )
        if not want:
            continue
        add.append({
            "kind": "image", "asset_id": stem, "alt_text": None,
            "line_start": ls, "line_end": le,
        })
        present.add(stem)
        placed[stem] = target
        log.setdefault("figure_injections", []).append(
            {"asset_id": stem, "where": target, "line_start": ls, "applies_to": applies}
        )

    if not add:
        return raw
    merged = raw + add
    merged.sort(key=lambda b: (b.get("line_start") is None, b.get("line_start") or 0))
    return merged


def _inject_reattributed(
    unit: dict, ctx: MappingContext, raw: list, *, log: dict, where: str, target: str
) -> list:
    """跨单元归属回填——真主单元按预解析登记注入被误派的图。

    Layer 2 契约：只有 Manifest 携带 image_layout（布局证据在场）时才启用
    跨单元回填；无布局证据时保持既有 Unit 边界。
    """
    if layout_ev.get_layout(ctx) is None:
        return raw
    try:
        from .figure_attribution import reattributed_map

        reatt = reattributed_map(ctx)
    except Exception as exc:  # noqa: BLE001
        log.setdefault("figure_reattribution_errors", []).append(
            {"where": target, "error": type(exc).__name__}
        )
        return raw
    if not reatt:
        return raw
    present = {b.get("asset_id") for b in raw if b.get("kind") == "image"}
    uid = unit.get("unit_id")
    add = []
    for stem, res in reatt.items():
        if stem in present:
            continue
        if (res.get("owner") or "").lower() != (uid or "").lower():
            continue
        if _is_decorative(stem, ctx):
            continue
        want_sub = res.get("sub")
        if where in ("stem", "root"):
            if want_sub:
                continue
        elif want_sub != where:
            continue
        ev = None
        for f in (unit.get("figures") or []):
            if asset_furniture.stem_of(f.get("asset_ref") or "") == stem:
                ev = (f.get("evidence") or {}).get("line_start")
                break
        if ev is None:
            # 回填的图不在本单元 figures[]（如 Q13 收到 Q14 区的图）：
            # 用归属裁决的 md_line 作行锚，避免 line_start=None 被排到流末尾。
            ev = (res.get("evidence") or {}).get("md_line")
        add.append({"kind": "image", "asset_id": stem, "alt_text": None,
                    "line_start": ev, "line_end": ev})
        present.add(stem)
        log.setdefault("figure_reattributed_in", []).append(
            {
                "asset_id": stem,
                "where": target,
                "sub": want_sub,
                "owner": res.get("owner"),
                "evidence": _decision_evidence(res),
            }
        )
    if not add:
        return raw
    merged = raw + add
    merged.sort(key=lambda b: (b.get("line_start") is None, b.get("line_start") or 0))
    return merged


def _refine_option_specs(unit: dict, ctx: MappingContext, log: dict | None = None) -> list:
    """AF4/Q9：选项行绑定纠错（错位/共享行）——按 options_lines 内标签行
    （^LABEL[.．、:：]）确定性重扫描；全部标签唯一命中才覆盖 Manifest 绑定，
    否则保持原绑定（fail-open）。"""
    specs = [
        {"label": o["label"], "start": o["start_line"], "end": o["end_line"]}
        for o in (unit.get("options") or [])
    ]
    if not specs:
        return specs
    region = unit.get("options_lines")
    if not region or len(region) != 2:
        return _clamp_option_spans(specs, ctx.lines, log, unit.get("unit_id"))
    s0, e0 = int(region[0]), int(region[1])
    found: dict = {}
    for ln in range(max(1, s0), min(len(ctx.lines), e0) + 1):
        m = re.match(r"\s*([A-H])\s*[.．、:：]", ctx.lines[ln - 1])
        if m and m.group(1) not in found:
            found[m.group(1)] = ln
    labels = [s["label"].strip().upper() for s in specs]
    if not all(lb in found for lb in labels):
        return _clamp_option_spans(specs, ctx.lines, log, unit.get("unit_id"))
    starts = sorted(found[lb] for lb in labels)
    refined = []
    for spec in specs:
        lb = spec["label"].strip().upper()
        st = found[lb]
        nxt = min((x for x in starts if x > st), default=e0 + 1)
        end = nxt - 1
        # 尾部修剪：空行/分页线（---）不属选项正文
        while end > st:
            ln_txt = (ctx.lines[end - 1] if end - 1 < len(ctx.lines) else "").strip()
            if ln_txt == "" or re.fullmatch(r"-{3,}", ln_txt):
                end -= 1
            else:
                break
        refined.append({"label": spec["label"], "start": st, "end": end})
    if [(s["start"], s["end"]) for s in refined] != [(s["start"], s["end"]) for s in specs]:
        if log is not None:
            log["option_line_rebind"] = {
                "before": [(s["label"], s["start"], s["end"]) for s in specs],
                "after": [(s["label"], s["start"], s["end"]) for s in refined],
            }
    return _clamp_option_spans(refined, ctx.lines, log, unit.get("unit_id"))


# 下一题 / 下一小问 / 栏目标记行：选项正文到此必须停止。
_QSIDE_NEXT_MARKER_RE = re.compile(r"^\s*(?:\(\s*\d+\s*\)|（\s*\d+\s*）|\d{1,3}\s*[.．、])")
_OPT_LABEL_PREFIX_RE = re.compile(r"^\s*[A-H]\s*[.．、:：]")


def _clamp_option_spans(specs: list, lines: list, log: dict | None, unit_id) -> list:
    """选项跨度只允许收窄：不得吞掉下一选项，也不得吞掉下一题/下一小问。

    证据是源文行本身（标签行、题号行），不做任何生成。收窄后若跨度为 0 行，
    保持原跨度并登记（fail-open，交给 ContentAudit 而不是静默丢内容）。
    """
    if not specs:
        return specs
    order = sorted(specs, key=lambda s: int(s["start"]))
    out = []
    clamped = []
    for i, spec in enumerate(order):
        st, en = int(spec["start"]), int(spec["end"])
        limit = en
        if i + 1 < len(order):
            limit = min(limit, int(order[i + 1]["start"]) - 1)
        for ln in range(st, min(en, len(lines)) + 1):
            if _QSIDE_NEXT_MARKER_RE.match(lines[ln - 1]):
                limit = min(limit, ln - 1)
                break
        new_en = max(st, min(en, limit))
        if new_en < en:
            clamped.append({"label": spec.get("label"), "before": [st, en], "after": [st, new_en]})
        out.append({**spec, "start": st, "end": new_en})
    if clamped and log is not None:
        log.setdefault("option_span_clamped", []).extend(
            {"unit": unit_id, **c} for c in clamped
        )
    # 保持调用方的标签顺序
    by_label = {s["label"]: s for s in out}
    return [by_label.get(s["label"], s) for s in specs]


def _drop_option_line_blocks(raw: list, spans: list, log: dict | None, where: str) -> list:
    """题面里不得再保留已声明为选项的源行（否则 options 与 stem 各存一份）。

    只丢弃「整块落在某个选项跨度内、且文本以选项标号开头或为空」的文本块；
    部分重叠或非选项样式的块一律保留（fail-open，登记待复核）。
    """
    ranges = [(int(a), int(b)) for a, b in spans if a is not None and b is not None]
    if not ranges:
        return raw
    kept, dropped = [], []
    for b in raw:
        a, z = b.get("line_start"), b.get("line_end")
        if not isinstance(a, int):
            kept.append(b)
            continue
        z = z if isinstance(z, int) else a
        inside = any(a >= s and z <= e for s, e in ranges)
        txt = (b.get("text") or "") if b.get("kind") == "text" else ""
        if inside and (not txt.strip() or _OPT_LABEL_PREFIX_RE.match(txt)):
            dropped.append({"line_start": a, "line_end": z, "text": txt.strip()[:80]})
            continue
        kept.append(b)
    if dropped and log is not None:
        log.setdefault("option_lines_removed_from_stem", []).append({"where": where, "blocks": dropped})
    return kept


def _standalone_body(
    unit: dict, ctx: MappingContext, asset_sink: list, log: dict
):
    base = unit["unit_id"].lower()
    stem = unit.get("stem_lines")
    parent_blocks = []
    table = None

    opt_specs = _refine_option_specs(unit, ctx, log)
    options_raw, shared_tables = None, []
    if not opt_specs and unit.get("options_lines"):
        # AF2-A/Q11：Manifest 未声明选项条目但 options_lines 内有 HTML 表格
        # （标签列版式）→ 从表格标签列确定性派生 A-H 选项；表格网格照常保留。
        from .extract import detect_table_labels

        region = tuple(unit["options_lines"])
        probe = extract_range(ctx.lines, region[0], region[1])
        labels = detect_table_labels(probe.tables)
        if labels:
            opt_specs = [
                {"label": lb, "start": region[0], "end": region[1]} for lb in labels
            ]
            log["option_autodetect"] = {"labels": labels, "source": "table_label_column"}
    if opt_specs:
        from .extract import OptionSpec

        region = tuple(unit["options_lines"]) if unit.get("options_lines") else None
        options_raw, shared_tables = extract_options(
            ctx.lines,
            [OptionSpec(label=o["label"], start=o["start"], end=o["end"]) for o in opt_specs],
            region=region,
        )
        log["option_mode"] = (
            "shared_html_table" if shared_tables else "independent_ranges"
        )
        options_raw = _dedupe_option_text(options_raw, log, unit.get("unit_id"), ctx.lines, unit.get("options_lines"))
    opt_img_ids = {
        b.get("asset_id")
        for o in (options_raw or [])
        for b in o.get("blocks") or []
        if b.get("kind") == "image"
    }

    if stem:
        r = extract_range(ctx.lines, stem[0], stem[1])
        raw = _apply_extra_image_blocks(
            r.blocks, unit.get("extra_image_blocks") or [], unit.get("unit_id")
        )
        raw = _merge_extras_and_figures(
            unit, ctx, raw, log=log, where="stem", target=f"{base}",
            extra_present=opt_img_ids,
        )
        raw = _inject_reattributed(unit, ctx, raw, log=log, where="stem", target=f"{base}")
        # 选项已单独成 OptionItem，题面不得再保留同一批源行（Owner 58 条中的
        # duplicate_option / duplicate_text 主因）。
        raw = _drop_option_line_blocks(
            raw,
            [(o["start"], o["end"]) for o in (opt_specs or [])],
            log,
            f"{base}/stem",
        )
        parent_blocks = _blocks_from_raw(raw, asset_sink, ctx, base, log)

    if shared_tables:
        _ol = unit.get("options_lines") or [None, None]
        for st in shared_tables:
            stb = _raw_table_to_table_block(st, _ol[0], _ol[1])
            parent_blocks = list(parent_blocks) + [stb]

    options = tuple(
        OptionItem(
            label=o["label"],
            blocks=tuple(_blocks_from_raw(o["blocks"], asset_sink, ctx, base, log)),
            line_start=o["line_start"],
            line_end=o["line_end"],
        )
        for o in (options_raw or [])
    )

    body = QuestionBody(
        local_id=base,
        question_type=QuestionType(question_type(unit)),
        printed_number=unit.get("printed_number"),
        stem_blocks=tuple(parent_blocks) or (TextBlock(text=""),),
        options=options,
        material_ids=(),
        parent_question_ref=None,
        sub_question_ids=(),
        unit_type=UnitType(unit.get("unit_type") or "standalone_question"),
    )
    log["option_mode"] = log.get("option_mode", "none")
    return [body], []


# ---------------------------------------------------------------------------
# 解析块（Revision.explanation_blocks；含 extra_lines 补充图/表）
# ---------------------------------------------------------------------------


def _explanation_blocks(unit: dict, ctx: MappingContext, asset_sink: list, log: dict):
    blocks_raw = []
    ranges = []
    # AF2-B：extra_lines 是题面补图/题注区 → 归 body（_merge_extras_and_figures），
    # 不再进解析区（review-only 不得吞题面图）；此处只消费 explanation_lines。
    for key in ("explanation_lines",):
        r = unit.get(key)
        if not r:
            continue
        ranges.append({"field": key, "line_start": r[0], "line_end": r[1]})
        res = extract_range(ctx.lines, r[0], r[1])
        blocks_raw.extend(res.blocks)
    blocks = list(_blocks_from_raw(blocks_raw, asset_sink, ctx, "explanation_blocks", log))
    log["explanation_ranges"] = ranges
    # Owner 2026-11-22（4.3）：解析区内的图片资产必须进入 explanation_blocks，
    # 否则资产已登记却没有任何内容块引用它（学生端/审核端都看不到）。
    # 只按 line_no 落在解析区间内挂接，位置证据明确，不做语义猜测。
    placed = {
        getattr(b, "asset_id", None)
        for b in blocks
        if getattr(b, "kind", "") == "image"
    }
    added = []
    for r in ranges:
        for ln in range(int(r["line_start"]), int(r["line_end"]) + 1):
            asset = (ctx.image_by_line or {}).get(ln)
            if not asset:
                continue
            aid = asset.get("asset_id") or str(asset.get("src") or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if not aid or aid in placed:
                continue
            try:
                _register_asset(aid, asset_sink, ctx, "explanation")
            except Exception:  # noqa: BLE001 - 资产登记失败不阻断解析映射
                pass
            blocks.append(ImageBlock(asset_id=aid, alt_text=None))
            placed.add(aid)
            added.append({"asset_id": aid, "line": ln})
    if added:
        log["explanation_images_added"] = added
    log["explanation_block_count"] = len(blocks)
    return tuple(blocks)


# ---------------------------------------------------------------------------
# 主映射
# ---------------------------------------------------------------------------


def map_unit(unit: dict, ctx: MappingContext) -> UnitMapping:
    # R1 B2：学科必须由导入上下文显式提供（不猜测、不默认）
    if not (ctx.subject or "").strip():
        raise ValueError(
            f"{unit.get('unit_id')}: MappingContext.subject missing "
            "(fail-closed; subject must be provided explicitly by the "
            "import context, never guessed)"
        )
    # 英语 composite（grammar_fill/cloze/reading/seven_to_five，且试卷在
    # rules.ENGLISH_COMPOSITE_SCOPE_PAPERS 显式范围内）走专用确定性展开+
    # 答案解码分支（QCORE-DELIVERY-01-C-R3）；其余（含语文同名 reading
    # composite）走既有（n）标签路径，化学/语文代码不变。
    if unit.get("unit_type") == "composite_question":
        from . import english_composite

        if english_composite.is_english_composite(unit, ctx):
            return english_composite.map_unit(unit, ctx)

    unit_id = unit["unit_id"]
    log: dict = {"unit_id": unit_id}
    source_document_id = f"{ctx.paper_id}/{unit_id}"
    attribution, reason = resolve_attribution(unit, source_document_id)
    log["attribution"] = attribution
    log["attribution_reason"] = reason
    comp = answer_completeness(unit)
    log["answer_completeness_transport"] = comp
    log["answer_completeness_semantic_ignored"] = unit.get(
        "answer_completeness_semantic"
    )

    asset_sink: list = []
    if unit.get("unit_type") == "composite_question":
        bodies, materials = _composite_bodies_and_materials(unit, ctx, asset_sink, log)
    else:
        bodies, materials = _standalone_body(unit, ctx, asset_sink, log)
    # Layer 2：布局证据在场的图块顺序（只调顺序，不改文本/图/行号）
    bodies, materials = _apply_layout_order(bodies, materials, ctx, log, unit_id)

    explanation_blocks = _explanation_blocks(unit, ctx, asset_sink, log)

    # 答案区图片（C-CLOSURE C1）：必须在 assets 收口前登记。
    ans_img_records = tuple(_answer_region_images(unit, ctx, asset_sink, log))

    # ---- 答案对象（answers[] 逐条消费；在 assets 收口前完成以便答案图登记）----
    # P-04：sub_id 显式身份（answers[].sub_ref 首选）+ 完整标签格式键（回落）。
    sub_id_map: dict[str, str] = {}
    for b in bodies:
        if b.local_id:
            sub_id_map[b.local_id] = b.local_id
        if b.parent_question_ref is not None and b.printed_number:
            sub_id_map[_norm_label_key(b.printed_number)] = b.local_id

    def _asset_resolver(ref: str) -> str:
        return _register_answer_asset(ref, asset_sink, ctx)

    override_reason = owner_override_reason(source_document_id)
    answers = _build_answers(
        unit,
        attribution,
        log,
        sub_id_map=sub_id_map,
        asset_resolver=_asset_resolver,
        override_reason=override_reason,
        source_lines=ctx.lines,
    )
    answers, conflict_specs = _annotate_conflicts(answers, unit, unit_id, log)

    assets = tuple(
        Asset(
            asset_id=a["asset_id"],
            asset_role=a["asset_role"],
            target_path=a.get("target_path"),
            source_id=a["source_id"],
            page=a["page"],
            bbox=a["bbox"],
            storage_path=a["storage_path"],
            content_hash=a["content_hash"],
            mime_type=a["mime_type"],
            width=a["width"],
            height=a["height"],
            note=a["note"],
        )
        for a in asset_sink
    )
    log["assets"] = [
        {"asset_id": a.asset_id, "storage_path": a.storage_path,
         "content_hash": a.content_hash}
        for a in assets
    ]

    bodies, materials = _place_unreferenced_assets(bodies, materials, assets, log)
    bodies, materials = _dedupe_identical_blocks(bodies, materials, log)
    content = QuestionContent(
        bodies=tuple(bodies),
        materials=tuple(materials),
        assets=assets,
    )
    # Layer 2：布局消费结果 + 归属决策（log 可审计；证据记录 review-only）
    _attach_layout_log(unit, ctx, content, log)
    layout_records = tuple(_layout_evidence_records(unit, ctx, content, log))

    # G4-R1 R1-03：题面表格内容完整性检查（声明范围 ↔ 输出载体）
    table_missing = _table_content_missing(unit, ctx, bodies, materials, log)
    log["table_content_loss"] = table_missing[:20]
    if table_missing:
        log["table_content_loss_count"] = len(table_missing)

    evidence = _build_evidence(
        unit,
        answers,
        ctx,
        attribution,
        log,
        extra_records=tuple(ans_img_records) + layout_records,
        conflict_specs=conflict_specs,
        override_reason=override_reason,
    )

    qtype = question_type(unit)
    declared_value = (unit.get("answer_evidence") or {}).get("value")
    # P-1/P-3：override 单元的 declared_value 不声明（归属口径冻结）。
    declaration = StrictAnswerDeclaration(
        attribution=attribution,
        evidence_kind=(unit.get("answer_evidence") or {}).get("type") or "absent",
        declared_value=declared_value if override_reason is None else None,
        table_row_locator=(unit.get("answer_evidence") or {}).get("table_row_locator"),
        completeness=Completeness.INCOMPLETE,
    )
    log["declaration"] = declaration.model_dump(mode="json")

    # core.completeness：内容轴（G-07）——全部 TypedAnswer FULL 才 complete；
    # essay（Owner D-1）以解析区范文覆盖判 complete，不因无 TypedAnswer 判缺。
    all_full = bool(answers) and all(
        a.completeness == AnswerCompleteness.FULL for a in answers
    )
    if qtype == "essay":
        # Owner 2026-11-22：作文题不要求标准答案/范文；只看题目本身是否完整。
        covered = _essay_content_complete(unit, log)
        core_completeness = (
            Completeness.COMPLETE if covered else Completeness.INCOMPLETE
        )
        log["essay_model_text_present"] = _essay_model_text_covered(unit, {})
    else:
        core_completeness = (
            Completeness.COMPLETE if all_full else Completeness.INCOMPLETE
        )
    if table_missing and core_completeness == Completeness.COMPLETE:
        # R1-03：题面表格内容静默丢失时不得判 complete（fail-closed）
        core_completeness = Completeness.INCOMPLETE
        log["core_completeness_downgraded"] = "table_content_loss"
    # Owner C1（2026-11-22）：题内重复文本是对学生可见的内容缺陷，不得带着
    # 缺陷发布。只降级完整性（不删内容、不改文本），由 Admission 阻止发布，
    # 保留完整证据供复核与后续修复。
    try:
        _dup_lines = content_audit.duplicate_text_lines(content)
    except Exception:  # noqa: BLE001 - audit must never break mapping
        _dup_lines = []
    if _dup_lines:
        log["duplicate_text_lines"] = _dup_lines[:10]
        log["duplicate_text_line_count"] = len(_dup_lines)
        if core_completeness == Completeness.COMPLETE:
            core_completeness = Completeness.INCOMPLETE
            log["core_completeness_downgraded"] = "duplicate_text"
    declaration = _rebuild(declaration, completeness=core_completeness)
    log["declaration"] = declaration.model_dump(mode="json")
    log["core_completeness"] = core_completeness.value

    input_hashes = InputHashes(
        manifest_hash=ctx.manifest_sha,
        source_md_hash=ctx.source_md_sha,
        source_pdf_hash=ctx.source_pdf_sha,
    )
    source_document_id = f"{ctx.paper_id}/{unit_id}"
    idem_key = derive_idempotency_key(
        source_type="preprocessing",
        source_document_id=source_document_id,
        input_hashes=input_hashes,
    )

    stem_texts = "\n".join(
        getattr(b, "text", "")
        for body in bodies
        for b in body.stem_blocks
        if getattr(b, "kind", "") == "text"
    )
    fingerprint = "fp-e2e01-" + hashlib.sha256(
        f"{source_document_id}\n{stem_texts}".encode("utf-8")
    ).hexdigest()[:16]

    ingestion = IngestionIdentity(
        candidate_idempotency_key=idem_key,
        ingestion_run_id=ctx.ingestion_run_id,
        adapter_version=ADAPTER_VERSION,
        input_hashes=input_hashes,
        ingested_by="qcore-e2e-01-phase-c",
        note="sealed Phase-B artifacts only; no re-OCR/re-reslice/re-guess",
    )

    source = PreprocessingSource(
        source_document_id=source_document_id,
        manifest_ref=SourceDocumentRef(
            doc_role="manifest",
            content_hash=ctx.manifest_sha,
            locator_uri=ctx.manifest_path,
            byte_size=ctx.manifest_bytes,
        ),
        source_md_ref=SourceDocumentRef(
            doc_role="source_markdown",
            content_hash=ctx.source_md_sha,
            locator_uri=ctx.source_md_path,
            byte_size=ctx.source_md_bytes,
        ),
        source_pdf_ref=SourceDocumentRef(
            doc_role="source_pdf",
            content_hash=ctx.source_pdf_sha,
            locator_uri=ctx.source_pdf_name,
            byte_size=ctx.source_pdf_bytes,
        ),
        annotated_md_ref=SourceDocumentRef(
            doc_role="annotated_markdown",
            content_hash=ctx.annotated_md_sha,
            locator_uri=ctx.annotated_md_name,
            byte_size=ctx.annotated_md_bytes,
        ),
        unit=PreprocessingUnitRef(
            unit_id=unit["unit_id"],
            unit_type=UnitType(unit["unit_type"]),
            question_numbers=tuple(unit.get("question_numbers") or ()),
            original_question_type=unit.get("original_question_type"),
            section=unit.get("section"),
            printed_number=unit.get("printed_number"),
            stem_lines=tuple(unit["stem_lines"]) if unit.get("stem_lines") else None,
            options_lines=tuple(unit["options_lines"])
            if unit.get("options_lines")
            else None,
            answer_lines=tuple(unit["answer_lines"])
            if unit.get("answer_lines")
            else None,
            explanation_lines=tuple(unit["explanation_lines"])
            if unit.get("explanation_lines")
            else None,
            extra_lines=tuple(unit["extra_lines"]) if unit.get("extra_lines") else None,
            material_lines=tuple(unit["material_lines"])
            if unit.get("material_lines")
            else None,
            questions_lines=tuple(unit["questions_lines"])
            if unit.get("questions_lines")
            else None,
        ),
        grade=ctx.manifest.get("grade"),
        subject=ctx.subject,
        answer_declaration=declaration,
    )
    log["subject_mapping"] = {
        "value": ctx.subject,
        "source": "import_context.paper_level (MappingContext.subject)",
    }
    log["source_document_id"] = source_document_id
    log["idempotency_key"] = idem_key
    log["identity_fingerprint"] = fingerprint

    core_import = CandidateCore(
        question_type=QuestionType(qtype),
        content=content,
        answers=tuple(answers),
        evidence=evidence,
        completeness=core_completeness,
        identity_fingerprint=fingerprint,
        ingestion=ingestion,
        content_visibility=Visibility.REVIEW_ONLY,
        answer_visibility=Visibility.REVIEW_ONLY,
        explanation_visibility=Visibility.REVIEW_ONLY,
        evidence_visibility=Visibility.REVIEW_ONLY,
        created_by="qcore-e2e-01-phase-c",
        note=(
            "mapped from sealed Phase-B manifest; "
            f"answer ruling: {reason}"
        ),
    )

    try:
        candidate = PreprocessingCandidate(core=core_import, source=source)
    except Exception as _exc:
        _msg = str(_exc)
        if "requires the declared answer" in _msg:
            # Manifest declared completeness=complete, but the mapped
            # TypedAnswer does not fully represent the declared answer.
            # Fail closed to incomplete; never claim complete by force.
            _core_data = core_import.model_dump()
            _core_data["completeness"] = Completeness.INCOMPLETE
            core_import = CandidateCore.model_validate(_core_data)
            _src_data = source.model_dump()
            _src_data["answer_declaration"]["completeness"] = Completeness.INCOMPLETE
            source = type(source).model_validate(_src_data)
            candidate = PreprocessingCandidate(core=core_import, source=source)
            log["candidate_completeness_downgraded"] = "declared_answer_not_fully_represented"
        else:
            raise

    all_ranges = [
        r
        for r in (
            unit.get("stem_lines"),
            unit.get("options_lines"),
            unit.get("material_lines"),
            unit.get("questions_lines"),
            unit.get("extra_lines"),
            unit.get("answer_lines"),
            unit.get("explanation_lines"),
        )
        if r
    ]
    instance_fields = {
        "printed_number": unit.get("printed_number"),
        "question_numbers": tuple(unit.get("question_numbers") or ()),
        "section": unit.get("section"),
        "line_start": min(r[0] for r in all_ranges) if all_ranges else None,
        "line_end": max(r[1] for r in all_ranges) if all_ranges else None,
    }

    content_hash = canonical_content_hash(content, *answers, *explanation_blocks)
    log["content_hash"] = content_hash

    state_plan = "approve_publish" if core_completeness == Completeness.COMPLETE else "hold_not_ready"
    # G3-B B2（P-13/§5.1）：结构不确定声明 → 一律 hold_not_ready，不伪装确定。
    if unit.get("uncertainty"):
        state_plan = "hold_not_ready"
        log["uncertainty_hold"] = True
    log["state_plan"] = state_plan

    return UnitMapping(
        unit_id=unit_id,
        candidate=candidate,
        explanation_blocks=explanation_blocks,
        content_hash=content_hash,
        completeness=core_completeness.value,
        instance_fields=instance_fields,
        state_plan=state_plan,
        log=log,
    )


def map_all(ctx: MappingContext) -> list[UnitMapping]:
    out = []
    for unit in ctx.manifest["units"]:
        out.append(map_unit(unit, ctx))
    return out
