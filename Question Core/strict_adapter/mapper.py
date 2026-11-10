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


def _register_answer_asset(asset_ref: str, asset_sink: list, ctx: MappingContext) -> str:
    """答案图片槽位的 canonical asset_id 解析（DSH Phase3 基线 §0.2）。

    `asset_ref` 是无扩展名 stem；唯一命中 manifest.image_assets 的 src stem。
    已登记资产只提升 role 为 answer_image（查询便利），不重复登记。
    """
    stem = asset_ref.rsplit(".", 1)[0]
    # 唯一命中校验
    hits = [
        m
        for _, m in ctx.image_by_line.items()
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


def _essay_model_text_covered(unit: dict, log: dict) -> bool:
    """Owner D-1：作文范文条目须被解析区行区覆盖，才算作答参考已保留。"""
    expl = unit.get("explanation_lines")
    extra = unit.get("extra_lines")
    ranges = [r for r in (expl, extra) if r]
    if not ranges:
        return False
    for item in unit.get("answers") or []:
        lines = item.get("evidence_lines")
        if not lines or lines[0] is None:
            continue
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
    """印刷标签归一为数字键：``（1）``/``(1)``/``1`` → ``1``。"""
    import re

    if not label:
        return ""
    m = re.search(r"(\d+)", label)
    return m.group(1) if m else str(label).strip().upper()


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
    # 单值多选（题型明确）
    if qtype in ("multi_choice", "multiple_choice") and len(sub_items) == 1:
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
    # 单值单选（值形 = 单个 A–H 标签）
    if len(sub_items) == 1:
        raw = (sub_items[0].get("value_text") or "").strip()
        if qtype == "single_choice" or (
            len(raw) == 1 and "A" <= raw.upper() <= "H"
        ):
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
            if any(v is None for v in values)
            else "none"
        ),
        statements=fb_statements,
        slot_bindings=tuple(slot_bindings),
        note="; ".join(notes) or None,
    )
    return ans


def _build_answers(
    unit: dict,
    attribution: str,
    log: dict,
    *,
    sub_id_map: dict | None = None,
    asset_resolver=None,
    override_reason: str | None = None,
) -> tuple:
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

    # ---- 分组：composite 按 sub_label；standalone 为单对象 ----
    is_composite = (unit.get("unit_type") == "composite_question")
    groups: list[tuple[str | None, list[dict]]] = []
    seen: dict[str, int] = {}
    for it in prepared:
        key = it.get("sub_label")
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
        if any(i.get("value_text") is None and not i.get("asset_ref") for i in sub_items):
            return "disputed"
        if attribution == "not_attributable":
            return "partially_attributed"
        return "attributed"

    answers_out = []
    if is_composite:
        subs = []
        for sub_index, (sub_label, sub_items) in enumerate(groups):
            sub_statements = []
            slot_bindings = []
            for j, it in enumerate(sub_items):
                slot_id = _derive_slot_id(it, j, sub_label)
                stmt_value = it.get("value_text")
                if stmt_value is None and it.get("asset_ref"):
                    stmt_value = (
                        it.get("note")
                        or f"（图片答案：{it.get('asset_ref')}）"
                    )
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
                    (it.get("slot_id") or "").strip(),
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
                        sub_body_local_id=(sub_id_map or {}).get(
                            _norm_label_key(sub_label)
                        ),
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
                    sub_body_local_id=(sub_id_map or {}).get(
                        _norm_label_key(sub_label)
                    ),
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
                (it.get("slot_id") or "").strip(),
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

    # ---- 答案对象（answers[] 逐条消费；在 assets 收口前完成以便答案图登记）----
    sub_id_map: dict[str, str] = {}
    for b in bodies:
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

    content = QuestionContent(
        bodies=tuple(bodies),
        materials=tuple(materials),
        assets=assets,
    )

    evidence = _build_evidence(
        unit,
        answers,
        ctx,
        attribution,
        log,
        extra_records=ans_img_records,
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
        covered = _essay_model_text_covered(unit, log)
        core_completeness = (
            Completeness.COMPLETE if covered else Completeness.INCOMPLETE
        )
        log["essay_coverage"] = covered
    else:
        core_completeness = (
            Completeness.COMPLETE if all_full else Completeness.INCOMPLETE
        )
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
