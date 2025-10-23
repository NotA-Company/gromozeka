"""
Database migrations module, dood!

This module provides a migration system for managing database schema changes.
"""

from typing import List, Type
from .base import BaseMigration
from .manager import MigrationManager, MigrationError
from .versions import migration_001_initial_schema
from .versions import migration_002_add_is_spammer_to_chat_users

# Registry of all migrations in order, dood!
MIGRATIONS: List[Type[BaseMigration]] = [
    migration_001_initial_schema.Migration001InitialSchema,
    migration_002_add_is_spammer_to_chat_users.Migration002AddIsSpammerToChatUsers,
]

__all__ = [
    "BaseMigration",
    "MigrationManager",
    "MigrationError",
    "MIGRATIONS",
]