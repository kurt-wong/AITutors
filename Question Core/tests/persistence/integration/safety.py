"""Connection-target safety checks for PostgreSQL test connections.

Every test connection must pass :func:`verify_test_target` BEFORE any
Migration, DDL, DROP or data write runs.  The checks confirm the database
name, the connected user, the port, and that the server is the new AITutor
PostgreSQL instance (not any legacy instance).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

#: Host ports of the new AITutor-postgresql instance (Infrastructure README).
EXPECTED_PORT = 55432
EXPECTED_USER = "qcore_app"
#: Databases pre-created on the new instance by Infrastructure/initdb.
ALLOWED_DATABASES = {"qcore_dev_test", "qcore_dev_test_migrate"}
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
#: Synchronous drivers only (matches question_core.persistence.config).
ALLOWED_DRIVERS = frozenset({"postgresql", "postgresql+psycopg2"})


class UnsafeTestTarget(RuntimeError):
    """The connection does not point at the new AITutor PostgreSQL."""


def verify_test_target(
    url: str, *, expected_database: str | None = None
) -> dict[str, Any]:
    """Validate a test connection target. Returns evidence for reports.

    Hard-fails (never falls back, never guesses) when anything is off.
    """
    parsed = make_url(url)

    if parsed.drivername not in ALLOWED_DRIVERS:
        raise UnsafeTestTarget(
            f"test connections must use a synchronous PostgreSQL driver, "
            f"got {parsed.drivername!r}"
        )
    if (parsed.host or "") not in ALLOWED_HOSTS:
        raise UnsafeTestTarget(
            f"test connections must target localhost, got host {parsed.host!r}"
        )
    if parsed.port != EXPECTED_PORT:
        raise UnsafeTestTarget(
            f"test connections must use port {EXPECTED_PORT} of the new "
            f"Aitutor-postgresql instance, got port {parsed.port!r}"
        )
    dbname = parsed.database or ""
    if dbname not in ALLOWED_DATABASES:
        raise UnsafeTestTarget(
            f"database {dbname!r} is not one of the pre-created test "
            f"databases {sorted(ALLOWED_DATABASES)}"
        )
    if expected_database is not None and dbname != expected_database:
        raise UnsafeTestTarget(
            f"expected database {expected_database!r}, got {dbname!r}"
        )

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            server_version = conn.execute(text("SELECT version()")).scalar()
            current_user = conn.execute(text("SELECT current_user")).scalar()
            current_db = conn.execute(text("SELECT current_database()")).scalar()
            server_port = conn.execute(text("SHOW port")).scalar()
            superuser, createdb, createrole = conn.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).one()
            legacy_dbs = conn.execute(
                text(
                    "SELECT count(*) FROM pg_database "
                    "WHERE datname LIKE 'aitutors%'"
                )
            ).scalar()
    finally:
        engine.dispose()

    if not str(server_version).startswith("PostgreSQL 16"):
        raise UnsafeTestTarget(
            f"expected PostgreSQL 16.x on the new instance, got {server_version!r}"
        )
    if current_user != EXPECTED_USER:
        raise UnsafeTestTarget(
            f"test connections must run as {EXPECTED_USER!r}, got {current_user!r}"
        )
    if current_db != dbname:
        raise UnsafeTestTarget(
            f"connected database {current_db!r} differs from URL database {dbname!r}"
        )
    if superuser or createdb or createrole:
        raise UnsafeTestTarget(
            "the test account must not be superuser / createdb / createrole"
        )
    if legacy_dbs:
        raise UnsafeTestTarget(
            "the connected server still hosts aitutors* databases: this is "
            "NOT the new AITutor-postgresql instance"
        )

    return {
        "database": current_db,
        "user": current_user,
        "host": parsed.host,
        "port": parsed.port,
        "server_port": server_port,
        "server_version": server_version,
        "superuser": superuser,
        "createdb": createdb,
        "createrole": createrole,
        "legacy_aitutors_databases": legacy_dbs,
    }
