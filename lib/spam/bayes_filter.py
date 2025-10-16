"""
Naive Bayes spam filter implementation, dood!

This module contains the main spam classification logic using the multinomial
Naive Bayes algorithm with Laplace smoothing.
"""

import math
import logging
from typing import Callable, List, Optional, Dict, Sequence, Tuple
from dataclasses import dataclass

from .storage_interface import BayesStorageInterface
from .tokenizer import MessageTokenizer, TokenizerConfig
from .models import SpamScore, BayesModelStats

logger = logging.getLogger(__name__)


@dataclass
class BayesConfig:
    """Configuration for Bayes filter"""

    # Laplace smoothing parameter (avoid zero probabilities)
    alpha: float = 1.0

    # Minimum token occurrences to consider for classification
    min_token_count: int = 2

    # Use per-chat statistics (True) or global (False)
    per_chat_stats: bool = True

    # Default spam threshold (0-100)
    default_threshold: float = 50.0

    # Minimum confidence to trust classification
    min_confidence: float = 0.1

    # Maximum tokens to consider per message (performance)
    max_tokens_per_message: int = 1000

    # Weight for combining with other spam detection methods
    bayes_weight: float = 0.5

    # Tokenizer configuration
    tokenizer_config: Optional[TokenizerConfig] = None

    # Enable debug logging
    debug_logging: bool = False

    def __post_init__(self):
        """Validate configuration parameters"""
        if self.alpha <= 0:
            raise ValueError("Alpha must be positive for Laplace smoothing.")

        if not (0 <= self.default_threshold <= 100):
            raise ValueError("Default threshold must be between 0 and 100.")

        if not (0 <= self.min_confidence <= 1):
            raise ValueError("Min confidence must be between 0 and 1.")

        if not (0 <= self.bayes_weight <= 1):
            raise ValueError("Bayes weight must be between 0 and 1.")

        if self.tokenizer_config is None:
            self.tokenizer_config = TokenizerConfig()


