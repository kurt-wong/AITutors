"""Read-only Question Core source.

The compiler never opens a writable connection. The engine is created with
``default_transaction_read_only=on`` so PostgreSQL itself rejects any write the
code (or a future refactor) might attempt. The snapshot is a *derived* pilot
artifact under ``data/``; it is never written back.

Every published Revision is read through the canonical aggregate
(``QuestionCoreRepository.get_question_aggregate``) — the same read path the
Student API uses — so the compiler cannot invent question facts.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, ensure_dirs

SUBJECT_KEYWORDS = ("数学", "语文", "英语", "化学", "物理", "生物")

#: block kinds that may carry a figure / table inside the student content.
_BLOCK_ASSET_KIND = "image"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def subject_of(source_document_id: str) -> str:
    for keyword in SUBJECT_KEYWORDS:
        if keyword in (source_document_id or ""):
            return keyword
    return "unknown"


def _import_qcore(qcore_root: Path) -> None:
    root = str(qcore_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _make_engine(url: str):
    from sqlalchemy import create_engine

    return create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
    )
    tmp.replace(path)


def load_asset_allowlist(path: Path) -> dict[str, dict[str, Any]]:
    """asset_id → allowlist entry (url_path / content_hash / mime_type)."""
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = doc.get("allowlist") or []
    return {str(e.get("asset_id")): e for e in entries if e.get("asset_id")}


def flatten_blocks(blocks: list[dict[str, Any]]) -> str:
    """Concatenate the human-readable text of one block list."""
    parts: list[str] = []
    for block in blocks or []:
        kind = block.get("kind")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "table":
            for cell in block.get("cells") or []:
                parts.append(str(cell.get("content") or ""))
        elif kind == "image":
            parts.append(" ")  # images carry no searchable text
    return "\n".join(p.strip() for p in parts if p.strip())


def _blocks_have(blocks: list[dict[str, Any]], kind: str) -> bool:
    return any((b or {}).get("kind") == kind for b in blocks or [])


def build_catalog_entry(bundle: dict[str, Any], allowlist: dict[str, dict[str, Any]]) -> dict[str, Any]:
    content = bundle.get("content") or {}
    bodies = content.get("bodies") or []
    materials = content.get("materials") or []
    explanation = bundle.get("explanation_blocks") or []

    stem_texts: list[str] = []
    option_texts: list[str] = []
    has_image = False
    has_table = False
    for body in bodies:
        stem = body.get("stem_blocks") or []
        stem_texts.append(flatten_blocks(stem))
        has_image = has_image or _blocks_have(stem, "image")
        has_table = has_table or _blocks_have(stem, "table")
        for option in body.get("options") or []:
            option_texts.append(flatten_blocks(option.get("blocks") or []))
            has_image = has_image or _blocks_have(option.get("blocks") or [], "image")
            has_table = has_table or _blocks_have(option.get("blocks") or [], "table")
    material_texts = []
    for material in materials:
        blocks = material.get("blocks") or []
        material_texts.append(flatten_blocks(blocks))
        has_image = has_image or _blocks_have(blocks, "image")
        has_table = has_table or _blocks_have(blocks, "table")
    explanation_text = flatten_blocks(explanation)
    has_table = has_table or any(b.get("kind") == "table" for b in explanation)

    search_text = "\n".join(
        x
        for x in (
            "\n".join(stem_texts),
            "\n".join(material_texts),
            "\n".join(option_texts),
            explanation_text,
        )
        if x
    )
    has_math = "$" in search_text

    answers = bundle.get("answers") or []
    answer_display = " | ".join(
        str(a.get("answer_display") or a.get("answer_value") or "") for a in answers
    ).strip()
    asset_ids = [str(a.get("asset_id")) for a in (bundle.get("assets") or []) if a.get("asset_id")]
    unresolved_assets = [aid for aid in asset_ids if aid not in allowlist]
    answer_attribution = sorted(
        {str(a.get("attribution") or "unknown") for a in answers}
    )

    return {
        "question_id": bundle["question_id"],
        "revision_id": bundle["revision_id"],
        "revision_number": bundle.get("revision_number"),
        "question_type": bundle.get("question_type"),
        "subject": bundle.get("subject"),
        "source_document_id": bundle.get("source_document_id"),
        "printed_number": bundle.get("printed_number"),
        "section": bundle.get("section"),
        "content_hash": bundle.get("content_hash"),
        "answer_display": answer_display,
        "answer_count": len(answers),
        "answer_attribution": answer_attribution,
        "has_image": has_image,
        "has_table": has_table,
        "has_math": has_math,
        "explanation_blocks": len(explanation),
        "stem_text": "\n".join(t for t in stem_texts if t),
        "material_text": "\n".join(t for t in material_texts if t),
        "options_text": "\n".join(t for t in option_texts if t),
        "explanation_text": explanation_text,
        "search_text": search_text,
        "asset_ids": asset_ids,
        "unresolved_assets": unresolved_assets,
        "published": True,
    }


def build_snapshot(settings: Settings, *, only_published: bool = True) -> dict[str, Any]:
    """One pass over Question Core → ``data/qcore``. Returns meta/stats."""
    if not settings.qcore_database_url:
        raise RuntimeError(
            "QCORE_DATABASE_URL is empty; set it in the process env or in "
            "Teaching Script Compiler/.env.local"
        )
    ensure_dirs(settings)
    qcore_root = settings.qcore_root
    _import_qcore(qcore_root)

    from sqlalchemy import text

    from question_core.persistence import (
        DatabaseSettings,
        QuestionCoreRepository,
        session_scope,
    )

    db_settings = DatabaseSettings.from_env({"QCORE_DATABASE_URL": settings.qcore_database_url})
    engine = _make_engine(db_settings.url)
    allowlist = load_asset_allowlist(settings.asset_allowlist)

    bundles_dir = settings.data_dir / "qcore" / "bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)

    catalog: list[dict[str, Any]] = []
    stats = {
        "questions_scanned": 0,
        "published_bundles": 0,
        "skipped_unpublished": 0,
        "by_subject": {},
        "by_type": {},
        "with_explanation": 0,
        "with_image": 0,
        "with_table": 0,
        "unresolved_asset_questions": 0,
        "read_only": None,
    }

    with session_scope(engine) as session:
        read_only = session.execute(text("show transaction_read_only")).scalar()
        stats["read_only"] = str(read_only)
        repo = QuestionCoreRepository(session)
        qids = [
            row[0]
            for row in session.execute(
                text("select question_id from qcore_questions order by question_id")
            )
        ]
        stats["questions_scanned"] = len(qids)
        for qid in qids:
            agg = repo.get_question_aggregate(qid)
            rev = agg.published_revision()
            if rev is None:
                stats["skipped_unpublished"] += 1
                if only_published:
                    continue
                continue
            inst = agg.instances[0] if agg.instances else None
            source_document_id = inst.source_document_id if inst else ""
            latest = None
            for snap in agg.state_history:
                if str(snap.revision_id) == str(rev.revision_id):
                    latest = snap
            payload = rev.model_dump(mode="json")
            bundle = {
                "question_id": str(agg.identity.question_id),
                "revision_id": str(rev.revision_id),
                "revision_number": rev.revision_number,
                "question_type": payload.get("question_type"),
                "content_hash": payload.get("content_hash"),
                "subject": subject_of(source_document_id),
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
                "snapshot_taken_at": _utc_now(),
            }
            entry = build_catalog_entry(bundle, allowlist)
            _write_json(bundles_dir / f"{bundle['question_id']}.json", bundle)
            catalog.append(entry)
            stats["published_bundles"] += 1
            stats["by_subject"][bundle["subject"]] = (
                stats["by_subject"].get(bundle["subject"], 0) + 1
            )
            stats["by_type"][bundle["question_type"]] = (
                stats["by_type"].get(bundle["question_type"], 0) + 1
            )
            stats["with_explanation"] += 1 if bundle["explanation_blocks"] else 0
            stats["with_image"] += 1 if entry["has_image"] else 0
            stats["with_table"] += 1 if entry["has_table"] else 0
            stats["unresolved_asset_questions"] += 1 if entry["unresolved_assets"] else 0

    catalog.sort(
        key=lambda e: (
            str(e.get("source_document_id") or ""),
            e.get("printed_number") or "",
        )
    )
    meta = {
        "built_at": _utc_now(),
        "database": db_settings.dbname,
        "read_only_transaction": stats["read_only"],
        "asset_allowlist": str(settings.asset_allowlist),
        "asset_allowlist_size": len(allowlist),
        "counts": stats,
        "catalog_size": len(catalog),
    }
    _write_json(settings.data_dir / "qcore" / "catalog.json", catalog)
    _write_json(settings.data_dir / "qcore" / "meta.json", meta)
    return meta


def load_catalog(settings: Settings) -> list[dict[str, Any]]:
    path = settings.data_dir / "qcore" / "catalog.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"QCore snapshot missing: {path}; run `python -m tsc_compiler.cli snapshot`"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(settings: Settings, question_id: str) -> dict[str, Any]:
    path = settings.data_dir / "qcore" / "bundles" / f"{question_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"bundle missing for {question_id}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_meta(settings: Settings) -> dict[str, Any]:
    path = settings.data_dir / "qcore" / "meta.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
