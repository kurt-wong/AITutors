"""Formal Content Audit entrypoint（QCORE-DELIVERY-02-R1-CLOSEOUT）。

唯一正式内容审计入口。硬性规则 A–E 语义与 QCORE-DELIVERY-02-R1 已验证的
`runs/qcore_delivery_02_r1/_scripts/content_audit_r1.py` 逐字一致（同一规则集
的正式化迁移，不重新设计审计体系）：

A 选项非空：每个 OptionItem 至少一个有效非空内容块；空/纯空白 = FAIL。
B 选项覆盖：option_uncovered_lines 非空 = FAIL；声明选项的行内容必须被
  OptionItem 块（option_items 形态）或题干块（stem_text 形态，语文 composite
  既有结构）覆盖，不得以"别处出现过文本"替代映射证明。
C 来源定位：需追溯 TextBlock 必须有合法 line_start/line_end、指向真实源行、
  文本与行域对应；traceable=null/false 均 FAIL。
D 空内容块：普通文本块空内容 = FAIL；仅 composite 父级题干占位空块可显式豁免。
E 状态汇总：状态由检查结果计算；存在任一阻断问题则 unit FAIL；
  problems 清单与状态一致。

正式调用链（fail-closed）：
    strict_adapter.mapper.map_unit / english_composite.map_unit
        → UnitMapping
        → strict_adapter.admission.admit()  # 步骤 0 强制 enforce_content_audit
        → 契约校验 → 准入决策 → 实体构造 → 持久化

`enforce_content_audit(mapping, ctx)` 是唯一门禁函数：审计 FAIL 即抛
`ContentAuditError`（ValueError 子类），阻断准入与持久化，不降级为 warning。
`audit_unit(rec)` 为纯规则函数，供定向测试直接驱动。

历史审计实现（非正式入口，禁止作为质量验收标准）：
- runs/qcore_delivery_02/_scripts/phase3_content_audit.py —— DELIVERY-02
  失败基线证据，已知假阳性风险（曾放行 B1/B2/B3 缺陷），仅作历史证据封存。
- runs/qcore_delivery_02_r1/_scripts/content_audit_r1.py —— R1 运行期证据
  （本规则集的运行冻结副本）；正式代码与测试一律以本模块为唯一入口。
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "ContentAuditError",
    "audit_unit",
    "blocks_of",
    "build_audit_record",
    "enforce_content_audit",
]


class ContentAuditError(ValueError):
    """内容审计硬性规则未通过（fail-closed）。"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def _traceable(block: dict, source_lines: list[str]) -> bool | None:
    """块文本是否可溯源到声明行域：true / false / None（无定位=未验证）。"""
    txt = _norm(block.get("text") or "")
    if not txt:
        return None
    ls, le = block.get("line_start"), block.get("line_end")
    if ls is None or le is None:
        return None
    src = _norm(_strip_tags("\n".join(source_lines[ls - 1:le])))
    return txt in src or _norm(_strip_tags(txt)) in src


def audit_unit(rec: dict[str, Any]) -> dict:
    """对一个单元审计记录执行硬性规则 A–E。返回 {status, problems, details}。"""
    problems: list[str] = []
    details: dict[str, Any] = {}
    source_lines = rec.get("source_lines") or []
    n_src = rec.get("source_line_count") or len(source_lines)

    options = rec.get("options") or []
    stem_blocks = rec.get("stem_blocks") or []
    material_blocks = rec.get("material_blocks") or []
    explanation_blocks = rec.get("explanation_blocks") or []
    shape = rec.get("options_shape") or (
        "option_items" if options else "stem_text")

    # ---- D 空内容块（先行：空块也影响 A/C 判定）----
    def check_blocks(blocks: list[dict], where: str, exempt_empty: bool = False):
        for i, b in enumerate(blocks):
            txt = b.get("text") or ""
            kind = b.get("kind") or "text"
            if kind not in ("text", "math", "chemical"):
                continue  # image/table/material_ref 结构节点另论
            if not txt.strip():
                if exempt_empty and b.get("line_start") is not None:
                    details.setdefault("exempt_empty_blocks", []).append(
                        f"{where}[{i}] structural placeholder "
                        f"L{b.get('line_start')}")
                    continue
                problems.append(f"D: empty text block in {where}[{i}]")

    # A. 选项非空
    for o in options:
        blocks = o.get("blocks") or []
        if not any((b.get("text") or "").strip() for b in blocks):
            problems.append(
                f"A: option {o.get('label')!r} has no non-empty content block")
        check_blocks(blocks, f"option[{o.get('label')}]")

    # D. 其余块（composite 父级题干占位可豁免）
    parent_placeholder = (
        rec.get("is_composite_parent_placeholder") is True)
    check_blocks(stem_blocks, "stem", exempt_empty=parent_placeholder)
    check_blocks(material_blocks, "material")
    check_blocks(explanation_blocks, "explanation")

    # C. 来源定位（有文本的块必须定位且对应）
    def check_locators(blocks: list[dict], where: str):
        for i, b in enumerate(blocks):
            txt = (b.get("text") or "").strip()
            if not txt:
                continue
            ls, le = b.get("line_start"), b.get("line_end")
            if ls is None or le is None:
                problems.append(f"C: missing line locator on {where}[{i}]")
                continue
            if not (1 <= ls <= le <= n_src):
                problems.append(
                    f"C: illegal line range {ls}-{le} on {where}[{i}] "
                    f"(source has {n_src} lines)")
                continue
            t = _traceable(b, source_lines)
            if t is None:
                problems.append(f"C: traceable=null on {where}[{i}] L{ls}-{le}")
            elif t is False:
                problems.append(f"C: traceable=false on {where}[{i}] L{ls}-{le}")

    for o in options:
        check_locators(o.get("blocks") or [], f"option[{o.get('label')}]")
    check_locators(stem_blocks, "stem")
    check_locators(material_blocks, "material")
    check_locators(explanation_blocks, "explanation")

    # B. 选项覆盖
    man_ranges = [tuple(r) for r in (rec.get("manifest_option_lines") or [])]
    uncovered = list(rec.get("option_uncovered_lines") or [])
    if uncovered:
        problems.append(f"B: option_uncovered_lines={uncovered}")
    if man_ranges and shape == "option_items" and options:
        cov_ranges = []
        for o in options:
            for b in o.get("blocks") or []:
                if b.get("line_start"):
                    cov_ranges.append((b["line_start"], b.get("line_end")
                                       or b["line_start"]))
        missing = []
        for ls, le in man_ranges:
            for ln in range(ls, le + 1):
                if ln > n_src:
                    continue
                if not (source_lines and not source_lines[ln - 1].strip()):
                    if not any(a <= ln <= b for a, b in cov_ranges):
                        missing.append(ln)
        if missing:
            problems.append(
                f"B: manifest option lines not covered by option blocks: {missing}")
    elif man_ranges and shape == "stem_text":
        cov = [(b.get("line_start"), b.get("line_end"))
               for b in stem_blocks + material_blocks
               if b.get("line_start")]
        missing = []
        for ls, le in man_ranges:
            for ln in range(ls, le + 1):
                if ln > n_src:
                    continue
                if source_lines and not source_lines[ln - 1].strip():
                    continue
                if not any(a <= ln <= (b or a) for a, b in cov):
                    missing.append(ln)
        if missing:
            problems.append(
                f"B: manifest option lines not covered by stem/material "
                f"blocks (stem_text shape): {missing}")

    # E. 状态汇总
    status = "ok" if not problems else "FAIL"
    details["shape"] = shape
    return {"status": status, "problems": problems, "details": details}


