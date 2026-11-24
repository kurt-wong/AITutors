# -*- coding: utf-8 -*-
"""Revision-isolated cache tests."""

from __future__ import annotations

from conftest import make_bundle
from tsc_compiler import cache
from tsc_compiler.compiler import compile_script
from tsc_compiler.models import MODEL_ID, PROMPT_VERSION, RENDERER_VERSION, SCRIPT_SCHEMA_VERSION


def compile_for(bundle, allowlist=None, asset_base="http://assets.local"):
    return compile_script(bundle, allowlist=allowlist or {}, asset_base=asset_base)


def load(settings, question_id, revision_id):
    return cache.load(
        settings,
        question_id=question_id,
        revision_id=revision_id,
        language="zh-CN",
        script_schema_version=SCRIPT_SCHEMA_VERSION,
        prompt_version=PROMPT_VERSION,
        model=MODEL_ID,
        renderer_version=RENDERER_VERSION,
    )


def test_revisions_are_isolated(settings) -> None:
    rev1 = make_bundle(revision_id="22222222-2222-2222-2222-222222222222", revision_number=1)
    rev2 = make_bundle(
        revision_id="33333333-3333-3333-3333-333333333333",
        revision_number=2,
        stem="2. 已知集合 $ M=\\{2,3\\} $，则 $ M\\cup\\{4\\}= $（ ）",
    )
    first = compile_for(rev1)
    second = compile_for(rev2)
    first["validation"]["status"] = "pass"
    second["validation"]["status"] = "pass"
    path1 = cache.save(settings, first)
    path2 = cache.save(settings, second)
    assert path1 != path2
    assert "22222222" in str(path1) and "33333333" in str(path2)
    assert load(settings, rev1["question_id"], rev1["revision_id"])["script_id"] == first["script_id"]
    assert load(settings, rev2["question_id"], rev2["revision_id"])["script_id"] == second["script_id"]
    assert set(cache.revision_isolated(settings, rev1["question_id"])) == {
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    }


def test_renderer_version_changes_cache_path(settings) -> None:
    bundle = make_bundle()
    script = compile_for(bundle)
    path = cache.save(settings, script)
    other = cache.script_dir(
        settings,
        question_id=script["question_id"],
        revision_id=script["revision_id"],
        language="zh-CN",
        script_schema_version=SCRIPT_SCHEMA_VERSION,
        prompt_version=PROMPT_VERSION,
        model=MODEL_ID,
        renderer_version="interactive-lesson/9.9.9",
    )
    assert str(path) != str(other)
    assert not other.exists()


def test_index_records_validation_status(settings) -> None:
    bundle = make_bundle()
    script = compile_for(bundle)
    script["validation"] = {"status": "pass", "checks": [], "validated_at": "x"}
    cache.save(settings, script)
    rows = cache.list_scripts(settings)
    assert len(rows) == 1
    assert rows[0]["validation"] == "pass"
    assert rows[0]["steps"] >= 1
