"""
Naive Bayes spam filter implementation.

This module provides a comprehensive spam classification system using the multinomial
Naive Bayes algorithm with Laplace smoothing. It supports both global and per-chat
learning, configurable thresholds, and batch processing capabilities.

The filter is designed for real-time spam detection in messaging applications,
with features including:
- Token-based message classification
- Configurable spam thresholds and confidence levels
- Per-chat or global statistics tracking
- Batch learning for training data
- Performance optimization through token limiting
- Rare token cleanup for maintenance

Example:
    >>> from lib.bayes_filter.bayes_filter import NaiveBayesFilter, BayesConfig
    >>> from lib.bayes_filter.storage_interface import BayesStorageInterface
    >>>
    >>> # Initialize filter with storage and config
    >>> config = BayesConfig(defaultThreshold=70.0, perChatStats=True)
    >>> filter = NaiveBayesFilter(storage=storage, config=config)
    >>>
    >>> # Classify a message
    >>> result = await filter.classify("Buy cheap watches!", chatId=12345)
    >>> print(f"Spam score: {result.score}%, Is spam: {result.isSpam}")
    >>>
    >>> # Learn from spam/ham messages
    >>> await filter.learnSpam("Free money now!", chatId=12345)
    >>> await filter.learnHam("Hello, how are you?", chatId=12345)
"""

import logging
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .models import BayesModelStats, SpamScore
from .storage_interface import BayesStorageInterface
from .tokenizer import MessageTokenizer, TokenizerConfig

logger = logging.getLogger(__name__)


@dataclass
class BayesConfig:
    """Configuration for Naive Bayes spam filter.

    This dataclass encapsulates all configurable parameters for the spam filter,
    including smoothing parameters, thresholds, and performance settings.

    Attributes:
        alpha: Laplace smoothing parameter to avoid zero probabilities. Must be positive.
            Higher values provide more smoothing but may reduce accuracy. Default: 1.0.
        minTokenCount: Minimum number of times a token must appear to be considered
            for classification. Helps filter out noise from rare tokens. Default: 2.
        perChatStats: If True, maintain separate statistics per chat ID. If False,
            use global statistics across all chats. Default: True.
        defaultThreshold: Default spam threshold (0-100). Messages with scores above
            this threshold are classified as spam. Default: 50.0.
        minConfidence: Minimum confidence level (0-1) required to trust classification.
            Low confidence classifications are treated as neutral. Default: 0.1.
        maxTokensPerMessage: Maximum number of tokens to consider per message for
            performance optimization. Longer messages are truncated. Default: 2000.
        tokenizerConfig: Configuration for the message tokenizer. If None, uses
            default TokenizerConfig. Default: None.
        debugLogging: Enable debug-level logging for detailed classification information.
            Useful for development and troubleshooting. Default: False.
        defaultSpamProbability: Override the prior probability of spam (0-1). If None,
            uses empirical probability from training data. Default: None.

    Raises:
        ValueError: If alpha is not positive, defaultThreshold is not in [0, 100],
            or minConfidence is not in [0, 1].

    Example:
        >>> config = BayesConfig(
        ...     alpha=1.0,
        ...     defaultThreshold=70.0,
        ...     perChatStats=True,
        ...     minConfidence=0.2
        ... )
        >>> filter = NaiveBayesFilter(storage=storage, config=config)
    """

    # Laplace smoothing parameter (avoid zero probabilities)
    alpha: float = 1.0

    # Minimum token occurrences to consider for classification
    minTokenCount: int = 2

    # Use per-chat statistics (True) or global (False)
    perChatStats: bool = True

    # Default spam threshold (0-100)
    defaultThreshold: float = 50.0

    # Minimum confidence to trust classification
    minConfidence: float = 0.1

    # Maximum tokens to consider per message (performance)
    maxTokensPerMessage: int = 2000

    # Tokenizer configuration
    tokenizerConfig: Optional[TokenizerConfig] = None

    # Enable debug logging
    debugLogging: bool = False

    defaultSpamProbability: Optional[float] = None

    def __post_init__(self) -> None:
        """Validate configuration parameters.

        Ensures all configuration values are within acceptable ranges and
        initializes default values for optional parameters.

        Raises:
            ValueError: If any configuration parameter is invalid.
        """
        if self.alpha <= 0:
            raise ValueError("Alpha must be positive for Laplace smoothing.")

        if not (0 <= self.defaultThreshold <= 100):
            raise ValueError("Default threshold must be between 0 and 100.")

        if not (0 <= self.minConfidence <= 1):
            raise ValueError("Min confidence must be between 0 and 1.")

        if self.tokenizerConfig is None:
            self.tokenizerConfig = TokenizerConfig()


