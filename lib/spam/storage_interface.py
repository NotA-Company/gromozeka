"""
Abstract storage interface for Bayes filter, dood!

This module defines the abstract interface that storage implementations must follow.
This allows for easy testing and future storage backend changes.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional
from .models import TokenStats, ClassStats, BayesModelStats


class BayesStorageInterface(ABC):
    """
    Abstract interface for Bayes filter storage operations

    This interface defines all the storage operations needed by the Bayes filter.
    Implementations can use different backends (SQLite, PostgreSQL, Redis, etc.)
    """

    @abstractmethod
    async def getTokenStats(self, tokens: Iterable[str], chatId: Optional[int] = None) -> Dict[str, TokenStats]:
        """
        Get statistics for a specific tokens

        Args:
            tokens: The tokens to get statistics for
            chatId: Optional chat ID for per-chat statistics

        Returns:
            Dict: Token => TokenStats
        """
        pass

    @abstractmethod
    async def getClassStats(self, is_spam: bool, chat_id: Optional[int] = None) -> ClassStats:
        """
        Get statistics for spam or ham class

        Args:
            is_spam: True for spam class, False for ham class
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            ClassStats object (returns zero stats if no data found)
        """
        pass

    @abstractmethod
    async def updateTokenStats(
        self, token: str, is_spam: bool, increment: int = 1, chat_id: Optional[int] = None
    ) -> bool:
        """
        Update token statistics after learning

        Args:
            token: The token to update
            is_spam: True if this is from a spam message
            increment: How much to increment the count by
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            True if update succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def updateClassStats(
        self, isSpam: bool, messageIncrement: int = 1, tokenIncrement: int = 0, chatId: Optional[int] = None
    ) -> bool:
        """
        Update class statistics after learning

        Args:
            is_spam: True for spam class, False for ham class
            message_increment: How much to increment message count
            token_increment: How much to increment token count
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            True if update succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def getAllTokens(self, chat_id: Optional[int] = None) -> List[str]:
        """
        Get all known tokens (for vocabulary size calculation)

        Args:
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            List of all known tokens
        """
        pass

    @abstractmethod
    async def getVocabularySize(self, chatId: Optional[int] = None) -> int:
        """
        Get the size of the vocabulary (number of unique tokens)

        Args:
            chatId: Optional chat ID for per-chat statistics

        Returns:
            Number of unique tokens in vocabulary
        """
        pass

    @abstractmethod
    async def getModelStats(self, chat_id: Optional[int] = None) -> BayesModelStats:
        """
        Get overall model statistics

        Args:
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            BayesModelStats with overall model information
        """
        pass

    @abstractmethod
    async def clearStats(self, chat_id: Optional[int] = None) -> bool:
        """
        Clear all statistics (reset learning)

        Args:
            chat_id: Optional chat ID to clear (None = clear all)

        Returns:
            True if clear succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def batchUpdateTokens(self, token_updates: List[Dict[str, Any]], chat_id: Optional[int] = None) -> bool:
        """
        Update multiple tokens in a single batch operation for performance

        Args:
            token_updates: List of dicts with 'token', 'is_spam', 'increment' keys
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            True if batch update succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def getTopSpamTokens(self, limit: int = 10, chat_id: Optional[int] = None) -> List[TokenStats]:
        """
        Get the top spam-indicating tokens

        Args:
            limit: Maximum number of tokens to return
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            List of TokenStats ordered by spam probability
        """
        pass

    @abstractmethod
    async def getTopHamTokens(self, limit: int = 10, chat_id: Optional[int] = None) -> List[TokenStats]:
        """
        Get the top ham-indicating tokens

        Args:
            limit: Maximum number of tokens to return
            chat_id: Optional chat ID for per-chat statistics

        Returns:
            List of TokenStats ordered by ham probability
        """
        pass

    @abstractmethod
    async def cleanupRareTokens(self, min_count: int = 2, chat_id: Optional[int] = None) -> int:
        """
        Remove tokens that appear less than min_count times

        Args:
            min_count: Minimum total count to keep a token
            chat_id: Optional chat ID for per-chat cleanup

        Returns:
            Number of tokens removed
        """
        pass
