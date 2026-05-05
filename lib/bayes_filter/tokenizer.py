"""Text tokenization and preprocessing for Bayes spam filter.

This module provides functionality for converting raw message text into tokens
that can be analyzed by the Bayes filter. It includes various preprocessing
options such as URL removal, mention filtering, stopword filtering, and n-gram
generation. The module supports both Russian and English text processing.

Classes:
    TokenizerConfig: Configuration settings for the tokenizer.
    MessageTokenizer: Main tokenizer class for processing messages.

Example:
    >>> config = TokenizerConfig(min_token_length=3, use_bigrams=True)
    >>> tokenizer = MessageTokenizer(config)
    >>> tokens = tokenizer.tokenize("Hello world! This is a test.")
    >>> print(tokens)
    ['hello', 'world', 'test', 'hello_world', 'world_this', 'this_is', 'is_a', 'a_test']
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set


@dataclass
class TokenizerConfig:
    """Configuration settings for message tokenizer.

    This dataclass defines all configurable parameters for the MessageTokenizer,
    including token length constraints, preprocessing options, n-gram generation
    settings, and stopword lists.

    Attributes:
        min_token_length: Minimum length for tokens to be included. Defaults to 2.
        max_token_length: Maximum length for tokens to be included. Defaults to 50.
        lowercase: Whether to convert all text to lowercase. Defaults to True.
        remove_urls: Whether to remove URLs from text. Defaults to True.
        remove_mentions: Whether to remove @mentions from text. Defaults to True.
        remove_numbers: Whether to remove numeric tokens. Defaults to False.
        remove_emoji: Whether to remove emoji characters. Defaults to False.
        use_bigrams: Whether to generate word pairs (2-grams). Defaults to True.
        use_trigrams: Whether to generate word triplets (3-grams). Defaults to False.
        stopwords: Set of words to ignore during tokenization. Defaults to None,
            which triggers use of default Russian and English stopwords.
        preserve_punctuation: Whether to keep punctuation as separate tokens.
            Defaults to False.
        normalize_whitespace: Whether to normalize multiple spaces to single space.
            Defaults to True.

    Example:
        >>> config = TokenizerConfig(min_token_length=3, use_bigrams=True)
        >>> tokenizer = MessageTokenizer(config)
    """

    min_token_length: int = 2
    max_token_length: int = 50
    lowercase: bool = True
    remove_urls: bool = True
    remove_mentions: bool = True
    remove_numbers: bool = False
    remove_emoji: bool = False
    use_bigrams: bool = True
    use_trigrams: bool = False
    stopwords: Optional[Set[str]] = None
    preserve_punctuation: bool = False
    normalize_whitespace: bool = True

    def __post_init__(self) -> None:
        """Initialize default stopwords if not provided.

        This method is automatically called after the dataclass is initialized.
        It sets the stopwords to the default Russian and English stopwords if
        no custom stopwords were provided.
        """
        if self.stopwords is None:
            self.stopwords = self._get_default_stopwords()

    def getStopwords(self) -> Set[str]:
        """Get the current set of stopwords.

        Returns:
            Set of stopwords to filter out during tokenization. If stopwords
            were not explicitly set, returns the default Russian and English
            stopwords.

        Example:
            >>> config = TokenizerConfig()
            >>> stopwords = config.getStopwords()
            >>> len(stopwords)
            87
        """
        if self.stopwords is None:
            self.__post_init__()
            return self._get_default_stopwords()
        return self.stopwords

    def _get_default_stopwords(self) -> Set[str]:
        """Get default Russian and English stopwords.

        Returns:
            Set of common Russian and English words that should be filtered out
            during tokenization. Includes pronouns, prepositions, conjunctions,
            and other high-frequency words that provide little semantic value.

        The default set includes:
            - Russian: и, в, не, на, я, что, с, а, как, это, etc.
            - English: the, a, an, and, or, but, in, on, at, to, etc.
        """
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
            "чтобы",
            "кто",
            "кто_то",
            "кто-то",
            "мне",
            "тоже",
            "то",
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
    """Tokenizes messages for Bayes filter analysis.

    This tokenizer converts raw message text into a list of tokens that can be
    analyzed by the Bayes filter. It supports various preprocessing options
    including URL removal, mention filtering, stopword filtering, and n-gram
    generation. The tokenizer handles both Russian and English text.

    Attributes:
        config: TokenizerConfig object containing all configuration settings.
        _url_pattern: Compiled regex pattern for matching URLs.
        _mention_pattern: Compiled regex pattern for matching @mentions.
        _number_pattern: Compiled regex pattern for matching numbers.
        _emoji_pattern: Compiled regex pattern for matching emoji characters.
        _word_pattern: Compiled regex pattern for matching word characters.
        _whitespace_pattern: Compiled regex pattern for matching whitespace.

    Example:
        >>> config = TokenizerConfig(min_token_length=3, use_bigrams=True)
        >>> tokenizer = MessageTokenizer(config)
        >>> tokens = tokenizer.tokenize("Hello world! This is a test.")
        >>> print(tokens)
        ['hello', 'world', 'test', 'hello_world', 'world_this', 'this_is', 'is_a', 'a_test']
    """

    def __init__(self, config: Optional[TokenizerConfig] = None) -> None:
        """Initialize tokenizer with configuration.

        Args:
            config: TokenizerConfig object containing tokenizer settings. If None,
                uses default configuration.

        Raises:
            TypeError: If config is not None and not a TokenizerConfig instance.
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
        """Convert text into list of tokens.

        This method applies preprocessing, extracts words, filters them based on
        configuration, and generates n-grams if enabled.

        Args:
            text: Message text to tokenize.
            ignoreTrigrams: If True, skip trigram generation even if enabled in
                config. Useful for performance optimization. Defaults to False.

        Returns:
            List of tokens including unigrams, bigrams (if enabled), and trigrams
            (if enabled and not ignored). Returns empty list if text is empty or
            contains only whitespace.

        Example:
            >>> tokenizer = MessageTokenizer()
            >>> tokens = tokenizer.tokenize("Hello world!")
            >>> print(tokens)
            ['hello', 'world', 'hello_world']
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
        """Apply text preprocessing based on configuration.

        This method applies various preprocessing steps to the input text based on
        the tokenizer configuration, including URL removal, mention filtering,
        number removal, emoji removal, whitespace normalization, and case conversion.

        Args:
            text: Raw text to preprocess.

        Returns:
            Preprocessed text with unwanted elements removed and normalized.
        """
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
        """Extract words from preprocessed text.

        This method extracts words from the preprocessed text. The extraction
        method depends on the preserve_punctuation configuration option.

        Args:
            text: Preprocessed text to extract words from.

        Returns:
            List of extracted words. If preserve_punctuation is True, splits on
            whitespace to preserve punctuation. Otherwise, extracts only word
            characters using regex.
        """
        if self.config.preserve_punctuation:
            # Split on whitespace to preserve punctuation
            words = text.split()
        else:
            # Extract only word characters
            words = self._word_pattern.findall(text)

        return words

    def _filter_words(self, words: List[str]) -> List[str]:
        """Filter words based on length and stopwords.

        This method filters the list of words based on the minimum and maximum
        token length configuration and removes any stopwords.

        Args:
            words: List of words to filter.

        Returns:
            Filtered list of words that meet the length criteria and are not
            stopwords.
        """
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
        """Generate n-grams from filtered words.

        This method generates unigrams, bigrams, and optionally trigrams from the
        filtered word list based on the tokenizer configuration.

        Args:
            words: List of filtered words to generate n-grams from.
            ignoreTrigrams: If True, skip trigram generation even if enabled in
                config. Defaults to False.

        Returns:
            List of tokens including unigrams, bigrams (if enabled), and trigrams
            (if enabled and not ignored). N-grams are joined with underscores.
        """
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
        """Get token frequency statistics for a text.

        This method tokenizes the text and calculates the frequency of each token.

        Args:
            text: Text to analyze.

        Returns:
            Dictionary mapping tokens to their frequencies. Tokens that appear
            multiple times will have higher values.

        Example:
            >>> tokenizer = MessageTokenizer()
            >>> stats = tokenizer.get_token_stats("hello world hello")
            >>> print(stats)
            {'hello': 2, 'world': 1, 'hello_world': 1, 'world_hello': 1}
        """
        tokens = self.tokenize(text)
        stats = {}

        for token in tokens:
            stats[token] = stats.get(token, 0) + 1

        return stats

    def get_unique_tokens(self, text: str) -> Set[str]:
        """Get unique tokens from text.

        This method tokenizes the text and returns only the unique tokens.

        Args:
            text: Text to analyze.

        Returns:
            Set of unique tokens. Duplicates are removed.

        Example:
            >>> tokenizer = MessageTokenizer()
            >>> tokens = tokenizer.get_unique_tokens("hello world hello")
            >>> print(tokens)
            {'hello', 'world', 'hello_world', 'world_hello'}
        """
        return set(self.tokenize(text))

    def preprocess_for_display(self, text: str) -> str:
        """Preprocess text for display purposes (without tokenization).

        This method applies preprocessing to the text but does not perform
        tokenization. Useful for displaying cleaned text to users.

        Args:
            text: Text to preprocess.

        Returns:
            Preprocessed text suitable for display, with URLs, mentions, numbers,
            and emoji removed (if configured), and whitespace normalized.

        Example:
            >>> tokenizer = MessageTokenizer()
            >>> cleaned = tokenizer.preprocess_for_display("Hello @user! Check https://example.com")
            >>> print(cleaned)
            hello ! check
        """
        return self._preprocess_text(text)

    def estimate_spam_indicators(self, text: str) -> Dict[str, float]:
        """Estimate potential spam indicators in text.

        This method analyzes the text and calculates various metrics that may
        indicate spam content, such as URL count, mention count, capitalization
        ratio, and punctuation usage.

        Args:
            text: Text to analyze.

        Returns:
            Dictionary with spam indicator scores including:
                - url_count: Number of URLs found in text.
                - mention_count: Number of @mentions found in text.
                - number_count: Number of numeric sequences found in text.
                - emoji_count: Number of emoji characters found in text.
                - caps_ratio: Ratio of uppercase letters to total letters (0.0-1.0).
                - exclamation_count: Number of exclamation marks.
                - question_count: Number of question marks.
                - length: Total length of text in characters.
                - word_count: Number of words in text.

        Example:
            >>> tokenizer = MessageTokenizer()
            >>> indicators = tokenizer.estimate_spam_indicators("CLICK HERE NOW!!!")
            >>> print(indicators['exclamation_count'])
            3
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
        """Calculate ratio of uppercase letters to total letters.

        This helper method calculates the proportion of uppercase letters in
        the text, which can be an indicator of spam or aggressive messaging.

        Args:
            text: Text to analyze.

        Returns:
            Ratio of uppercase letters to total letters as a float between
            0.0 and 1.0. Returns 0.0 if text contains no letters.
        """
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return 0.0

        caps = [c for c in letters if c.isupper()]
        return len(caps) / len(letters)

    def validate_config(self) -> List[str]:
        """Validate tokenizer configuration.

        This method checks the current configuration for potential issues
        that could affect tokenizer performance or correctness.

        Returns:
            List of validation error messages. Returns empty list if
            configuration is valid.

        Example:
            >>> tokenizer = MessageTokenizer()
            >>> errors = tokenizer.validate_config()
            >>> if errors:
            ...     print("Configuration errors:", errors)
        """
        errors = []

        if self.config.min_token_length < 1:
            errors.append("min_token_length must be at least 1")

        if self.config.max_token_length < self.config.min_token_length:
            errors.append("max_token_length must be >= min_token_length")

        if self.config.max_token_length > 100:
            errors.append("max_token_length should not exceed 100 for performance")

        return errors
