"""Revision-isolated TeachingScript cache.

The cache key is the spec §19 tuple. The on-disk path repeats every key
component, so a new revision can never overwrite the previous revision's
script: old scripts stay addressable for audit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .models import CACHE_KEY_FIELDS


def _safe(value: str) -> str:
    return str(value).replace("|", "_").replace("/", "_").replace("\\", "_")


def script_dir(
    settings: Settings,
    *,
    question_id: str,
    revision_id: str,
    language: str,
    script_schema_version: str,
    prompt_version: str,
    model: str,
    renderer_version: str,
) -> Path:
    return (
        settings.data_dir
        / "scripts"
        / _safe(question_id)
        / _safe(revision_id)
        / _safe(language)
        / _safe(script_schema_version)
        / _safe(prompt_version)
        / _safe(model)
        / _safe(renderer_version)
    )


def _dir_from_script(settings: Settings, script: dict[str, Any]) -> Path:
    return script_dir(
        settings,
        question_id=str(script["question_id"]),
        revision_id=str(script["revision_id"]),
        language=str(script["language"]),
        script_schema_version=str(script["script_schema_version"]),
        prompt_version=str(script["prompt_version"]),
        model=str(script["model"]),
        renderer_version=str(script["renderer_version"]),
    )


def save(settings: Settings, script: dict[str, Any]) -> Path:
    directory = _dir_from_script(settings, script)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "script.json"
    tmp = directory / "script.json.tmp"
    tmp.write_text(
        json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
    )
    tmp.replace(path)
    _append_index(settings, script, path)
    return path


def load(
    settings: Settings,
    *,
    question_id: str,
    revision_id: str,
    language: str,
    script_schema_version: str,
    prompt_version: str,
    model: str,
    renderer_version: str,
) -> dict[str, Any] | None:
    directory = script_dir(
        settings,
        question_id=question_id,
        revision_id=revision_id,
        language=language,
        script_schema_version=script_schema_version,
        prompt_version=prompt_version,
        model=model,
        renderer_version=renderer_version,
    )
    path = directory / "script.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _append_index(settings: Settings, script: dict[str, Any], path: Path) -> None:
    index_path = settings.data_dir / "scripts" / "index.json"
    records: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            records = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            records = []
    key = script["cache_key"]
    records = [r for r in records if r.get("cache_key") != key]
    records.append(
        {
            "cache_key": key,
            **{field: script.get(field) for field in CACHE_KEY_FIELDS},
            "script_id": script.get("script_id"),
            "content_hash": script.get("content_hash"),
            "validation": (script.get("validation") or {}).get("status"),
            "steps": len(script.get("steps") or []),
            "path": str(path.relative_to(settings.data_dir)),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
    )
    tmp.replace(index_path)


def list_scripts(settings: Settings) -> list[dict[str, Any]]:
    index_path = settings.data_dir / "scripts" / "index.json"
    if not index_path.is_file():
        return []
    return json.loads(index_path.read_text(encoding="utf-8"))


def revision_isolated(settings: Settings, question_id: str) -> list[str]:
    """All revision ids that have a cached script for one question."""
    root = settings.data_dir / "scripts" / _safe(question_id)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())
