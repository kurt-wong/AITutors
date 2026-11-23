"""Student-facing read API with strict visibility enforcement.

新建最小学生读取 API（FastAPI）。规则（契约 Visibility 语义）：

* 未发布（无 PUBLISHED revision）的 Question 对学生完全不可见。
* 已发布：题干/选项/材料/图片（content）可见。
* 答案 / 解析 / 证据按各自 visibility 枚举控制：
  ``review_only`` 对学生永不返回；``student_after_submit`` 仅在
  ``submitted=true`` 时返回；``public`` 返回。
* 响应脱敏：不暴露 ingestion/idempotency/content_hash/内部 note/证据定位符
  等内部字段。

不复用 ARCHIVE V3 的 student_questions 路由——本模块为当前架构新写。
"""

from __future__ import annotations

import re
from typing import Callable

from fastapi import FastAPI, HTTPException, Query

VISIBILITY_RANK = {"review_only": 0, "student_after_submit": 1, "public": 2}


def field_visible(visibility: str, submitted: bool) -> bool:
    """review_only → 永不；student_after_submit → 仅提交后；public → 总是。"""
    rank = VISIBILITY_RANK.get(visibility, 0)
    if rank >= 2:
        return True
    if rank == 1:
        return bool(submitted)
    return False


def _block_public(block) -> dict:
    """内容块对学生可见形态（去内部 note）。"""
    kind = block.get("kind") if isinstance(block, dict) else block.kind
    if isinstance(block, dict):
        data = dict(block)
    else:
        data = block.model_dump(mode="json")
    if kind == "text":
        return {"kind": "text", "text": data["text"]}
    if kind == "image":
        return {"kind": "image", "asset_id": data["asset_id"], "alt_text": data.get("alt_text")}
    if kind == "table":
        return {
            "kind": "table",
            "n_rows": data["n_rows"],
            "n_cols": data["n_cols"],
            "cells": [
                {
                    "row_index": c["row_index"],
                    "col_index": c["col_index"],
                    "content": c["content"],
                }
                for c in data["cells"]
            ],
        }
    return {"kind": kind}


def _content_public(content, *, with_order_meta: bool = False) -> dict:
    data = content.model_dump(mode="json")
    # C-CLOSURE C1：学生端只暴露「学生可见内容块实际引用」的资产。
    # 答案区资产（target_path=/answers，不被任何内容块引用）绝不下发。
    referenced: set[str] = set()

    def collect_refs(blocks):
        for b in blocks:
            if isinstance(b, dict) and b.get("kind") == "image":
                referenced.add(b.get("asset_id"))

    for b in data["bodies"]:
        collect_refs(b["stem_blocks"])
        for o in b["options"]:
            collect_refs(o["blocks"])
    for m in data["materials"]:
        collect_refs(m["blocks"])

    # AF2-C 顺序元数据（仅验收通道启用；正式契约输出不变）：
    # 块级 line_start/line_end（图块回退 asset note 的 line_no）+ body.material_ids
    # + material 行区——渲染层据此按源行序合并 materials/bodies，修复 materials-first
    # 顺序错位（Q19/语文材料顺序）。
    line_by_asset: dict[str, int] = {}
    if with_order_meta:
        for a in data["assets"]:
            m = re.search(r"line_no=(\d+)", a.get("note") or "")
            if m:
                line_by_asset[str(a.get("asset_id"))] = int(m.group(1))

    def with_lines(b: dict) -> dict:
        out = _block_public(b)
        if with_order_meta:
            ls, le = b.get("line_start"), b.get("line_end")
            if out.get("kind") == "image":
                ls = ls if ls is not None else line_by_asset.get(str(b.get("asset_id")))
                le = le if le is not None else ls
            out["line_start"] = ls
            out["line_end"] = le
        return out

    def body_min_line(b: dict):
        vals = [
            y.get("line_start")
            for y in b["stem_blocks"]
            if isinstance(y, dict) and y.get("line_start") is not None
        ]
        if not vals:
            vals = [
                line_by_asset.get(str(y.get("asset_id")))
                for y in b["stem_blocks"]
                if isinstance(y, dict) and y.get("kind") == "image"
            ]
            vals = [v for v in vals if v is not None]
        return min(vals) if vals else None

    return {
        "bodies": [
            {
                "local_id": b["local_id"],
                "question_type": b["question_type"],
                "printed_number": b["printed_number"],
                "stem_blocks": [with_lines(x) for x in b["stem_blocks"]],
                "options": [
                    {
                        "label": o["label"],
                        "blocks": [with_lines(x) for x in o["blocks"]],
                    }
                    for o in b["options"]
                ],
                "parent_question_ref": b["parent_question_ref"],
                "sub_question_ids": b["sub_question_ids"],
                **(
                    {"material_ids": list(b.get("material_ids") or []),
                     "line_start": body_min_line(b)}
                    if with_order_meta else {}
                ),
            }
            for b in data["bodies"]
        ],
        "materials": [
            {
                "material_id": m["material_id"],
                "blocks": [with_lines(x) for x in m["blocks"]],
                **(
                    {"line_start": m.get("line_start"), "line_end": m.get("line_end")}
                    if with_order_meta else {}
                ),
            }
            for m in data["materials"]
        ],
        "assets": [
            {
                "asset_id": a["asset_id"],
                "storage_path": a["storage_path"],
                "mime_type": a["mime_type"],
            }
            for a in data["assets"]
            if a["asset_id"] in referenced
        ],
    }