class NaiveBayesFilter:
    """
    Naive Bayes spam filter implementation

    Uses multinomial Naive Bayes algorithm with Laplace smoothing.
    Supports both global and per-chat learning.
    """

    def __init__(self, storage: BayesStorageInterface, config: Optional[BayesConfig] = None):
        """
        Initialize Bayes filter

        Args:
            storage: Storage interface implementation
            config: Filter configuration
        """
        self.storage = storage
        self.config = config or BayesConfig()
        self.tokenizer = MessageTokenizer(self.config.tokenizer_config)

        # Setup logging
        if self.config.debug_logging:
            logger.setLevel(logging.DEBUG)

        logger.info(f"Initialized NaiveBayesFilter with per_chat_stats={self.config.per_chat_stats}")

    async def classify(
        self, messageText: str, chatId: Optional[int] = None, threshold: Optional[float] = None
    ) -> SpamScore:
        """
        Classify a message as spam or ham

        Args:
            message_text: Text to classify
            chat_id: Optional chat ID for per-chat statistics
            threshold: Spam threshold (0-100), uses config default if None

        Returns:
            SpamScore with classification results
        """
        if threshold is None:
            threshold = self.config.default_threshold

        # Tokenize message
        tokens = self.tokenizer.tokenize(messageText)

        if not tokens:
            # No tokens, cannot classify
            logger.debug("No tokens found in message, returning neutral score.")
            return SpamScore(score=50.0, is_spam=False, confidence=0.0, token_scores={})

        # Limit tokens for performance
        if len(tokens) > self.config.max_tokens_per_message:
            logger.warning(f"Message has {len(tokens)} tokens, limiting to {self.config.max_tokens_per_message}.")
            tokens = tokens[: self.config.max_tokens_per_message]

        # Get chat ID parameter
        chat_id_param = chatId if self.config.per_chat_stats else None

        # Get class statistics
        try:
            spam_stats = await self.storage.getClassStats(True, chat_id_param)
            ham_stats = await self.storage.getClassStats(False, chat_id_param)
        except Exception as e:
            logger.error(f"Failed to get class stats: {e}.")
            return SpamScore(score=50.0, is_spam=False, confidence=0.0, token_scores={})

        # Check if we have training data
        total_messages = spam_stats.message_count + ham_stats.message_count
        if total_messages == 0:
            logger.debug("No training data available, returning neutral score.")
            return SpamScore(score=50.0, is_spam=False, confidence=0.0, token_scores={})

        # Calculate prior probabilities
        #p_spam = spam_stats.message_count / total_messages
        #p_ham = ham_stats.message_count / total_messages
        p_spam = 0.5
        p_ham = 0.5

        logger.debug(f"Prior probabilities: P(spam)={p_spam:.3f}, P(ham)={p_ham:.3f}.")

        # Calculate log probabilities (to avoid underflow)
        log_p_spam = math.log(p_spam)
        log_p_ham = math.log(p_ham)

        # Get vocabulary size for Laplace smoothing
        try:
            vocab_size = await self.storage.getVocabularySize(chat_id_param)
        except Exception as e:
            logger.error(f"Failed to get vocabulary size: {e}.")
            vocab_size = 1000  # Fallback estimate

        token_scores = {}
        known_tokens = 0

        # Calculate likelihood for each unique token
        unique_tokens = set(tokens)
        for token in unique_tokens:
            try:
                token_stats = await self.storage.getTokenStats(token, chat_id_param)
            except Exception as e:
                logger.error(f"Failed to get token stats for '{token}': {e}.")
                continue

            if token_stats is None or token_stats.total_count < self.config.min_token_count:
                # Unknown or rare token, skip
                logger.debug(
                    f"Skipping rare token '{token}' (count: {token_stats.total_count if token_stats else 0})."
                )
                continue

            known_tokens += 1

            # Count occurrences of this token in the message
            token_count = tokens.count(token)

            # Laplace smoothing: P(token|class) = (count + alpha) / (total + alpha * vocab_size)
            p_token_spam = (token_stats.spam_count + self.config.alpha) / (
                spam_stats.token_count + self.config.alpha * vocab_size
            )
            p_token_ham = (token_stats.ham_count + self.config.alpha) / (
                ham_stats.token_count + self.config.alpha * vocab_size
            )

            # Add to log probabilities (multiply by token count for frequency)
            log_p_spam += math.log(p_token_spam) * token_count
            log_p_ham += math.log(p_token_ham) * token_count

            # Store individual token contribution for debugging
            token_spam_prob = (p_token_spam / (p_token_spam + p_token_ham)) * 100
            token_scores[token] = token_spam_prob

            logger.debug(f"Token '{token}' (count: {token_count}): spam_prob={token_spam_prob:.1f}%.")

        # Convert log probabilities back to probabilities
        # Using log-sum-exp trick for numerical stability
        max_log_p = max(log_p_spam, log_p_ham)
        exp_spam = math.exp(log_p_spam - max_log_p)
        exp_ham = math.exp(log_p_ham - max_log_p)

        # Normalize to get probability
        spam_probability = exp_spam / (exp_spam + exp_ham)
        spam_score = spam_probability * 100

        # Calculate confidence based on number of known tokens and training data
        confidence = self._calculate_confidence(known_tokens, len(unique_tokens), total_messages)

        is_spam = spam_score >= threshold and confidence >= self.config.min_confidence

        logger.debug(
            f"Classification result: score={spam_score:.2f}%, confidence={confidence:.3f}, is_spam={is_spam}."
        )

        return SpamScore(score=spam_score, is_spam=is_spam, confidence=confidence, token_scores=token_scores)

    def _calculate_confidence(self, known_tokens: int, total_tokens: int, training_messages: int) -> float:
        """Calculate confidence in classification based on available data"""
        if total_tokens == 0:
            return 0.0

        # Token coverage: how many tokens we know about
        token_coverage = known_tokens / total_tokens

        # Training data factor: more training data = higher confidence
        training_factor = min(1.0, training_messages / 100)  # Cap at 100 messages

        # Combine factors
        confidence = (token_coverage * 0.7) + (training_factor * 0.3)

        return min(1.0, confidence)

    async def learnSpam(self, message_text: str, chatId: Optional[int] = None) -> bool:
        """
        Learn from a spam message

        Args:
            message_text: Spam message text
            chat_id: Optional chat ID for per-chat learning

        Returns:
            True if learning succeeded
        """
        return await self._learn(message_text, is_spam=True, chat_id=chatId)

    async def learnHam(self, messageText: str, chatId: Optional[int] = None) -> bool:
        """
        Learn from a ham (non-spam) message

        Args:
            message_text: Ham message text
            chat_id: Optional chat ID for per-chat learning

        Returns:
            True if learning succeeded
        """
        return await self._learn(messageText, is_spam=False, chat_id=chatId)

    async def _learn(self, message_text: str, is_spam: bool, chat_id: Optional[int] = None) -> bool:
        """
        Internal learning method

        Args:
            message_text: Message text to learn from
            is_spam: True if spam, False if ham
            chat_id: Optional chat ID

        Returns:
            True if learning succeeded
        """
        # Tokenize message
        tokens = self.tokenizer.tokenize(message_text)

        if not tokens:
            logger.warning("No tokens found in training message, skipping.")
            return False

        chat_id_param = chat_id if self.config.per_chat_stats else None

        try:
            # Update class statistics
            await self.storage.updateClassStats(
                is_spam=is_spam, message_increment=1, token_increment=len(tokens), chat_id=chat_id_param
            )

            # Batch update token statistics for performance
            token_updates = []
            token_counts = {}

            # Count token frequencies
            for token in tokens:
                token_counts[token] = token_counts.get(token, 0) + 1

            # Prepare batch updates
            for token, count in token_counts.items():
                token_updates.append({"token": token, "is_spam": is_spam, "increment": count})

            # Perform batch update
            success = await self.storage.batchUpdateTokens(token_updates, chat_id_param)

            if success:
                class_name = "spam" if is_spam else "ham"
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
        """
        Learn from multiple messages in batch

        Args:
            messages: List of (text, is_spam, chat_id) tuples
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with learning statistics
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
        """
        Get information about the current model

        Args:
            chat_id: Optional chat ID for per-chat stats

        Returns:
            BayesModelStats with model information
        """
        chat_id_param = chat_id if self.config.per_chat_stats else None

        try:
            return await self.storage.getModelStats(chat_id_param)
        except Exception as e:
            logger.error(f"Failed to get model info: {e}.")
            # Return empty stats as fallback
            return BayesModelStats(
                total_spam_messages=0, total_ham_messages=0, total_tokens=0, vocabulary_size=0, chat_id=chat_id_param
            )

    async def reset(self, chat_id: Optional[int] = None) -> bool:
        """
        Reset all learned statistics

        Args:
            chat_id: Optional chat ID to reset (None = reset all)

        Returns:
            True if reset succeeded
        """
        chat_id_param = chat_id if self.config.per_chat_stats else None

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
        """
        Remove rarely occurring tokens to improve performance

        Args:
            min_count: Minimum total count to keep a token
            chat_id: Optional chat ID for per-chat cleanup

        Returns:
            Number of tokens removed
        """
        chat_id_param = chat_id if self.config.per_chat_stats else None

        try:
            removed = await self.storage.cleanupRareTokens(min_count, chat_id_param)
            logger.info(f"Cleaned up {removed} rare tokens (min_count={min_count}).")
            return removed
        except Exception as e:
            logger.error(f"Failed to cleanup rare tokens: {e}.")
            return 0

    def validate_config(self) -> List[str]:
        """
        Validate filter configuration

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Validate tokenizer config
        tokenizer_errors = self.tokenizer.validate_config()
        errors.extend([f"Tokenizer: {error}" for error in tokenizer_errors])

        return errors
