"""Unit tests: environment configuration and the protected-database guard."""

from __future__ import annotations

import pytest

from question_core.persistence.config import DatabaseSettings
from question_core.persistence.exceptions import ConfigurationError


class TestDatabaseSettings:
    def test_full_url_env(self):
        settings = DatabaseSettings.from_env(
            {
                "QCORE_DATABASE_URL": "postgresql+psycopg2://u:p@localhost:5432/qcore_dev_test"
            }
        )
        assert settings.dbname == "qcore_dev_test"
        assert settings.url.startswith("postgresql+psycopg2://")

    def test_discrete_vars(self):
        settings = DatabaseSettings.from_env(
            {
                "QCORE_PG_HOST": "127.0.0.1",
                "QCORE_PG_USER": "aitutors",
                "QCORE_PG_PASSWORD": "secret",
                "QCORE_PG_DBNAME": "qcore_dev_test",
            }
        )
        assert settings.dbname == "qcore_dev_test"
        assert "@127.0.0.1:5432/" in settings.url

    def test_missing_config_raises(self):
        with pytest.raises(ConfigurationError) as exc:
            DatabaseSettings.from_env({})
        assert "QCORE_DATABASE_URL" in str(exc.value)
        assert "QCORE_PG_HOST" in str(exc.value)

    def test_partial_config_names_missing_vars(self):
        with pytest.raises(ConfigurationError) as exc:
            DatabaseSettings.from_env({"QCORE_PG_HOST": "127.0.0.1"})
        message = str(exc.value)
        assert "QCORE_PG_USER" in message
        assert "QCORE_PG_DBNAME" in message

    @pytest.mark.parametrize(
        "dbname",
        ["aitutors", "aitutors_test", "aitutors_e2e_009_zh"],
    )
    def test_protected_databases_rejected(self, dbname):
        with pytest.raises(ConfigurationError) as exc:
            DatabaseSettings.from_env(
                {
                    "QCORE_DATABASE_URL": f"postgresql+psycopg2://u:p@localhost:5432/{dbname}"
                }
            )
        assert "protected" in str(exc.value)

    def test_non_postgresql_driver_rejected(self):
        with pytest.raises(ConfigurationError):
            DatabaseSettings.from_env(
                {
                    "QCORE_DATABASE_URL": "sqlite:///qcore.db",
                }
            )

    def test_asyncpg_url_rejected(self):
        """The persistence layer is synchronous SQLAlchemy - asyncpg URLs
        are rejected at configuration time (R1-FIX-2 F7)."""
        with pytest.raises(ConfigurationError) as exc:
            DatabaseSettings.from_env(
                {
                    "QCORE_DATABASE_URL": "postgresql+asyncpg://u:p@localhost:55432/qcore_dev_test"
                }
            )
        message = str(exc.value).lower()
        assert "synchronous" in message
        assert "asyncpg" in message

    def test_sync_driver_urls_accepted(self):
        for url in (
            "postgresql://u:p@localhost:55432/qcore_dev_test",
            "postgresql+psycopg2://u:p@localhost:55432/qcore_dev_test",
        ):
            settings = DatabaseSettings.from_env(
                {"QCORE_DATABASE_URL": url}
            )
            assert settings.dbname == "qcore_dev_test"

    def test_invalid_url_rejected(self):
        with pytest.raises(ConfigurationError):
            DatabaseSettings.from_env({"QCORE_DATABASE_URL": "not a url"})
