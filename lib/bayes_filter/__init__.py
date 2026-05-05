"""Bayes Filter Library for Gromozeka Bot.

This library provides a comprehensive Naive Bayes spam filter implementation
for the Gromozeka bot system. It supports both per-chat and global learning
modes, allowing for personalized spam detection across different conversations.

The library implements the multinomial Naive Bayes algorithm with Laplace
smoothing to handle unseen tokens and prevent zero probabilities. It includes
configurable tokenization, flexible storage backends, and detailed classification
results with confidence scores.

Main Components:
    - NaiveBayesFilter: Main spam classification engine with learning capabilities
    - BayesConfig: Configuration class for filter behavior and parameters
    - SpamScore: Classification result with score, confidence, and token contributions
    - MessageTokenizer: Text preprocessing and tokenization with multiple options
    - TokenizerConfig: Configuration for tokenization behavior
    - BayesStorageInterface: Abstract storage interface for backend implementations
    - TokenStats: Statistics for individual tokens (spam/ham counts)
    - ClassStats: Statistics for message classes (spam/ham)

Features:
    - Per-chat and global learning modes
    - Configurable Laplace smoothing parameter
    - Support for unigrams, bigrams, and trigrams
    - Multi-language support (Russian and English)
    - Confidence-based classification
    - Detailed token-level scoring
    - Flexible storage interface for different backends

Example:
    >>> from lib.bayes_filter import NaiveBayesFilter, BayesConfig
    >>> from lib.bayes_filter.storage_interface import BayesStorageInterface
    >>>
    >>> # Initialize with storage backend
    >>> storage = BayesStorageInterface()  # Use concrete implementation
    >>> config = BayesConfig(perChatStats=True, defaultThreshold=70.0)
    >>> bayes_filter = NaiveBayesFilter(storage, config)
    >>>
    >>> # Classify a message
    >>> result = await bayes_filter.classify("Buy cheap products now!", chatId=123)
    >>> print(f"Spam score: {result.score:.2f}%")
    >>> print(f"Is spam: {result.isSpam}")
    >>> print(f"Confidence: {result.confidence:.2f}")
    >>>
    >>> # Learn from examples
    >>> await bayes_filter.learn_spam("Buy cheap products now!", chatId=123)
    >>> await bayes_filter.learn_ham("Hey, how are you doing?", chatId=123)

Module Attributes:
    __version__: Library version string
    __author__: Library author information
"""

from .bayes_filter import BayesConfig, NaiveBayesFilter, SpamScore
from .models import ClassStats, TokenStats
from .storage_interface import BayesStorageInterface
from .tokenizer import MessageTokenizer, TokenizerConfig

__version__ = "1.0.0"
"""Version of the Bayes filter library."""

__author__ = "Gromozeka Bot Team (Prinny style, dood!)"
"""Author information for the Bayes filter library."""

__all__ = [
    # Main classes
    "NaiveBayesFilter",
    "BayesConfig",
    "SpamScore",
    # Tokenizer
    "MessageTokenizer",
    "TokenizerConfig",
    # Storage interface
    "BayesStorageInterface",
    # Data models
    "TokenStats",
    "ClassStats",
]
