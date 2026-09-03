"""Tests for getSqlProvider factory function.

Tests the provider factory in lib/db/providers/__init__.py, which instantiates
concrete provider instances based on configuration. These tests are
provider-construction-only; no connections are made.
"""

import pytest

from lib.db.providers import SQLProviderConfig, getSqlProvider
from lib.db.providers.base import BaseSQLProvider
from lib.db.providers.sqlink import SQLinkProvider
from lib.db.providers.sqlite3 import SQLite3Provider


class TestGetSqlProvider:
    """Tests for getSqlProvider factory function."""

    def test_sqlite3_provider_returns_sqlite3_instance(self):
        """Test that provider='sqlite3' returns SQLite3Provider instance."""
        config: SQLProviderConfig = {
            "provider": "sqlite3",
            "parameters": {"dbPath": ":memory:"},
        }

        provider = getSqlProvider(config)

        assert isinstance(provider, SQLite3Provider)
        assert provider.dbPath == ":memory:"

    def test_sqlink_provider_returns_sqlink_instance(self):
        """Test that provider='sqlink' returns SQLinkProvider instance."""
        config: SQLProviderConfig = {
            "provider": "sqlink",
            "parameters": {
                "url": "http://example.com",
                "user": "testuser",
                "password": "testpass",
                "database": "testdb",
            },
        }

        provider = getSqlProvider(config)

        assert isinstance(provider, SQLinkProvider)
        assert provider.url == "http://example.com"
        assert provider.user == "testuser"
        assert provider.password == "testpass"
        assert provider.database == "testdb"

    def test_unknown_provider_raises_value_error(self):
        """Test that unknown provider string raises ValueError."""
        config: SQLProviderConfig = {
            "provider": "unknown_provider",
            "parameters": {},
        }

        with pytest.raises(ValueError, match="Unknown provider: unknown_provider"):
            getSqlProvider(config)

    def test_missing_provider_key_raises_value_error(self):
        """Test that missing 'provider' key raises ValueError.

        Pins the actual behavior: config.get("provider") returns None,
        which falls through to the ValueError with 'Missing the required'
        message.
        """
        config: SQLProviderConfig = {
            "parameters": {},
        }  # type: ignore[assignment]

        with pytest.raises(ValueError, match="missing the required 'provider' key"):
            getSqlProvider(config)

    def test_all_providers_return_base_provider_instance(self):
        """Test that all registered providers return BaseSQLProvider subclasses."""
        sqlite3Config: SQLProviderConfig = {
            "provider": "sqlite3",
            "parameters": {"dbPath": ":memory:"},
        }

        sqlinkConfig: SQLProviderConfig = {
            "provider": "sqlink",
            "parameters": {
                "url": "http://example.com",
                "user": "testuser",
                "password": "testpass",
                "database": "testdb",
            },
        }

        sqlite3Provider = getSqlProvider(sqlite3Config)
        sqlinkProvider = getSqlProvider(sqlinkConfig)

        # All providers should inherit from BaseSQLProvider
        assert isinstance(sqlite3Provider, BaseSQLProvider)
        assert isinstance(sqlinkProvider, BaseSQLProvider)
