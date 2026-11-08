"""Engine / session management and health checks."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .config import DatabaseSettings
from .exceptions import DatabaseConnectionError


def create_db_engine(settings: DatabaseSettings) -> Engine:
    """Create a SQLAlchemy engine from settings (connection is lazy)."""
    return create_engine(
        settings.url,
        pool_pre_ping=True,
        future=True,
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional unit of work: commit on success, rollback on error."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check(engine: Engine) -> dict[str, Any]:
    """Probe the database. Raises DatabaseConnectionError when unreachable."""
    try:
        with engine.connect() as conn:
            server_version = conn.execute(text("SELECT version()")).scalar()
            current_db = conn.execute(
                text("SELECT current_database()")
            ).scalar()
            current_user = conn.execute(text("SELECT current_user")).scalar()
    except OperationalError as exc:
        raise DatabaseConnectionError(
            f"cannot reach PostgreSQL at {engine.url.render_as_string(hide_password=True)}: {exc}"
        ) from exc
    return {
        "status": "ok",
        "database": current_db,
        "user": current_user,
        "server_version": server_version,
    }
