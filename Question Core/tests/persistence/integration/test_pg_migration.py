"""Real PostgreSQL migration tests.

Rules honoured here:

* only ``QCORE_MIGRATION_TEST_DATABASE_URL`` (the pre-created dedicated
  database) is used - tests never CREATE/DROP databases and never touch
  ``template1`` or any other instance;
* the safety check runs BEFORE any migration/DDL;
* a clean slate is produced with ``alembic downgrade base`` (migration
  machinery only) instead of dropping the database.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from .conftest import (
    TEST_DATABASE_URL,
    migration_database_url,
    run_alembic,
)
from .safety import verify_test_target

pytestmark = pytest.mark.pg

_MIGRATION_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "migrations",
    "versions",
)


@pytest.fixture
def migration_target():
    """Validated migration-test connection (pre-created database)."""
    url = migration_database_url()
    evidence = verify_test_target(
        url, expected_database="qcore_dev_test_migrate"
    )
    return url, evidence


@pytest.fixture
def empty_migration_db(migration_target):
    """A schema-less dedicated database (reset via alembic downgrade)."""
    url, evidence = migration_target
    # reset first so repeated runs start from an empty schema
    run_alembic(url, "base")
    yield url, evidence


class TestMigrationLifecycle:
    def test_upgrade_from_empty_database(self, empty_migration_db):
        url, evidence = empty_migration_db
        run_alembic(url, "head")

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
                    )
                }
                version = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                triggers = (
                    conn.execute(
                        text(
                            "SELECT tgname FROM pg_trigger WHERE NOT "
                            "tgisinternal AND "
                            "tgrelid = 'qcore_revisions'::regclass"
                        )
                    )
                    .scalars()
                    .all()
                )
                state_triggers = (
                    conn.execute(
                        text(
                            "SELECT count(*) FROM pg_trigger WHERE NOT "
                            "tgisinternal AND tgname = "
                            "'qcore_state_history_immutable'"
                        )
                    )
                    .scalar()
                )
        finally:
            engine.dispose()

        expected_tables = {
            "qcore_candidates",
            "qcore_questions",
            "qcore_revisions",
            "qcore_question_instances",
            "qcore_answer_rows",
            "qcore_evidence_records",
            "qcore_evidence_conflicts",
            "qcore_asset_refs",
            "qcore_material_refs",
            "qcore_state_history",
        }
        assert expected_tables <= tables
        assert version is not None and len(version) >= 8
        assert "qcore_revisions_immutable" in triggers
        # R1-FIX-2: state history append-only trigger exists exactly once
        assert state_triggers == 1
        # the migration database is the pre-created dedicated one
        assert evidence["database"] == "qcore_dev_test_migrate"

    def test_repeated_upgrade_preserves_data(self, empty_migration_db):
        url, _ = empty_migration_db
        run_alembic(url, "head")

        engine = create_engine(url)
        try:
            question_id = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO qcore_questions "
                        "(question_id, contract_created_at) "
                        "VALUES (:qid, now())"
                    ),
                    {"qid": question_id},
                )
        finally:
            engine.dispose()

        # running the migration again must be a no-op for existing data
        run_alembic(url, "head")

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                surviving = conn.execute(
                    text(
                        "SELECT count(*) FROM qcore_questions WHERE "
                        "question_id = :qid"
                    ),
                    {"qid": question_id},
                ).scalar()
                version = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
        finally:
            engine.dispose()

        assert surviving == 1
        assert version is not None

    def test_repeated_upgrade_creates_no_duplicate_objects(
        self, empty_migration_db
    ):
        url, _ = empty_migration_db
        run_alembic(url, "head")
        run_alembic(url, "head")

        engine = create_engine(url)
        try:
            with engine.connect() as conn:
                trigger_count = conn.execute(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE NOT "
                        "tgisinternal AND tgname IN ("
                        "'qcore_revisions_immutable', "
                        "'qcore_state_history_immutable')"
                    )
                ).scalar()
                function_count = conn.execute(
                    text(
                        "SELECT count(*) FROM pg_proc WHERE proname IN ("
                        "'qcore_block_revision_mutation', "
                        "'qcore_block_state_history_mutation')"
                    )
                ).scalar()
        finally:
            engine.dispose()

        assert trigger_count == 2  # exactly one per table
        assert function_count == 2

    def test_main_test_database_keeps_data_across_re_upgrades(
        self, engine, clean_db
    ):
        from question_core.persistence import (
            QuestionCoreRepository,
            session_scope,
        )

        from tests.persistence.synthetic import make_rich_aggregate

        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        run_alembic(TEST_DATABASE_URL, "head")

        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_question_aggregate(
                aggregate.identity.question_id
            )
        assert restored == aggregate


class TestMigrationSafety:
    def test_migration_never_recreates_databases(self):
        """Migration versions must only manage schema objects; hiding
        migration problems by dropping/recreating the database is not
        allowed, and tests must not do it either."""
        root = os.path.abspath(_MIGRATION_DIR)
        assert os.path.isdir(root), root
        for name in os.listdir(root):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                source = fh.read().lower()
            assert "drop database" not in source
            assert "create database" not in source

    def test_downgrade_is_defined(self):
        root = os.path.abspath(_MIGRATION_DIR)
        for name in os.listdir(root):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                source = fh.read()
            assert "def downgrade()" in source

    def test_test_code_never_creates_databases(self):
        """The test-suite source must not CREATE/DROP databases or touch
        template1 - the dedicated migration database is pre-created.
        This very file is excluded (it quotes the prohibition)."""
        root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        self_path = os.path.abspath(__file__)
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.abspath(os.path.join(dirpath, name))
                if path == self_path:
                    continue
                with open(path, encoding="utf-8") as fh:
                    source = fh.read().lower()
                assert "create database" not in source, name
                assert "drop database" not in source, name
                assert "template1" not in source, name
