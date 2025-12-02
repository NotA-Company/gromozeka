"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import datetime
import hashlib
import logging
import sqlite3
import threading
from contextlib import contextmanager
from types import UnionType
from typing import Any, Dict, List, Optional, cast

import dateutil
from telegram import Chat

# Import from shared_enums to avoid circular dependency
from internal.models import MessageIdType, MessageType

from .models import (
    CacheDict,
    CacheStorageDict,
    CacheType,
    ChatInfoDict,
    ChatMessageDict,
    ChatSummarizationCacheDict,
    ChatTopicInfoDict,
    ChatUserDict,
    DelayedTaskDict,
    MediaAttachmentDict,
    MediaStatus,
    MessageCategory,
    SpamMessageDict,
    SpamReason,
)

logger = logging.getLogger(__name__)

DEFAULT_THREAD_ID: int = 0

MEDIA_TABLE_TABLE_ALIAS = "ma"
MEDIA_TABLE_PREFIX = "media_"
MEDIA_FIELDS_WITH_PREFIX = f"""
{MEDIA_TABLE_TABLE_ALIAS}.file_unique_id as {MEDIA_TABLE_PREFIX}file_unique_id,
{MEDIA_TABLE_TABLE_ALIAS}.file_id        as {MEDIA_TABLE_PREFIX}file_id,
{MEDIA_TABLE_TABLE_ALIAS}.file_size      as {MEDIA_TABLE_PREFIX}file_size,
{MEDIA_TABLE_TABLE_ALIAS}.media_type     as {MEDIA_TABLE_PREFIX}media_type,
{MEDIA_TABLE_TABLE_ALIAS}.metadata       as {MEDIA_TABLE_PREFIX}metadata,
{MEDIA_TABLE_TABLE_ALIAS}.status         as {MEDIA_TABLE_PREFIX}status,
{MEDIA_TABLE_TABLE_ALIAS}.mime_type      as {MEDIA_TABLE_PREFIX}mime_type,
{MEDIA_TABLE_TABLE_ALIAS}.local_url      as {MEDIA_TABLE_PREFIX}local_url,
{MEDIA_TABLE_TABLE_ALIAS}.prompt         as {MEDIA_TABLE_PREFIX}prompt,
{MEDIA_TABLE_TABLE_ALIAS}.description    as {MEDIA_TABLE_PREFIX}description,
{MEDIA_TABLE_TABLE_ALIAS}.created_at     as {MEDIA_TABLE_PREFIX}created_at,
{MEDIA_TABLE_TABLE_ALIAS}.updated_at     as {MEDIA_TABLE_PREFIX}updated_at
""".strip()


def convert_timestamp(val: bytes) -> datetime.datetime:
    valStr = val.decode("utf-8")
    ret = dateutil.parser.parse(valStr)
    # logger.debug(f"Converted {valStr} to {repr(ret)}")
    return ret
    # return datetime.datetime.strptime(valStr, '%Y-%m-%d %H:%M:%S')


def convert_boolean(val: bytes) -> bool:
    # logger.debug(f"Converting {val} (int: {int(val)}, {int(val[0])}) to {bool(int(val[0]))}")
    if len(val) == 0:
        return False
    elif len(val) == 1:
        return bool(int(val))
    else:
        raise ValueError(f"Invalid boolean value: {val}")


def adapt_datetime(val: datetime.datetime) -> str:
    """Adapt datetime.datetime to SQLite format string for sqlite3, dood!"""
    # Use SQLite's datetime format (YYYY-MM-DD HH:MM:SS) for consistency with CURRENT_TIMESTAMP
    # Strip microseconds to match SQLite's CURRENT_TIMESTAMP format exactly
    return val.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


# Register converters for reading from database
sqlite3.register_converter("timestamp", convert_timestamp)
sqlite3.register_converter("boolean", convert_boolean)

# Register adapters for writing to database (Python 3.12+ requirement)
sqlite3.register_adapter(datetime.datetime, adapt_datetime)


class SourceConfig:
    """
    Configuration for a single database source.
    """

    __slots__ = ["dbPath", "readonly", "timeout", "poolSize"]

    def __init__(
        self,
        *,
        dbPath: str,
        readonly: bool = False,
        timeout: int = 10,
        poolSize: int = 5,
    ) -> None:
        self.dbPath = dbPath
        """Path do DB file"""
        self.readonly = readonly
        """Whether the database is read-only"""
        self.timeout = timeout
        """Connection timeout in seconds"""
        self.poolSize = poolSize
        """Maximum connections per source"""

    def __repr__(self) -> str:
        retList = []
        for slot in self.__slots__:
            retList.append(f"{slot}={getattr(self, slot)}")

        return self.__class__.__name__ + "(" + ", ".join(retList) + ")"


