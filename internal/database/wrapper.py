"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import datetime
import logging
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import dateutil
from telegram import Chat

# Import from shared_enums to avoid circular dependency
from internal.models import MessageType

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
    return val.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')


# Register converters for reading from database
sqlite3.register_converter("timestamp", convert_timestamp)
sqlite3.register_converter("boolean", convert_boolean)

# Register adapters for writing to database (Python 3.12+ requirement)
sqlite3.register_adapter(datetime.datetime, adapt_datetime)


class DatabaseWrapper:
    """
    A wrapper around SQLite that provides a consistent interface
    that can be easily replaced with other database backends.
    """

    def __init__(self, dbPath: str, maxConnections: int = 5, timeout: float = 30.0):
        self.dbPath = dbPath
        self.maxConnections = maxConnections
        self.timeout = timeout
        self._local = threading.local()
        self._initDatabase()

    def _getConnection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(
                self.dbPath,
                timeout=self.timeout,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    @contextmanager
    def getCursor(self):
        """Context manager for database operations."""
        conn = self._getConnection()
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
        """Close database connections."""
        if hasattr(self._local, "connection"):
            self._local.connection.close()

    def _initDatabase(self):
        """Initialize the database with required tables, dood!"""
        with self.getCursor() as cursor:
            # Settings table for storing key-value pairs
            # This table is needed BEFORE migrations run for version tracking
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

        # Import here to avoid circular dependency, dood!
        from .migrations import MigrationManager

        # Run migrations, dood!
        migrationManager = MigrationManager(self)

        # Try auto-discovery first, fall back to manual registration
        try:
            migrationManager.loadMigrationsFromVersions()
            logger.info("Using auto-discovered migrations, dood!")
        except Exception as e:
            logger.error(f"Migrations Auto-discovery failed: {e}")
            raise e

        migrationManager.migrate()

        logger.info("Database initialization complete, dood!")

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
            required_fields = {
                "chat_id": int,
                "message_id": int,
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
            return row_dict  # type: ignore

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

    def setSetting(self, key: str, value: str) -> bool:
        """Set a configuration setting."""
        try:
            with self.getCursor() as cursor:
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
            logger.error(f"Failed to set setting {key}: {e}")
            return False

    def getSetting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a configuration setting."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row["value"] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default

    def getSettings(self) -> Dict[str, str]:
        """Get all configuration settings."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("SELECT * FROM settings")
                return {row["key"]: row["value"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings: {e}")
            return {}

    ###
    # Chat messages manipulation functions
    ###
    def saveChatMessage(
        self,
        date: datetime.datetime,
        chatId: int,
        userId: int,
        messageId: int,
        replyId: Optional[int] = None,
        threadId: Optional[int] = None,
        messageText: str = "",
        messageType: MessageType = MessageType.TEXT,
        messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
        rootMessageId: Optional[int] = None,
        quoteText: Optional[str] = None,
        mediaId: Optional[str] = None,
    ) -> bool:
        """Save a chat message with detailed information."""
        if threadId is None:
            threadId = DEFAULT_THREAD_ID
        try:
            with self.getCursor() as cursor:
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
    ) -> List[ChatMessageDict]:
        """Get chat messages from a specific chat newer than the given date."""
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

            with self.getCursor() as cursor:
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

    def getChatMessageByMessageId(self, chatId: int, messageId: int) -> Optional[ChatMessageDict]:
        """Get a specific chat message by message_id, chat_id, and optional thread_id."""
        logger.debug(f"Getting chat message for chat {chatId}, message_id {messageId}")
        try:
            with self.getCursor() as cursor:
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
        self, chatId: int, rootMessageId: int, threadId: Optional[int] = None
    ) -> List[ChatMessageDict]:
        """Get all chat messages in a conversation thread by root message ID."""
        logger.debug(f"Getting chat messages for chat {chatId}, thread {threadId}, root_message_id {rootMessageId}")
        try:
            with self.getCursor() as cursor:
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

    def getChatMessagesByUser(self, chatId: int, userId: int, limit: int = 100) -> List[ChatMessageDict]:
        """Get all chat messages by user ID."""
        logger.debug(f"Getting chat messages for chat {chatId}, user {userId}")
        try:
            with self.getCursor() as cursor:
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
        messageId: int,
        messageCategory: MessageCategory,
    ) -> bool:
        """Update the category of a chat message."""
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    """
                    UPDATE chat_messages
                    SET category = :category
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
            chatId: The unique identifier of the chat, dood
            userId: The unique identifier of the user, dood
            username: The current @username of the user (may be None) (Note: Should be with @ sign)
            fullName: The current full name/display name of the user

        Returns:
            bool: True if the operation succeeded, False if an exception occurred

        Note:
            The updated_at timestamp is automatically set to CURRENT_TIMESTAMP
            on both insert and update operations, dood.
        """
        try:
            with self.getCursor() as cursor:
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

    def getChatUser(self, chatId: int, userId: int) -> Optional[ChatUserDict]:
        """Get the username of a user in a chat."""
        try:
            with self.getCursor() as cursor:
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
        """Mark a user as spammer."""
        try:
            with self.getCursor() as cursor:
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
        """Update metadata for a chat user."""
        try:
            with self.getCursor() as cursor:
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

    def getChatUserByUsername(self, chatId: int, username: str) -> Optional[ChatUserDict]:
        """Get the user id of a user in a chat."""
        try:
            with self.getCursor() as cursor:
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
    ) -> List[ChatUserDict]:
        """Get the usernames of all users in a chat, optionally filtered by when they last sent a message."""
        try:
            with self.getCursor() as cursor:
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

    def getUserChats(self, userId: int) -> List[ChatInfoDict]:
        """Get chats, user was seen in"""
        try:
            with self.getCursor() as cursor:
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
                return [self._validateDictIsChatInfoDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get user#{userId} chats: {e}")
            logger.exception(e)
            return []

    def getAllGroupChats(self) -> List[ChatInfoDict]:
        """Get chats, user was seen in"""
        try:
            with self.getCursor() as cursor:
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
                return [self._validateDictIsChatInfoDict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get group chats: {e}")
            logger.exception(e)
            return []

    ###
    # User Data manipulation functions
    ###

    def addUserData(self, userId: int, chatId: int, key: str, data: str) -> bool:
        """Add user knowledge to the database."""
        try:
            with self.getCursor() as cursor:
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

    def getUserData(self, userId: int, chatId: int) -> Dict[str, str]:
        """Get user knowledge from the database."""
        try:
            with self.getCursor() as cursor:
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
        """Delete specific user data"""
        try:
            with self.getCursor() as cursor:
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
        """Clear all user data in chat"""
        try:
            with self.getCursor() as cursor:
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
        """Set a setting for a chat."""
        try:
            with self.getCursor() as cursor:
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
        """UnSet a setting for a chat."""
        try:
            with self.getCursor() as cursor:
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
        """Clear all a settings for a chat."""
        try:
            with self.getCursor() as cursor:
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

    def getChatSetting(self, chatId: int, setting: str) -> Optional[str]:
        """Get a setting for a chat."""
        try:
            with self.getCursor() as cursor:
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

    def getChatSettings(self, chatId: int) -> Dict[str, str]:
        """Get all settings for a chat."""
        try:
            with self.getCursor() as cursor:
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
            with self.getCursor() as cursor:
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

    def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
        """Get chat info from the database."""
        try:
            with self.getCursor() as cursor:
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
        """Store user as chat member + update username and updated_at."""
        if topicName is None:
            topicName = "Default"
        try:
            with self.getCursor() as cursor:
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

    def getChatTopics(self, chatId: int) -> List[ChatTopicInfoDict]:
        """Get chat topics."""
        try:
            with self.getCursor() as cursor:
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
        firstMessageId: int,
        lastMessageId: int,
        prompt: str,
    ) -> str:
        """Make CSID for chat summarization cache"""
        # TODO: Should we use some SHA512?
        return f"{chatId}:{topicId}_{firstMessageId}:{lastMessageId}-{prompt}"

    def addChatSummarization(
        self, chatId: int, topicId: Optional[int], firstMessageId: int, lastMessageId: int, prompt: str, summary: str
    ) -> bool:
        """Store chat summarization into cache"""
        csid = self._makeChatSummarizationCSID(chatId, topicId, firstMessageId, lastMessageId, prompt)

        try:
            with self.getCursor() as cursor:
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
        firstMessageId: int,
        lastMessageId: int,
        prompt: str,
    ) -> Optional[ChatSummarizationCacheDict]:
        """Fetch chat summarization from cache by chatId, topicId, firstMessageId, lastMessageId and prompt"""
        try:
            csid = self._makeChatSummarizationCSID(chatId, topicId, firstMessageId, lastMessageId, prompt)
            with self.getCursor() as cursor:
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
        """Add a media attachment to the database."""
        try:
            with self.getCursor() as cursor:
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
        fileUniqueId: str,
        status: Optional[MediaStatus] = None,
        metadata: Optional[str] = None,
        mimeType: Optional[str] = None,
        localUrl: Optional[str] = None,
        description: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> bool:
        """Update a media attachment in the database."""
        try:
            query = ""
            values = {"fileUniqueId": fileUniqueId}

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

            with self.getCursor() as cursor:
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

    def getMediaAttachment(self, fileUniqueId: str) -> Optional[MediaAttachmentDict]:
        """Get a media attachment from the database."""
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM media_attachments
                    WHERE file_unique_id = ?
                """,
                    (fileUniqueId,),
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
        """Add a delayed task to the database."""
        try:
            with self.getCursor() as cursor:
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
        """Update a delayed task in the database."""
        try:
            with self.getCursor() as cursor:
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

    def getPendingDelayedTasks(self) -> List[DelayedTaskDict]:
        """Get all pending delayed tasks from the database."""
        try:
            with self.getCursor() as cursor:
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
        self, chatId: int, userId: int, messageId: int, messageText: str, spamReason: SpamReason, score: float
    ) -> bool:
        """Add spam message to the database."""
        try:
            with self.getCursor() as cursor:
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
        self, chatId: int, userId: int, messageId: int, messageText: str, spamReason: SpamReason, score: float
    ) -> bool:
        """Add ham message to the database."""
        try:
            with self.getCursor() as cursor:
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

    def getSpamMessagesByText(self, text: str) -> List[SpamMessageDict]:
        """Get spam messages by text."""
        try:
            with self.getCursor() as cursor:
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

    def getSpamMessages(self, limit: int = 1000) -> List[SpamMessageDict]:
        """Get spam messages."""
        try:
            with self.getCursor() as cursor:
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
        """Delete spam messages by user id."""
        try:
            with self.getCursor() as cursor:
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

    def getSpamMessagesByUserId(self, chatId: int, userId: int) -> List[SpamMessageDict]:
        """Get spam messages by user id."""
        try:
            with self.getCursor() as cursor:
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

    def getCacheStorage(self) -> List[CacheStorageDict]:
        """Get all cache storage entries"""
        try:
            with self.getCursor() as cursor:
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
        """Store cache entry in cache_storage table"""
        try:
            with self.getCursor() as cursor:
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
        """Store cache entry in cache_storage table"""
        try:
            with self.getCursor() as cursor:
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

    def getCacheEntry(self, key: str, cacheType: CacheType, ttl: Optional[int] = None) -> Optional[CacheDict]:
        """Get weather cache entry by key and type"""
        try:
            # TTL of 0 or negative means entry must be from the future (impossible), so return None
            if ttl is not None and ttl <= 0:
                return None

            # Use datetime.now(datetime.UTC) to match SQLite's CURRENT_TIMESTAMP which is in UTC
            minimalUpdatedAt = (
                datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=ttl)
                if ttl is not None and ttl > 0
                else None
            )
            # logger.debug(f"getCacheEntry({key}, {cacheType}, {ttl})")
            # logger.debug(f"ttl is {ttl}, minimal updated_at is {minimalUpdatedAt}")
            with self.getCursor() as cursor:
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
                    row_dict = dict(row)
                    return self._validateDictIsCacheDict(row_dict)
                return None
        except Exception as e:
            logger.error(f"Failed to get cache entry: {e}")
            return None

    def setCacheEntry(self, key: str, data: str, cacheType: CacheType) -> bool:
        """Store weather cache entry"""
        try:
            with self.getCursor() as cursor:
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
        """
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    f"""
                    DELETE FROM cache_{cacheType}
                    """
                )
        except Exception as e:
            logger.error(f"Failed to clear cache {cacheType}: {e}")
