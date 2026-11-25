"""Read-only exporter: QCore aggregates -> semantic catalog entries.

Unlike ``qcore_source.build_snapshot`` this includes **all** admitted questions,
not only published ones. That is required for Track A evaluation: the isolated
expansion database intentionally keeps every imported question in
``pending_review`` / ``unpublished`` (Admission never auto-publishes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..config import load_settings
from ..qcore_source import build_catalog_entry, subject_of

SUBJECT_KEYWORDS = ("语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治")


def _subject(source_document_id: str) -> str:
    for keyword in SUBJECT_KEYWORDS:
        if keyword in (source_document_id or ""):
            return keyword
    return subject_of(source_document_id)


def _import_qcore(root: Path) -> None:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def export_catalog(
    database_url: str | None = None,
    *,
    qcore_root: Path | None = None,
) -> list[dict[str, Any]]:
    settings = load_settings()
    url = database_url or settings.qcore_database_url
    if not url:
        raise RuntimeError("QCORE_DATABASE_URL is empty")
    root = qcore_root or settings.qcore_root
    _import_qcore(root)

    from question_core.persistence import (  # noqa: PLC0415
        DatabaseSettings,
        QuestionCoreRepository,
        session_scope,
    )

    db_settings = DatabaseSettings.from_env({"QCORE_DATABASE_URL": url})
    engine = create_engine(
        db_settings.url,
        pool_pre_ping=True,
        future=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    entries: list[dict[str, Any]] = []
    with session_scope(engine) as session:
        read_only = session.execute(text("show transaction_read_only")).scalar()
        if str(read_only).lower() not in {"on", "true", "1"}:
            raise RuntimeError(f"refusing to export without read-only transaction: {read_only}")
        repo = QuestionCoreRepository(session)
        qids = [
            row[0]
            for row in session.execute(text("select question_id from qcore_questions order by question_id"))
        ]
        for qid in qids:
            agg = repo.get_question_aggregate(qid)
            revs = list(agg.revisions)
            if not revs:
                continue
            rev = agg.published_revision() or max(revs, key=lambda r: r.revision_number)
            inst = agg.instances[0] if agg.instances else None
            source_document_id = inst.source_document_id if inst else ""
            payload = rev.model_dump(mode="json")
            latest = None
            for snap in agg.state_history:
                if str(snap.revision_id) == str(rev.revision_id):
                    latest = snap
            bundle = {
                "question_id": str(agg.identity.question_id),
                "revision_id": str(rev.revision_id),
                "revision_number": rev.revision_number,
                "question_type": payload.get("question_type"),
                "content_hash": payload.get("content_hash"),
                "subject": _subject(source_document_id),
                "source_document_id": source_document_id,
                "printed_number": inst.printed_number if inst else None,
                "section": inst.section if inst else None,
                "question_numbers": list(inst.question_numbers) if inst else [],
                "line_start": inst.line_start if inst else None,
                "line_end": inst.line_end if inst else None,
                "content": payload.get("content") or {},
                "answers": payload.get("answers") or [],
                "explanation_blocks": payload.get("explanation_blocks") or [],
                "answer_visibility": payload.get("answer_visibility"),
                "explanation_visibility": payload.get("explanation_visibility"),
                "review_state": str(getattr(latest, "review", "")) if latest else None,
                "publication_state": str(getattr(latest, "publication", "")) if latest else None,
                "assets": (payload.get("content") or {}).get("assets") or [],
            }
            entry = build_catalog_entry(bundle, {})
            entry["review_state"] = bundle["review_state"]
            entry["publication_state"] = bundle["publication_state"]
            entry["published"] = bool(agg.published_revision())
            entries.append(entry)
    return entries


def write_catalog(entries: list[dict[str, Any]], out: str | Path) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "count": len(entries),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return path