class NaiveBayesFilter:
    """Naive Bayes spam filter implementation.

    This class implements a multinomial Naive Bayes classifier for spam detection
    with Laplace smoothing. It supports both global and per-chat learning modes,
    configurable thresholds, and batch processing capabilities.

    The filter uses token-based classification, where each message is tokenized
    and the probability of it being spam is calculated based on token frequencies
    in the training data.

    Attributes:
        storage: Storage interface for persisting and retrieving statistics.
        config: Configuration object containing filter parameters.
        tokenizer: Message tokenizer for extracting tokens from text.

    Example:
        >>> from lib.bayes_filter.bayes_filter import NaiveBayesFilter, BayesConfig
        >>> from lib.bayes_filter.storage_interface import BayesStorageInterface
        >>>
        >>> # Initialize with custom config
        >>> config = BayesConfig(defaultThreshold=70.0, perChatStats=True)
        >>> filter = NaiveBayesFilter(storage=storage, config=config)
        >>>
        >>> # Classify a message
        >>> result = await filter.classify("Buy cheap watches!", chatId=12345)
        >>> if result.isSpam:
        ...     print("Spam detected!")
        >>>
        >>> # Train the filter
        >>> await filter.learnSpam("Free money now!", chatId=12345)
        >>> await filter.learnHam("Hello, how are you?", chatId=12345)
    """

    def __init__(self, storage: BayesStorageInterface, config: Optional[BayesConfig] = None) -> None:
        """Initialize Naive Bayes filter.

        Args:
            storage: Storage interface implementation for persisting statistics.
            config: Filter configuration. If None, uses default BayesConfig.

        Raises:
            ValueError: If configuration validation fails.
        """
        self.storage = storage
        self.config = config or BayesConfig()
        self.tokenizer = MessageTokenizer(self.config.tokenizerConfig)

        # Setup logging
        if self.config.debugLogging:
            logger.setLevel(logging.DEBUG)

        logger.info(f"Initialized NaiveBayesFilter with per_chat_stats={self.config.perChatStats}")

    async def classify(
        self,
        messageText: str,
        chatId: Optional[int] = None,
        threshold: Optional[float] = None,
        ignoreTrigrams: bool = False,
    ) -> SpamScore:
        """Classify a message as spam or ham.

        Uses the multinomial Naive Bayes algorithm with Laplace smoothing to
        calculate the probability that a message is spam. The classification
        considers token frequencies from training data and applies confidence
        thresholds to ensure reliable results.

        Args:
            messageText: Text content to classify.
            chatId: Optional chat ID for per-chat statistics. If None and
                perChatStats is enabled, uses global statistics.
            threshold: Spam threshold (0-100). Messages with scores above this
                threshold are classified as spam. If None, uses config.defaultThreshold.
            ignoreTrigrams: If True, skip trigram tokenization for faster processing.

        Returns:
            SpamScore object containing:
                - score: Spam probability (0-100)
                - isSpam: Boolean classification result
                - confidence: Confidence level (0-1) in the classification
                - tokenScores: Dictionary of individual token contributions

        Raises:
            Exception: If storage operations fail (caught and logged, returns neutral score).

        Example:
            >>> result = await filter.classify(
            ...     "Buy cheap watches!",
            ...     chatId=12345,
            ...     threshold=70.0
            ... )
            >>> print(f"Score: {result.score}%, Is spam: {result.isSpam}")
            >>> print(f"Confidence: {result.confidence}")
        """
        if threshold is None:
            threshold = self.config.defaultThreshold

        # Tokenize message
        tokens = self.tokenizer.tokenize(messageText, ignoreTrigrams=ignoreTrigrams)

        if not tokens:
            # No tokens, cannot classify
            logger.debug("No tokens found in message, returning neutral score.")
            return SpamScore(score=50.0, isSpam=False, confidence=0.0, tokenScores={})

        # Limit tokens for performance
        if len(tokens) > self.config.maxTokensPerMessage:
            logger.warning(f"Message has {len(tokens)} tokens, limiting to {self.config.maxTokensPerMessage}.")
            tokens = tokens[: self.config.maxTokensPerMessage]

        # Get chat ID parameter
        chatIdParam = chatId if self.config.perChatStats else None

        # Get class statistics
        try:
            spam_stats = await self.storage.getClassStats(True, chatIdParam)
            ham_stats = await self.storage.getClassStats(False, chatIdParam)
        except Exception as e:
            logger.error(f"Failed to get class stats: {e}.")
            return SpamScore(score=50.0, isSpam=False, confidence=0.0, tokenScores={})

        # Check if we have training data
        total_messages = spam_stats.message_count + ham_stats.message_count
        if total_messages == 0:
            logger.debug("No training data available, returning neutral score.")
            return SpamScore(score=50.0, isSpam=False, confidence=0.0, tokenScores={})

        # Calculate prior probabilities
        pSpam = 0.5
        pHam = 0.5
        if self.config.defaultSpamProbability is None:
            pSpam = spam_stats.message_count / total_messages
            pHam = ham_stats.message_count / total_messages
        else:
            pSpam = self.config.defaultSpamProbability
            pHam = 1 - pSpam

        logger.debug(f"Prior probabilities: P(spam)={pSpam:.3f}, P(ham)={pHam:.3f}.")

        # Calculate log probabilities (to avoid underflow)
        logPSpam = math.log(pSpam)
        logPHam = math.log(pHam)

        # Get vocabulary size for Laplace smoothing
        try:
            vocab_size = await self.storage.getVocabularySize(chatIdParam)
        except Exception as e:
            logger.error(f"Failed to get vocabulary size: {e}.")
            vocab_size = 1000  # Fallback estimate

        tokenScores = {}
        known_tokens = 0

        # Calculate likelihood for each unique token
        uniqueTokens = set(tokens)
        tokenStatsDict = await self.storage.getTokenStats(uniqueTokens, chatIdParam)
        for token in uniqueTokens:
            tokenStats = tokenStatsDict.get(token, None)

            if tokenStats is None or tokenStats.totalCount < self.config.minTokenCount:
                # Unknown or rare token, skip
                logger.debug(f"Skipping rare token '{token}' (count: {tokenStats.totalCount if tokenStats else 0}).")
                continue

            known_tokens += 1

            # Count occurrences of this token in the message
            tokenCount = tokens.count(token)

            # Laplace smoothing: P(token|class) = (count + alpha) / (total + alpha * vocab_size)
            pTokenSpam = (tokenStats.spamCount + self.config.alpha) / (
                spam_stats.token_count + self.config.alpha * vocab_size
            )
            pTokenHam = (tokenStats.hamCount + self.config.alpha) / (
                ham_stats.token_count + self.config.alpha * vocab_size
            )

            # Add to log probabilities (multiply by token count for frequency)
            logPSpam += math.log(pTokenSpam) * tokenCount
            logPHam += math.log(pTokenHam) * tokenCount

            # Store individual token contribution for debugging
            tokenSpamProb = (pTokenSpam / (pTokenSpam + pTokenHam)) * 100
            tokenScores[token] = tokenSpamProb

            # Note: For debug purposes only
            maxLogP = max(logPSpam, logPHam)
            expSpam = math.exp(logPSpam - maxLogP)
            expHam = math.exp(logPHam - maxLogP)

            # Normalize to get probability
            spamProbability = expSpam / (expSpam + expHam)
            spamScore = spamProbability * 100

            logger.debug(
                f"Token '{token}' (count: {tokenCount}): spam_prob={tokenSpamProb:.1f}%, "
                f"logPSpam={logPSpam:.3f}, logPHam={logPHam:.3f}, spamScore={spamScore:.1f}%."
            )

        # Convert log probabilities back to probabilities
        # Using log-sum-exp trick for numerical stability
        maxLogP = max(logPSpam, logPHam)
        expSpam = math.exp(logPSpam - maxLogP)
        expHam = math.exp(logPHam - maxLogP)

        # Normalize to get probability
        spamProbability = expSpam / (expSpam + expHam)
        spamScore = spamProbability * 100

        # Calculate confidence based on number of known tokens and training data
        confidence = self._calculate_confidence(known_tokens, len(uniqueTokens), total_messages)

        isSpam = spamScore >= threshold and confidence >= self.config.minConfidence

        logger.debug(f"Classification result: score={spamScore:.2f}%, confidence={confidence:.3f}, is_spam={isSpam}.")

        return SpamScore(score=spamScore, isSpam=isSpam, confidence=confidence, tokenScores=tokenScores)

    def _calculate_confidence(self, known_tokens: int, total_tokens: int, training_messages: int) -> float:
        """Calculate confidence in classification based on available data.

        Confidence is computed as a weighted combination of token coverage
        (how many tokens in the message are known from training data) and
        training data volume (how many messages have been trained).

        Args:
            known_tokens: Number of tokens in the message that appear in training data.
            total_tokens: Total number of unique tokens in the message.
            training_messages: Total number of messages in the training set.

        Returns:
            Confidence score between 0.0 and 1.0, where higher values indicate
            greater confidence in the classification result.

        Note:
            The confidence calculation uses a 70/30 weight split between
            token coverage and training data volume. Token coverage is
            considered more important as it directly affects classification
            accuracy.
        """
        if total_tokens == 0:
            return 0.0

        # Token coverage: how many tokens we know about
        token_coverage = known_tokens / total_tokens

        # Training data factor: more training data = higher confidence
        training_factor = min(1.0, training_messages / 100)  # Cap at 100 messages

        # Combine factors
        confidence = (token_coverage * 0.7) + (training_factor * 0.3)

        return min(1.0, confidence)

    async def learnSpam(self, messageText: str, chatId: Optional[int] = None) -> bool:
        """Learn from a spam message.

        Tokenizes the message and updates the spam statistics in storage.
        This improves the filter's ability to identify similar spam messages
        in the future.

        Args:
            messageText: Spam message text to learn from.
            chatId: Optional chat ID for per-chat learning. If None and
                perChatStats is enabled, uses global statistics.

        Returns:
            True if learning succeeded, False if the message had no tokens
            or storage operations failed.

        Example:
            >>> success = await filter.learnSpam("Free money now!", chatId=12345)
            >>> if success:
            ...     print("Successfully learned from spam message")
        """
        return await self._learn(messageText, isSpam=True, chat_id=chatId)

    async def learnHam(self, messageText: str, chatId: Optional[int] = None) -> bool:
        """Learn from a ham (non-spam) message.

        Tokenizes the message and updates the ham statistics in storage.
        This improves the filter's ability to identify legitimate messages
        and reduce false positives.

        Args:
            messageText: Ham message text to learn from.
            chatId: Optional chat ID for per-chat learning. If None and
                perChatStats is enabled, uses global statistics.

        Returns:
            True if learning succeeded, False if the message had no tokens
            or storage operations failed.

        Example:
            >>> success = await filter.learnHam("Hello, how are you?", chatId=12345)
            >>> if success:
            ...     print("Successfully learned from ham message")
        """
        return await self._learn(messageText, isSpam=False, chat_id=chatId)

    async def _learn(self, messageText: str, isSpam: bool, chat_id: Optional[int] = None) -> bool:
        """Internal learning method.

        Tokenizes the message and updates statistics in storage. Updates both
        class-level statistics (message count, token count) and token-level
        statistics (spam/ham counts for each token).

        Args:
            messageText: Message text to learn from.
            isSpam: True if the message is spam, False if ham.
            chat_id: Optional chat ID for per-chat learning.

        Returns:
            True if learning succeeded, False if the message had no tokens
            or storage operations failed.

        Note:
            Uses batch updates for token statistics to improve performance
            when processing messages with many repeated tokens.
        """
        # Tokenize message
        tokens = self.tokenizer.tokenize(messageText)

        if not tokens:
            logger.warning("No tokens found in training message, skipping.")
            return False

        chat_id_param = chat_id if self.config.perChatStats else None

        try:
            # Update class statistics
            await self.storage.updateClassStats(
                isSpam=isSpam, messageIncrement=1, tokenIncrement=len(tokens), chatId=chat_id_param
            )

            # Batch update token statistics for performance
            token_updates = []
            token_counts = {}

            # Count token frequencies
            for token in tokens:
                token_counts[token] = token_counts.get(token, 0) + 1

            # Prepare batch updates
            for token, count in token_counts.items():
                token_updates.append({"token": token, "is_spam": isSpam, "increment": count})

            # Perform batch update
            success = await self.storage.batchUpdateTokens(token_updates, chat_id_param)

            if success:
                class_name = "spam" if isSpam else "ham"
                logger.debug(f"Successfully learned {class_name} message with {len(tokens)} tokens.")
            else:
                logger.error("Failed to update token statistics during learning.")

            return success

        except Exception as e:
            logger.error(f"Failed to learn from message: {e}.")
            return False

    async def batch_learn(
        self,
        messages: Sequence[Tuple[str, bool, Optional[int]]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, int]:
        """Learn from multiple messages in batch.

        Processes a sequence of messages for training, updating statistics for each.
        Useful for bulk training operations or importing training data.

        Args:
            messages: Sequence of tuples containing (text, is_spam, chat_id) where:
                - text: Message text to learn from
                - is_spam: True if spam, False if ham
                - chat_id: Optional chat ID for per-chat learning
            progress_callback: Optional callback function called after each message
                with (current, total) progress. Signature: callback(current: int, total: int) -> None

        Returns:
            Dictionary containing learning statistics:
                - total: Total number of messages processed
                - success: Number of successfully learned messages
                - failed: Number of failed learning operations
                - spam_learned: Number of spam messages learned
                - ham_learned: Number of ham messages learned

        Example:
            >>> messages = [
            ...     ("Buy cheap watches!", True, 12345),
            ...     ("Hello, how are you?", False, 12345),
            ...     ("Free money now!", True, 12345)
            ... ]
            >>>
            >>> def progress(current, total):
            ...     print(f"Progress: {current}/{total}")
            >>>
            >>> stats = await filter.batch_learn(messages, progress_callback=progress)
            >>> print(f"Learned {stats['spam_learned']} spam and {stats['ham_learned']} ham messages")
        """
        stats = {"total": len(messages), "success": 0, "failed": 0, "spam_learned": 0, "ham_learned": 0}

        for i, (text, is_spam, chat_id) in enumerate(messages):
            success = await self._learn(text, is_spam, chat_id)

            if success:
                stats["success"] += 1
                if is_spam:
                    stats["spam_learned"] += 1
                else:
                    stats["ham_learned"] += 1
            else:
                stats["failed"] += 1

            # Call progress callback if provided
            if progress_callback:
                progress_callback(i + 1, len(messages))

        logger.info(f"Batch learning completed: {stats}.")
        return stats

    async def getModelInfo(self, chat_id: Optional[int] = None) -> BayesModelStats:
        """Get information about the current model.

        Retrieves statistics about the trained model, including message counts,
        token counts, and vocabulary size. Useful for monitoring training progress
        and model health.

        Args:
            chat_id: Optional chat ID for per-chat stats. If None and perChatStats
                is enabled, returns global statistics.

        Returns:
            BayesModelStats object containing:
                - total_spam_messages: Total number of spam messages trained
                - total_ham_messages: Total number of ham messages trained
                - total_tokens: Total number of tokens across all messages
                - vocabulary_size: Number of unique tokens in vocabulary
                - chat_id: Chat ID for per-chat stats (None if global)

        Note:
            If storage operations fail, returns empty stats with zero values.
            This ensures the method never raises exceptions for model info queries.

        Example:
            >>> stats = await filter.getModelInfo(chatId=12345)
            >>> print(f"Trained on {stats.total_spam_messages} spam and {stats.total_ham_messages} ham messages")
            >>> print(f"Vocabulary size: {stats.vocabulary_size}")
        """
        chat_id_param = chat_id if self.config.perChatStats else None

        try:
            return await self.storage.getModelStats(chat_id_param)
        except Exception as e:
            logger.error(f"Failed to get model info: {e}.")
            # Return empty stats as fallback
            return BayesModelStats(
                total_spam_messages=0, total_ham_messages=0, total_tokens=0, vocabulary_size=0, chat_id=chat_id_param
            )

    async def reset(self, chat_id: Optional[int] = None) -> bool:
        """Reset all learned statistics.

        Clears all training data for the specified scope (global or per-chat).
        This is useful for retraining the filter from scratch or clearing
        corrupted data.

        Args:
            chat_id: Optional chat ID to reset. If None and perChatStats is enabled,
                resets all global statistics. If perChatStats is False, resets
                global statistics regardless of this parameter.

        Returns:
            True if reset succeeded, False if storage operations failed.

        Warning:
            This operation is irreversible. All training data will be lost.

        Example:
            >>> success = await filter.reset(chatId=12345)
            >>> if success:
            ...     print("Successfully reset statistics for chat 12345")
        """
        chat_id_param = chat_id if self.config.perChatStats else None

        try:
            success = await self.storage.clearStats(chat_id_param)
            if success:
                scope = f"chat {chat_id}" if chat_id_param else "global"
                logger.info(f"Successfully reset {scope} Bayes filter statistics.")
            else:
                logger.error("Failed to reset Bayes filter statistics.")
            return success
        except Exception as e:
            logger.error(f"Failed to reset statistics: {e}.")
            return False

    async def cleanup_rare_tokens(self, min_count: int = 2, chat_id: Optional[int] = None) -> int:
        """Remove rarely occurring tokens to improve performance.

        Deletes tokens that appear fewer than min_count times in the training data.
        This reduces memory usage and improves classification speed by removing
        noise from rare tokens that don't contribute significantly to accuracy.

        Args:
            min_count: Minimum total count (spam + ham) required to keep a token.
                Tokens with fewer occurrences are removed. Default: 2.
            chat_id: Optional chat ID for per-chat cleanup. If None and perChatStats
                is enabled, cleans up global statistics.

        Returns:
            Number of tokens removed from storage.

        Note:
            This operation does not affect message counts, only token statistics.
            Removed tokens will be treated as unknown in future classifications.

        Example:
            >>> removed = await filter.cleanup_rare_tokens(min_count=5, chatId=12345)
            >>> print(f"Removed {removed} rare tokens")
        """
        chat_id_param = chat_id if self.config.perChatStats else None

        try:
            removed = await self.storage.cleanupRareTokens(min_count, chat_id_param)
            logger.info(f"Cleaned up rare tokens (min_count={min_count}).")
            return removed if removed is not None else 0
        except Exception as e:
            logger.error(f"Failed to cleanup rare tokens: {e}.")
            return 0

    def validate_config(self) -> List[str]:
        """Validate filter configuration.

        Checks all configuration parameters for validity, including the filter
        configuration and the tokenizer configuration.

        Returns:
            List of validation error messages. Empty list indicates all
            configurations are valid.

        Example:
            >>> errors = filter.validate_config()
            >>> if errors:
            ...     print("Configuration errors:")
            ...     for error in errors:
            ...         print(f"  - {error}")
            >>> else:
            ...     print("Configuration is valid")
        """
        errors = []

        # Validate tokenizer config
        tokenizer_errors = self.tokenizer.validate_config()
        errors.extend([f"Tokenizer: {error}" for error in tokenizer_errors])

        return errors
