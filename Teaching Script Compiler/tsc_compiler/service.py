"""Compile/validate/cache orchestration shared by the CLI and the HTTP API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import cache
from .compiler import CompileError, compile_script
from .config import Settings, ensure_dirs
from .models import (
    DEFAULT_LANGUAGE,
    MODEL_ID,
    PROMPT_VERSION,
    RENDERER_VERSION,
    SCRIPT_SCHEMA_VERSION,
)
from .qcore_source import (
    load_asset_allowlist,
    load_bundle,
    load_catalog,
    subject_of,
)
from .validator import validate_script
from .validator import validate_script


@dataclass
class CompileOutcome:
    question_id: str
    revision_id: str
    status: str
    code: str | None
    message: str | None
    from_cache: bool
    steps: int
    checks_failed: list[str]
    cache_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "revision_id": self.revision_id,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "from_cache": self.from_cache,
            "steps": self.steps,
            "checks_failed": self.checks_failed,
            "cache_path": self.cache_path,
        }


def _allowlist(settings: Settings) -> dict[str, Any]:
    return load_asset_allowlist(settings.asset_allowlist)


def compile_bundle(
    settings: Settings, bundle: dict[str, Any], *, language: str = DEFAULT_LANGUAGE
) -> dict[str, Any]:
    script = compile_script(
        bundle,
        allowlist=_allowlist(settings),
        asset_base=settings.asset_base,
        language=language,
    )
    validate_script(script, bundle, expected_revision_id=bundle["revision_id"])
    return script


def get_or_compile(
    settings: Settings,
    question_id: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    force: bool = False,
    persist: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Return (script, bundle, from_cache). Raises CompileError / FileNotFoundError."""
    ensure_dirs(settings)
    bundle = load_bundle(settings, question_id)
    if force:
        cached = None
    else:
        cached = cache.load(
            settings,
            question_id=question_id,
            revision_id=bundle["revision_id"],
            language=language,
            script_schema_version=SCRIPT_SCHEMA_VERSION,
            prompt_version=PROMPT_VERSION,
            model=MODEL_ID,
            renderer_version=RENDERER_VERSION,
        )
    if cached is not None:
        # Never trust a cached verdict: re-run the full validator against the
        # current bundle. A stale script (older compiler semantics) is rebuilt
        # instead of being served.
        validate_script(
            cached, bundle, expected_revision_id=bundle["revision_id"]
        )
        if (
            (cached.get("validation") or {}).get("status") == "pass"
            and cached.get("content_hash") == bundle.get("content_hash")
        ):
            return cached, bundle, True
    script = compile_bundle(settings, bundle, language=language)
    if persist and script["validation"]["status"] == "pass":
        cache.save(settings, script)
    return script, bundle, False


def compile_catalog(
    settings: Settings,
    *,
    question_ids: list[str] | None = None,
    subject: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    force: bool = False,
    limit: int | None = None,
) -> list[CompileOutcome]:
    catalog = load_catalog(settings)
    by_id = {entry["question_id"]: entry for entry in catalog}
    if question_ids is None:
        selected = [
            entry
            for entry in catalog
            if (subject is None or entry.get("subject") == subject)
        ]
    else:
        selected = [by_id[qid] for qid in question_ids if qid in by_id]
    if limit is not None:
        selected = selected[:limit]
    outcomes: list[CompileOutcome] = []
    for entry in selected:
        qid = entry["question_id"]
        try:
            script, bundle, from_cache = get_or_compile(
                settings, qid, language=language, force=force
            )
            failed = [
                c["name"]
                for c in (script["validation"] or {}).get("checks") or []
                if c["status"] == "fail"
            ]
            outcomes.append(
                CompileOutcome(
                    question_id=qid,
                    revision_id=script["revision_id"],
                    status=str((script["validation"] or {}).get("status")),
                    code=None if not failed else "VALIDATION_FAILED",
                    message=None if not failed else ", ".join(failed),
                    from_cache=from_cache,
                    steps=len(script["steps"]),
                    checks_failed=failed,
                    cache_path=str(
                        cache.script_dir(
                            settings,
                            question_id=qid,
                            revision_id=script["revision_id"],
                            language=language,
                            script_schema_version=SCRIPT_SCHEMA_VERSION,
                            prompt_version=PROMPT_VERSION,
                            model=MODEL_ID,
                            renderer_version=RENDERER_VERSION,
                        )
                    ),
                )
            )
        except CompileError as exc:
            outcomes.append(
                CompileOutcome(
                    question_id=qid,
                    revision_id=entry["revision_id"],
                    status="fail",
                    code=exc.code,
                    message=exc.message,
                    from_cache=False,
                    steps=0,
                    checks_failed=[],
                    cache_path=None,
                )
            )
    return outcomes


def teaching_bundle(
    settings: Settings,
    question_id: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    init_step: str | None = None,
) -> dict[str, Any]:
    """The Teaching Bundle the Interactive Lesson (and DeepTutor) consumes."""
    script, bundle, from_cache = get_or_compile(
        settings, question_id, language=language
    )
    if (script.get("validation") or {}).get("status") != "pass":
        raise CompileError("SCRIPT_INVALID", "script did not pass validation")
    return {
        "question_id": script["question_id"],
        "revision_id": script["revision_id"],
        "revision_number": script["revision_number"],
        "language": language,
        "script_schema_version": SCRIPT_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "from_cache": from_cache,
        "init_step": init_step or "s1",
        "question": {
            "subject": script.get("subject"),
            "source_document_id": script.get("source_document_id"),
            "printed_number": script.get("printed_number"),
            "question_type": script.get("question_type"),
            "title": script.get("title"),
            "content_hash": script.get("content_hash"),
        },
        "script": script,
        "assets": [
            {
                "asset_id": a.get("asset_id"),
                "storage_path": a.get("storage_path"),
                "mime_type": a.get("mime_type"),
            }
            for a in bundle.get("assets") or []
        ],
        "answer_visibility": bundle.get("answer_visibility"),
        "explanation_visibility": bundle.get("explanation_visibility"),
    }


def report_rows(settings: Settings) -> list[dict[str, Any]]:
    """Join catalog + cache index into a per-question acceptance table."""
    catalog = load_catalog(settings)
    index = {row["cache_key"]: row for row in cache.list_scripts(settings)}
    rows: list[dict[str, Any]] = []
    for entry in catalog:
        key = "|".join(
            [
                entry["question_id"],
                entry["revision_id"],
                DEFAULT_LANGUAGE,
                SCRIPT_SCHEMA_VERSION,
                PROMPT_VERSION,
                MODEL_ID,
                RENDERER_VERSION,
            ]
        )
        row = index.get(key)
        rows.append(
            {
                "question_id": entry["question_id"],
                "revision_id": entry["revision_id"],
                "source_document_id": entry.get("source_document_id"),
                "printed_number": entry.get("printed_number"),
                "subject": entry.get("subject"),
                "question_type": entry.get("question_type"),
                "has_image": entry.get("has_image"),
                "has_table": entry.get("has_table"),
                "has_math": entry.get("has_math"),
                "explanation_blocks": entry.get("explanation_blocks"),
                "teaching_script": bool(row),
                "validation": (row or {}).get("validation"),
                "steps": (row or {}).get("steps"),
                "script_id": (row or {}).get("script_id"),
                "cache_path": (row or {}).get("path"),
            }
        )
    return rows


def write_json(path: str, payload: Any) -> None:
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
    )


def subject_for_bundle(bundle: dict[str, Any]) -> str:
    return bundle.get("subject") or subject_of(bundle.get("source_document_id") or "")
