"""Alembic environment for Question Core.

The URL is taken from the environment through
``question_core.persistence.config`` (never from this file or the ini).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from question_core.persistence.config import DatabaseSettings  # noqa: E402
from question_core.persistence.models import Base  # noqa: E402

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Strict: migrations read ONLY the explicitly injected URL variable -
    # no discrete-variable fallback, no ambient defaults.
    url = os.environ.get("QCORE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "QCORE_DATABASE_URL is required to run migrations"
        )
    return DatabaseSettings.from_env({"QCORE_DATABASE_URL": url}).url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
