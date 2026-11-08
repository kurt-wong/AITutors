"""Integration-test fixtures: a REAL PostgreSQL database.

No SQLite, no mocks, no implicit fallbacks.  The connection comes from ONE
environment variable per test database and nothing else:

* ``QCORE_TEST_DATABASE_URL``          - the main test database.
* ``QCORE_MIGRATION_TEST_DATABASE_URL`` - the pre-created migration test
  database (used by the migration tests only).

Missing configuration fails loudly.  Nothing reads the Windows registry,
the ambient system environment, or any legacy database.  Before any
Migration, DDL or write runs, the target is validated by
``safety.verify_test_target`` (database name, user, port, instance).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # Question Core/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.persistence.integration.safety import (  # noqa: E402
    UnsafeTestTarget,
    verify_test_target,
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"{name} is not set. PostgreSQL integration tests require the "
            "explicit test connection URLs (real PostgreSQL only, no "
            "SQLite/mocks, no implicit fallbacks). See "
            "Infrastructure/README.md."
        )
    return value


def _test_database_url() -> str:
    return _require_env("QCORE_TEST_DATABASE_URL")


def migration_database_url() -> str:
    """Explicit URL of the pre-created migration test database."""
    return _require_env("QCORE_MIGRATION_TEST_DATABASE_URL")


TEST_DATABASE_URL = _test_database_url()

_ALL_TABLES = (
    "qcore_answer_rows",
    "qcore_evidence_records",
    "qcore_evidence_conflicts",
    "qcore_asset_refs",
    "qcore_material_refs",
    "qcore_state_history",
    "qcore_question_instances",
    "qcore_revisions",
    "qcore_questions",
    "qcore_candidates",
)


def run_alembic(url: str, revision: str = "head") -> None:
    """Run an alembic command against ``url``.

    The URL is injected explicitly; alembic itself reads only the
    ``QCORE_DATABASE_URL`` variable (see migrations/env.py).
    """
    from alembic import command
    from alembic.config import Config

    previous = os.environ.get("QCORE_DATABASE_URL")
    os.environ["QCORE_DATABASE_URL"] = url
    try:
        config = Config(str(_PROJECT_ROOT / "alembic.ini"))
        if revision == "head":
            command.upgrade(config, revision)
        elif revision == "base":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)
    finally:
        if previous is None:
            os.environ.pop("QCORE_DATABASE_URL", None)
        else:
            os.environ["QCORE_DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def target_evidence():
    """Safety verification of the main test target (runs before any DDL)."""
    try:
        return verify_test_target(
            TEST_DATABASE_URL, expected_database="qcore_dev_test"
        )
    except UnsafeTestTarget as exc:
        pytest.fail(f"test connection safety check failed: {exc}")


@pytest.fixture(scope="session")
def engine(target_evidence):
    from question_core.persistence.engine import (
        create_db_engine,
        health_check,
    )
    from question_core.persistence.config import DatabaseSettings

    # Safety was verified BEFORE any migration/DDL (target_evidence runs
    # first). Only now touch the schema.
    run_alembic(TEST_DATABASE_URL, "head")
    settings = DatabaseSettings.from_env({"QCORE_DATABASE_URL": TEST_DATABASE_URL})
    eng = create_db_engine(settings)
    report = health_check(eng)
    assert report["status"] == "ok"
    assert report["database"] == "qcore_dev_test"
    yield eng
    eng.dispose()


@pytest.fixture
def clean_db(engine):
    """Empty every qcore_ table around the test.

    TRUNCATE does not fire row triggers, so the revision-immutability
    trigger does not interfere with test cleanup.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(_ALL_TABLES)} CASCADE"))
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(_ALL_TABLES)} CASCADE"))
