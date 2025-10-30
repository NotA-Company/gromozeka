"""
Spam Detection Library for Gromozeka Bot

This library provides a Naive Bayes filter implementation for spam detection
with support for both per-chat and global learning, dood!

Main Components:
- BayesFilter: Main spam classification engine
- TokenStats, ClassStats: Data models for statistics
- BayesStorageInterface: Abstract storage interface
- MessageTokenizer: Text preprocessing and tokenization
- DatabaseBayesStorage: Database implementation of storage interface

Usage:
    from lib.spam import NaiveBayesFilter, BayesConfig
    from lib.spam.database_storage import DatabaseBayesStorage

    # Initialize
    storage = DatabaseBayesStorage(database)
    bayes_filter = NaiveBayesFilter(storage)

    # Classify message
    result = await bayes_filter.classify("Buy cheap products now!")
    print(f"Spam score: {result.score:.2f}%")

    # Learn from examples
    await bayes_filter.learn_spam("Buy cheap products now!")
    await bayes_filter.learn_ham("Hey, how are you doing?")
"""

from .bayes_filter import BayesConfig, NaiveBayesFilter, SpamScore
from .models import ClassStats, TokenStats
from .storage_interface import BayesStorageInterface
from .tokenizer import MessageTokenizer, TokenizerConfig

__version__ = "1.0.0"
__author__ = "Gromozeka Bot Team (Prinny style, dood!)"

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
