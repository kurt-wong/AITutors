# -*- coding: utf-8 -*-
"""HTTP API contract tests (synthetic snapshot, no network)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import make_bundle, write_snapshot
from tsc_compiler.api import create_app


def client(settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_and_catalog(settings) -> None:
    bundle = make_bundle()
    write_snapshot(settings, [bundle])
    api = client(settings)
    health = api.get("/health").json()
    assert health["status"] == "ok"
    catalog = api.get("/api/catalog").json()
    assert catalog["count"] == 1
    assert catalog["questions"][0]["question_id"] == bundle["question_id"]


def test_bundle_is_served_and_wrong_revision_conflicts(settings) -> None:
    bundle = make_bundle()
    write_snapshot(settings, [bundle])
    api = client(settings)
    ok = api.get(f"/api/teaching-bundles/{bundle['question_id']}")
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["revision_id"] == bundle["revision_id"]
    assert payload["script"]["validation"]["status"] == "pass"
    conflict = api.get(
        f"/api/teaching-bundles/{bundle['question_id']}",
        params={"revision_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert conflict.status_code == 409


def test_missing_question_is_404(settings) -> None:
    write_snapshot(settings, [make_bundle()])
    api = client(settings)
    response = api.get("/api/teaching-bundles/not-a-question")
    assert response.status_code == 404


def test_text_search_endpoint(settings) -> None:
    bundle = make_bundle()
    write_snapshot(settings, [bundle])
    api = client(settings)
    response = api.post(
        "/api/search/text",
        json={"text": bundle["content"]["bodies"][0]["stem_blocks"][0]["text"], "use_llm": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"]
    assert body["candidates"][0]["question_id"] == bundle["question_id"]
    assert body["may_teach"] in (True, False)
    assert "ocr" not in body  # text-only search carries no OCR payload


def test_ocr_failure_is_fail_closed(settings, monkeypatch) -> None:
    write_snapshot(settings, [make_bundle()])

    def fake_ocr(*_args, **_kwargs):
        return {"status": "failed", "error": "no api", "engine": "fake"}

    monkeypatch.setattr("tsc_compiler.api.ocr_bytes", fake_ocr)
    api = client(settings)
    response = api.post(
        "/api/search/photo",
        files={"file": ("q.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["decision"] == "ocr_failed"
    assert "candidates" not in body
    assert body["message"]
