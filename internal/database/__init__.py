"""Database management components for Gromozeka bot.

This module provides the core database abstraction layer for the Gromozeka bot,
serving as the entry point for all database-related functionality. It exports
the primary database interface and query parameterization utilities that enable
safe, efficient, and portable database operations across multiple database backends.

The database layer is designed to support:
- Multi-source database configurations (read/write splitting, read replicas)
- Portable SQL generation across different database providers (SQLite, PostgreSQL, MySQL)
- Safe parameterized queries to prevent SQL injection
- Connection pooling and management
- Transaction handling and rollback support

Key Components:
    Database: Main database interface for managing database connections, executing
        queries, and handling transactions. Provides methods for both read and write
        operations with automatic routing to appropriate database sources.
    ParametrizedQuery: Utility class for creating parameterized SQL queries safely.
        Helps construct SQL queries with proper parameter binding to prevent SQL
        injection attacks and ensure query portability across database backends.

Usage Example:
    >>> from internal.database import Database, ParametrizedQuery
    >>>
    >>> # Initialize database with configuration
    >>> db = Database(config)
    >>>
    >>> # Execute a parameterized query
    >>> query = ParametrizedQuery("SELECT * FROM users WHERE id = :userId")
    >>> result = db.executeRead(query, {"userId": 123})
    >>>
    >>> # Execute a write operation
    >>> writeQuery = ParametrizedQuery("INSERT INTO users (name) VALUES (:name)")
    >>> db.executeWrite(writeQuery, {"name": "John Doe"})

Architecture:
    The database layer follows a multi-source architecture where:
    - Write operations are routed to the primary database
    - Read operations can be distributed across read replicas
    - Each database source is managed by a provider implementation
    - Providers handle database-specific SQL dialect differences

Note:
    This module is part of Stage 2: Database Layer in the Gromozeka architecture.
    All database operations should go through this layer to maintain consistency
    and portability across different database backends.
"""

from .database import Database
from .providers import ParametrizedQuery

__all__ = [
    "Database",
    "ParametrizedQuery",
]
