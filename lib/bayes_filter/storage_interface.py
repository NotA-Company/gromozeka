"""Abstract storage interface for Bayes filter.

This module defines the abstract interface that storage implementations must follow
to support the Bayes spam filter. The interface provides methods for storing and
retrieving token statistics, class statistics, and overall model statistics. This
abstraction allows for easy testing with mock implementations and future storage
backend changes (SQLite, PostgreSQL, Redis, etc.).

Classes:
    BayesStorageInterface: Abstract base class defining the storage interface.

Example:
    To implement a custom storage backend, inherit from BayesStorageInterface
    and implement all abstract methods:

    >>> class MyStorage(BayesStorageInterface):
    ...     async def getTokenStats(self, tokens, chatId=None):
    ...         # Implementation here
    ...         pass
    ...     # Implement other abstract methods...
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

from .models import BayesModelStats, ClassStats, TokenStats


class BayesStorageInterface(ABC):
    """Abstract interface for Bayes filter storage operations.

    This interface defines all the storage operations needed by the Bayes filter
    to maintain and query token and class statistics. Implementations can use
    different backends (SQLite, PostgreSQL, Redis, in-memory, etc.) while
    providing a consistent API to the filter.

    The interface supports both global statistics and per-chat statistics through
    the optional chat_id parameter, allowing for context-aware spam filtering.

    Attributes:
        None (this is an abstract interface with no instance attributes).

    Example:
        >>> storage = MyStorageImplementation()
        >>> stats = await storage.getTokenStats(["free", "money"], chatId=123)
        >>> print(stats["free"].spamCount)
        50
    """

    @abstractmethod
    async def getTokenStats(self, tokens: Iterable[str], chatId: Optional[int] = None) -> Dict[str, TokenStats]:
        """Get statistics for specific tokens.

        Retrieves the spam and ham occurrence counts for each requested token.
        If a token has not been seen before, it will not be included in the
        returned dictionary.

        Args:
            tokens: An iterable of token strings to get statistics for.
            chatId: Optional chat ID for per-chat statistics. If None, returns
                global statistics across all chats.

        Returns:
            A dictionary mapping token strings to their corresponding TokenStats
            objects. Tokens that have not been seen are not included in the result.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.

        Example:
            >>> stats = await storage.getTokenStats(["free", "money"], chatId=123)
            >>> print(stats["free"].spamCount)
            50
        """
        pass

    @abstractmethod
    async def getClassStats(self, is_spam: bool, chat_id: Optional[int] = None) -> ClassStats:
        """Get statistics for spam or ham class.

        Retrieves aggregate statistics for either the spam or ham class,
        including total message count and total token count. If no data
        exists for the requested class, returns zero statistics.

        Args:
            is_spam: True to get spam class statistics, False for ham class.
            chat_id: Optional chat ID for per-chat statistics. If None, returns
                global statistics across all chats.

        Returns:
            A ClassStats object containing message_count and token_count for the
            requested class. Returns zero stats (0, 0) if no data exists.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.

        Example:
            >>> spam_stats = await storage.getClassStats(is_spam=True, chat_id=123)
            >>> print(spam_stats.message_count)
            100
        """
        pass

    @abstractmethod
    async def updateTokenStats(
        self, token: str, is_spam: bool, increment: int = 1, chat_id: Optional[int] = None
    ) -> bool:
        """Update token statistics after learning.

        Increments the spam or ham count for a specific token. This method is
        called during the training process when the filter learns from a new
        message.

        Args:
            token: The token string to update statistics for.
            is_spam: True if this token appeared in a spam message, False for ham.
            increment: The amount to increment the count by (default: 1). Can be
                used for weighted training or batch updates.
            chat_id: Optional chat ID for per-chat statistics. If None, updates
                global statistics.

        Returns:
            True if the update succeeded, False otherwise.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.
            ValueError: If increment is negative.

        Example:
            >>> success = await storage.updateTokenStats("free", is_spam=True, chat_id=123)
            >>> print(success)
            True
        """
        pass

    @abstractmethod
    async def updateClassStats(
        self, isSpam: bool, messageIncrement: int = 1, tokenIncrement: int = 0, chatId: Optional[int] = None
    ) -> bool:
        """Update class statistics after learning.

        Increments the message and token counts for either the spam or ham class.
        This method is called during the training process to track overall
        statistics for each class.

        Args:
            isSpam: True to update spam class statistics, False for ham class.
            messageIncrement: The amount to increment the message count by
                (default: 1). Typically 1 for each message processed.
            tokenIncrement: The amount to increment the token count by
                (default: 0). Should be set to the number of tokens in the message.
            chatId: Optional chat ID for per-chat statistics. If None, updates
                global statistics.

        Returns:
            True if the update succeeded, False otherwise.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.
            ValueError: If messageIncrement or tokenIncrement are negative.

        Example:
            >>> success = await storage.updateClassStats(
            ...     isSpam=True, messageIncrement=1, tokenIncrement=5, chatId=123
            ... )
            >>> print(success)
            True
        """
        pass

    @abstractmethod
    async def getAllTokens(self, chat_id: Optional[int] = None) -> List[str]:
        """Get all known tokens.

        Retrieves a list of all unique tokens that have been seen and stored.
        This is useful for vocabulary size calculation and analysis.

        Args:
            chat_id: Optional chat ID for per-chat statistics. If None, returns
                tokens from global statistics across all chats.

        Returns:
            A list of all unique token strings that have been stored. The list
            may be empty if no tokens have been learned yet.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.

        Example:
            >>> tokens = await storage.getAllTokens(chat_id=123)
            >>> print(len(tokens))
            2000
        """
        pass

    @abstractmethod
    async def getVocabularySize(self, chatId: Optional[int] = None) -> int:
        """Get the size of the vocabulary.

        Returns the number of unique tokens in the vocabulary. This is a
        convenience method that is equivalent to len(getAllTokens()) but may
        be more efficient in some implementations.

        Args:
            chatId: Optional chat ID for per-chat statistics. If None, returns
                vocabulary size from global statistics.

        Returns:
            The number of unique tokens in the vocabulary. Returns 0 if no
            tokens have been learned yet.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.

        Example:
            >>> vocab_size = await storage.getVocabularySize(chatId=123)
            >>> print(vocab_size)
            2000
        """
        pass

    @abstractmethod
    async def getModelStats(self, chat_id: Optional[int] = None) -> BayesModelStats:
        """Get overall model statistics.

        Retrieves comprehensive statistics about the trained Bayes model,
        including total spam/ham messages, total tokens, vocabulary size,
        and derived ratios.

        Args:
            chat_id: Optional chat ID for per-chat statistics. If None, returns
                global model statistics.

        Returns:
            A BayesModelStats object containing total_spam_messages,
            total_ham_messages, total_tokens, vocabulary_size, and chat_id.
            The object also provides properties for total_messages, spam_ratio,
            and ham_ratio.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.

        Example:
            >>> stats = await storage.getModelStats(chat_id=123)
            >>> print(stats.spam_ratio)
            0.16666666666666666
        """
        pass

    @abstractmethod
    async def clearStats(self, chat_id: Optional[int] = None) -> bool:
        """Clear all statistics.

        Resets all learned statistics, effectively untraining the filter. This
        can be used to start fresh or to clear statistics for a specific chat.

        Args:
            chat_id: Optional chat ID to clear statistics for. If None, clears
                all global statistics across all chats.

        Returns:
            True if the clear operation succeeded, False otherwise.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.

        Example:
            >>> success = await storage.clearStats(chat_id=123)
            >>> print(success)
            True
        """
        pass

    @abstractmethod
    async def batchUpdateTokens(self, token_updates: List[Dict[str, Any]], chat_id: Optional[int] = None) -> bool:
        """Update multiple tokens in a single batch operation.

        Performs a batch update of multiple token statistics for improved
        performance when processing many tokens at once. This is more efficient
        than calling updateTokenStats multiple times.

        Args:
            token_updates: A list of dictionaries, each containing the keys:
                - 'token' (str): The token string to update.
                - 'is_spam' (bool): True if from spam, False for ham.
                - 'increment' (int): Amount to increment by (default: 1).
            chat_id: Optional chat ID for per-chat statistics. If None, updates
                global statistics.

        Returns:
            True if the batch update succeeded, False otherwise.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.
            ValueError: If any token update dictionary is missing required keys
                or contains invalid values.

        Example:
            >>> updates = [
            ...     {"token": "free", "is_spam": True, "increment": 1},
            ...     {"token": "money", "is_spam": True, "increment": 1},
            ... ]
            >>> success = await storage.batchUpdateTokens(updates, chat_id=123)
            >>> print(success)
            True
        """
        pass

    @abstractmethod
    async def getTopSpamTokens(self, limit: int = 10, chat_id: Optional[int] = None) -> List[TokenStats]:
        """Get the top spam-indicating tokens.

        Retrieves the tokens that are most strongly associated with spam,
        ordered by their spam probability. This is useful for analysis and
        understanding what the filter considers spammy.

        Args:
            limit: Maximum number of tokens to return (default: 10).
            chat_id: Optional chat ID for per-chat statistics. If None, returns
                tokens from global statistics.

        Returns:
            A list of TokenStats objects ordered by spam probability (highest
            first). Each TokenStats contains token, spamCount, hamCount, and
            totalCount. The list may be shorter than limit if there are fewer
            tokens available.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.
            ValueError: If limit is negative.

        Example:
            >>> top_spam = await storage.getTopSpamTokens(limit=5, chat_id=123)
            >>> for stat in top_spam:
            ...     print(f"{stat.token}: {stat.spamCount} spam, {stat.hamCount} ham")
        """
        pass

    @abstractmethod
    async def getTopHamTokens(self, limit: int = 10, chat_id: Optional[int] = None) -> List[TokenStats]:
        """Get the top ham-indicating tokens.

        Retrieves the tokens that are most strongly associated with ham
        (legitimate messages), ordered by their ham probability. This is useful
        for analysis and understanding what the filter considers legitimate.

        Args:
            limit: Maximum number of tokens to return (default: 10).
            chat_id: Optional chat ID for per-chat statistics. If None, returns
                tokens from global statistics.

        Returns:
            A list of TokenStats objects ordered by ham probability (highest
            first). Each TokenStats contains token, spamCount, hamCount, and
            totalCount. The list may be shorter than limit if there are fewer
            tokens available.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.
            ValueError: If limit is negative.

        Example:
            >>> top_ham = await storage.getTopHamTokens(limit=5, chat_id=123)
            >>> for stat in top_ham:
            ...     print(f"{stat.token}: {stat.hamCount} ham, {stat.spamCount} spam")
        """
        pass

    @abstractmethod
    async def cleanupRareTokens(self, min_count: int = 2, chat_id: Optional[int] = None) -> None:
        """Remove tokens that appear less than min_count times.

        Cleans up the vocabulary by removing rare tokens that don't appear
        frequently enough to be statistically significant. This helps reduce
        memory usage and improve filter performance.

        Args:
            min_count: Minimum total count (spam + ham) required to keep a token
                (default: 2). Tokens with totalCount < min_count will be removed.
            chat_id: Optional chat ID for per-chat cleanup. If None, cleans up
                global statistics.

        Returns:
            None. The method performs the cleanup in-place.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by subclasses.
            ValueError: If min_count is negative.

        Example:
            >>> await storage.cleanupRareTokens(min_count=3, chat_id=123)
            >>> # Tokens appearing less than 3 times total are now removed
        """
        pass
