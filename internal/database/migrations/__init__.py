"""
Database migrations module.

This module provides a migration system for managing database schema changes.
It exports the base migration class, migration manager, and migration error
exception for use throughout the application.
"""

from .base import BaseMigration
from .manager import MigrationError, MigrationManager

__all__ = [
    "BaseMigration",
    "MigrationManager",
    "MigrationError",
]
