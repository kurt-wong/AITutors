# -*- coding: utf-8 -*-
"""Pre-prod security contract: service token + scoped lesson token."""

from __future__ import annotations

import dataclasses
import time

from fastapi.testclient import TestClient

from conftest import make_bundle, write_snapshot
from tsc_compiler.api import create_app
from tsc_compiler.auth import _sign


def secured(settings):
    return dataclasses.replace(
        settings,
        require_auth=True,
        service_token="svc-token-for-tests",
        signing_secret="signing-secret-for-tests",
    )


def test_api_requires_service_token(settings) -> None:
    write_snapshot(settings, [make_bundle()])
    client = TestClient(create_app(secured(settings)))
    assert client.get("/api/catalog").status_code == 401
    assert client.get("/api/catalog", headers={"X-TSC-Token": "wrong"}).status_code == 401
    ok = client.get("/api/catalog", headers={"X-TSC-Token": "svc-token-for-tests"})
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "no-store"


def test_health_is_public_and_reports_auth(settings) -> None:
    client = TestClient(create_app(secured(settings)))
    body = client.get("/health").json()
    assert body["auth_required"] is True
    assert body["service_token_configured"] is True


def test_missing_service_token_configuration_fails_closed(settings) -> None:
    insecure = dataclasses.replace(settings, require_auth=True, service_token="", signing_secret="")
    client = TestClient(create_app(insecure))
    response = client.get("/api/catalog")
    assert response.status_code == 503


def test_lesson_token_is_scoped_and_expires(settings) -> None:
    bundle = make_bundle()
    write_snapshot(settings, [bundle])
    client = TestClient(create_app(secured(settings)))
    service = {"X-TSC-Token": "svc-token-for-tests"}

    access = client.post(
        "/api/lesson-access",
        json={"question_id": bundle["question_id"], "revision_id": bundle["revision_id"]},
        headers=service,
    )
    assert access.status_code == 200
    body = access.json()
    token = body["access_token"]
    assert body["revision_id"] == bundle["revision_id"]

    # The iframe can read exactly this revision with the scoped token...
    ok = client.get(
        f"/api/teaching-bundles/{bundle['question_id']}",
        params={"revision_id": bundle["revision_id"], "access_token": token},
    )
    assert ok.status_code == 200
    # ...but not another question, another revision, or an expired token.
    other = client.get(
        "/api/teaching-bundles/00000000-0000-0000-0000-000000000000",
        params={"revision_id": bundle["revision_id"], "access_token": token},
    )
    assert other.status_code == 401
    wrong_revision = client.get(
        f"/api/teaching-bundles/{bundle['question_id']}",
        params={"revision_id": "00000000-0000-0000-0000-000000000000", "access_token": token},
    )
    assert wrong_revision.status_code == 401

    past_expiry = int(time.time()) - 5
    past_payload = (
        f"v1|{past_expiry}|{bundle['question_id']}|{bundle['revision_id']}"
    )
    past = (
        f"v1.{past_expiry}.{bundle['revision_id']}."
        + _sign("signing-secret-for-tests", past_payload)
    )
    expired_response = client.get(
        f"/api/teaching-bundles/{bundle['question_id']}",
        params={"revision_id": bundle["revision_id"], "access_token": past},
    )
    assert expired_response.status_code == 401


def test_lesson_access_rejects_wrong_revision(settings) -> None:
    bundle = make_bundle()
    write_snapshot(settings, [bundle])
    client = TestClient(create_app(secured(settings)))
    response = client.post(
        "/api/lesson-access",
        json={
            "question_id": bundle["question_id"],
            "revision_id": "00000000-0000-0000-0000-000000000000",
        },
        headers={"X-TSC-Token": "svc-token-for-tests"},
    )
    assert response.status_code == 409


def test_search_requires_service_token(settings) -> None:
    write_snapshot(settings, [make_bundle()])
    client = TestClient(create_app(secured(settings)))
    response = client.post("/api/search/text", json={"text": "任意文本"})
    assert response.status_code == 401