# ---------------------------------------------------------------------------
# 正式导入路径的记录构造与门禁
# ---------------------------------------------------------------------------


def blocks_of(bl) -> list[dict]:
    """契约 ContentBlock 序列 → 审计记录块字典（与 R1 运行期口径一致）。"""
    return [{"kind": getattr(x, "kind", "text"),
             "text": getattr(x, "text", "") or "",
             "line_start": getattr(x, "line_start", None),
             "line_end": getattr(x, "line_end", None)}
            for x in bl]


def build_audit_record(unit: dict, mapping, ctx) -> dict[str, Any]:
    """由 Manifest unit + UnitMapping + MappingContext 构造审计记录。

    字段口径与 R1 验证脚本（phase6_verify）逐项一致，保证 38/38 已验证
    结果可复现。
    """
    content = mapping.candidate.core.content
    parent_bodies = [b for b in content.bodies
                     if b.parent_question_ref is None]
    man_opt_lines = [(o["start_line"], o["end_line"])
                     for o in ((unit or {}).get("options") or [])]
    return {
        "unit_id": mapping.unit_id,
        "source_lines": list(ctx.lines),
        "source_line_count": len(ctx.lines),
        "manifest_option_lines": man_opt_lines,
        "options": [
            {"label": o.label, "blocks": blocks_of(o.blocks),
             "line_start": o.line_start, "line_end": o.line_end}
            for body in content.bodies for o in body.options],
        "stem_blocks": blocks_of(
            [b for body in content.bodies for b in body.stem_blocks]),
        "material_blocks": blocks_of(
            [b for mat in content.materials for b in mat.blocks]),
        "explanation_blocks": blocks_of(mapping.explanation_blocks),
        "options_shape": (
            "option_items" if any(body.options for body in content.bodies)
            else "stem_text"),
        "is_composite_parent_placeholder": (
            (unit or {}).get("unit_type") == "composite_question"
            and len(parent_bodies) == 1
            and len(parent_bodies[0].stem_blocks) == 1
            and not (parent_bodies[0].stem_blocks[0].text or "").strip()
        ),
    }


def enforce_content_audit(mapping, ctx) -> dict:
    """正式唯一审计门禁（fail-closed）。

    在准入决策与任何持久化之前执行硬性规则 A–E；FAIL 即抛
    `ContentAuditError`，不产出可入库的错误 Candidate。
    Manifest 单元缺失同样 fail-closed（无法审计即不得准入）。
    """
    unit = None
    for u in (ctx.manifest or {}).get("units") or []:
        if u.get("unit_id") == mapping.unit_id:
            unit = u
            break
    if unit is None:
        raise ContentAuditError(
            f"{mapping.unit_id}: manifest unit not found in "
            f"MappingContext.manifest['units'] (fail-closed: cannot audit "
            f"without the declared source unit)")
    rec = build_audit_record(unit, mapping, ctx)
    result = audit_unit(rec)
    if result["status"] != "ok":
        raise ContentAuditError(
            f"{mapping.unit_id}: content audit FAIL: {result['problems']}")
    return result
