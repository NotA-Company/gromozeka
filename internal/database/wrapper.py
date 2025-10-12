"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import datetime
import dateutil
import sqlite3
import logging
import threading
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from .models import (
    ChatInfoDict,
    ChatMessageDict,
    ChatTopicDict,
    ChatUserDict,
    DelayedTaskDict,
    MediaAttachmentDict,
    MediaStatus,
    MessageCategory,
    SpamReason,
)
from ..bot.models import MessageType

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
    if len(val) == 0:
        return False
    elif len(val) == 1:
        return bool(int(val[0]))
    else:
        raise ValueError(f"Invalid boolean value: {val}")


sqlite3.register_converter("timestamp", convert_timestamp)
sqlite3.register_converter("boolean", convert_boolean)


class DatabaseWrapper:
    """
    A wrapper around SQLite that provides a consistent interface
    that can be easily replaced with other database backends.
    """

    def __init__(self, db_path: str, maxConnections: int = 5, timeout: float = 30.0):
        self.dbPath = db_path
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
        """Initialize the database with required tables."""
        with self.getCursor() as cursor:
            # Settings table for storing key-value pairs
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (   -- No TypedDict needed
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Chat messages table for storing detailed chat message information
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (          -- See ChatMessageDict
                    chat_id INTEGER NOT NULL,                       -- Chat ID
                    message_id INTEGER NOT NULL,                    -- Message ID (unique for ChatID)
                    date TIMESTAMP NOT NULL,                        -- Date of message
                    user_id INTEGER NOT NULL,                       -- ID of sender user
                    reply_id INTEGER,                               -- ID of replied message if any
                    thread_id INTEGER NOT NULL DEFAULT 0,           -- ID of thread if any (0 for main topic)
                    root_message_id INTEGER,                        -- ID of root message if any
                                                                        -- (for getting full sequence)
                    message_text TEXT NOT NULL,                     -- Message text (Can be empty for non-text messages)
                    message_type TEXT DEFAULT 'text' NOT NULL,      -- Message type (See MessageType)
                    message_category TEXT DEFAULT 'user' NOT NULL,  -- Who sent message (See MessageCategory)
                    quote_text TEXT,                                -- if it is Reply with quote - quoted text
                    media_id TEXT,                                  -- Link to file_unique_id in media_attachments
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Date, when this message was added to DB
                    PRIMARY KEY (chat_id, message_id)
                )
            """
            )

            # Chat-specific settings
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_settings (  -- No TypedDict needed (see chat_srttings.py)
                    chat_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, key)
                )
            """
            )

            # Per-chat known users + some stats (messages count + last seen)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_users ( -- See ChatUserDict
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    timezone TEXT,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id)
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_info ( -- See ChatInfoDict
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    type TEXT NOT NULL,
                    is_forum BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Chat stats (currently only messages count per date)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_stats (
                    chat_id INTEGER NOT NULL,
                    date TIMESTAMP NOT NULL,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, date)
                )
            """
            )

            # Chat user stats (currently only messages count per date)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_user_stats (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    date TIMESTAMP NOT NULL,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id, date)
                )
            """
            )

            # Table with saved Media info (see MessageType for currenlty supported media)
            # PhotoSize(file_id='Ag...Q', file_size=47717, file_unique_id='A..y', height=320, width=320)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS media_attachments ( -- See MediaAttachmentDict
                    file_unique_id TEXT PRIMARY KEY,        -- Unique id of media - preserved for time
                    file_id TEXT,                           -- FileID for getting file content
                    file_size INTEGER,                      -- File size if any
                    media_type TEXT NOT NULL,              -- Type of media (see MessageType for supported types)
                    metadata TEXT NOT NULL,                 -- JSON metadata (format is media_type specific)
                    status TEXT NOT NULL DEFAULT 'pending', -- Status (possible values to be defined later)
                    mime_type TEXT,                         -- Mime Type if any
                    local_url TEXT,                         -- Local URL if media was downloaded
                    prompt TEXT,                            -- Prompt used to generate media (bot-generated only)
                    description TEXT,                       -- Description of media? generated by LLM

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Table for delayed tasks
            # TODO: Think about dropping old task, which is_done == True
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS delayed_tasks ( -- See DelayedTaskDict
                    id TEXT PRIMARY KEY NOT NULL,           -- Unique task ID (usually uuid)
                    delayed_ts INTEGER NOT NULL,            -- DelayedTS (in bot's timezone. Or it Timestamp? dunno)
                    function TEXT NOT NULL,                 -- Function to call (see DelayedTaskFunction)
                    kwargs TEXT NOT NULL,                   -- Function args (JSON-serialized Dict[str, Any])
                    is_done BOOLEAN NOT NULL DEFAULT FALSE, -- If task is done

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Some knowledge about user, collected during discussion
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_data (
                    user_id INTEGER NOT NULL,    -- User ID
                    chat_id INTEGER NOT NULL,    -- Chat ID (We store user's data for each chat individually)
                    key TEXT NOT NULL,           -- Key
                    data TEXT NOT NULL,          -- JSON-serialized data (str | List[str])

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, chat_id, key)
                )
            """
            )

            # Spam messages for learning
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS spam_messages (
                    chat_id INTEGER NOT NULL,    -- Chat ID
                    user_id INTEGER NOT NULL,    -- User ID
                    message_id INTEGER NOT NULL, -- Message ID

                    text TEXT NOT NULL,         -- Message text
                    reason TEXT NOT NULL,       -- Reason for spam (see SpamReason)
                    score FLOAT NOT NULL,       -- Spam score (0 - 100)

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id, message_id)
                )
            """
            )

            # Chat Topics
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_topics ( -- See ChatTopicDict
                    chat_id INTEGER NOT NULL,   -- Chat ID
                    topic_id INTEGER NOT NULL,  -- Topic ID

                    icon_color INTEGER,
                    icon_custom_emoji_id TEXT,
                    name TEXT,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, topic_id)
                )
            """
            )

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

    def _validateDictIsChatTopicDict(self, row_dict: Dict[str, Any]) -> ChatTopicDict:
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
                    logger.warning(
                        f"Field '{field}' has type {type(row_dict[field])}, expected {expected_type}"
                    )

            # Return the validated dictionary cast as DelayedTaskDict
            return row_dict  # type: ignore

        except Exception as e:
            logger.error(f"Failed to validate DelayedTaskDict: {e}")
            logger.error(f"Row data: {row_dict}")
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
        logger.debug(f"Getting chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId})")
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

    ###
    # Chat Users manipulation functions
    ###

    def updateChatUser(self, chatId: int, userId: int, username: str, fullName: str) -> bool:
        """Store user as chat member + update username and updated_at."""
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
            logger.error(f"Failed to get username for user {userId} in chat {chatId}: {e}")
            return None

    def getChatUsers(
        self,
        chatId: int,
        limit: int = 10,
        seenSince: Optional[datetime.datetime] = None,
    ) -> List[ChatUserDict]:
        """Get the usernames of all users in a chat."""
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

    def getChatSetting(self, chatId: int, setting: str) -> Optional[str]:
        """Get a setting for a chat."""
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT value FROM chat_settings
                    WHERE
                        chat_id = ?
                        AND setting = ?
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
    def addChatInfo(
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

    def getChatTopics(self, chatId: int) -> List[ChatTopicDict]:
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
    # SPAM Processing functions
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

    def getSpamMessagesByText(self, text: str) -> List[Dict[str, Any]]:
        """Get spam messages by text."""
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM spam_messages
                    WHERE
                        text LIKE :text
                """,
                    {
                        "text": f"%{text}%",
                    },
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get spam messages: {e}")
            return []
