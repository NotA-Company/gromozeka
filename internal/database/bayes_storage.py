"""
Database implementation of Bayes storage interface, dood!

This module provides a concrete implementation of the BayesStorageInterface
using the existing DatabaseWrapper from the Gromozeka project.
"""

import logging
from typing import List, Optional, Dict, Any

from internal.database.wrapper import DatabaseWrapper
from ...lib.spam.storage_interface import BayesStorageInterface
from ...lib.spam.models import TokenStats, ClassStats, BayesModelStats

logger = logging.getLogger(__name__)


class DatabaseBayesStorage(BayesStorageInterface):
    """
    Database implementation of Bayes storage interface

    Uses the existing DatabaseWrapper to store and retrieve Bayes filter
    statistics in SQLite database tables.
    """

    def __init__(self, db: DatabaseWrapper):
        """
        Initialize database storage

        Args:
            db: DatabaseWrapper instance
        """
        self.db = db
        logger.info("Initialized DatabaseBayesStorage, dood!")

    async def getTokenStats(self, token: str, chat_id: Optional[int] = None) -> Optional[TokenStats]:
        """Get statistics for a specific token"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT token, spam_count, ham_count, total_count
                    FROM bayes_tokens
                    WHERE token = :token
                        AND ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    """,
                    {"token": token, "chat_id": chat_id},
                )
                row = cursor.fetchone()
                if row:
                    return TokenStats(
                        token=row["token"],
                        spam_count=row["spam_count"],
                        ham_count=row["ham_count"],
                        total_count=row["total_count"],
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get token stats for '{token}': {e}, dood!")
            return None

    async def getClassStats(self, is_spam: bool, chat_id: Optional[int] = None) -> ClassStats:
        """Get statistics for spam or ham class"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT message_count, token_count
                    FROM bayes_classes
                    WHERE is_spam = :is_spam
                        AND ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    """,
                    {"is_spam": is_spam, "chat_id": chat_id},
                )
                row = cursor.fetchone()
                if row:
                    return ClassStats(message_count=row["message_count"], token_count=row["token_count"])
                return ClassStats(message_count=0, token_count=0)
        except Exception as e:
            logger.error(f"Failed to get class stats for is_spam={is_spam}: {e}, dood!")
            return ClassStats(message_count=0, token_count=0)

    async def updateTokenStats(
        self, token: str, is_spam: bool, increment: int = 1, chat_id: Optional[int] = None
    ) -> bool:
        """Update token statistics after learning"""
        try:
            with self.db.getCursor() as cursor:
                # Use INSERT OR REPLACE for SQLite compatibility
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO bayes_tokens
                        (token, chat_id, spam_count, ham_count, total_count, created_at, updated_at)
                    VALUES (
                        :token,
                        :chat_id,
                        COALESCE((SELECT spam_count FROM bayes_tokens WHERE token = :token AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :spam_inc,
                        COALESCE((SELECT ham_count FROM bayes_tokens WHERE token = :token AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :ham_inc,
                        COALESCE((SELECT total_count FROM bayes_tokens WHERE token = :token AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :increment,
                        COALESCE((SELECT created_at FROM bayes_tokens WHERE token = :token AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), CURRENT_TIMESTAMP),
                        CURRENT_TIMESTAMP
                    )
                    """,
                    {
                        "token": token,
                        "chat_id": chat_id,
                        "spam_inc": increment if is_spam else 0,
                        "ham_inc": increment if not is_spam else 0,
                        "increment": increment,
                    },
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update token stats for '{token}': {e}, dood!")
            return False

    async def updateClassStats(
        self, is_spam: bool, message_increment: int = 1, token_increment: int = 0, chat_id: Optional[int] = None
    ) -> bool:
        """Update class statistics after learning"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO bayes_classes
                        (chat_id, is_spam, message_count, token_count, created_at, updated_at)
                    VALUES (
                        :chat_id,
                        :is_spam,
                        COALESCE((SELECT message_count FROM bayes_classes WHERE is_spam = :is_spam AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :msg_inc,
                        COALESCE((SELECT token_count FROM bayes_classes WHERE is_spam = :is_spam AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :tok_inc,
                        COALESCE((SELECT created_at FROM bayes_classes WHERE is_spam = :is_spam AND
                                 ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), CURRENT_TIMESTAMP),
                        CURRENT_TIMESTAMP
                    )
                    """,
                    {"chat_id": chat_id, "is_spam": is_spam, "msg_inc": message_increment, "tok_inc": token_increment},
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update class stats for is_spam={is_spam}: {e}, dood!")
            return False

    async def getAllTokens(self, chat_id: Optional[int] = None) -> List[str]:
        """Get all known tokens (for vocabulary)"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT token FROM bayes_tokens
                    WHERE ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    ORDER BY token
                    """,
                    {"chat_id": chat_id},
                )
                return [row["token"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all tokens: {e}, dood!")
            return []

    async def getVocabularySize(self, chat_id: Optional[int] = None) -> int:
        """Get the size of the vocabulary (number of unique tokens)"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) as vocab_size FROM bayes_tokens
                    WHERE ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    """,
                    {"chat_id": chat_id},
                )
                row = cursor.fetchone()
                return row["vocab_size"] if row else 0
        except Exception as e:
            logger.error(f"Failed to get vocabulary size: {e}, dood!")
            return 0

    async def getModelStats(self, chat_id: Optional[int] = None) -> BayesModelStats:
        """Get overall model statistics"""
        try:
            with self.db.getCursor() as cursor:
                # Get class statistics
                cursor.execute(
                    """
                    SELECT
                        SUM(CASE WHEN is_spam = 1 THEN message_count ELSE 0 END) as spam_messages,
                        SUM(CASE WHEN is_spam = 0 THEN message_count ELSE 0 END) as ham_messages,
                        SUM(token_count) as total_tokens
                    FROM bayes_classes
                    WHERE ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    """,
                    {"chat_id": chat_id},
                )
                row = cursor.fetchone()

                spam_messages = row["spam_messages"] or 0
                ham_messages = row["ham_messages"] or 0
                total_tokens = row["total_tokens"] or 0

                # Get vocabulary size
                vocab_size = await self.getVocabularySize(chat_id)

                return BayesModelStats(
                    total_spam_messages=spam_messages,
                    total_ham_messages=ham_messages,
                    total_tokens=total_tokens,
                    vocabulary_size=vocab_size,
                    chat_id=chat_id,
                )
        except Exception as e:
            logger.error(f"Failed to get model stats: {e}, dood!")
            return BayesModelStats(
                total_spam_messages=0, total_ham_messages=0, total_tokens=0, vocabulary_size=0, chat_id=chat_id
            )

    async def clearStats(self, chat_id: Optional[int] = None) -> bool:
        """Clear all statistics (reset learning)"""
        try:
            with self.db.getCursor() as cursor:
                if chat_id is None:
                    # Clear all global stats (where chat_id IS NULL)
                    cursor.execute("DELETE FROM bayes_tokens WHERE chat_id IS NULL")
                    cursor.execute("DELETE FROM bayes_classes WHERE chat_id IS NULL")
                    logger.info("Cleared global Bayes statistics, dood!")
                else:
                    # Clear specific chat
                    cursor.execute("DELETE FROM bayes_tokens WHERE chat_id = ?", (chat_id,))
                    cursor.execute("DELETE FROM bayes_classes WHERE chat_id = ?", (chat_id,))
                    logger.info(f"Cleared Bayes statistics for chat {chat_id}, dood!")
                return True
        except Exception as e:
            logger.error(f"Failed to clear stats: {e}, dood!")
            return False

    async def batchUpdateTokens(self, token_updates: List[Dict[str, Any]], chat_id: Optional[int] = None) -> bool:
        """Update multiple tokens in a single batch operation for performance"""
        if not token_updates:
            return True

        try:
            with self.db.getCursor() as cursor:
                for update in token_updates:
                    token = update["token"]
                    is_spam = update["is_spam"]
                    increment = update["increment"]

                    # Use the same logic as update_token_stats but in batch
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO bayes_tokens
                            (token, chat_id, spam_count, ham_count, total_count, created_at, updated_at)
                        VALUES (
                            :token,
                            :chat_id,
                            COALESCE((SELECT spam_count FROM bayes_tokens WHERE token = :token AND
                                ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :spam_inc,
                            COALESCE((SELECT ham_count FROM bayes_tokens WHERE token = :token AND
                                ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :ham_inc,
                            COALESCE((SELECT total_count FROM bayes_tokens WHERE token = :token AND
                                ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), 0) + :increment,
                            COALESCE((SELECT created_at FROM bayes_tokens WHERE token = :token AND
                                ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)), CURRENT_TIMESTAMP),
                            CURRENT_TIMESTAMP
                        )
                        """,
                        {
                            "token": token,
                            "chat_id": chat_id,
                            "spam_inc": increment if is_spam else 0,
                            "ham_inc": increment if not is_spam else 0,
                            "increment": increment,
                        },
                    )

                logger.debug(f"Batch updated {len(token_updates)} tokens, dood!")
                return True
        except Exception as e:
            logger.error(f"Failed to batch update tokens: {e}, dood!")
            return False

    async def getTopSpamTokens(self, limit: int = 10, chat_id: Optional[int] = None) -> List[TokenStats]:
        """Get the top spam-indicating tokens"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT token, spam_count, ham_count, total_count,
                           CAST(spam_count AS REAL) / CAST(total_count AS REAL) as spam_ratio
                    FROM bayes_tokens
                    WHERE total_count >= 2
                        AND ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    ORDER BY spam_ratio DESC, spam_count DESC
                    LIMIT :limit
                    """,
                    {"chat_id": chat_id, "limit": limit},
                )

                results = []
                for row in cursor.fetchall():
                    results.append(
                        TokenStats(
                            token=row["token"],
                            spam_count=row["spam_count"],
                            ham_count=row["ham_count"],
                            total_count=row["total_count"],
                        )
                    )
                return results
        except Exception as e:
            logger.error(f"Failed to get top spam tokens: {e}, dood!")
            return []

    async def getTopHamTokens(self, limit: int = 10, chat_id: Optional[int] = None) -> List[TokenStats]:
        """Get the top ham-indicating tokens"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT token, spam_count, ham_count, total_count,
                           CAST(ham_count AS REAL) / CAST(total_count AS REAL) as ham_ratio
                    FROM bayes_tokens
                    WHERE total_count >= 2
                        AND ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    ORDER BY ham_ratio DESC, ham_count DESC
                    LIMIT :limit
                    """,
                    {"chat_id": chat_id, "limit": limit},
                )

                results = []
                for row in cursor.fetchall():
                    results.append(
                        TokenStats(
                            token=row["token"],
                            spam_count=row["spam_count"],
                            ham_count=row["ham_count"],
                            total_count=row["total_count"],
                        )
                    )
                return results
        except Exception as e:
            logger.error(f"Failed to get top ham tokens: {e}, dood!")
            return []

    async def cleanupRareTokens(self, min_count: int = 2, chat_id: Optional[int] = None) -> int:
        """Remove tokens that appear less than min_count times"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM bayes_tokens
                    WHERE total_count < :min_count
                        AND ((:chat_id IS NULL AND chat_id IS NULL) OR chat_id = :chat_id)
                    """,
                    {"min_count": min_count, "chat_id": chat_id},
                )
                removed_count = cursor.rowcount
                logger.info(f"Removed {removed_count} rare tokens (min_count={min_count}), dood!")
                return removed_count
        except Exception as e:
            logger.error(f"Failed to cleanup rare tokens: {e}, dood!")
            return 0
