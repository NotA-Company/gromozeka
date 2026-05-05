"""Data models and types for Bayes spam filter.

This module defines the core data structures used throughout the spam detection
library. It includes enums for classification results, dataclasses for token and
class statistics, spam scoring results, training examples, and overall model
statistics.

Classes:
    SpamClassification: Enum for spam detection classification results.
    TokenStats: Statistics for a single token in the Bayes filter.
    ClassStats: Statistics for a message class (spam/ham).
    SpamScore: Result of spam classification with detailed metrics.
    BayesTrainingExample: Training example for the Bayes filter.
    BayesModelStats: Overall statistics for the Bayes model.

Example:
    >>> from lib.bayes_filter.models import SpamScore, SpamClassification
    >>> score = SpamScore(
    ...     score=85.5,
    ...     isSpam=True,
    ...     confidence=0.92,
    ...     tokenScores={"free": 0.95, "money": 0.88}
    ... )
    >>> print(score.classification)
    SpamClassification.SPAM
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class SpamClassification(Enum):
    """Classification results for spam detection.

    This enum defines the possible outcomes of spam classification:
    - SPAM: Message is classified as spam
    - HAM: Message is classified as legitimate (not spam)
    - UNKNOWN: Classification is uncertain or indeterminate

    Attributes:
        SPAM: Message is spam.
        HAM: Message is legitimate.
        UNKNOWN: Classification is uncertain.
    """

    SPAM = "spam"
    HAM = "ham"
    UNKNOWN = "unknown"


@dataclass
class TokenStats:
    """Statistics for a single token in the Bayes filter.

    This dataclass tracks how often a specific token appears in spam and ham
    messages, which is used to calculate the token's spam probability.

    Attributes:
        token: The token string (e.g., a word or phrase).
        spamCount: Number of occurrences in spam messages.
        hamCount: Number of occurrences in ham messages.
        totalCount: Total occurrences across all messages.

    Example:
        >>> stats = TokenStats(token="free", spamCount=50, hamCount=5, totalCount=55)
        >>> print(stats.spamCount)
        50
    """

    token: str
    spamCount: int
    """Occurrences in spam messages."""
    hamCount: int
    """Occurrences in ham messages"""
    totalCount: int
    """Total occurrences"""

    def __post_init__(self) -> None:
        """Validate and correct token statistics consistency.

        Ensures that totalCount equals the sum of spamCount and hamCount.
        If they don't match, totalCount is automatically corrected.

        Raises:
            ValueError: If spamCount or hamCount are negative.
        """
        if self.spamCount < 0:
            raise ValueError("spamCount cannot be negative")
        if self.hamCount < 0:
            raise ValueError("hamCount cannot be negative")
        if self.totalCount != self.spamCount + self.hamCount:
            self.totalCount = self.spamCount + self.hamCount


@dataclass
class ClassStats:
    """Statistics for a message class (spam/ham).

    This dataclass tracks aggregate statistics for a specific message class,
    including the total number of messages and tokens in that class.

    Attributes:
        message_count: Total number of messages in this class.
        token_count: Total number of tokens across all messages in this class.

    Example:
        >>> stats = ClassStats(message_count=100, token_count=5000)
        >>> print(stats.message_count)
        100
    """

    message_count: int
    """Total messages in this class"""
    token_count: int
    """Total tokens in this class"""

    def __post_init__(self) -> None:
        """Validate and correct class statistics.

        Ensures that message_count and token_count are non-negative.
        If they are negative, they are automatically set to zero.

        Raises:
            ValueError: If message_count or token_count are negative.
        """
        if self.message_count < 0:
            raise ValueError("message_count cannot be negative")
        if self.token_count < 0:
            raise ValueError("token_count cannot be negative")


@dataclass
class SpamScore:
    """Result of spam classification with detailed metrics.

    This dataclass contains the complete result of spam classification, including
    the spam probability score, classification decision, confidence level, and
    individual token contributions.

    Attributes:
        score: Probability of spam as a percentage (0-100).
        isSpam: True if the message is classified as spam.
        confidence: Confidence in the prediction (0-1).
        tokenScores: Dictionary mapping tokens to their spam probabilities.
        classification: The final classification result.

    Example:
        >>> score = SpamScore(
        ...     score=85.5,
        ...     isSpam=True,
        ...     confidence=0.92,
        ...     tokenScores={"free": 0.95, "money": 0.88}
        ... )
        >>> print(score.classification)
        SpamClassification.SPAM
    """

    score: float
    """Probability of spam (0-100)"""
    isSpam: bool
    """True if score > threshold"""
    confidence: float
    """Confidence in prediction (0-1)"""
    tokenScores: Dict[str, float]
    """Individual token contributions"""
    classification: SpamClassification = SpamClassification.UNKNOWN

    def __post_init__(self) -> None:
        """Initialize classification and validate score ranges.

        Sets the classification based on the isSpam flag and score value.
        Ensures that score is within [0, 100] and confidence is within [0, 1].

        Raises:
            ValueError: If score or confidence are outside valid ranges.
        """
        if self.isSpam:
            self.classification = SpamClassification.SPAM
        elif self.score < 50.0:
            self.classification = SpamClassification.HAM
        else:
            self.classification = SpamClassification.UNKNOWN

        # Ensure score is within valid range
        if not 0.0 <= self.score <= 100.0:
            self.score = max(0.0, min(100.0, self.score))

        # Ensure confidence is within valid range
        if not 0.0 <= self.confidence <= 1.0:
            self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class BayesTrainingExample:
    """Training example for the Bayes filter.

    This dataclass represents a single training example used to train the
    Bayes spam filter. Each example consists of text content and its known
    classification (spam or ham).

    Attributes:
        text: The text content of the training example.
        is_spam: True if this is a spam example, False for ham.
        chat_id: Optional chat ID for context-specific training.
        weight: Weight for this training example (default: 1.0).

    Raises:
        ValueError: If text is empty or weight is not positive.

    Example:
        >>> example = BayesTrainingExample(
        ...     text="Free money now!",
        ...     is_spam=True,
        ...     weight=2.0
        ... )
        >>> print(example.is_spam)
        True
    """

    text: str
    is_spam: bool
    chat_id: Optional[int] = None
    weight: float = 1.0
    """Weight for this training example"""

    def __post_init__(self) -> None:
        """Validate training example data.

        Ensures that text is not empty and weight is positive.

        Raises:
            ValueError: If text is empty or contains only whitespace.
            ValueError: If weight is not positive.
        """
        if not self.text or not self.text.strip():
            raise ValueError("Training text cannot be empty, dood!")
        if self.weight <= 0:
            raise ValueError("Training weight must be positive, dood!")


@dataclass
class BayesModelStats:
    """Overall statistics for the Bayes model.

    This dataclass provides aggregate statistics about the trained Bayes model,
    including message counts, token counts, vocabulary size, and derived ratios.

    Attributes:
        total_spam_messages: Total number of spam messages used for training.
        total_ham_messages: Total number of ham messages used for training.
        total_tokens: Total number of tokens across all training messages.
        vocabulary_size: Number of unique tokens in the vocabulary.
        chat_id: Optional chat ID for context-specific statistics.

    Example:
        >>> stats = BayesModelStats(
        ...     total_spam_messages=100,
        ...     total_ham_messages=500,
        ...     total_tokens=10000,
        ...     vocabulary_size=2000
        ... )
        >>> print(stats.spam_ratio)
        0.16666666666666666
    """

    total_spam_messages: int
    total_ham_messages: int
    total_tokens: int
    vocabulary_size: int
    chat_id: Optional[int] = None

    @property
    def total_messages(self) -> int:
        """Total number of training messages.

        Returns:
            The sum of spam and ham messages.

        Example:
            >>> stats = BayesModelStats(100, 500, 10000, 2000)
            >>> stats.total_messages
            600
        """
        return self.total_spam_messages + self.total_ham_messages

    @property
    def spam_ratio(self) -> float:
        """Ratio of spam messages to total messages.

        Returns:
            The proportion of spam messages (0.0 to 1.0). Returns 0.0 if
            there are no messages.

        Example:
            >>> stats = BayesModelStats(100, 500, 10000, 2000)
            >>> stats.spam_ratio
            0.16666666666666666
        """
        if self.total_messages == 0:
            return 0.0
        return self.total_spam_messages / self.total_messages

    @property
    def ham_ratio(self) -> float:
        """Ratio of ham messages to total messages.

        Returns:
            The proportion of ham messages (0.0 to 1.0). Returns 0.0 if
            there are no messages.

        Example:
            >>> stats = BayesModelStats(100, 500, 10000, 2000)
            >>> stats.ham_ratio
            0.8333333333333334
        """
        if self.total_messages == 0:
            return 0.0
        return self.total_ham_messages / self.total_messages
