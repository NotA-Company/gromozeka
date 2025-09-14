"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import datetime
import sqlite3
import logging
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager
import threading

logger = logging.getLogger(__name__)


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
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
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
    def get_cursor(self):
        """Context manager for database operations."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            cursor.close()

    def _init_database(self):
        """Initialize the database with required tables."""
        with self.get_cursor() as cursor:
            # Users table for storing user information
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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TIMESTAMP NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    reply_id INTEGER,
                    thread_id INTEGER,
                    root_message_id INTEGER,
                    message_text TEXT NOT NULL,
                    message_type TEXT DEFAULT 'text' NOT NULL,
                    message_category TEXT DEFAULT 'user' NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_users (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    messages_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

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

    def saveUser(self, userId: int, userName: Optional[str] = None,
                  firstName: Optional[str] = None, lastName: Optional[str] = None) -> bool:
        """Save or update user information."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO users
                    (user_id, username, first_name, last_name, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (userId, userName, firstName, lastName))
                return True
        except Exception as e:
            logger.error(f"Failed to save user {userId}: {e}")
            return False

    # DEPRECATED
    def getUser(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user information by user_id."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            return None

    def setSetting(self, key: str, value: str) -> bool:
        """Set a configuration setting."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO settings
                    (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, value))
                return True
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
            return False

    def getSetting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a configuration setting."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row['value'] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default

    def getSettings(self) -> Dict[str, str]:
        """Get all configuration settings."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT * FROM settings")
                return {row['key']: row['value'] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings: {e}")
            return {}

    def savePrivateMessage(self, user_id: int, message_text: str, reply_text: str = '') -> bool:
        """Save a message to the database."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO messages (user_id, message_text, reply_text)
                    VALUES (?, ?, ?)
                """, (user_id, message_text, reply_text))
                return True
        except Exception as e:
            logger.error(f"Failed to save message from user {user_id}: {e}")
            return False

    def getUserMessages(self, userId: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from a user."""
        try:
            with self.get_cursor() as cursor:
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

    def saveChatMessage(self, date, chatId: int, userId: int, userName: str, messageId: int,
                         replyId: Optional[int] = None, threadId: Optional[int] = None,
                         messageText: str = '', messageType: str = 'text', messageCategory: str = 'user', rootMessageId: Optional[int] = None) -> bool:
        """Save a chat message with detailed information."""
        try:
            with self.get_cursor() as cursor:
                today = datetime.datetime.now(datetime.timezone.utc)
                today = today.replace(hour=0, minute=0, second=0, microsecond=0)
                cursor.execute("""
                    INSERT INTO chat_messages
                    (date, chat_id, user_id, user_name, message_id,
                        reply_id, thread_id, message_text, message_type,
                        message_category, root_message_id)
                    VALUES
                    (?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?)
                """, (date, chatId, userId, userName, messageId,
                      replyId, threadId, messageText, messageType,
                      messageCategory, rootMessageId))
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

    def getChatMessageSince(self, chatId: int, sinceDateTime, threadId: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get chat messages from a specific chat newer than the given date."""
        logger.debug(f"Getting chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId})")
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM chat_messages
                    WHERE
                        chat_id = ?
                        AND date > ?
                        AND ((? IS NULL) OR (thread_id = ?))
                    ORDER BY date ASC
                """, (chatId, sinceDateTime, threadId, threadId))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get chat messages for chat {chatId} since {sinceDateTime} (threadId={threadId}): {e}")
            return []

    def getChatMessageByMessageId(self, chatId: int, messageId: int, threadId: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get a specific chat message by message_id, chat_id, and optional thread_id."""
        logger.debug(f"Getting chat message for chat {chatId}, thread {threadId}, message_id {messageId}")
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM chat_messages
                    WHERE
                        chat_id = ?
                        AND message_id = ?
                        AND ((? IS NULL) OR (thread_id = ?))
                    LIMIT 1
                """, (chatId, messageId, threadId, threadId))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get chat message for chat {chatId}, thread {threadId}, message_id {messageId}: {e}")
            return None

    def getChatMessagesByRootId(self, chatId: int, rootMessageId: int, threadId: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all chat messages in a conversation thread by root message ID."""
        logger.debug(f"Getting chat messages for chat {chatId}, thread {threadId}, root_message_id {rootMessageId}")
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM chat_messages
                    WHERE
                        chat_id = ?
                        AND root_message_id = ?
                        AND ((? IS NULL) OR (thread_id = ?))
                    ORDER BY date ASC
                """, (chatId, rootMessageId, threadId, threadId))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get chat messages for chat {chatId}, thread {threadId}, root_message_id {rootMessageId}: {e}")
            return []

    def close(self):
        """Close database connections."""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()

    def updateChatUser(self, chatId: int, userId: int, username: str) -> bool:
        """Store user as chat member + update username and updated_at."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO chat_users
                        (username, chat_id, user_id, updated_at)
                    VALUES
                        (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(chat_id, user_id) DO UPDATE SET
                        username = excluded.username,
                        updated_at = CURRENT_TIMESTAMP
                """, (username, chatId, userId))
                return True
        except Exception as e:
            logger.error(f"Failed to update username for user {userId} in chat {chatId}: {e}")
            return False

    def getChatUser(self, chatId: int, userId: int) -> Optional[Dict[str, Any]]:
        """Get the username of a user in a chat."""
        try:
            with self.get_cursor() as cursor:
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

    def getChatUsers(self, chatId: int, limit: int = 10, seenSince: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        """Get the usernames of all users in a chat."""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM chat_users
                    WHERE
                        chat_id = ?
                        AND (? IS NULL OR seen_since < ?)
                    LIMIT ?
                """, (chatId, seenSince,seenSince, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get usernames for chat {chatId}: {e}")
            return []

    def setChatSetting(self, chatId: int, key: str, value: Any) -> bool:
        """Set a setting for a chat."""
        try:
            with self.get_cursor() as cursor:
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
            with self.get_cursor() as cursor:
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
            with self.get_cursor() as cursor:
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
            with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT key, value FROM chat_settings
                    WHERE chat_id = ?
                """, (chatId,))
                return {row['key']: row['value'] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get settings for chat {chatId}: {e}")
            return {}