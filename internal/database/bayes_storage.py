"""
Database implementation of Bayes storage interface, dood!

This module provides a concrete implementation of the BayesStorageInterface
using the existing DatabaseWrapper from the Gromozeka project.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional

from internal.database.wrapper import DatabaseWrapper
from lib.bayes_filter.models import BayesModelStats, ClassStats, TokenStats
from lib.bayes_filter.storage_interface import BayesStorageInterface

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

    async def getTokenStats(self, tokens: Iterable[str], chatId: Optional[int] = None) -> Dict[str, TokenStats]:
        """Get statistics for a specific tokens"""
        params: Dict[str, Any] = {"chatId": chatId}
        placeholders = []
        for i, token in enumerate(tokens):
            tName = f"token{i}"
            placeholders.append(":" + tName)
            params[tName] = token

        tokenPlaceholdersStr = ", ".join(placeholders)
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT token, spam_count, ham_count, total_count
                    FROM bayes_tokens
                    WHERE
                        token IN ({tokenPlaceholdersStr})
                        AND ((:chatId IS NULL AND chat_id IS NULL) OR chat_id = :chatId)
                    """,
                    params,
                )
                ret: Dict[str, TokenStats] = {}
                for row in cursor.fetchall():
                    rDict = dict(row)
                    ret[rDict["token"]] = TokenStats(
                        token=row["token"],
                        spamCount=row["spam_count"],
                        hamCount=row["ham_count"],
                        totalCount=row["total_count"],
                    )
                return ret
        except Exception as e:
            logger.error(f"Failed to get token stats for '{tokens}': {e}, dood!")
            return {}

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
                    INSERT INTO bayes_tokens
                        (token, chat_id, spam_count, ham_count, total_count, created_at, updated_at)
                    VALUES (
                        :token,
                        :chat_id,
                        :spam_inc,
                        :ham_inc,
                        :increment,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(token, chat_id) DO UPDATE SET
                        spam_count = spam_count + :spam_inc,
                        ham_count = ham_count + :ham_inc,
                        total_count = total_count + :increment,
                        updated_at = CURRENT_TIMESTAMP
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
        self, isSpam: bool, messageIncrement: int = 1, tokenIncrement: int = 0, chatId: Optional[int] = None
    ) -> bool:
        """Update class statistics after learning"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO bayes_classes
                        (chat_id, is_spam, message_count, token_count, created_at, updated_at)
                    VALUES (
                        :chat_id,
                        :is_spam,
                        :msg_inc,
                        :tok_inc,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(chat_id, is_spam) DO UPDATE SET
                        message_count = message_count + :msg_inc,
                        token_count = token_count + :tok_inc,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    {"chat_id": chatId, "is_spam": isSpam, "msg_inc": messageIncrement, "tok_inc": tokenIncrement},
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update class stats for is_spam={isSpam}: {e}, dood!")
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

    async def getVocabularySize(self, chatId: Optional[int] = None) -> int:
        """Get the size of the vocabulary (number of unique tokens)"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) as vocab_size FROM bayes_tokens
                    WHERE ((:chatId IS NULL AND chat_id IS NULL) OR chat_id = :chatId)
                    """,
                    {"chatId": chatId},
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
                        INSERT INTO bayes_tokens
                            (token, chat_id, spam_count, ham_count, total_count, created_at, updated_at)
                        VALUES (
                            :token,
                            :chat_id,
                            :spam_inc,
                            :ham_inc,
                            :increment,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP
                        )
                        ON CONFLICT(token, chat_id) DO UPDATE SET
                            spam_count = spam_count + :spam_inc,
                            ham_count = ham_count + :ham_inc,
                            total_count = total_count + :increment,
                            updated_at = CURRENT_TIMESTAMP
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
                            spamCount=row["spam_count"],
                            hamCount=row["ham_count"],
                            totalCount=row["total_count"],
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
                            spamCount=row["spam_count"],
                            hamCount=row["ham_count"],
                            totalCount=row["total_count"],
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
