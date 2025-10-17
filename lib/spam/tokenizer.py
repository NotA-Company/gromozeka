"""
Text tokenization and preprocessing for Bayes spam filter, dood!

This module handles converting raw message text into tokens that can be analyzed
by the Bayes filter. It includes various preprocessing options and supports
both Russian and English text.
"""

import re
from typing import List, Set, Dict, Optional
from dataclasses import dataclass


@dataclass
class TokenizerConfig:
    """Configuration for message tokenizer"""

    min_token_length: int = 2
    max_token_length: int = 50
    lowercase: bool = True
    remove_urls: bool = True
    remove_mentions: bool = True
    remove_numbers: bool = False
    remove_emoji: bool = False
    use_bigrams: bool = True  # Include word pairs
    use_trigrams: bool = False  # Include word triplets
    stopwords: Optional[Set[str]] = None  # Words to ignore
    preserve_punctuation: bool = False  # Keep punctuation as tokens
    normalize_whitespace: bool = True  # Normalize multiple spaces

    def __post_init__(self):
        """Initialize default stopwords if not provided"""
        if self.stopwords is None:
            self.stopwords = self._get_default_stopwords()

    def getStopwords(self) -> Set[str]:
        """Get stopwords"""
        if self.stopwords is None:
            self.__post_init__()
            return self._get_default_stopwords()
        return self.stopwords

    def _get_default_stopwords(self) -> Set[str]:
        """Get default Russian and English stopwords"""
        return {
            # Russian common words
            "и",
            "в",
            "не",
            "на",
            "я",
            "что",
            "с",
            "а",
            "как",
            "это",
            "он",
            "она",
            "они",
            "мы",
            "вы",
            "ты",
            "к",
            "по",
            "из",
            "за",
            "от",
            "до",
            "при",
            "для",
            "или",
            "но",
            "да",
            "нет",
            "все",
            "так",
            "уже",
            "еще",
            "там",
            "тут",
            "где",
            "когда",
            "если",
            # English common words
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
        }


