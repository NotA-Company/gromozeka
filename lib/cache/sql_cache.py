"""
Generic database cache implementation.

Provides a database-backed cache implementation that uses the DatabaseManager
to store and retrieve cached data. Supports different cache namespaces
and configurable key/value conversion strategies.
"""

import datetime
import logging
from typing import Any, Dict, Optional, TypedDict

from lib.db import utils as dbUtils
from lib.db.manager import DatabaseManager
from lib.db.providers.base import ExcludedValue

from .interface import CacheInterface, K, V
from .key_generator import HashKeyGenerator
from .types import KeyGenerator, ValueConverter
from .value_converter import JsonValueConverter

logger = logging.getLogger(__name__)


class _CacheRowDict(TypedDict):
    """Row type for cache table queries."""

    key: str
    """Cache key."""
    data: str
    """JSON-serialized response data."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class GenericDatabaseCache(CacheInterface[K, V]):
    """
    Database-backed cache implementation.

    Stores data in the database using the DatabaseManager. Supports different cache
    namespaces for organizing data and uses configurable key generators and
    value converters for flexible data handling.

    Type Parameters:
        K: The key type (any hashable type)
        V: The value type (any type)

    Attributes:
        manager: Database manager instance for provider access
        dataSource: Optional data source identifier for multi-source configurations
        namespace: Cache namespace (string identifier)
        keyGenerator: KeyGenerator instance for converting keys to strings
        valueConverter: ValueConverter instance for serializing/deserializing values

    Example:
        >>> from lib.cache import GenericDatabaseCache, StringKeyGenerator
        >>> from lib.db.manager import DatabaseManager
        >>>
        >>> manager = DatabaseManager(...)
        >>> cache = GenericDatabaseCache[str, dict](
        ...     manager=manager,
        ...     namespace="weather",
        ...     keyGenerator=StringKeyGenerator()
        ... )
        >>> await cache.set("moscow", {"temp": 20, "humidity": 50})
        >>> weather = await cache.get("moscow")
    """

    __slots__ = ("manager", "dataSource", "namespace", "keyGenerator", "valueConverter")

    def __init__(
        self,
        manager: DatabaseManager,
        namespace: str,
        keyGenerator: Optional[KeyGenerator[K]] = None,
        valueConverter: Optional[ValueConverter[V]] = None,
        *,
        dataSource: Optional[str] = None,
    ):
        """
        Initialize cache with database manager.

        Args:
            manager: Database manager instance for provider access
            namespace: Cache namespace (string identifier) for organizing cache data
            keyGenerator: Optional KeyGenerator instance for converting keys to strings.
                         If None, uses HashKeyGenerator by default.
            valueConverter: Optional ValueConverter instance for serializing/deserializing values.
                           If None, uses JsonValueConverter by default.
            dataSource: Optional data source identifier for multi-source configurations.
        """
        self.manager = manager
        self.dataSource = dataSource
        self.namespace = namespace
        self.keyGenerator: KeyGenerator[K] = keyGenerator if keyGenerator is not None else HashKeyGenerator()
        self.valueConverter: ValueConverter[V] = (
            valueConverter if valueConverter is not None else JsonValueConverter[V]()
        )

    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """
        Get cached data if exists and not expired.

        Args:
            key: Cache key to retrieve
            ttl: Optional time-to-live in seconds. If provided, only returns entries
                 that are not older than this value.

        Returns:
            Optional[V]: Cached value if found and not expired, None otherwise.
        """
        # TTL of 0 or negative means entry must be from the future (impossible), so return None
        if ttl is not None and ttl <= 0:
            return None

        minimalUpdatedAt = (
            dbUtils.getCurrentTimestamp() - datetime.timedelta(seconds=ttl) if ttl is not None and ttl > 0 else None
        )

        try:
            _key = self.keyGenerator.generateKey(key)
            sqlProvider = await self.manager.getProvider(dataSource=self.dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT key, data, created_at, updated_at
                FROM cache
                WHERE namespace = :namespace AND
                        key = :cacheKey AND
                        (:minimalUpdatedAt IS NULL OR updated_at >= :minimalUpdatedAt)
            """,
                {
                    "namespace": self.namespace,
                    "cacheKey": _key,
                    "minimalUpdatedAt": minimalUpdatedAt,
                },
            )

            if row:
                cacheRow = dbUtils.sqlToTypedDict(row, _CacheRowDict)
                return self.valueConverter.decode(cacheRow["data"])
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    async def set(self, key: K, value: V) -> bool:
        """
        Store data in cache.

        Args:
            key: Cache key to store
            value: Value to cache

        Returns:
            bool: True if successfully stored, False on error.
        """
        try:
            _key = self.keyGenerator.generateKey(key)
            data = self.valueConverter.encode(value)
            sqlProvider = await self.manager.getProvider(dataSource=self.dataSource, readonly=False)
            now = dbUtils.getCurrentTimestamp()
            await sqlProvider.upsert(
                table="cache",
                values={
                    "namespace": self.namespace,
                    "key": _key,
                    "data": data,
                    "created_at": now,
                    "updated_at": now,
                },
                conflictColumns=["namespace", "key"],
                updateExpressions={
                    "data": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    async def clear(self) -> None:
        """
        Clear all cache entries in this namespace.

        Returns:
            None
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=self.dataSource, readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM cache
                WHERE
                    namespace = :cacheType
            """,
                {"cacheType": self.namespace},
            )
        except Exception as e:
            logger.error(f"Failed to clear cache {self.namespace}: {e}")

    async def clearOld(self, ttl: Optional[int]) -> bool:
        """
        Delete this cache's entries older than the given TTL.

        Scoped to the instance's own namespace (and data source, where the
        implementation has one). Best-effort: implementation errors are logged
        and reported through the return value, never raised.

        For ttl > 0, entries strictly older than now - ttl are deleted;
        ttl of 0 or None deletes every entry of the namespace outright.

        Args:
            ttl: Age threshold in seconds. For ttl > 0, entries strictly
                older than ``now - ttl`` are deleted. ``ttl`` of ``0`` or
                ``None`` deletes every entry of the namespace outright.
                Negative values are not part of the contract (legacy SQL
                happened to delete everything; implementations need not
                honor them).

        Returns:
            bool: True if the sweep completed successfully — regardless of
                whether any entries matched — False on backend error.
        """
        # Calculate the cutoff timestamp
        if ttl is None:
            ttl = 0
        now = dbUtils.getCurrentTimestamp()

        try:
            sqlProvider = await self.manager.getProvider(dataSource=self.dataSource, readonly=False)
            # Clear old entries of this instance's namespace
            # Special case: ttl=0 means delete everything (even entries with updated_at == now)
            if ttl == 0:
                # Delete all entries in this namespace
                await sqlProvider.execute(
                    """
                    DELETE FROM cache
                    WHERE
                        namespace = :cacheType
                """,
                    {"cacheType": self.namespace},
                )
            else:
                # Delete only entries strictly older than the cutoff
                cutoffTime = now - datetime.timedelta(seconds=ttl)
                await sqlProvider.execute(
                    """
                    DELETE FROM cache
                    WHERE
                        namespace = :cacheType AND
                        updated_at < :cutoffTime
                """,
                    {
                        "cacheType": self.namespace,
                        "cutoffTime": cutoffTime,
                    },
                )

            logger.info(f"Cleared old cache entries (older than {ttl}s, namespace={self.namespace}).")
            return True
        except Exception as e:
            logger.error(f"Failed to clear old cache entries: {e}")
            return False

    def getStats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns basic statistics about the cache state including the namespace
        and enabled status. Additional statistics could be added in the future
        such as entry count, hit/miss ratios, and size information.

        Returns:
            Dict[str, Any]: Dictionary containing cache statistics with keys:
                - enabled: bool indicating if cache is enabled
                - namespace: str namespace identifier
                - backend: str backend type identifier
                - keyGenerator: str key generator class name
                - valueConverter: str value converter class name
        """
        return {
            "enabled": True,
            "namespace": self.namespace,
            "backend": "database",
            "keyGenerator": type(self.keyGenerator).__name__,
            "valueConverter": type(self.valueConverter).__name__,
        }
