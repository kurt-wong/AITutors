# -*- coding: utf-8 -*-
"""PBA 隔离验收候选读取服务（QCORE-PRE-BULK-OWNER-ACCEPTANCE-01-R1，只读）。

职责：为 Owner 目视验收提供 `qcore_prebulk_accept_01` **全部候选**（含
pending_review / incomplete / not_ready）的读取通道——**验收可见性 ≠ 学生可见性**：
Admission 完整性是生产质量判定，不是禁止检查候选的理由。

硬边界：
- 仅绑定隔离验收库（fail-closed 断言），零写入路径；
- 不使用正式 Student API 的发布过滤作为验收读取条件（正式 :8811 行为零改动）；
- 答案/解析仍按 field_visible 可见性保护（review_only 不下发；不接受 submitted
  绕过——submitted 参数忽略，与正式契约一致处保持，不放宽保护）；
- 不做发布/状态迁移；不对正式学生提供访问；
- 页面须标注验收环境与每题 Admission 状态（由响应字段承载）。

响应形状与 Student API 同构（复用 student_api 的 _content_public/_block_public/
field_visible 整形件），差异仅：列表不过滤发布态 + 附加 admission 元数据 + 资产 URL。

运行：
  QCORE_DATABASE_URL=.../qcore_prebulk_accept_01 python acceptance_candidate_server.py --port 8814
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote

_QC_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_QC_ROOT), str(_QC_ROOT / "strict_adapter")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RUN_ROOT = Path(os.environ.get(
    "QCORE_ACCEPTANCE_RUN_ROOT",
    r"D:\Project\AITutors\runs\qcore_prebulk_owner_acceptance_01",
))
OCR_ROOT = RUN_ROOT / "production" / "ocr"
SUBJECTS = ["化学", "数学", "物理", "生物", "英语", "语文", "历史", "地理", "政治"]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def subject_of(source_document_id: str) -> str | None:
    hits = [s for s in SUBJECTS if s in (source_document_id or "")]
    return hits[0] if len(hits) == 1 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8814)
    ap.add_argument("--bind", default="127.0.0.1")
    args = ap.parse_args()

    from question_core.persistence import (
        DatabaseSettings,
        QuestionCoreRepository,
        create_db_engine,
        session_scope,
    )
    from strict_adapter.student_api import (
        _block_public,
        _content_public,
        field_visible,
    )
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, JSONResponse
    import uvicorn

    settings = DatabaseSettings.from_env()
    expected_db = os.environ.get(
        "QCORE_ACCEPTANCE_DBNAME", "qcore_prebulk_accept_01"
    )
    assert settings.dbname == expected_db, (
        f"acceptance candidate server must bind {expected_db}, "
        f"got {settings.dbname}"
    )
    engine = create_db_engine(settings)

    def load_all():
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            out = []
            ids = session.execute(
                __import__("sqlalchemy").text("select question_id from qcore_questions order by question_id")
            )
            for (qid,) in ids:
                agg = repo.get_question_aggregate(qid)
                if agg is not None:
                    out.append(agg)
            return out

    def admission_meta(agg):
        snap = None
        if agg.state_history:
            snap = agg.state_history[-1]
        inst = agg.instances[0] if agg.instances else None
        return {
            "admission_review": str(snap.review.value if hasattr(snap.review, "value") else snap.review) if snap else None,
            "admission_completeness": str(snap.completeness.value if hasattr(snap.completeness, "value") else snap.completeness) if snap else None,
            "publication_state": str(snap.publication.value if hasattr(snap.publication, "value") else snap.publication) if snap else None,
            "source_document_id": inst.source_document_id if inst else None,
        }

    def asset_url(subject: str | None, storage_path: str) -> str | None:
        if not subject or not storage_path:
            return None
        fn = storage_path.replace("\\", "/").split("/")[-1]
        if Path(fn).suffix.lower() not in IMAGE_SUFFIXES:
            return None
        # 绝对 URL：<img> 直连候选服务（跨源图片无需 CORS）。相对路径会被浏览器
        # 按页面源解析到 :3782 而 404（R1 复核实证的破图根因）。
        from urllib.parse import quote as _q
        return f"http://{args.bind}:{args.port}/assets/{_q(subject)}/{_q(fn)}"

    def attach_urls(content: dict, subject: str | None) -> dict:
        url_by_asset = {}
        for a in content.get("assets") or []:
            a["url"] = asset_url(subject, a.get("storage_path") or "")
            url_by_asset[str(a.get("asset_id") or "")] = a["url"]

        def walk(blocks):
            for b in blocks or []:
                if b.get("kind") == "image":
                    aid = str(b.get("asset_id") or "")
                    b["url"] = url_by_asset.get(aid) or asset_url(
                        subject, (b.get("storage_path") or ""))
        for body in content.get("bodies") or []:
            walk(body.get("stem_blocks"))
            for o in body.get("options") or []:
                walk(o.get("blocks"))
        for m in content.get("materials") or []:
            walk(m.get("blocks"))
        return content

    app = FastAPI(title="qcore-acceptance-candidates", version="0.1.0")

    @app.get("/student/questions")
    def list_questions():
        rows = []
        for agg in load_all():
            rev = agg.current_revision()
            inst = agg.instances[0] if agg.instances else None
            meta = admission_meta(agg)
            rows.append({
                "question_id": str(agg.identity.question_id),
                "revision_id": str(rev.revision_id),
                "printed_number": inst.printed_number if inst else None,
                "section": inst.section if inst else None,
                "question_type": rev.question_type.value if hasattr(rev.question_type, "value") else rev.question_type,
                **meta,
            })
        return {"count": len(rows), "questions": rows}

    @app.get("/student/questions/{question_id}")
    def get_question(question_id: str, submitted: bool = False):
        # N-R1-1 修正：submitted 参数**真正忽略**（固定 False）——验收读取绝不因
        # 自报提交放开可见性（不以 submitted 绕过答案保护）。即使未来候选带
        # student_after_submit 可见性，?submitted=true 也不会下发答案。
        submitted = False
        from uuid import UUID
        try:
            qid = UUID(question_id)
        except ValueError:
            raise HTTPException(404, "question not available")
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            agg = repo.get_question_aggregate(qid)
        if agg is None:
            raise HTTPException(404, "question not available")
        rev = agg.current_revision()
        meta = admission_meta(agg)
        subject = subject_of(meta["source_document_id"])
        content = attach_urls(_content_public(rev.content, with_order_meta=True), subject)
        answer_vis = rev.answer_visibility.value if hasattr(rev.answer_visibility, "value") else rev.answer_visibility
        expl_vis = rev.explanation_visibility.value if hasattr(rev.explanation_visibility, "value") else rev.explanation_visibility
        detail = {
            "question_id": str(agg.identity.question_id),
            "revision_id": str(rev.revision_id),
            "revision_number": rev.revision_number,
            "question_type": rev.question_type.value if hasattr(rev.question_type, "value") else rev.question_type,
            "content": content,
            "answer_visible": field_visible(answer_vis, submitted),
            "explanation_visible": field_visible(expl_vis, submitted),
            **meta,
        }
        if detail["answer_visible"]:
            from strict_adapter.student_api import _answers_public
            detail["answers"] = _answers_public(rev.answers)
        else:
            detail["answers"] = []
            detail["answers_note"] = "answers hidden by visibility policy"
        if detail["explanation_visible"]:
            detail["explanation_blocks"] = [_block_public(b) for b in rev.explanation_blocks]
        else:
            detail["explanation_blocks"] = []
            detail["explanation_note"] = "explanation hidden by visibility policy"
        return detail

    @app.get("/assets/{subject}/{filename}")
    def get_asset(subject: str, filename: str):
        if subject not in SUBJECTS:
            raise HTTPException(404, "asset not found")
        name = unquote(filename)
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise HTTPException(404, "asset not found")
        target = (OCR_ROOT / subject / "imgs" / name).resolve()
        try:
            target.relative_to(OCR_ROOT.resolve())
        except ValueError:
            raise HTTPException(404, "asset not found")
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES or not target.is_file():
            raise HTTPException(404, "asset not found")
        return FileResponse(target)

    uvicorn.run(app, host=args.bind, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
