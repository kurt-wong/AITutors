# -*- coding: utf-8 -*-
"""Asynchronous OCR job contract (pre-prod)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from conftest import make_bundle, write_snapshot
from tsc_compiler.api import create_app


def wait_job(client: TestClient, job_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/search/jobs/{job_id}").json()
        if body.get("status") in {"succeeded", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {body}")


def test_job_succeeds_and_carries_result(settings, monkeypatch) -> None:
    bundle = make_bundle()
    write_snapshot(settings, [bundle])
    stem = bundle["content"]["bodies"][0]["stem_blocks"][0]["text"]

    def fake_ocr(_settings, _content, **_kwargs):
        return {
            "status": "ok",
            "engine": "fake-ocr",
            "pages": 1,
            "duration_s": 0.01,
            "job_id": "fake-job",
            "text": stem,
        }

    monkeypatch.setattr("tsc_compiler.api.ocr_bytes", fake_ocr)
    client = TestClient(create_app(settings))
    created = client.post(
        "/api/search/photo/jobs",
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
    )
    assert created.status_code == 202
    job = created.json()
    assert job["status"] in {"queued", "running"}
    done = wait_job(client, job["job_id"])
    assert done["status"] == "succeeded", done
    assert done["stage"] == "done"
    assert done["result"]["candidates"]
    assert done["result"]["ocr"]["text"] == stem
    assert done["result"]["search_id"]
    # The search artifact is persisted for audit.
    assert (settings.data_dir / "photo" / done["result"]["search_id"] / "result.json").is_file()


def test_ocr_failure_is_terminal_and_does_not_match(settings, monkeypatch) -> None:
    write_snapshot(settings, [make_bundle()])

    def failing_ocr(_settings, _content, **_kwargs):
        return {"status": "failed", "error": "ocr down", "engine": "fake-ocr"}

    monkeypatch.setattr("tsc_compiler.api.ocr_bytes", failing_ocr)
    client = TestClient(create_app(settings))
    created = client.post(
        "/api/search/photo/jobs",
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
    )
    done = wait_job(client, created.json()["job_id"])
    assert done["status"] == "failed"
    assert done["stage"] == "ocr"
    assert "ocr down" in done["error"]
    assert "result" not in done


def test_unknown_job_is_404(settings) -> None:
    client = TestClient(create_app(settings))
    assert client.get("/api/search/jobs/does-not-exist").status_code == 404


def test_upload_validation(settings) -> None:
    client = TestClient(create_app(settings))
    bad_type = client.post(
        "/api/search/photo/jobs",
        files={"file": ("photo.exe", b"abc", "application/octet-stream")},
    )
    assert bad_type.status_code == 415
    empty = client.post(
        "/api/search/photo/jobs",
        files={"file": ("photo.jpg", b"", "image/jpeg")},
    )
    assert empty.status_code == 400