class DatabaseWrapper:
    """
    A wrapper around SQLite that provides a consistent interface
    that can be easily replaced with other database backends.
    """

    def __init__(
        self,
        dbPath: Optional[str] = None,
        maxConnections: int = 5,
        timeout: float = 30.0,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize database wrapper with single or multi-source configuration, dood!

        Args:
            dbPath: Single database path (legacy mode, mutually exclusive with config)
            maxConnections: Max connections per source (default: 5)
            timeout: Connection timeout in seconds (default: 30.0)
            config: Multi-source config dict with 'sources', 'chatMapping', 'defaultSource'

        Raises:
            ValueError: If neither or both dbPath and config provided
        """
        # Validate initialization parameters
        if dbPath is None and config is None:
            raise ValueError("Either dbPath or config must be provided, dood!")
        if dbPath is not None and config is not None:
            raise ValueError("Cannot provide both dbPath and config - choose one mode, dood!")

        if dbPath:
            config = {
                "default": "default",
                "sources": {
                    "default": {
                        "path": dbPath,
                        "readonly": False,
                        "pool-size": maxConnections,
                        "timeout": timeout,
                    },
                },
            }

        if config is None:
            raise RuntimeError("Somehow config is None")

        logger.info("Initializing database wrapper in multi-source mode, dood!")
        self._initializeMultiSource(config, maxConnections, timeout)

        # Initialize database schema (works for both modes)
        self._initDatabase()

    def _initializeMultiSource(self, config: Dict[str, Any], defaultMaxConnections: int, defaultTimeout: float):
        """
        Initialize multi-source configuration and connection pools, dood!

        Args:
            config: Multi-source config dict with sources, chatMapping, default
            defaultMaxConnections: Default max connections per source
            defaultTimeout: Default timeout per source in seconds
        """
        # Initialize data structures for multi-source mode
        self._connections: Dict[str, threading.local] = {}
        self._sources: Dict[str, SourceConfig] = {}
        self._chatMapping: Dict[int, str] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._defaultSource: str = config.get("default", "default")

        # Parse and store source configurations
        sources = config.get("sources", {})
        if not sources:
            raise ValueError("Multi-source config must contain at least one source, dood!")

        for sourceName, sourceConfig in sources.items():
            if "path" not in sourceConfig:
                raise ValueError(f"Source '{sourceName}' missing required 'path' field, dood!")

            # Store source configuration with defaults
            self._sources[sourceName] = SourceConfig(
                dbPath=sourceConfig["path"],
                readonly=sourceConfig.get("readonly", False),
                poolSize=sourceConfig.get("pool-size", defaultMaxConnections),
                timeout=sourceConfig.get("timeout", defaultTimeout),
            )

            # Initialize thread-local storage for this source
            self._connections[sourceName] = threading.local()

            # Initialize lock for thread-safe connection management
            self._locks[sourceName] = threading.Lock()

            logger.info(f"Configured source '{sourceName}': {self._sources[sourceName]}, dood!")

        # Validate default source exists
        if self._defaultSource not in self._sources:
            raise ValueError(f"Default source '{self._defaultSource}' not found in sources configuration, dood!")

        # Parse chat-to-source mapping
        chatMapping = config.get("chatMapping", {})
        for chatId, sourceName in chatMapping.items():
            # Convert chatId to int if it's a string
            chatIdInt = int(chatId) if isinstance(chatId, str) else chatId

            # Validate source exists
            if sourceName not in self._sources:
                logger.warning(
                    f"Chat {chatIdInt} mapped to non-existent source '{sourceName}', "
                    f"will fall back to default source '{self._defaultSource}', dood!"
                )
                continue

            self._chatMapping[chatIdInt] = sourceName
            logger.debug(f"Mapped chat {chatIdInt} to source '{sourceName}', dood!")

        logger.info(
            f"Multi-source initialization complete: {len(self._sources)} sources, "
            f"{len(self._chatMapping)} chat mappings, default='{self._defaultSource}', dood!"
        )

    def _getConnection(
        self,
        *,
        chatId: Optional[int] = None,
        dataSource: Optional[str] = None,
        readonly: bool = False,
    ) -> sqlite3.Connection:
        """
        Get thread-local connection with 3-tier routing: dataSource → chatMapping → default, dood!

        Args:
            chatId: Chat ID for tier-2 routing via chatMapping
            dataSource: Explicit source name for tier-1 routing (highest priority)
            readonly: Request readonly connection (default: False = writable)

        Returns:
            sqlite3.Connection: Thread-local connection for selected source

        Raises:
            ValueError: If readonly=False on readonly source
        """
        # Multi-source mode - determine which source to use via 3-tier routing
        sourceName: str

        # Tier 1: Explicit dataSource parameter (highest priority)
        if dataSource is not None:
            if dataSource not in self._sources:
                logger.warning(
                    f"Explicit dataSource '{dataSource}' not found in configuration, "
                    f"falling back to default source '{self._defaultSource}', dood!"
                )
                sourceName = self._defaultSource
            else:
                logger.debug(f"Using explicit dataSource '{dataSource}' (tier 1 routing), dood!")
                sourceName = dataSource

        # Tier 2: ChatId mapping lookup (medium priority)
        elif chatId is not None:
            if chatId in self._chatMapping:
                mappedSource = self._chatMapping[chatId]
                # Validate mapped source still exists
                if mappedSource not in self._sources:
                    logger.warning(
                        f"Chat {chatId} mapped to non-existent source '{mappedSource}', "
                        f"falling back to default source '{self._defaultSource}', dood!"
                    )
                    sourceName = self._defaultSource
                else:
                    logger.debug(f"Using chatId {chatId} mapping to source '{mappedSource}' (tier 2 routing), dood!")
                    sourceName = mappedSource
            else:
                logger.debug(
                    f"Chat {chatId} not in mapping, using default source "
                    f"'{self._defaultSource}' (tier 3 fallback), dood!"
                )
                sourceName = self._defaultSource

        # Tier 3: Default source fallback (lowest priority)
        else:
            logger.debug(
                f"No routing parameters provided, using default source '{self._defaultSource}' (tier 3 fallback), dood!"
            )
            sourceName = self._defaultSource

        # Readonly validation - check before returning connection
        sourceConfig = self._sources[sourceName]
        if not readonly and sourceConfig.readonly:
            raise ValueError(
                f"Cannot perform write operation on readonly source '{sourceName}', dood! "
                f"This source is configured as readonly."
            )

        # Get or create thread-local connection for this source
        threadLocal = self._connections[sourceName]

        if not hasattr(threadLocal, "connection"):
            # Need to create new connection - acquire lock for thread safety
            with self._locks[sourceName]:
                # Double-check after acquiring lock (another thread might have created it)
                if not hasattr(threadLocal, "connection"):
                    logger.debug(
                        f"Creating new connection for source '{sourceName}' "
                        f"(path={sourceConfig.dbPath}, readonly={sourceConfig.readonly}), dood!"
                    )

                    # Create connection with source-specific configuration
                    threadLocal.connection = sqlite3.connect(
                        sourceConfig.dbPath,
                        timeout=sourceConfig.timeout,
                        check_same_thread=False,
                        detect_types=sqlite3.PARSE_DECLTYPES,
                    )
                    threadLocal.connection.row_factory = sqlite3.Row

                    # Enable query_only mode for readonly sources
                    if sourceConfig.readonly:
                        threadLocal.connection.execute("PRAGMA query_only = ON")
                        logger.debug(f"Enabled query_only mode for readonly source '{sourceName}', dood!")

        return threadLocal.connection

    @contextmanager
    def getCursor(
        self,
        *,
        chatId: Optional[int] = None,
        dataSource: Optional[str] = None,
        readonly: bool = False,
    ):
        """
        Context manager for database operations with routing support, dood!

        Args:
            chatId: Chat ID for routing
            dataSource: Explicit source name for routing
            readonly: Request readonly connection (default: False = writable)

        Yields:
            sqlite3.Cursor: Database cursor with auto-commit/rollback
        """
        conn = self._getConnection(chatId=chatId, dataSource=dataSource, readonly=readonly)
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database operation failed: {e}")
            logger.exception(e)
            raise
        finally:
            cursor.close()

    def close(self):
        """Close all database connections across all sources, dood!"""
        for sourceName, threadLocal in self._connections.items():
            if hasattr(threadLocal, "connection"):
                try:
                    threadLocal.connection.close()
                    logger.debug(f"Closed connection for source '{sourceName}', dood!")
                except Exception as e:
                    logger.error(f"Error closing connection for source '{sourceName}': {e}")

    def _initDatabase(self):
        """Initialize database schema and run migrations for all non-readonly sources, dood!"""
        # Import here to avoid circular dependency, dood!
        from .migrations import MigrationManager

        migrationManager = MigrationManager(self)
        try:
            migrationManager.loadMigrationsFromVersions()
            logger.info("Loaded migrations, dood!")
        except Exception as e:
            logger.error(f"Migration auto-discovery failed: {e}")
            raise e

        # Initialize each non-readonly datasource
        for sourceName, sourceConfig in self._sources.items():
            if sourceConfig.readonly:
                logger.info(f"Skipping DB initialization for readonly source '{sourceName}', dood!")
                continue

            logger.info(f"Initializing database for source '{sourceName}', dood!")

            # Create settings table (needed before migrations for version tracking)
            with self.getCursor(dataSource=sourceName) as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )

            # Run migrations for this source
            migrationManager.migrate(dataSource=sourceName)
            logger.info(f"Database initialization complete for source '{sourceName}', dood!")

        logger.info("All non-readonly databases initialized, dood!")

    ###
    # TypedDict validation and conversion helpers
    ###

    def _validateDictIsChatMessageDict(self, row_dict: Dict[str, Any]) -> ChatMessageDict:
        """
        Validate and convert a database row dictionary to ChatMessageDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Convert enum string values to proper enum types if needed
            if "message_category" in row_dict and isinstance(row_dict["message_category"], str):
                try:
                    row_dict["message_category"] = MessageCategory(row_dict["message_category"])
                except ValueError:
                    logger.warning(f"Unknown message_category: {row_dict['message_category']}")
                    # Keep as string if not a valid enum value

            if (
                "media_status" in row_dict
                and row_dict["media_status"] is not None
                and isinstance(row_dict["media_status"], str)
            ):
                try:
                    row_dict["media_status"] = MediaStatus(row_dict["media_status"])
                except ValueError:
                    logger.warning(f"Unknown media_status: {row_dict['media_status']}")
                    # Keep as string if not a valid enum value

            # Ensure required fields are present with proper types
            required_fields: Dict[str, UnionType | type | tuple[type, ...]] = {
                "chat_id": int,
                "message_id": MessageIdType,
                "date": datetime.datetime,
                "user_id": int,
                "thread_id": int,
                "message_text": str,
                "message_type": str,
                "created_at": datetime.datetime,
                "username": str,
                "full_name": str,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(
                        f"Field '{field}' has unexpected type: {type(row_dict[field])}, " f"expected {expected_type}"
                    )

            # Return the validated dictionary cast as ChatMessageDict
            return cast(ChatMessageDict, row_dict)

        except Exception as e:
            logger.error(f"Failed to validate ChatMessageDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsChatUserDict(self, row_dict: Dict[str, Any]) -> ChatUserDict:
        """
        Validate and convert a database row dictionary to ChatUserDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "chat_id": int,
                "user_id": int,
                "username": str,
                "full_name": str,
                "messages_count": int,
                "metadata": str,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(
                        f"Field '{field}' has unexpected type: {type(row_dict[field])}, " f"expected {expected_type}"
                    )

            # Return the validated dictionary cast as ChatUserDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate ChatUserDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsChatInfoDict(self, row_dict: Dict[str, Any]) -> ChatInfoDict:
        """
        Validate and convert a database row dictionary to ChatInfoDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "chat_id": int,
                "type": str,
                "is_forum": bool,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(
                        f"Field '{field}' has unexpected type: {type(row_dict[field])}, " f"expected {expected_type}"
                    )

            # Return the validated dictionary cast as ChatInfoDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate ChatInfoDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsChatTopicDict(self, row_dict: Dict[str, Any]) -> ChatTopicInfoDict:
        """
        Validate and convert a database row dictionary to ChatTopicDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "chat_id": int,
                "topic_id": int,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(
                        f"Field '{field}' has unexpected type: {type(row_dict[field])}, " f"expected {expected_type}"
                    )

            # Return the validated dictionary cast as ChatTopicDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate ChatTopicDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsMediaAttachmentDict(self, row_dict: Dict[str, Any]) -> MediaAttachmentDict:
        """
        Validate and convert a database row dictionary to MediaAttachmentDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Convert enum string values to proper enum types if needed
            if "status" in row_dict and isinstance(row_dict["status"], str):
                try:
                    row_dict["status"] = MediaStatus(row_dict["status"])
                except ValueError:
                    logger.warning(f"Unknown media status: {row_dict['status']}")
                    # Keep as string if not a valid enum value

            # Ensure required fields are present with proper types
            required_fields = {
                "file_unique_id": str,
                "media_type": str,
                "metadata": str,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(
                        f"Field '{field}' has unexpected type: {type(row_dict[field])}, " f"expected {expected_type}"
                    )

            # Return the validated dictionary cast as MediaAttachmentDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate MediaAttachmentDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsDelayedTaskDict(self, row_dict: Dict[str, Any]) -> DelayedTaskDict:
        """
        Validate and convert a database row dictionary to DelayedTaskDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "id": str,
                "delayed_ts": int,
                "function": str,
                "kwargs": str,
                "is_done": bool,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(f"Field '{field}' has type {type(row_dict[field])}, expected {expected_type}")

            # Return the validated dictionary cast as DelayedTaskDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate DelayedTaskDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsSpamMessageDict(self, row_dict: Dict[str, Any]) -> SpamMessageDict:
        """
        Validate and convert a database row dictionary to SpamMessageDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Convert enum string values to proper enum types if needed
            if "reason" in row_dict and isinstance(row_dict["reason"], str):
                try:
                    row_dict["reason"] = SpamReason(row_dict["reason"])
                except ValueError:
                    logger.warning(f"Unknown spam reason: {row_dict['reason']}")
                    # Keep as string if not a valid enum value

            # Ensure required fields are present with proper types
            required_fields = {
                "chat_id": int,
                "user_id": int,
                "message_id": int,
                "text": str,
                "score": float,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(f"Field '{field}' has type {type(row_dict[field])}, expected {expected_type}")

            # Return the validated dictionary cast as SpamMessageDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate SpamMessageDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsChatSummarizationCacheDict(self, row_dict: Dict[str, Any]) -> ChatSummarizationCacheDict:
        """
        Validate and convert a database row dictionary to ChatSummarizationCacheDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "csid": str,
                "chat_id": int,
                "first_message_id": int,
                "last_message_id": int,
                "prompt": str,
                "summary": str,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in row_dict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if row_dict[field] is not None and not isinstance(row_dict[field], expected_type):
                    logger.warning(f"Field '{field}' has type {type(row_dict[field])}, expected {expected_type}")

            # Return the validated dictionary cast as ChatSummarizationCacheDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate ChatSummarizationCacheDict: {e}")
            logger.error(f"Row data: {row_dict}")
            raise

    def _validateDictIsCacheDict(self, rowDict: Dict[str, Any]) -> CacheDict:
        """
        Validate and convert a database row dictionary to CacheDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "key": str,
                "data": str,
                "created_at": datetime.datetime,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in rowDict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if rowDict[field] is not None and not isinstance(rowDict[field], expected_type):
                    logger.warning(f"Field '{field}' has type {type(rowDict[field])}, expected {expected_type}")

            # Return the validated dictionary cast as CacheDict
            return rowDict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate CacheDict: {e}")
            logger.error(f"Row data: {rowDict}")
            raise

    def _validateDictIsCacheStorageDict(self, rowDict: Dict[str, Any]) -> CacheStorageDict:
        """
        Validate and convert a database row dictionary to CacheStorageDict.
        This ensures the returned data matches the expected TypedDict structure.
        """
        try:
            # Ensure required fields are present with proper types
            required_fields = {
                "namespace": str,
                "key": str,
                "value": str,
                "updated_at": datetime.datetime,
            }

            for field, expected_type in required_fields.items():
                if field not in rowDict:
                    logger.error(f"Missing required field '{field}' in database row")
                    raise ValueError(f"Missing required field: {field}")

                if rowDict[field] is not None and not isinstance(rowDict[field], expected_type):
                    logger.warning(f"Field '{field}' has type {type(rowDict[field])}, expected {expected_type}")

            # Return the validated dictionary cast as CacheStorageDict
            return rowDict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate CacheStorageDict: {e}")
            logger.error(f"Row data: {rowDict}")
            raise

    ###
    # Global Settings manipulation functions (Are they used an all?)
    ###

    def setSetting(self, key: str, value: str, *, dataSource: Optional[str] = None) -> bool:
        """
        Set a configuration setting.

        Args:
            key: Setting key
            value: Setting value
            dataSource: Optional data source name for explicit routing

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(dataSource=dataSource, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO settings
                    (key, value, updated_at)
                    VALUES (:key, :value, CURRENT_TIMESTAMP)
                """,
                    {
                        "key": key,
                        "value": value,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to set setting {key} in {dataSource}: {e}")
            return False

    def getSetting(self, key: str, default: Optional[str] = None, *, dataSource: Optional[str] = None) -> Optional[str]:
        """Get a configuration setting.

        Args:
            key: Setting key to retrieve
            default: Default value if key not found
            dataSource: Optional data source name

        Returns:
            Setting value or default if not found"""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row["value"] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key} in {dataSource}: {e}")
            return default

    def getSettings(self, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """Get all configuration settings.

        Args:
            dataSource: Optional data source name

        Returns:
            Dictionary of all key-value settings"""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute("SELECT * FROM settings")
                return {row["key"]: row["value"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings in {dataSource}: {e}")
            return {}

    ###
    # Chat messages manipulation functions
    ###
    def saveChatMessage(
        self,
        date: datetime.datetime,
        chatId: int,
        userId: int,
        messageId: MessageIdType,
        replyId: Optional[MessageIdType] = None,
        threadId: Optional[int] = None,
        messageText: str = "",
        messageType: MessageType = MessageType.TEXT,
        messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
        rootMessageId: Optional[MessageIdType] = None,
        quoteText: Optional[str] = None,
        mediaId: Optional[str] = None,
    ) -> bool:
        """
        Save a chat message with detailed information.

        Args:
            date: Message timestamp
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            messageId: Message identifier
            replyId: Optional reply message ID
            threadId: Optional thread ID
            messageText: Message text content
            messageType: Type of message
            messageCategory: Message category
            rootMessageId: Optional root message ID for threads
            quoteText: Optional quoted text
            mediaId: Optional media attachment ID

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        messageId = str(messageId)
        if replyId is not None:
            replyId = str(replyId)
        if rootMessageId is not None:
            rootMessageId = str(rootMessageId)

        if threadId is None:
            threadId = DEFAULT_THREAD_ID
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                today = date.replace(hour=0, minute=0, second=0, microsecond=0)
                cursor.execute(
                    """
                    INSERT INTO chat_messages
                    (date, chat_id, user_id, message_id,
                        reply_id, thread_id, message_text, message_type,
                        message_category, root_message_id, quote_text,
                        media_id
                        )
                    VALUES
                    (:date, :chatId, :userId, :messageId,
                        :replyId, :threadId, :messageText, :messageType,
                        :messageCategory, :rootMessageId, :quoteText,
                        :mediaId
                        )
                """,
                    {
                        "date": date,
                        "chatId": chatId,
                        "userId": userId,
                        "messageId": messageId,
                        "replyId": replyId,
                        "threadId": threadId,
                        "messageText": messageText,
                        "messageType": messageType,
                        "messageCategory": str(messageCategory),
                        "rootMessageId": rootMessageId,
                        "quoteText": quoteText,
                        "mediaId": mediaId,
                    },
                )

                cursor.execute(
                    """
                    UPDATE chat_users
                    SET messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE chat_id = ? AND user_id = ?
                """,
                    (chatId, userId),
                )

                cursor.execute(
                    """
                    INSERT INTO chat_stats
                    (chat_id, date, messages_count, updated_at)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id, date) DO UPDATE SET
                        messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    (chatId, today),
                )

                cursor.execute(
                    """
                    INSERT INTO chat_user_stats
                    (chat_id, user_id, date, messages_count, updated_at)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id, user_id, date) DO UPDATE SET
                        messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    (chatId, userId, today),
                )

                return True
        except Exception as e:
            logger.error(f"Failed to save chat message from user {userId} in chat {chatId}: {e}")
            return False

    def getChatMessagesSince(
        self,
        chatId: int,
        sinceDateTime: Optional[datetime.datetime] = None,
        tillDateTime: Optional[datetime.datetime] = None,
        threadId: Optional[int] = None,
        limit: Optional[int] = None,
        messageCategory: Optional[List[MessageCategory]] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """
        Get chat messages from a specific chat newer than the given date.

        Args:
            chatId: Chat identifier
            sinceDateTime: Optional start date for message filtering
            tillDateTime: Optional end date for message filtering
            threadId: Optional thread identifier for filtering
            limit: Optional maximum number of messages to return
            messageCategory: Optional list of message categories to filter
            dataSource: Optional data source name for explicit routing

        Returns:
            List of ChatMessageDict objects matching the criteria
        """
        logger.debug(
            f"Getting chat messages for chat {chatId}:{threadId} "
            f"date: [{sinceDateTime},{tillDateTime}], limit: {limit}, "
            f"messageCategory: {messageCategory}"
        )
        try:
            params = {
                "chatId": chatId,
                "sinceDateTime": sinceDateTime,
                "tillDateTime": tillDateTime,
                "threadId": threadId,
                "messageCategory": None if messageCategory is None else True,
            }

            placeholders = []
            if messageCategory is not None:
                for i, category in enumerate(messageCategory):
                    placeholders.append(f":messageCategory{i}")
                    params[f"messageCategory{i}"] = category

            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                query = f"""
                    SELECT c.*, u.username, u.full_name, {MEDIA_FIELDS_WITH_PREFIX}  FROM chat_messages c
                    JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                    LEFT JOIN media_attachments ma ON c.media_id IS NOT NULL AND c.media_id = ma.file_unique_id
                    WHERE
                        c.chat_id = :chatId
                        AND (:sinceDateTime   IS NULL OR c.date > :sinceDateTime)
                        AND (:tillDateTime    IS NULL OR c.date < :tillDateTime)
                        AND (:threadId        IS NULL OR c.thread_id = :threadId)
                        AND (:messageCategory IS NULL OR message_category IN ({", ".join(placeholders)}))
                    ORDER BY c.date DESC
                """
                if limit is not None:
                    query += f" LIMIT {int(limit)}"

                cursor.execute(
                    query,
                    params,
                )
                rows = cursor.fetchall()
                return [self._validateDictIsChatMessageDict(dict(row)) for row in rows]
        except Exception as e:
            logger.error(
                f"Failed to get chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId}): {e}"
            )
            return []

    def getChatMessageByMessageId(
        self, chatId: int, messageId: MessageIdType, *, dataSource: Optional[str] = None
    ) -> Optional[ChatMessageDict]:
        """
        Get a specific chat message by message_id, chat_id, and optional thread_id.

        Args:
            chatId: Chat identifier
            messageId: Message identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatMessageDict or None if not found
        """
        logger.debug(f"Getting chat message for chat {chatId}, message_id {messageId}")
        messageId = str(messageId)
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    f"""
                    SELECT c.*, u.username, u.full_name, {MEDIA_FIELDS_WITH_PREFIX} FROM chat_messages c
                    JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                    LEFT JOIN media_attachments ma ON c.media_id IS NOT NULL AND c.media_id = ma.file_unique_id
                    WHERE
                        c.chat_id = :chatId
                        AND c.message_id = :messageId
                    LIMIT 1
                """,
                    {"chatId": chatId, "messageId": messageId},
                )
                row = cursor.fetchone()
                return self._validateDictIsChatMessageDict(dict(row)) if row else None
        except Exception as e:
            logger.error(f"Failed to get chat message for chat {chatId}, message_id {messageId}: {e}")
            return None

    def getChatMessagesByRootId(
        self,
        chatId: int,
        rootMessageId: int,
        threadId: Optional[int] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[ChatMessageDict]:
        """Get all chat messages in a conversation thread by root message ID.

        Args:
            chatId: Chat identifier
            rootMessageId: Root message ID to find thread messages for
            threadId: Optional thread ID to filter by
            dataSource: Optional data source identifier for multi-source database routing

        Returns:
            List of chat message dictionaries in the thread
        """
        logger.debug(f"Getting chat messages for chat {chatId}, thread {threadId}, root_message_id {rootMessageId}")
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    f"""
                    SELECT c.*, u.username, u.full_name, {MEDIA_FIELDS_WITH_PREFIX} FROM chat_messages c
                    JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                    LEFT JOIN media_attachments ma ON c.media_id IS NOT NULL AND c.media_id = ma.file_unique_id
                    WHERE
                        c.chat_id = :chatId
                        AND c.root_message_id = :rootMessageId
                        AND ((:threadId IS NULL) OR (c.thread_id = :threadId))
                    ORDER BY c.date ASC
                """,
                    {
                        "chatId": chatId,
                        "rootMessageId": rootMessageId,
                        "threadId": threadId,
                    },
                )
                rows = cursor.fetchall()
                return [self._validateDictIsChatMessageDict(dict(row)) for row in rows]
        except Exception as e:
            logger.error(
                f"Failed to get chat messages for chat {chatId}, thread {threadId}, "
                f"root_message_id {rootMessageId}: {e}"
            )
            return []

    def getChatMessagesByUser(
        self, chatId: int, userId: int, limit: int = 100, *, dataSource: Optional[str] = None
    ) -> List[ChatMessageDict]:
        """
        Get all chat messages by user ID.

        Args:
            chatId: Chat identifier
            userId: User identifier
            limit: Maximum number of messages to return (default: 100)
            dataSource: Optional data source name for explicit routing

        Returns:
            List of ChatMessageDict
        """
        logger.debug(f"Getting chat messages for chat {chatId}, user {userId}")
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    f"""
                    SELECT c.*, u.username, u.full_name, {MEDIA_FIELDS_WITH_PREFIX} FROM chat_messages c
                    JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                    LEFT JOIN media_attachments ma ON c.media_id IS NOT NULL AND c.media_id = ma.file_unique_id
                    WHERE
                        c.chat_id = :chatId
                        AND c.user_id = :userId
                    ORDER BY c.date DESC
                    LIMIT :limit
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "limit": limit,
                    },
                )
                return [self._validateDictIsChatMessageDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get chat messages for chat {chatId}, user {userId}: {e}")
            return []

    def updateChatMessageCategory(
        self,
        chatId: int,
        messageId: MessageIdType,
        messageCategory: MessageCategory,
    ) -> bool:
        """Update the category of a chat message."""
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    UPDATE chat_messages
                    SET message_category = :category
                    WHERE
                        chat_id = :chatId
                        AND message_id = :messageId
                """,
                    {
                        "chatId": chatId,
                        "messageId": messageId,
                        "category": messageCategory,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update category for message {messageId} in chat {chatId}: {e}")
            return False

    ###
    # Chat Users manipulation functions
    ###

    def updateChatUser(self, chatId: int, userId: int, username: str, fullName: str) -> bool:
        """Store or update a user as a chat member with their current information.

        This method performs an upsert operation on the chat_users table. If the user
        is not already a member of the chat, they will be added. If they already exist,
        their @username, full_name, and updated_at timestamp will be refreshed.

        Args:
            chatId: The unique identifier of the chat (used for source routing)
            userId: The unique identifier of the user
            username: The current @username of the user (may be None) (Note: Should be with @ sign)
            fullName: The current full name/display name of the user

        Returns:
            bool: True if the operation succeeded, False if an exception occurred

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
            The updated_at timestamp is automatically set to CURRENT_TIMESTAMP
            on both insert and update operations, dood.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_users
                        (chat_id, user_id, username, full_name, updated_at)
                    VALUES
                        (:chatId, :userId, :username, :fullName, CURRENT_TIMESTAMP)
                    ON CONFLICT(chat_id, user_id) DO UPDATE SET
                        username = excluded.username,
                        full_name = excluded.full_name,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "username": username,
                        "fullName": fullName,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update username for user {userId} in chat {chatId}: {e}")
            return False

    def getChatUser(self, chatId: int, userId: int, *, dataSource: Optional[str] = None) -> Optional[ChatUserDict]:
        """
        Get the username of a user in a chat.

        Args:
            chatId: Chat identifier
            userId: User identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatUserDict or None if not found
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM chat_users
                    WHERE
                        chat_id = ?
                        AND user_id = ?
                    LIMIT 1
                """,
                    (chatId, userId),
                )
                row = cursor.fetchone()
                return self._validateDictIsChatUserDict(dict(row)) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {userId} in chat {chatId}: {e}")
            return None

    def markUserIsSpammer(self, chatId: int, userId: int, isSpammer: bool) -> bool:
        """
        Mark a user as spammer.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            isSpammer: Whether user is a spammer

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    UPDATE chat_users
                    SET is_spammer = :isSpammer
                    WHERE
                        chat_id = :chatId
                        AND user_id = :userId
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "isSpammer": isSpammer,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to mark user {userId} as spammer in chat {chatId}: {e}")
            return False

    def updateUserMetadata(self, chatId: int, userId: int, metadata: str) -> bool:
        """
        Update metadata for a chat user.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            metadata: Metadata string

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    UPDATE chat_users
                    SET metadata = :metadata,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE
                        chat_id = :chatId
                        AND user_id = :userId
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "metadata": metadata,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update metadata for user {userId} in chat {chatId}: {e}")
            return False

    def getChatUserByUsername(
        self,
        chatId: int,
        username: str,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[ChatUserDict]:
        """
        Get the user id of a user in a chat.

        Args:
            chatId: Chat identifier
            username: Username to search for
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatUserDict or None if not found
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM chat_users
                    WHERE
                        chat_id = :chatId
                        AND username = :username
                    LIMIT 1
                """,
                    {
                        "chatId": chatId,
                        "username": username,
                    },
                )
                row = cursor.fetchone()
                return self._validateDictIsChatUserDict(dict(row)) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {username} in chat {chatId}: {e}")
            return None

    def getChatUsers(
        self,
        chatId: int,
        limit: int = 10,
        seenSince: Optional[datetime.datetime] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[ChatUserDict]:
        """
        Get the usernames of all users in a chat,
        optionally filtered by when they last sent a message.

        Args:
            chatId: The chat ID to get users from
            limit: Maximum number of users to return
            seenSince: Optional datetime to filter users by last message time
            dataSource: Optional data source identifier for multi-source database routing

        Returns:
            List of ChatUserDict objects representing users in the chat
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM chat_users
                    WHERE
                        chat_id = :chatId
                        AND (:seenSince IS NULL OR updated_at > :seenSince)
                    ORDER BY updated_at DESC
                    LIMIT :limit
                """,
                    {
                        "chatId": chatId,
                        "limit": limit,
                        "seenSince": seenSince,
                    },
                )

                return [self._validateDictIsChatUserDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get users for chat {chatId}: {e}")
            return []

    def getUserChats(self, userId: int, *, dataSource: Optional[str] = None) -> List[ChatInfoDict]:
        """
        Get chats user was seen in.

        Args:
            userId: User identifier
            dataSource: Optional data source name. If None in multi-source mode,
                       aggregates from all sources and deduplicates by (userId, chatId).

        Returns:
            List of ChatInfoDict
        """

        # Multi-source aggregation
        logger.debug(f"Aggregating getUserChats for user {userId} from sources, dood!")
        allResults = []
        seen = set()  # Deduplicate by (userId, chatId)

        sourcesList = [dataSource] if dataSource else self._sources.keys()

        for sourceName in sourcesList:
            try:
                with self.getCursor(dataSource=sourceName, readonly=True) as cursor:
                    cursor.execute(
                        """
                        SELECT ci.* FROM chat_info ci
                        JOIN chat_users cu ON cu.chat_id = ci.chat_id
                        WHERE
                            user_id = :userId
                    """,
                        {
                            "userId": userId,
                        },
                    )
                    for row in cursor.fetchall():
                        chatInfo = self._validateDictIsChatInfoDict(dict(row))
                        key = (userId, chatInfo["chat_id"])
                        if key not in seen:
                            seen.add(key)
                            allResults.append(chatInfo)
            except Exception as e:
                logger.warning(f"Failed to get chats from source '{sourceName}': {e}, dood!")
                continue

        logger.debug(f"Aggregated {len(allResults)} unique chats for user {userId}, dood!")
        return allResults

    def getAllGroupChats(self, *, dataSource: Optional[str] = None) -> List[ChatInfoDict]:
        """
        Get all group chats.

        Args:
            dataSource: Optional data source name. If None in multi-source mode,
                       aggregates from all sources and deduplicates by chatId.

        Returns:
            List of ChatInfoDict
        """
        # Multi-source aggregation
        logger.debug("Aggregating getAllGroupChats from sources, dood!")
        allResults = []
        seen = set()  # Deduplicate by chatId

        sourcesList = [dataSource] if dataSource else self._sources.keys()
        for sourceName in sourcesList:
            try:
                with self.getCursor(dataSource=sourceName, readonly=True) as cursor:
                    cursor.execute(
                        """
                        SELECT ci.* FROM chat_info ci
                        WHERE
                            type in (:groupChat, :supergroupChat)
                    """,
                        {
                            "groupChat": Chat.GROUP,
                            "supergroupChat": Chat.SUPERGROUP,
                        },
                    )
                    for row in cursor.fetchall():
                        chatInfo = self._validateDictIsChatInfoDict(dict(row))
                        chatId = chatInfo["chat_id"]
                        if chatId not in seen:
                            seen.add(chatId)
                            allResults.append(chatInfo)
            except Exception as e:
                logger.warning(f"Failed to get group chats from source '{sourceName}': {e}, dood!")
                continue

        logger.debug(f"Aggregated {len(allResults)} unique group chats, dood!")
        return allResults

    ###
    # User Data manipulation functions
    ###

    def addUserData(self, userId: int, chatId: int, key: str, data: str) -> bool:
        """
        Add user knowledge to the database.

        Args:
            userId: User identifier
            chatId: Chat identifier (used for source routing)
            key: Data key
            data: Data value

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_data
                        (user_id, chat_id, key, data)
                    VALUES
                        (:userId, :chatId, :key, :data)
                    ON CONFLICT DO UPDATE SET
                        data = :data,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    {
                        "userId": userId,
                        "chatId": chatId,
                        "key": key,
                        "data": data,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to add user knowledge: {e}")
            return False

    def getUserData(self, userId: int, chatId: int, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """
        Get user knowledge from the database.

        Args:
            userId: User identifier
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            Dictionary mapping keys to data values
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM user_data
                    WHERE
                        user_id = :userId AND chat_id = :chatId
                """,
                    {
                        "userId": userId,
                        "chatId": chatId,
                    },
                )
                return {row["key"]: row["data"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get user knowledge: {e}")
            return {}

    def deleteUserData(self, userId: int, chatId: int, key: str) -> bool:
        """
        Delete specific user data.

        Args:
            userId: User identifier
            chatId: Chat identifier (used for source routing)
            key: Data key to delete

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    DELETE FROM user_data
                    WHERE chat_id = :chatId AND
                        user_id = :userId AND
                        key = :key
                    """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "key": key,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to delete user {chatId}:{userId} data {key}: {e}")
            return False

    def clearUserData(self, userId: int, chatId: int) -> bool:
        """
        Clear all user data in chat.

        Args:
            userId: User identifier
            chatId: Chat identifier (used for source routing)

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    DELETE FROM user_data
                    WHERE chat_id = :chatId AND
                        user_id = :userId
                    """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to clear user {chatId}:{userId} data: {e}")
            return False

    ###
    # Chat Settings manipulation (see chat_settings.py for more details)
    ###

    def setChatSetting(self, chatId: int, key: str, value: Any) -> bool:
        """
        Set a setting for a chat.

        Args:
            chatId: Chat identifier (used for source routing)
            key: Setting key
            value: Setting value

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO chat_settings
                        (chat_id, key, value, updated_at)
                    VALUES
                        (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (chatId, key, value),
                )
                return True
        except Exception as e:
            logger.error(f"Failed to set setting {key} for chat {chatId}: {e}")
            return False

    def unsetChatSetting(self, chatId: int, key: str) -> bool:
        """
        Unset a setting for a chat.

        Args:
            chatId: Chat identifier (used for source routing)
            key: Setting key to remove

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    DELETE FROM chat_settings
                    WHERE chat_id = ?
                        AND key = ?
                """,
                    (chatId, key),
                )
                return True
        except Exception as e:
            logger.error(f"Failed to unset setting {key} for chat {chatId}: {e}")
            return False

    def clearChatSettings(self, chatId: int) -> bool:
        """
        Clear all settings for a chat.

        Args:
            chatId: Chat identifier (used for source routing)

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    DELETE FROM chat_settings
                    WHERE chat_id = ?
                """,
                    (chatId,),
                )
                return True
        except Exception as e:
            logger.error(f"Failed to clear settings for chat {chatId}: {e}")
            return False

    def getChatSetting(self, chatId: int, setting: str, *, dataSource: Optional[str] = None) -> Optional[str]:
        """
        Get a setting for a chat.

        Args:
            chatId: Chat identifier
            setting: Setting key to retrieve
            dataSource: Optional data source name for explicit routing

        Returns:
            Setting value or None if not found
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT value FROM chat_settings
                    WHERE
                        chat_id = ?
                        AND key = ?
                    LIMIT 1
                """,
                    (chatId, setting),
                )
                row = cursor.fetchone()
                return row["value"] if row else None
        except Exception as e:
            logger.error(f"Failed to get setting {setting} for chat {chatId}: {e}")
            return None

    def getChatSettings(self, chatId: int, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """Get all settings for a chat."""
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT key, value FROM chat_settings
                    WHERE chat_id = ?
                """,
                    (chatId,),
                )
                return {row["key"]: row["value"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings for chat {chatId}: {e}")
            return {}

    ###
    # Chat Info manipulation
    ###
    def updateChatInfo(
        self,
        chatId: int,
        type: str,
        title: Optional[str] = None,
        username: Optional[str] = None,
        isForum: Optional[bool] = False,
    ) -> bool:
        """Add chat info to the database."""
        if isForum is None:
            isForum = False
        try:
            with self.getCursor(chatId=chatId) as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_info
                        (chat_id, type, title, username, is_forum)
                    VALUES
                        (:chatId, :type, :title, :username, :isForum)
                    ON CONFLICT DO UPDATE SET
                        type = :type,
                        title = :title,
                        username = :username,
                        is_forum = :isForum,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    {
                        "chatId": chatId,
                        "type": type,
                        "title": title,
                        "username": username,
                        "isForum": isForum,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to add chat info: {e}")
            logger.exception(e)
            return False

    def getChatInfo(self, chatId: int, *, dataSource: Optional[str] = None) -> Optional[ChatInfoDict]:
        """
        Get chat info from the database.

        Args:
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatInfoDict or None if not found
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM chat_info
                    WHERE
                        chat_id = :chatId
                """,
                    {
                        "chatId": chatId,
                    },
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return self._validateDictIsChatInfoDict(dict(row))
        except Exception as e:
            logger.error(f"Failed to get chat info: {e}")
            return None

    def updateChatTopicInfo(
        self,
        chatId: int,
        topicId: int,
        iconColor: Optional[int] = None,
        customEmojiId: Optional[str] = None,
        topicName: Optional[str] = None,
    ) -> bool:
        """
        Store or update chat topic information.

        Args:
            chatId: Chat identifier (used for source routing)
            topicId: Topic identifier
            iconColor: Optional icon color
            customEmojiId: Optional custom emoji ID
            topicName: Optional topic name

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        if topicName is None:
            topicName = "Default"
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_topics
                        (chat_id, topic_id, icon_color, icon_custom_emoji_id, name, updated_at)
                    VALUES
                        (:chatId, :topicId, :iconColor, :customEmojiId, :topicName, CURRENT_TIMESTAMP)
                    ON CONFLICT(chat_id, topic_id) DO UPDATE SET
                        icon_color = excluded.icon_color,
                        icon_custom_emoji_id = excluded.icon_custom_emoji_id,
                        name = excluded.name,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    {
                        "chatId": chatId,
                        "topicId": topicId,
                        "iconColor": iconColor,
                        "customEmojiId": customEmojiId,
                        "topicName": topicName,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update chat topic {topicId} in chat {chatId}: {e}")
            return False

    def getChatTopics(self, chatId: int, *, dataSource: Optional[str] = None) -> List[ChatTopicInfoDict]:
        """
        Get chat topics.

        Args:
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            List of ChatTopicInfoDict
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM chat_topics
                    WHERE
                        chat_id = :chatId
                """,
                    {
                        "chatId": chatId,
                    },
                )
                return [self._validateDictIsChatTopicDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get chat topics: {e}")
            return []

    ###
    # Chat Summarization
    ###
    def _makeChatSummarizationCSID(
        self,
        chatId: int,
        topicId: Optional[int],
        firstMessageId: MessageIdType,
        lastMessageId: MessageIdType,
        prompt: str,
    ) -> str:
        """
        Make CSID for chat summarization cache using SHA512 hash.

        Args:
            chatId: Chat identifier
            topicId: Optional topic identifier
            firstMessageId: First message ID in the range
            lastMessageId: Last message ID in the range
            prompt: Summarization prompt text

        Returns:
            SHA512 hash string of the cache key components
        """
        cacheKeyString = f"{chatId}:{topicId}_{firstMessageId}:{lastMessageId}-{prompt}"
        return hashlib.sha512(cacheKeyString.encode("utf-8")).hexdigest()

    def addChatSummarization(
        self,
        chatId: int,
        topicId: Optional[int],
        firstMessageId: MessageIdType,
        lastMessageId: MessageIdType,
        prompt: str,
        summary: str,
    ) -> bool:
        """
        Store chat summarization into cache.

        Args:
            chatId: Chat identifier (used for source routing)
            topicId: Optional topic identifier
            firstMessageId: First message ID in range
            lastMessageId: Last message ID in range
            prompt: Summarization prompt
            summary: Generated summary

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        csid = self._makeChatSummarizationCSID(chatId, topicId, firstMessageId, lastMessageId, prompt)

        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_summarization_cache
                        (csid, chat_id, topic_id, first_message_id, last_message_id,
                         prompt, summary, created_at, updated_at)
                    VALUES (:csid, :chatId, :topicId, :firstMessageId, :lastMessageId,
                            :prompt, :summary, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(csid) DO UPDATE SET
                        summary = excluded.summary,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    {
                        "csid": csid,
                        "chatId": chatId,
                        "topicId": topicId,
                        "firstMessageId": firstMessageId,
                        "lastMessageId": lastMessageId,
                        "prompt": prompt,
                        "summary": summary,
                    },
                )
                logger.debug(f"Added/updated chat summarization cache: csid={csid}")
                return True
        except Exception as e:
            logger.error(f"Failed to add chat summarization cache: {e}")
            return False

    def getChatSummarization(
        self,
        chatId: int,
        topicId: Optional[int],
        firstMessageId: MessageIdType,
        lastMessageId: MessageIdType,
        prompt: str,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[ChatSummarizationCacheDict]:
        """Fetch chat summarization from cache by chatId, topicId, firstMessageId, lastMessageId and prompt"""
        try:
            csid = self._makeChatSummarizationCSID(chatId, topicId, firstMessageId, lastMessageId, prompt)
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM chat_summarization_cache
                    WHERE
                        csid = :csid
                    """,
                    {"csid": csid},
                )
                row = cursor.fetchone()
                if row:
                    row_dict = dict(row)
                    return self._validateDictIsChatSummarizationCacheDict(row_dict)
                return None
        except Exception as e:
            logger.error(f"Failed to get chat summarization cache: {e}")
            return None

    ###
    # Media Attachments manipulation functions
    ###

    def addMediaAttachment(
        self,
        *,
        fileUniqueId: str,
        fileId: str,
        fileSize: Optional[int] = None,
        mediaType: MessageType = MessageType.IMAGE,
        mimeType: Optional[str] = None,
        metadata: str = "{}",
        status: MediaStatus = MediaStatus.NEW,
        localUrl: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """
        Add a media attachment to the database.

        Args:
            fileUniqueId: Unique file identifier
            fileId: File identifier
            fileSize: Optional file size
            mediaType: Type of media
            mimeType: Optional MIME type
            metadata: JSON metadata
            status: Media status
            localUrl: Optional local URL
            prompt: Optional prompt
            description: Optional description

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO media_attachments
                        (file_unique_id, file_id, file_size,
                               media_type, metadata, status,
                               mime_type, local_url, prompt,
                               description
                               )
                    VALUES
                        (:fileUniqueId, :fileId, :fileSize,
                               :mediaType, :metadata, :status,
                               :mimeType, :localUrl, :prompt,
                               :description)
                """,
                    {
                        "fileUniqueId": fileUniqueId,
                        "fileId": fileId,
                        "fileSize": fileSize,
                        "mediaType": mediaType,
                        "metadata": metadata,
                        "status": status,
                        "mimeType": mimeType,
                        "localUrl": localUrl,
                        "prompt": prompt,
                        "description": description,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to add media attachment: {e}")
            return False

    def updateMediaAttachment(
        self,
        mediaId: str,
        *,
        fileSize: Optional[int] = None,
        status: Optional[MediaStatus] = None,
        metadata: Optional[str] = None,
        mimeType: Optional[str] = None,
        localUrl: Optional[str] = None,
        description: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> bool:
        """
        Update a media attachment in the database.

        Args:
            mediaId: Media identifier
            fileSize: Optional file size
            status: Optional media status
            metadata: Optional JSON metadata
            mimeType: Optional MIME type
            localUrl: Optional local URL
            description: Optional description
            prompt: Optional prompt

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            query = ""
            values: Dict[str, str | int] = {"fileUniqueId": mediaId}

            if status is not None:
                query += "status = :status, "
                values["status"] = status
            if metadata is not None:
                query += "metadata = :metadata, "
                values["metadata"] = metadata
            if mimeType is not None:
                query += "mime_type = :mimeType, "
                values["mimeType"] = mimeType
            if localUrl is not None:
                query += "local_url = :localUrl, "
                values["localUrl"] = localUrl
            if description is not None:
                query += "description = :description, "
                values["description"] = description
            if prompt is not None:
                query += "prompt = :prompt, "
                values["prompt"] = prompt
            if fileSize is not None:
                query += "file_size = :fileSize, "
                values["fileSize"] = fileSize

            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    f"""
                    UPDATE media_attachments
                    SET
                        {query}
                        updated_at = CURRENT_TIMESTAMP
                    WHERE
                        file_unique_id = :fileUniqueId
                """,
                    values,
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update media attachment: {e}")
            return False

    def getMediaAttachment(self, mediaId: str, *, dataSource: Optional[str] = None) -> Optional[MediaAttachmentDict]:
        """Get a media attachment from the database."""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM media_attachments
                    WHERE file_unique_id = ?
                """,
                    (mediaId,),
                )

                row = cursor.fetchone()
                if row:
                    row_dict = dict(row)
                    return self._validateDictIsMediaAttachmentDict(row_dict)
                return None
        except Exception as e:
            logger.error(f"Failed to get media attachment: {e}")
            return None

    ###
    # Delayed Tasks manipulation (see bot/models.py)
    ###

    def addDelayedTask(self, taskId: str, function: str, kwargs: str, delayedTS: int) -> bool:
        """
        Add a delayed task to the database.

        Args:
            taskId: Task identifier
            function: Function name
            kwargs: JSON kwargs
            delayedTS: Delayed timestamp

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO delayed_tasks
                        (id, function, kwargs, delayed_ts)
                    VALUES
                        (:id, :function, :kwargs, :delayedTS)
                """,
                    {
                        "id": taskId,
                        "function": function,
                        "kwargs": kwargs,
                        "delayedTS": delayedTS,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to add delayed task: {e}")
            return False

    def updateDelayedTask(self, id: str, isDone: bool) -> bool:
        """
        Update a delayed task in the database.

        Args:
            id: Task identifier
            isDone: Whether task is done

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    """
                    UPDATE delayed_tasks
                    SET
                        is_done = :isDone,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE
                        id = :id
                """,
                    {
                        "id": id,
                        "isDone": isDone,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update delayed task: {e}")
            return False

    def getPendingDelayedTasks(self, *, dataSource: Optional[str] = None) -> List[DelayedTaskDict]:
        """Get all pending delayed tasks from the database."""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM delayed_tasks
                    WHERE
                        is_done = :isDone
                """,
                    {
                        "isDone": False,
                    },
                )
                return [self._validateDictIsDelayedTaskDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get pending delayed tasks: {e}")
            return []

    ###
    # SPAM/Ham Processing functions
    ###

    def addSpamMessage(
        self,
        chatId: int,
        userId: int,
        messageId: MessageIdType,
        messageText: str,
        spamReason: SpamReason,
        score: float,
    ) -> bool:
        """
        Add spam message to the database.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            messageId: Message identifier
            messageText: Message text
            spamReason: Reason for spam classification
            score: Spam score

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        messageId = str(messageId)
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO spam_messages
                        (chat_id, user_id, message_id, text, reason, score)
                    VALUES
                        (:chatId, :userId, :messageId, :messageText, :spamReason, :score)
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "messageId": messageId,
                        "messageText": messageText,
                        "spamReason": spamReason.value,
                        "score": score,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to add spam message: {e}")
            return False

    def addHamMessage(
        self,
        chatId: int,
        userId: int,
        messageId: MessageIdType,
        messageText: str,
        spamReason: SpamReason,
        score: float,
    ) -> bool:
        """
        Add ham message to the database.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            messageId: Message identifier
            messageText: Message text
            spamReason: Reason for ham classification
            score: Ham score

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        messageId = str(messageId)
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO ham_messages
                        (chat_id, user_id, message_id, text, reason, score)
                    VALUES
                        (:chatId, :userId, :messageId, :messageText, :spamReason, :score)
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                        "messageId": messageId,
                        "messageText": messageText,
                        "spamReason": spamReason.value,
                        "score": score,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to add ham message: {e}")
            return False

    def getSpamMessagesByText(self, text: str, *, dataSource: Optional[str] = None) -> List[SpamMessageDict]:
        """Get spam messages by text."""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM spam_messages
                    WHERE
                        text = :text
                """,
                    {
                        "text": text,
                    },
                )
                return [self._validateDictIsSpamMessageDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []

    def getSpamMessages(self, limit: int = 1000, *, dataSource: Optional[str] = None) -> List[SpamMessageDict]:
        """Get spam messages."""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM spam_messages
                    LIMIT :limit
                """,
                    {
                        "limit": limit,
                    },
                )
                return [self._validateDictIsSpamMessageDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []

    def deleteSpamMessagesByUserId(self, chatId: int, userId: int) -> bool:
        """
        Delete spam messages by user id.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(chatId=chatId, readonly=False) as cursor:
                cursor.execute(
                    """
                    DELETE FROM spam_messages
                    WHERE
                        chat_id = :chatId AND
                        user_id = :userId
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to delete spam messages: {e}")
            return False

    def getSpamMessagesByUserId(
        self, chatId: int, userId: int, *, dataSource: Optional[str] = None
    ) -> List[SpamMessageDict]:
        """
        Get spam messages by user id.

        Args:
            chatId: Chat identifier
            userId: User identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            List of SpamMessageDict
        """
        try:
            with self.getCursor(chatId=chatId, dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM spam_messages
                    WHERE
                        chat_id = :chatId AND
                        user_id = :userId
                """,
                    {
                        "chatId": chatId,
                        "userId": userId,
                    },
                )
                return [self._validateDictIsSpamMessageDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []

    ###
    # Cache manipulation functions
    ###

    def getCacheStorage(self, *, dataSource: Optional[str] = None) -> List[CacheStorageDict]:
        """Get all cache storage entries

        Args:
            dataSource: Optional data source identifier for multi-source database routing

        Returns:
            List of cache storage dictionaries"""
        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    """
                    SELECT namespace, key, value, updated_at
                    FROM cache_storage
                    ORDER BY updated_at DESC
                    """
                )
                return [self._validateDictIsCacheStorageDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get cache storage: {e}")
            return []

    def setCacheStorage(self, namespace: str, key: str, value: str) -> bool:
        """
        Store cache entry in cache_storage table.

        Args:
            namespace: Cache namespace
            key: Cache key
            value: Cache value

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    """
                    INSERT INTO cache_storage
                        (namespace, key, value, updated_at)
                    VALUES
                        (:namespace, :key, :value, CURRENT_TIMESTAMP)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = :value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    {
                        "namespace": namespace,
                        "key": key,
                        "value": value,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to set cache storage: {e}")
            return False

    def unsetCacheStorage(self, namespace: str, key: str) -> bool:
        """
        Delete cache entry from cache_storage table.

        Args:
            namespace: Cache namespace
            key: Cache key

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    """
                    DELETE FROM cache_storage
                    WHERE
                        namespace = :namespace AND
                        key = :key
                    """,
                    {
                        "namespace": namespace,
                        "key": key,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to unset cache storage: {e}")
            return False

    def getCacheEntry(
        self,
        key: str,
        cacheType: CacheType,
        ttl: Optional[int] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[CacheDict]:
        """
        Get cache entry by key and type.

        Args:
            key: Cache key
            cacheType: Type of cache
            ttl: Time-to-live in seconds (optional)
            dataSource: Optional data source name. If None in multi-source mode,
                       returns first match from any source.

        Returns:
            CacheDict or None if not found
        """
        # TTL of 0 or negative means entry must be from the future (impossible), so return None
        if ttl is not None and ttl <= 0:
            return None

        # Use datetime.now(datetime.UTC) to match SQLite's CURRENT_TIMESTAMP which is in UTC
        minimalUpdatedAt = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=ttl)
            if ttl is not None and ttl > 0
            else None
        )

        try:
            with self.getCursor(dataSource=dataSource, readonly=True) as cursor:
                cursor.execute(
                    f"""
                    SELECT *
                    FROM cache_{cacheType}
                    WHERE key = :cacheKey AND
                    (:minimalUpdatedAt IS NULL OR updated_at >= :minimalUpdatedAt)
                """,
                    {
                        "cacheKey": key,
                        "minimalUpdatedAt": minimalUpdatedAt,
                    },
                )

                row = cursor.fetchone()
                if row:
                    rowDict = dict(row)
                    return self._validateDictIsCacheDict(rowDict)
                return None
        except Exception as e:
            logger.error(f"Failed to get cache entry: {e}")
            return None

    def setCacheEntry(self, key: str, data: str, cacheType: CacheType) -> bool:
        """
        Store cache entry.

        Args:
            key: Cache key
            data: Cache data
            cacheType: Type of cache

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO cache_{cacheType}
                        (key, data, created_at, updated_at)
                    VALUES
                        (:key, :data, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        data = :data,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    {"key": key, "data": data},
                )
                return True
        except Exception as e:
            logger.error(f"Failed to set cache entry: {e}")
            return False

    def clearCache(self, cacheType: CacheType) -> None:
        """
        Clear all entries from a specific cache table.

        Args:
            cacheType: The type of cache to clear (WEATHER, GEOCODING, or YANDEX_SEARCH)

        Raises:
            Logs an error message if the cache clearing operation fails

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            with self.getCursor(readonly=False) as cursor:
                cursor.execute(
                    f"""
                    DELETE FROM cache_{cacheType}
                    """
                )
        except Exception as e:
            logger.error(f"Failed to clear cache {cacheType}: {e}")
