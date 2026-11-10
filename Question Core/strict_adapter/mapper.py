"""Deterministic unit → PreprocessingCandidate mapping.

每一步都可回溯到 Manifest 已声明的行区 / 已裁决口径（`rules.py`）。
禁止：重新识别结构、猜测答案、语义补全、修改 Manifest。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from uuid import UUID

from question_core.contracts.v1 import (
    AnswerCompleteness,
    AnswerEvidenceKind,
    Asset,
    CandidateCore,
    ChemicalBlock,
    Completeness,
    EvidenceBundle,
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
    OptionItem,
    PreprocessingCandidate,
    PreprocessingSource,
    PreprocessingUnitRef,
    QuestionBody,
    QuestionContent,
    QuestionType,
    SingleChoiceAnswer,
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

from . import ADAPTER_VERSION
from .extract import (
    RawTable,
    extract_options,
    extract_range,
    load_source_lines,
    split_sub_segments,
)
from .rules import (
    answer_completeness,
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


def _raw_table_to_table_block(rt: RawTable, line_start: int, line_end: int) -> TableBlock:
    cells = tuple(
        TableCell(
            row_index=c["row_index"],
            col_index=c["col_index"],
            content=c["content"],
            rowspan=c["rowspan"],
            colspan=c["colspan"],
            is_header=c["is_header"],
        )
        for c in rt.cells
    )
    return TableBlock(n_rows=rt.n_rows, n_cols=rt.n_cols, cells=cells)


def _blocks_from_raw(raw_blocks: list, asset_sink: list, ctx: MappingContext, target_hint: str):
    """raw block dicts → contract ContentBlocks；图片同时登记 Asset。"""
    out = []
    for rb in raw_blocks:
        kind = rb["kind"]
        if kind == "text":
            out.append(
                TextBlock(
                    text=rb["text"],
                    line_start=rb.get("line_start"),
                    line_end=rb.get("line_end"),
                )
            )
        elif kind == "image":
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


def _register_asset(asset_id: str, asset_sink: list, ctx: MappingContext, target_hint: str) -> None:
    if any(a["asset_id"] == asset_id for a in asset_sink):
        return
    meta = None
    for _, m in ctx.image_by_line.items():
        src_name = m["src"].rsplit("/", 1)[-1]
        if src_name.rsplit(".", 1)[0] == asset_id:
            meta = m
            break
    if meta is None:
        raise ValueError(f"image asset {asset_id!r} not found in manifest.image_assets")
    asset_sink.append(
        {
            "asset_id": asset_id,
            "asset_role": "figure",
            "storage_path": meta["artifact_path"],
            "content_hash": meta["sha256"],
            "mime_type": "image/jpeg",
            "source_id": ctx.source_md_name,
            "page": None,
            "bbox": None,
            "width": None,
            "height": None,
            "note": f"src={meta['src']}; line_no={meta['line_no']}; bytes={meta['bytes']}",
        }
    )


# ---------------------------------------------------------------------------
# 答案对象（按归属口径）
# ---------------------------------------------------------------------------


def _build_answers(unit: dict, attribution: str, log: dict) -> tuple:
    ev = unit.get("answer_evidence") or {}
    value = ev.get("value")
    comp = answer_completeness(unit)
    comp_enum = AnswerCompleteness(comp)
    kind = ev.get("type") or "absent"

    if attribution == "not_attributable":
        # 契约 not_attributable 参照实现（tests/test_strict_boundary.py:101-140）：
        # 不携带声称归属的 TypedAnswer；原值由 Evidence 保留。
        log["answers"] = []
        log["answers_policy"] = (
            "not_attributable: no TypedAnswer constructed; verbatim answer "
            "lines preserved as EvidenceRecord raw_value (no evidence dropped, "
            "no answer fabricated)"
        )
        return ()

    if not value:
        log["answers"] = []
        log["answers_policy"] = "no declared value: no TypedAnswer"
        return ()

    if kind == "answer_lines" and question_type(unit) == "single_choice":
        ans = SingleChoiceAnswer(
            answer_value=value.strip(),
            answer_display=value,
            evidence_kind=AnswerEvidenceKind.ANSWER_LINES,
            completeness=comp_enum,
            grading_rule="exact",
            note="verbatim manifest declared_value; transport completeness is "
            "the only completeness authority (P-2)",
        )
        log["answers"] = [
            {
                "answer_type": "single_choice",
                "answer_value": ans.answer_value,
                "completeness": comp,
                "evidence_kind": "answer_lines",
            }
        ]
        log["answers_policy"] = "declared standalone choice: direct map"
        return (ans,)

    # 复合题（Q8/Q9/Q11）：保留答案内容，完整性 unknown；不建立逐子问归属
    # （item↔子问对应关系未由 Manifest 声明，P-2 不得提升）。
    items = tuple(s.strip() for s in value.split("；") if s.strip() != "")
    if not items:
        items = (value,)
    ans = FillBlankAnswer(
        answer_value=items,
        answer_display=value,
        evidence_kind=AnswerEvidenceKind.ANSWER_LINES,
        completeness=comp_enum,
        grading_rule="manual",
        note=(
            "items = deterministic split of manifest declared_value on '；' "
            f"(n={len(items)}); per-sub-question attribution NOT established "
            "(manifest answer_completeness=unknown, P-2); manual grading only"
        ),
    )
    log["answers"] = [
        {
            "answer_type": "fill_blank",
            "items": list(items),
            "completeness": comp,
            "evidence_kind": "answer_lines",
            "item_split": "declared_value.split('；')",
        }
    ]
    log["answers_policy"] = (
        "composite declared answer: content preserved verbatim (split on '；'), "
        "completeness kept at transport value, no per-sub attribution claimed"
    )
    return (ans,)


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


def _build_evidence(
    unit: dict,
    answers: tuple,
    ctx: MappingContext,
    attribution: str,
    log: dict,
    extra_records: tuple = (),
) -> EvidenceBundle:
    ev = unit.get("answer_evidence") or {}
    ev_lines = ev.get("lines") or unit.get("answer_lines")
    value = ev.get("value")
    recs = list(extra_records)

    target = "/answers/0/answer_value" if answers else "/answers"
    note_parts = [f"attribution={attribution}"]
    normalized = None
    if attribution != "not_attributable":
        normalized = value
    elif value and unit["unit_id"] not in ("Q10", "Q12"):
        # Q3 型：值在源文中可见，但按契约 kind 映射不可声明为正式答案。
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
                evidence_status=EvidenceStatus.ACTIVE,
                note="; ".join(note_parts),
            )
        )

    # P-1/P-3：Manifest value 保留为独立 DISPUTED 记录，不得伪装为源文证据。
    # C-CLOSURE C2：source_kind=preprocessing_manifest 的记录必须用 Manifest
    # JSON Pointer 定位（不得拿 OCR Markdown 行号冒充 Manifest 行号）。
    if unit["unit_id"] in ("Q10", "Q12") and value:
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
                evidence_status=EvidenceStatus.DISPUTED,
                note=(
                    "manifest declared_value retained for audit but DISPUTED: "
                    + (
                        "P-1 label duplication/order scrambling/compression/"
                        "semantic completion"
                        if unit["unit_id"] == "Q10"
                        else "P-3 image semantic descriptions absent from "
                        "source lines; must not pose as source answer evidence"
                    )
                    + "; locator = manifest JSON Pointer (C-CLOSURE C2)"
                ),
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
            "status": r.evidence_status.value,
            "note": r.note,
        }
        for r in recs
    ]
    return EvidenceBundle(records=tuple(recs))


# ---------------------------------------------------------------------------
# 内容（bodies / materials / assets）
# ---------------------------------------------------------------------------


def _composite_bodies_and_materials(
    unit: dict, ctx: MappingContext, asset_sink: list, log: dict
):
    unit_id = unit["unit_id"]
    base = unit_id.lower()
    qrange = unit.get("questions_lines")
    mrange = unit.get("material_lines")
    if not qrange:
        raise ValueError(f"{unit_id}: composite unit without questions_lines")

    materials = []
    material_ids = []
    if mrange:
        mres = extract_range(ctx.lines, mrange[0], mrange[1])
        mblocks = _blocks_from_raw(mres.blocks, asset_sink, ctx, f"{base}-material")
        mat = Material(
            material_id=f"{base}-material",
            title=None,
            blocks=tuple(mblocks),
            line_start=mrange[0],
            line_end=mrange[1],
            note="shared material extracted from manifest.material_lines (verbatim)",
        )
        materials.append(mat)
        material_ids.append(mat.material_id)

    skip = [tuple(mrange)] if mrange else []
    segs, leads = split_sub_segments(ctx.lines, qrange[0], qrange[1], skip)
    log["sub_segments"] = [
        {"label": lb, "line_start": s, "line_end": e} for lb, s, e in segs
    ]
    log["lead_ranges"] = [{"line_start": a, "line_end": b} for a, b in leads]

    if not segs:
        raise ValueError(
            f"{unit_id}: composite unit produced no sub-question segments; "
            "refusing to guess structure"
        )

    parent_blocks = []
    for a, b in leads:
        r = extract_range(ctx.lines, a, b)
        parent_blocks.extend(_blocks_from_raw(r.blocks, asset_sink, ctx, f"{base}"))
    if not parent_blocks:
        parent_blocks = [TextBlock(text="", line_start=qrange[0], line_end=qrange[0])]

    sub_ids = [f"{base}-s{i+1}" for i in range(len(segs))]
    parent = QuestionBody(
        local_id=base,
        question_type=QuestionType(question_type(unit)),
        printed_number=unit.get("printed_number"),
        stem_blocks=tuple(parent_blocks),
        options=(),
        material_ids=tuple(material_ids),
        parent_question_ref=None,
        sub_question_ids=tuple(sub_ids),
        unit_type=UnitType(unit.get("unit_type") or "composite_question"),
        note=(
            "composite parent; sub-questions segmented ONLY on printed labels "
            f"at line starts within questions_lines {qrange} (cut points logged)"
        ),
    )

    bodies = [parent]
    for (label, s, e), sub_id in zip(segs, sub_ids):
        r = extract_range(ctx.lines, s, e)
        blocks = _blocks_from_raw(r.blocks, asset_sink, ctx, sub_id)
        if not blocks:
            blocks = [TextBlock(text="", line_start=s, line_end=e)]
        bodies.append(
            QuestionBody(
                local_id=sub_id,
                question_type=QuestionType(question_type(unit)),
                printed_number=label,
                stem_blocks=tuple(blocks),
                options=(),
                material_ids=tuple(material_ids),
                parent_question_ref=base,
                sub_question_ids=(),
                unit_type=UnitType(unit.get("unit_type") or "composite_question"),
                note=f"sub-question segmented on printed label {label!r} (L{s}-L{e})",
            )
        )
    return bodies, materials


def _standalone_body(
    unit: dict, ctx: MappingContext, asset_sink: list, log: dict
):
    base = unit["unit_id"].lower()
    stem = unit.get("stem_lines")
    parent_blocks = []
    table = None
    if stem:
        r = extract_range(ctx.lines, stem[0], stem[1])
        parent_blocks = _blocks_from_raw(r.blocks, asset_sink, ctx, base)

    opt_specs = [
        {"label": o["label"], "start": o["start_line"], "end": o["end_line"]}
        for o in (unit.get("options") or [])
    ]
    options_raw, shared_table = None, None
    if opt_specs:
        from .extract import OptionSpec

        options_raw, shared_table = extract_options(
            ctx.lines,
            [OptionSpec(label=o["label"], start=o["start"], end=o["end"]) for o in opt_specs],
        )
        log["option_mode"] = (
            "shared_html_table" if shared_table is not None else "independent_ranges"
        )
    if shared_table is not None:
        st = _raw_table_to_table_block(
            shared_table,
            unit["options_lines"][0] if unit.get("options_lines") else None,
            unit["options_lines"][1] if unit.get("options_lines") else None,
        )
        parent_blocks = list(parent_blocks) + [st]

    options = tuple(
        OptionItem(
            label=o["label"],
            blocks=tuple(_blocks_from_raw(o["blocks"], asset_sink, ctx, base)),
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
    for key in ("extra_lines", "explanation_lines"):
        r = unit.get(key)
        if not r:
            continue
        ranges.append({"field": key, "line_start": r[0], "line_end": r[1]})
        res = extract_range(ctx.lines, r[0], r[1])
        blocks_raw.extend(res.blocks)
    blocks = _blocks_from_raw(blocks_raw, asset_sink, ctx, "explanation_blocks")
    log["explanation_ranges"] = ranges
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

    explanation_blocks = _explanation_blocks(unit, ctx, asset_sink, log)

    # 答案区图片（C-CLOSURE C1）：必须在 assets 收口前登记。
    ans_img_records = tuple(_answer_region_images(unit, ctx, asset_sink, log))

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

    content = QuestionContent(
        bodies=tuple(bodies),
        materials=tuple(materials),
        assets=assets,
    )

    answers = _build_answers(unit, attribution, log)
    evidence = _build_evidence(
        unit, answers, ctx, attribution, log, extra_records=ans_img_records
    )

    qtype = question_type(unit)
    declared_value = (unit.get("answer_evidence") or {}).get("value")
    declaration = StrictAnswerDeclaration(
        attribution=attribution,
        evidence_kind=(unit.get("answer_evidence") or {}).get("type") or "absent",
        declared_value=declared_value if attribution != "not_attributable" else None,
        table_row_locator=(unit.get("answer_evidence") or {}).get("table_row_locator"),
        completeness=(
            Completeness.INCOMPLETE
            if attribution == "not_attributable"
            else Completeness.COMPLETE
        ),
    )
    log["declaration"] = declaration.model_dump(mode="json")

    # core.completeness：全部 TypedAnswer FULL 且归属可确认才允许 complete（F2）
    all_full = bool(answers) and all(
        a.completeness == AnswerCompleteness.FULL for a in answers
    )
    core_completeness = (
        Completeness.COMPLETE
        if (attribution != "not_attributable" and all_full)
        else Completeness.INCOMPLETE
    )
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

    candidate = PreprocessingCandidate(core=core_import, source=source)

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
