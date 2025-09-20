"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import datetime
import sqlite3
import logging
import threading
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from .models import MediaStatus
from ..bot.models import MessageType

logger = logging.getLogger(__name__)

DEFAULT_THREAD_ID: int = 0

MEDIA_TABLE_TABLE_ALIAS="ma"
MEDIA_TABLE_PREFIX = 'media_'
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
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                self.dbPath,
                timeout=self.timeout,
                check_same_thread=False
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
        if hasattr(self._local, 'connection'):
            self._local.connection.close()

    def _initDatabase(self):
        """Initialize the database with required tables."""
        with self.getCursor() as cursor:
            # Users table for storing user information
            # TODO: Rethink and rewrite it
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Settings table for storing key-value pairs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Messages table for storing message history (optional)
            # TODO: Rethink and rewrite it, maybe use chat messages table instead
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message_text TEXT NOT NULL,
                    reply_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)

            # Chat messages table for storing detailed chat message information
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    chat_id INTEGER NOT NULL,                       -- Chat ID
                    message_id INTEGER NOT NULL,                    -- Message ID (unique for ChatID)
                    date TIMESTAMP NOT NULL,                        -- Date of message
                    user_id INTEGER NOT NULL,                       -- ID of sender user
                    reply_id INTEGER,                               -- ID of replied message if any
                    thread_id INTEGER NOT NULL DEFAULT 0,           -- ID of thread if any (only for if chat has topics, null for main topic)
                    root_message_id INTEGER,                        -- ID of root message if any (for getting full sequence of messages in dialog)
                    message_text TEXT NOT NULL,                     -- Message text (Can be empty for non-text messages)
                    message_type TEXT DEFAULT 'text' NOT NULL,      -- Message type (See MessageType for supported types)
                    message_category TEXT DEFAULT 'user' NOT NULL,  -- Actually who sent message (user or bot, may be changed in future)
                    quote_text TEXT,                                -- if it is Reply with quote - quoted text
                    media_id TEXT,                                  -- Link to file_unique_id in media_attachments table if any
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Date, when this message was added to DB
                    PRIMARY KEY (chat_id, message_id)
                )
            """)

            # Chat-specific settings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_settings (
                    chat_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, key)
                )
            """)

            # Per-chat known users + some stats (messages count + last seen)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_users (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            # Chat stats (currently only messages count per date)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_stats (
                    chat_id INTEGER NOT NULL,
                    date TIMESTAMP NOT NULL,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, date)
                )
            """)

            # Chat user stats (currently only messages count per date)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_user_stats (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    date TIMESTAMP NOT NULL,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id, date)
                )
            """)

            # Table with saved Media info (see MessageType for currenlty supported media)
            # PhotoSize(file_id='Ag...Q', file_size=47717, file_unique_id='A..y', height=320, width=320)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS media_attachments (
                    file_unique_id TEXT PRIMARY KEY,        -- Unique id of media - said thait it will be preserver for time
                    file_id TEXT,                           -- FileID for getting file content (dunno, why i save it into database)
                    file_size INTEGER,                      -- File size if any
                    media_type TEXT NOT NULL,              -- Type of media (see MessageType for supported types)
                    metadata TEXT NOT NULL,                 -- JSON metadata (format is media_type specific)
                    status TEXT NOT NULL DEFAULT 'pending', -- Status (possible values to be defined later)
                    mime_type TEXT,                         -- Mime Type if any
                    local_url TEXT,                         -- Local URL if media was downloaded
                    prompt TEXT,                            -- Prompt used to generate media (Only for media, generated and sent by bot)
                    description TEXT,                       -- Description of media? generated by LLM

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def saveUser(self, userId: int, userName: Optional[str] = None,
                  firstName: Optional[str] = None, lastName: Optional[str] = None) -> bool:
        """Save or update user information."""
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO users
                    (user_id, username, first_name, last_name, updated_at)
                    VALUES (:userId, :userName, :firstName, :lastName, CURRENT_TIMESTAMP)
                """,
                    {
                        "userId": userId,
                        "userName": userName,
                        "firstName": firstName,
                        "lastName": lastName,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to save user {userId}: {e}")
            return False

    # DEPRECATED
    def getUser(self, userId: int) -> Optional[Dict[str, Any]]:
        """Get user information by user_id."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (userId,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {userId}: {e}")
            return None

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
                return row['value'] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default

    def getSettings(self) -> Dict[str, str]:
        """Get all configuration settings."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("SELECT * FROM settings")
                return {row['key']: row['value'] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings: {e}")
            return {}

    def savePrivateMessage(
        self, userId: int, messageText: str, replyText: str = ""
    ) -> bool:
        """Save a message to the database."""
        try:
            with self.getCursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO messages (user_id, message_text, reply_text)
                    VALUES (:userId, :messageText, :replyText)
                """,
                    {
                        "userId": userId,
                        "messageText": messageText,
                        "replyText": replyText,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to save message from user {userId}: {e}")
            return False

    def getUserMessages(self, userId: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from a user."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    SELECT * FROM messages
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (userId, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get messages for user {userId}: {e}")
            return []

    def saveChatMessage(
        self,
        date: datetime.datetime,
        chatId: int,
        userId: int,
        messageId: int,
        replyId: Optional[int] = None,
        threadId: Optional[int] = None,
        messageText: str = "",
        messageType: str = "text",
        messageCategory: str = "user",
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
                cursor.execute("""
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
                """, {
                    "date": date,
                    "chatId": chatId,
                    "userId": userId,
                    "messageId": messageId,
                    "replyId": replyId,
                    "threadId": threadId,
                    "messageText": messageText,
                    "messageType": messageType,
                    "messageCategory": messageCategory,
                    "rootMessageId": rootMessageId,
                    "quoteText": quoteText,
                    "mediaId": mediaId,
                })

                cursor.execute("""
                    UPDATE chat_users
                    SET messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE chat_id = ? AND user_id = ?
                """, (chatId, userId))

                cursor.execute("""
                    INSERT INTO chat_stats
                    (chat_id, date, messages_count, updated_at)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id, date) DO UPDATE SET
                        messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """, (chatId, today))

                cursor.execute("""
                    INSERT INTO chat_user_stats
                    (chat_id, user_id, date, messages_count, updated_at)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (chat_id, user_id, date) DO UPDATE SET
                        messages_count = messages_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                """, (chatId, userId, today))

                return True
        except Exception as e:
            logger.error(f"Failed to save chat message from user {userId} in chat {chatId}: {e}")
            return False

    def getChatMessageSince(self, chatId: int, sinceDateTime: Optional[datetime.datetime], threadId: Optional[int] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get chat messages from a specific chat newer than the given date."""
        logger.debug(f"Getting chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId})")
        try:
            with self.getCursor() as cursor:
                query = f"""
                    SELECT c.*, u.username, u.full_name, {MEDIA_FIELDS_WITH_PREFIX}  FROM chat_messages c
                    JOIN chat_users u ON c.user_id = u.user_id AND c.chat_id = u.chat_id
                    LEFT JOIN media_attachments ma ON c.media_id IS NOT NULL AND c.media_id = ma.file_unique_id
                    WHERE
                        c.chat_id = :chatId
                        AND (:sinceDateTime IS NULL OR c.date > :sinceDateTime)
                        AND ((:threadId IS NULL) OR (c.thread_id = :threadId))
                    ORDER BY c.date DESC
                """
                if limit is not None:
                    query += f" LIMIT {int(limit)}"

                cursor.execute(
                    query,
                    {
                        "chatId": chatId,
                        "sinceDateTime": sinceDateTime,
                        "threadId": threadId,
                    },
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId}): {e}")
            return []

    def getChatMessageByMessageId(
        self, chatId: int, messageId: int, threadId: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a specific chat message by message_id, chat_id, and optional thread_id."""
        logger.debug(
            f"Getting chat message for chat {chatId}, thread {threadId}, message_id {messageId}"
        )
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
                        AND ((:threadId IS NULL) OR (c.thread_id = :threadId))
                    LIMIT 1
                """,
                    {"chatId": chatId, "messageId": messageId, "threadId": threadId},
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get chat message for chat {chatId}, thread {threadId}, message_id {messageId}: {e}")
            return None

    def getChatMessagesByRootId(
        self, chatId: int, rootMessageId: int, threadId: Optional[int] = None
    ) -> List[Dict[str, Any]]:
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
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get chat messages for chat {chatId}, thread {threadId}, root_message_id {rootMessageId}: {e}")
            return []

    def updateChatUser(
        self, chatId: int, userId: int, username: str, fullName: str
    ) -> bool:
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

    def getChatUser(self, chatId: int, userId: int) -> Optional[Dict[str, Any]]:
        """Get the username of a user in a chat."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    SELECT * FROM chat_users
                    WHERE
                        chat_id = ?
                        AND user_id = ?
                    LIMIT 1
                """, (chatId, userId))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get username for user {userId} in chat {chatId}: {e}")
            return None

    def getChatUsers(
        self,
        chatId: int,
        limit: int = 10,
        seenSince: Optional[datetime.datetime] = None,
    ) -> List[Dict[str, Any]]:
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

                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get users for chat {chatId}: {e}")
            return []

    def setChatSetting(self, chatId: int, key: str, value: Any) -> bool:
        """Set a setting for a chat."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO chat_settings
                        (chat_id, key, value, updated_at)
                    VALUES
                        (?, ?, ?, CURRENT_TIMESTAMP)
                """, (chatId, key, value))
                return True
        except Exception as e:
            logger.error(f"Failed to set setting {key} for chat {chatId}: {e}")
            return False

    def unsetChatSetting(self, chatId: int, key: str) -> bool:
        """UnSet a setting for a chat."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    DELETE FROM chat_settings
                    WHERE chat_id = ?
                        AND key = ?
                """, (chatId, key))
                return True
        except Exception as e:
            logger.error(f"Failed to unset setting {key} for chat {chatId}: {e}")
            return False

    def getChatSetting(self, chatId: int, setting: str) -> Optional[str]:
        """Get a setting for a chat."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    SELECT value FROM chat_settings
                    WHERE
                        chat_id = ?
                        AND setting = ?
                    LIMIT 1
                """, (chatId, setting))
                row = cursor.fetchone()
                return row['value'] if row else None
        except Exception as e:
            logger.error(f"Failed to get setting {setting} for chat {chatId}: {e}")
            return None

    def getChatSettings(self, chatId: int) -> Dict[str, str]:
        """Get all settings for a chat."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    SELECT key, value FROM chat_settings
                    WHERE chat_id = ?
                """, (chatId,))
                return {row['key']: row['value'] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings for chat {chatId}: {e}")
            return {}

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
    ) -> bool:
        """Update a media attachment in the database."""
        try:
            query = ""
            values = {"fileUniqueId": fileUniqueId }

            if status is not None:
                query += "status = :status, "
                values['status'] = status
            if metadata is not None:
                query += "metadata = :metadata, "
                values['metadata'] = metadata
            if mimeType is not None:
                query += "mime_type = :mimeType, "
                values['mimeType'] = mimeType
            if localUrl is not None:
                query += "local_url = :localUrl, "
                values['localUrl'] = localUrl
            if description is not None:
                query += "description = :description, "
                values['description'] = description

            with self.getCursor() as cursor:
                cursor.execute(f"""
                    UPDATE media_attachments
                    SET
                        {query}
                        updated_at = CURRENT_TIMESTAMP
                    WHERE
                        file_unique_id = :fileUniqueId
                """, values)
                return True
        except Exception as e:
            logger.error(f"Failed to update media attachment: {e}")
            return False

    def getMediaAttachment(self, fileUniqueId: str) -> Optional[Dict[str, Any]]:
        """Get a media attachment from the database."""
        try:
            with self.getCursor() as cursor:
                cursor.execute("""
                    SELECT * FROM media_attachments
                    WHERE file_unique_id = ?
                """, (fileUniqueId,))

                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get media attachment: {e}")
            return None
