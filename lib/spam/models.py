"""
Data models and types for Bayes spam filter, dood!

This module defines the core data structures used throughout the spam detection library.
"""

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class SpamClassification(Enum):
    """Classification results for spam detection"""

    SPAM = "spam"
    HAM = "ham"
    UNKNOWN = "unknown"


@dataclass
class TokenStats:
    """Statistics for a single token in the Bayes filter"""

    token: str
    spamCount: int  # Occurrences in spam messages
    hamCount: int  # Occurrences in ham messages
    totalCount: int  # Total occurrences

    def __post_init__(self):
        """Validate token statistics consistency"""
        if self.totalCount != self.spamCount + self.hamCount:
            self.totalCount = self.spamCount + self.hamCount


@dataclass
class ClassStats:
    """Statistics for a message class (spam/ham)"""

    message_count: int  # Total messages in this class
    token_count: int  # Total tokens in this class

    def __post_init__(self):
        """Validate class statistics"""
        if self.message_count < 0:
            self.message_count = 0
        if self.token_count < 0:
            self.token_count = 0


@dataclass
class SpamScore:
    """Result of spam classification"""

    score: float  # Probability of spam (0-100)
    is_spam: bool  # True if score > threshold
    confidence: float  # Confidence in prediction (0-1)
    token_scores: Dict[str, float]  # Individual token contributions
    classification: SpamClassification = SpamClassification.UNKNOWN

    def __post_init__(self):
        """Set classification based on is_spam flag"""
        if self.is_spam:
            self.classification = SpamClassification.SPAM
        elif self.score < 50.0:  # If not spam and score is low, it's ham
            self.classification = SpamClassification.HAM
        else:
            self.classification = SpamClassification.UNKNOWN

        # Ensure score is within valid range
        self.score = max(0.0, min(100.0, self.score))

        # Ensure confidence is within valid range
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class BayesTrainingExample:
    """Training example for the Bayes filter"""

    text: str
    is_spam: bool
    chat_id: Optional[int] = None
    weight: float = 1.0  # Weight for this training example

    def __post_init__(self):
        """Validate training example"""
        if not self.text or not self.text.strip():
            raise ValueError("Training text cannot be empty, dood!")
        if self.weight <= 0:
            raise ValueError("Training weight must be positive, dood!")


@dataclass
class BayesModelStats:
    """Overall statistics for the Bayes model"""

    total_spam_messages: int
    total_ham_messages: int
    total_tokens: int
    vocabulary_size: int
    chat_id: Optional[int] = None

    @property
    def total_messages(self) -> int:
        """Total number of training messages"""
        return self.total_spam_messages + self.total_ham_messages

    @property
    def spam_ratio(self) -> float:
        """Ratio of spam messages to total messages"""
        if self.total_messages == 0:
            return 0.0
        return self.total_spam_messages / self.total_messages

    @property
    def ham_ratio(self) -> float:
        """Ratio of ham messages to total messages"""
        if self.total_messages == 0:
            return 0.0
        return self.total_ham_messages / self.total_messages
