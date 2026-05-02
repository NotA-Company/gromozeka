"""
Edge case tests for keepConnection parameter, dood!

This module tests various edge cases and scenarios for the keepConnection
parameter to ensure it works correctly across different database types and
configurations.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.providers.sqlite3 import SQLite3Provider


class TestKeepConnectionEdgeCases:
    """Test edge cases for keepConnection parameter, dood!"""

    @pytest.mark.asyncio
    async def test_keep_connection_true_with_file_db(self):
        """Test keepConnection=True with file-based database, dood!"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"

            config: DatabaseManagerConfig = {
                "default": "default",
                "chatMapping": {},
                "providers": {
                    "default": {
                        "provider": "sqlite3",
                        "parameters": {
                            "dbPath": str(db_path),
                            "keepConnection": True,
                        },
                    }
                },
            }

            db = Database(config)
            await db.manager.getProvider()

            # Connection should be kept open
            provider = await db.manager.getProvider()
            assert provider._connection is not None

            # Perform multiple operations
            await db.common.setSetting("key1", "value1")
            await db.common.setSetting("key2", "value2")

            # Connection should still be open
            assert provider._connection is not None

            await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_keep_connection_false_with_memory_db(self):
        """Test keepConnection=False with in-memory database (explicit override), dood!

        NOTE: This test demonstrates that keepConnection=False with in-memory databases
        causes data loss between operations because the connection is closed and the
        in-memory database is destroyed. This is expected behavior and shows why
        the auto-detection feature (keepConnection=None) is important for in-memory DBs.
        """
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": ":memory:",
                        "keepConnection": False,  # Explicit override
                    },
                }
            },
        }

        db = Database(config)

        # First operation will trigger migration and set value
        await db.common.setSetting("key1", "value1")

        # Connection should be closed after operation
        provider = await db.manager.getProvider()
        assert provider._connection is None

        # Second operation - data will be lost because connection was closed
        # and in-memory database was destroyed
        value = await db.common.getSetting("key1")
        assert value is None  # Data lost as expected

        # Connection should be closed again
        assert provider._connection is None

        await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_keep_connection_none_with_memory_db(self):
        """Test keepConnection=None with in-memory database (auto-detect), dood!"""
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": ":memory:",
                        # keepConnection not specified (None)
                    },
                }
            },
        }

        db = Database(config)
        provider = await db.manager.getProvider()

        # For in-memory databases, should auto-detect and keep connection
        assert provider._connection is not None

        # Perform multiple operations
        await db.common.setSetting("key1", "value1")
        await db.common.setSetting("key2", "value2")

        # Connection should still be open
        assert provider._connection is not None

        await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_keep_connection_none_with_file_db(self):
        """Test keepConnection=None with file-based database (auto-detect), dood!"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"

            config: DatabaseManagerConfig = {
                "default": "default",
                "chatMapping": {},
                "providers": {
                    "default": {
                        "provider": "sqlite3",
                        "parameters": {
                            "dbPath": str(db_path),
                            # keepConnection not specified (None)
                        },
                    }
                },
            }

            db = Database(config)
            provider = await db.manager.getProvider()

            # For file-based databases, should auto-detect and not keep connection
            assert provider._connection is None

            # Perform operation
            await db.common.setSetting("key1", "value1")

            # Connection should be closed
            assert provider._connection is None

            await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_concurrent_operations_with_keep_connection_true(self):
        """Test concurrent operations with keepConnection=True, dood!"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"

            config: DatabaseManagerConfig = {
                "default": "default",
                "chatMapping": {},
                "providers": {
                    "default": {
                        "provider": "sqlite3",
                        "parameters": {
                            "dbPath": str(db_path),
                            "keepConnection": True,
                        },
                    }
                },
            }

            db = Database(config)
            await db.manager.getProvider()

            # Perform concurrent operations
            async def set_value(key: str, value: str):
                await db.common.setSetting(key, value)

            await asyncio.gather(
                set_value("key1", "value1"),
                set_value("key2", "value2"),
                set_value("key3", "value3"),
                set_value("key4", "value4"),
                set_value("key5", "value5"),
            )

            # Verify all values were set
            for i in range(1, 6):
                value = await db.common.getSetting(f"key{i}")
                assert value == f"value{i}"

            await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_connection_leak_prevention(self):
        """Test that connections don't leak with keepConnection=False, dood!"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"

            config: DatabaseManagerConfig = {
                "default": "default",
                "chatMapping": {},
                "providers": {
                    "default": {
                        "provider": "sqlite3",
                        "parameters": {
                            "dbPath": str(db_path),
                            "keepConnection": False,
                        },
                    }
                },
            }

            db = Database(config)

            # Perform many operations
            for i in range(100):
                await db.common.setSetting(f"key{i}", f"value{i}")

            # Connection should be closed
            provider = await db.manager.getProvider()
            assert provider._connection is None

            await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_provider_direct_instantiation_keep_connection(self):
        """Test provider instantiation with different keepConnection values, dood!"""
        # Test with keepConnection=True
        provider1 = SQLite3Provider(":memory:", keepConnection=True)
        assert provider1.keepConnection is True
        await provider1.connect()
        assert provider1._connection is not None
        await provider1.disconnect()

        # Test with keepConnection=False
        provider2 = SQLite3Provider(":memory:", keepConnection=False)
        assert provider2.keepConnection is False

        # Test with keepConnection=None (auto-detect for in-memory)
        provider3 = SQLite3Provider(":memory:", keepConnection=None)
        assert provider3.keepConnection is True  # Auto-detected

        # Test with keepConnection=None (auto-detect for file)
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            provider4 = SQLite3Provider(str(db_path), keepConnection=None)
            assert provider4.keepConnection is False  # Auto-detected

    @pytest.mark.asyncio
    async def test_cursor_context_manager_keep_connection_override(self):
        """Test cursor context manager with keepConnection override, dood!"""
        provider = SQLite3Provider(":memory:", keepConnection=False)

        # Use cursor with keepConnection=True override
        async with provider.cursor(keepConnection=True) as cursor:
            await cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            await cursor.execute("INSERT INTO test (id, value) VALUES (1, 'test')")

        # Connection should be kept open due to override
        assert provider._connection is not None

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_memory_db_data_persistence_with_keep_connection(self):
        """Test that in-memory DB data persists with keepConnection=True, dood!"""
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": ":memory:",
                        "keepConnection": True,
                    },
                }
            },
        }

        db = Database(config)

        # Set value
        await db.common.setSetting("key1", "value1")

        # Value should be retrievable
        value = await db.common.getSetting("key1")
        assert value == "value1"

        await db.manager.closeAll()

    @pytest.mark.asyncio
    async def test_memory_db_data_loss_without_keep_connection(self):
        """Test that in-memory DB data is lost without keepConnection, dood!"""
        config: DatabaseManagerConfig = {
            "default": "default",
            "chatMapping": {},
            "providers": {
                "default": {
                    "provider": "sqlite3",
                    "parameters": {
                        "dbPath": ":memory:",
                        "keepConnection": False,
                    },
                }
            },
        }

        db = Database(config)

        # Set value
        await db.common.setSetting("key1", "value1")

        # Value should NOT be retrievable (connection was closed, data lost)
        value = await db.common.getSetting("key1")
        assert value is None

        await db.manager.closeAll()
