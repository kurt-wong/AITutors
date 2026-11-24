"""Service authentication and short-lived lesson access tokens.

Two credentials exist:

* ``TSC_SERVICE_TOKEN`` — server-to-server shared secret. Only DeepTutor's
  Next proxy holds it; browsers never see it.
* signed lesson token — scoped to one ``question_id`` + ``revision_id`` with a
  short TTL, minted only through the service-authenticated endpoint. This is
  what the Interactive Lesson iframe uses, so "copy the bundle URL" stops
  working after a few minutes and never works for another question.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

TOKEN_PREFIX = "v1"


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def issue_lesson_token(
    secret: str, question_id: str, revision_id: str, ttl_seconds: int
) -> tuple[str, int]:
    expires_at = int(time.time()) + max(30, ttl_seconds)
    payload = f"{TOKEN_PREFIX}|{expires_at}|{question_id}|{revision_id}"
    signature = _sign(secret, payload)
    return f"{TOKEN_PREFIX}.{expires_at}.{revision_id}.{signature}", expires_at


def verify_lesson_token(
    secret: str, token: str, question_id: str, revision_id: str | None
) -> tuple[bool, str]:
    if not secret:
        return False, "signing secret is not configured"
    parts = (token or "").split(".")
    if len(parts) != 4:
        return False, "malformed lesson token"
    prefix, expires_raw, token_revision, signature = parts
    if prefix != TOKEN_PREFIX:
        return False, "unsupported lesson token version"
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return False, "malformed lesson token expiry"
    if expires_at < int(time.time()):
        return False, "lesson token expired"
    if revision_id is not None and token_revision != revision_id:
        return False, "lesson token is scoped to another revision"
    payload = f"{TOKEN_PREFIX}|{expires_at}|{question_id}|{token_revision}"
    if not constant_time_equal(_sign(secret, payload), signature):
        return False, "lesson token signature mismatch"
    return True, "ok"
