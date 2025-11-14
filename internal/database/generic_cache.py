"""
TODO
"""

import logging
from typing import Any, Dict, Optional

from lib.cache import CacheInterface, HashKeyGenerator, JsonValueConverter, K, KeyGenerator, V, ValueConverter

from .models import CacheType
from .wrapper import DatabaseWrapper

logger = logging.getLogger(__name__)


class GenericDatabaseCache(CacheInterface[K, V]):
    """TODO"""

    def __init__(
        self,
        db: DatabaseWrapper,
        namespace: CacheType,
        keyGenerator: Optional[KeyGenerator[K]] = None,
        valueConverter: Optional[ValueConverter[V]] = None,
    ):
        """
        Initialize cache with database wrapper

        Args:
            db_wrapper: DatabaseWrapper instance from internal.database.wrapper
            TODO: Update
        """
        self.db = db
        self.namespace = namespace
        self.keyGenerator: KeyGenerator[K] = keyGenerator if keyGenerator is not None else HashKeyGenerator()
        self.valueConverter: ValueConverter[V] = (
            valueConverter if valueConverter is not None else JsonValueConverter[V]()
        )

    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        """Get cached data if exists and not expired"""
        try:
            _key = self.keyGenerator.generateKey(key)
            cacheEntry = self.db.getCacheEntry(_key, cacheType=self.namespace, ttl=ttl)
            if cacheEntry is not None:
                return self.valueConverter.decode(cacheEntry["data"])
            return None
        except Exception as e:
            logger.error(f"Failed to get cache entry {key}: {e}")
            return None

    async def set(self, key: K, value: V) -> bool:
        """Store data in cache"""
        try:
            _key = self.keyGenerator.generateKey(key)
            data = self.valueConverter.encode(value)
            return self.db.setCacheEntry(_key, data=data, cacheType=self.namespace)
        except Exception as e:
            logger.error(f"Failed to set cache entry {key}: {e}")
            return False

    async def clear(self) -> None:
        self.db.clearCache(self.namespace)

    def getStats(self) -> Dict[str, Any]:
        """TODO"""
        # Add more stats, probably?
        return {"enabled": True}
