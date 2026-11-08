"""Environment-driven database configuration.

No credentials or connection strings are hardcoded. The full URL is read
from ``QCORE_DATABASE_URL``, or the discrete ``QCORE_PG_HOST`` /
``QCORE_PG_PORT`` / ``QCORE_PG_USER`` / ``QCORE_PG_PASSWORD`` /
``QCORE_PG_DBNAME`` variables.

The module also refuses to connect to the legacy AITutor databases
(``aitutors``, ``aitutors_test`` and every database whose name starts with
``aitutors``): Question Core persistence must stay on its own databases.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import make_url

from .exceptions import ConfigurationError

#: Databases owned by the legacy AITutor runtime. Question Core must never
#: connect to these; the guard below rejects them by name prefix.
PROTECTED_DB_PREFIX = "aitutors"

#: Synchronous PostgreSQL drivers only - the persistence layer is sync
#: SQLAlchemy (asyncpg URLs are rejected at configuration time).
_ALLOWED_DRIVERS = frozenset({"postgresql", "postgresql+psycopg2"})

_URL_VAR = "QCORE_DATABASE_URL"
_DISCRETE_VARS = {
    "host": "QCORE_PG_HOST",
    "port": "QCORE_PG_PORT",
    "user": "QCORE_PG_USER",
    "password": "QCORE_PG_PASSWORD",
    "dbname": "QCORE_PG_DBNAME",
}


@dataclass(frozen=True)
class DatabaseSettings:
    """Resolved connection settings."""

    url: str
    dbname: str

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "DatabaseSettings":
        env = os.environ if environ is None else environ

        raw_url = env.get(_URL_VAR, "").strip()
        if raw_url:
            url = raw_url
        else:
            missing = [
                var
                for key, var in _DISCRETE_VARS.items()
                if key != "port" and not env.get(var, "").strip()
            ]
            if missing:
                raise ConfigurationError(
                    "PostgreSQL connection is not configured. Set "
                    f"{_URL_VAR} (full SQLAlchemy URL) or the discrete "
                    "variables "
                    + ", ".join(_DISCRETE_VARS.values())
                    + ". Missing: "
                    + ", ".join(missing)
                )
            user = env[_DISCRETE_VARS["user"]].strip()
            password = env[_DISCRETE_VARS["password"]]
            host = env[_DISCRETE_VARS["host"]].strip()
            port = env.get(_DISCRETE_VARS["port"], "5432").strip() or "5432"
            dbname = env[_DISCRETE_VARS["dbname"]].strip()
            url = (
                f"postgresql+psycopg2://{user}:{password}"
                f"@{host}:{port}/{dbname}"
            )

        try:
            parsed = make_url(url)
        except Exception as exc:  # noqa: BLE001 - sqlalchemy raises several kinds
            raise ConfigurationError(
                f"{_URL_VAR} is not a valid SQLAlchemy URL: {exc}"
            ) from exc

        if parsed.drivername not in _ALLOWED_DRIVERS:
            raise ConfigurationError(
                "Question Core persistence is a SYNCHRONOUS SQLAlchemy "
                "layer; only postgresql and postgresql+psycopg2 URLs are "
                f"accepted, got driver '{parsed.drivername}'"
            )

        dbname = parsed.database or ""
        if not dbname:
            raise ConfigurationError(
                "the connection URL does not name a database"
            )
        if dbname.startswith(PROTECTED_DB_PREFIX):
            raise ConfigurationError(
                f"refusing to use protected database '{dbname}': Question "
                "Core must use its own isolated database (e.g. "
                "qcore_dev / qcore_dev_test), never the legacy "
                f"'{PROTECTED_DB_PREFIX}*' databases"
            )

        return cls(url=url, dbname=dbname)
