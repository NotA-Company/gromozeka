"""Conftest for lib.stats tests.

This module provides fixtures specific to the stats storage tests.
"""

from typing import AsyncGenerator

import pytest

from internal.database import Database
from internal.database.manager import DatabaseManagerConfig
from internal.database.migrations.versions.migration_016_add_stat_tables import (
    getMigration,
)
from internal.database.stats_storage import DatabaseStatsStorage


@pytest.fixture
async def statsStorage() -> AsyncGenerator[DatabaseStatsStorage, None]:
    """Create a DatabaseStatsStorage backed by the test database.

    Applies migration 016 to create stat_events and stat_aggregates tables.

    Yields:
        DatabaseStatsStorage instance ready for testing.
    """
    # Create a test Database instance with in-memory SQLite
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)

    try:
        # Apply migration 016 to create stat tables
        provider = await db.manager.getProvider(dataSource="default", readonly=False)
        migration = getMigration()()
        await migration.up(provider)

        # Create storage with default data source
        storage = DatabaseStatsStorage(
            db=db,
            eventType="llm_request",
            dataSource="default",
        )
        yield storage
    finally:
        await db.manager.closeAll()