def _answers_public(answers) -> list[dict]:
    out = []
    for a in answers:
        d = a.model_dump(mode="json")
        out.append(
            {
                "answer_type": d["answer_type"],
                "answer_value": d["answer_value"],
                "answer_display": d["answer_display"],
                "grading_rule": d["grading_rule"],
                "completeness": d["completeness"],
            }
        )
    return out


def build_student_detail(aggregate, submitted: bool) -> dict | None:
    """已发布 revision 的学生视图；未发布返回 None。"""
    rev = aggregate.published_revision()
    if rev is None:
        return None
    detail = {
        "question_id": str(aggregate.identity.question_id),
        "revision_id": str(rev.revision_id),
        "revision_number": rev.revision_number,
        "question_type": rev.question_type.value
        if hasattr(rev.question_type, "value")
        else rev.question_type,
        # C-AF2-1（Owner 授权 2026 AF3）：下发行序元数据（block line_start/line_end、
        # body material_ids、material 行区）——可选字段，学生可见内容零变化；
        # DT 渲染器据以按源行序合并 materials/bodies（修复 Q19/语文材料顺序错位）。
        "content": _content_public(rev.content, with_order_meta=True),
        "answer_visible": field_visible(
            rev.answer_visibility.value
            if hasattr(rev.answer_visibility, "value")
            else rev.answer_visibility,
            submitted,
        ),
        "explanation_visible": field_visible(
            rev.explanation_visibility.value
            if hasattr(rev.explanation_visibility, "value")
            else rev.explanation_visibility,
            submitted,
        ),
    }
    if detail["answer_visible"]:
        detail["answers"] = _answers_public(rev.answers)
    else:
        detail["answers"] = []
        detail["answers_note"] = "answers hidden by visibility policy"
    if detail["explanation_visible"]:
        detail["explanation_blocks"] = [
            _block_public(b) for b in rev.explanation_blocks
        ]
    else:
        detail["explanation_blocks"] = []
        detail["explanation_note"] = "explanation hidden by visibility policy"
    return detail


def build_student_list(aggregates) -> list[dict]:
    out = []
    for agg in aggregates:
        rev = agg.published_revision()
        if rev is None:
            continue
        inst = agg.instances[0] if agg.instances else None
        out.append(
            {
                "question_id": str(agg.identity.question_id),
                "revision_id": str(rev.revision_id),
                "printed_number": inst.printed_number if inst else None,
                "section": inst.section if inst else None,
                "question_type": rev.question_type.value
                if hasattr(rev.question_type, "value")
                else rev.question_type,
            }
        )
    return out


def create_student_app(reader: Callable[[], list]) -> FastAPI:
    """reader() → 全部 QuestionAggregate（数据库读取由调用方提供）。"""
    app = FastAPI(title="qcore-student-api", version="0.1.0")

    @app.get("/student/questions")
    def list_questions() -> dict:
        aggs = reader()
        items = build_student_list(aggs)
        return {"count": len(items), "questions": items}

    @app.get("/student/questions/{question_id}")
    def get_question(
        question_id: str,
        submitted: bool = Query(default=False),
    ) -> dict:
        aggs = reader()
        for agg in aggs:
            if str(agg.identity.question_id) == question_id:
                detail = build_student_detail(agg, submitted)
                if detail is None:
                    # 未发布：不得泄漏存在性之外的任何内容
                    raise HTTPException(
                        status_code=404,
                        detail="question not available",
                    )
                return detail
        raise HTTPException(status_code=404, detail="question not available")

    return app