class MessageTokenizer:
    """
    Tokenizes messages for Bayes filter analysis

    This tokenizer converts raw message text into a list of tokens that can be
    analyzed by the Bayes filter. It supports various preprocessing options
    and handles both Russian and English text.
    """

    def __init__(self, config: Optional[TokenizerConfig] = None):
        """
        Initialize tokenizer with configuration

        Args:
            config: TokenizerConfig object, uses defaults if None
        """
        self.config = config or TokenizerConfig()

        # Compile regex patterns for better performance
        self._url_pattern = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+")
        self._mention_pattern = re.compile(r"@\w+")
        self._number_pattern = re.compile(r"\d+")
        self._emoji_pattern = re.compile(
            r"[\U0001F600-\U0001F64F]|"  # emoticons
            r"[\U0001F300-\U0001F5FF]|"  # symbols & pictographs
            r"[\U0001F680-\U0001F6FF]|"  # transport & map symbols
            r"[\U0001F1E0-\U0001F1FF]|"  # flags (iOS)
            r"[\U00002702-\U000027B0]|"  # dingbats
            r"[\U000024C2-\U0001F251]"  # enclosed characters
        )
        self._word_pattern = re.compile(r"\b\w+\b")
        self._whitespace_pattern = re.compile(r"\s+")

    def tokenize(self, text: str, ignoreTrigrams: bool = False) -> List[str]:
        """
        Convert text into list of tokens

        Args:
            text: Message text to tokenize

        Returns:
            List of tokens (words, bigrams, etc.)
        """
        if not text or not text.strip():
            return []

        # Preprocessing
        processed_text = self._preprocess_text(text)

        # Extract words
        words = self._extract_words(processed_text)

        # Filter words
        filtered_words = self._filter_words(words)

        # Generate n-grams
        tokens = self._generate_ngrams(filtered_words, ignoreTrigrams=ignoreTrigrams)

        return tokens

    def _preprocess_text(self, text: str) -> str:
        """Apply text preprocessing based on configuration"""
        processed = text

        if self.config.remove_urls:
            processed = self._url_pattern.sub("", processed)

        if self.config.remove_mentions:
            processed = self._mention_pattern.sub("", processed)

        if self.config.remove_numbers:
            processed = self._number_pattern.sub("", processed)

        if self.config.remove_emoji:
            processed = self._emoji_pattern.sub("", processed)

        if self.config.normalize_whitespace:
            processed = self._whitespace_pattern.sub(" ", processed)

        if self.config.lowercase:
            processed = processed.lower()

        return processed.strip()

    def _extract_words(self, text: str) -> List[str]:
        """Extract words from preprocessed text"""
        if self.config.preserve_punctuation:
            # Split on whitespace to preserve punctuation
            words = text.split()
        else:
            # Extract only word characters
            words = self._word_pattern.findall(text)

        return words

    def _filter_words(self, words: List[str]) -> List[str]:
        """Filter words based on length and stopwords"""
        filtered = []

        for word in words:
            # Check length
            if not (self.config.min_token_length <= len(word) <= self.config.max_token_length):
                continue

            # Check stopwords
            if word.lower() in self.config.getStopwords():
                continue

            filtered.append(word)

        return filtered

    def _generate_ngrams(self, words: List[str], ignoreTrigrams: bool = False) -> List[str]:
        """Generate n-grams from filtered words"""
        tokens = words.copy()  # Start with unigrams

        # Add bigrams if enabled
        if self.config.use_bigrams and len(words) > 1:
            bigrams = [f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1)]
            tokens.extend(bigrams)

        # Add trigrams if enabled
        if self.config.use_trigrams and not ignoreTrigrams and len(words) > 2:
            trigrams = [f"{words[i]}_{words[i + 1]}_{words[i + 2]}" for i in range(len(words) - 2)]
            tokens.extend(trigrams)

        return tokens

    def get_token_stats(self, text: str) -> Dict[str, int]:
        """
        Get token frequency statistics for a text

        Args:
            text: Text to analyze

        Returns:
            Dictionary mapping tokens to their frequencies
        """
        tokens = self.tokenize(text)
        stats = {}

        for token in tokens:
            stats[token] = stats.get(token, 0) + 1

        return stats

    def get_unique_tokens(self, text: str) -> Set[str]:
        """
        Get unique tokens from text

        Args:
            text: Text to analyze

        Returns:
            Set of unique tokens
        """
        return set(self.tokenize(text))

    def preprocess_for_display(self, text: str) -> str:
        """
        Preprocess text for display purposes (without tokenization)

        Args:
            text: Text to preprocess

        Returns:
            Preprocessed text suitable for display
        """
        return self._preprocess_text(text)

    def estimate_spam_indicators(self, text: str) -> Dict[str, float]:
        """
        Estimate potential spam indicators in text

        Args:
            text: Text to analyze

        Returns:
            Dictionary with spam indicator scores
        """
        indicators = {
            "url_count": len(self._url_pattern.findall(text)),
            "mention_count": len(self._mention_pattern.findall(text)),
            "number_count": len(self._number_pattern.findall(text)),
            "emoji_count": len(self._emoji_pattern.findall(text)),
            "caps_ratio": self._calculate_caps_ratio(text),
            "exclamation_count": text.count("!"),
            "question_count": text.count("?"),
            "length": len(text),
            "word_count": len(text.split()),
        }

        return indicators

    def _calculate_caps_ratio(self, text: str) -> float:
        """Calculate ratio of uppercase letters to total letters"""
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return 0.0

        caps = [c for c in letters if c.isupper()]
        return len(caps) / len(letters)

    def validate_config(self) -> List[str]:
        """
        Validate tokenizer configuration

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if self.config.min_token_length < 1:
            errors.append("min_token_length must be at least 1")

        if self.config.max_token_length < self.config.min_token_length:
            errors.append("max_token_length must be >= min_token_length")

        if self.config.max_token_length > 100:
            errors.append("max_token_length should not exceed 100 for performance")

        return errors
