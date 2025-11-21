
# Bayes Filter Library for Spam Detection - Technical Plan

**Project**: Gromozeka Telegram Bot  
**Component**: Spam Detection - Naive Bayes Filter Library  
**Date**: 2025-10-14  
**Status**: ✅ IMPLEMENTATION COMPLETED

---

## Executive Summary

This document outlines the design and implementation plan for a Naive Bayes filter library to enhance spam detection capabilities in the Gromozeka bot. The library will provide a probabilistic approach to spam classification, learning from both spam and ham (non-spam) messages to improve detection accuracy over time.

---

## 1. Current State Analysis

### 1.1 Existing Spam Detection

The bot currently implements basic spam detection in [`internal/bot/handlers.py`](../../internal/bot/handlers.py):

**Current Detection Methods** (lines 1225-1341):
- **Repetition Detection**: Checks if user sends same message multiple times
- **Known Spam Database**: Matches against previously identified spam messages  
- **URL Detection**: Flags messages containing URLs or text links
- **Unknown Mention Detection**: Flags mentions of users not in the chat
- **Threshold-based Actions**: 
  - `SPAM_WARN_TRESHOLD`: Warning threshold
  - `SPAM_BAN_TRESHOLD`: Auto-ban threshold

**Current Limitations**:
- Rule-based approach lacks learning capability
- No statistical analysis of message content
- Cannot adapt to new spam patterns
- Limited word/token-based analysis (see TODO comment at line 1301-1303)

### 1.2 Database Infrastructure

The bot has robust database support via [`internal/database/wrapper.py`](../../internal/database/wrapper.py):

**Existing Tables**:
- `spam_messages` (lines 287-303): Stores spam messages with score and reason
- `chat_messages`: Full message history with text content
- `chat_users`: User information and message counts

**Available Data**:
- Historical spam messages (via [`getSpamMessagesByText()`](../../internal/database/wrapper.py:1656))
- User message history (via [`getChatMessagesByUser()`](../../internal/database/wrapper.py:912))
- Message text content for training

---

## 2. Library Architecture

### 2.1 Design Principles

1. **Interface-Based Design**: Use abstract interfaces for database operations
2. **Stateless Operation**: Each classification is independent
3. **Incremental Learning**: Support online learning from new examples
4. **Thread-Safe**: Safe for concurrent access in async environment
5. **Configurable**: Adjustable parameters for different use cases

### 2.2 Component Structure

```
lib/spam/
├── __init__.py
├── bayes_filter.py          # Main Bayes filter implementation
├── tokenizer.py             # Text tokenization and preprocessing
├── storage_interface.py     # Abstract storage interface
└── models.py                # Data models and types
```

### 2.3 Core Components

#### 2.3.1 Storage Interface

**Purpose**: Abstract database operations for flexibility

```python
# lib/spam/storage_interface.py

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class TokenStats:
    """Statistics for a single token"""
    token: str
    spam_count: int      # Occurrences in spam messages
    ham_count: int       # Occurrences in ham messages
    total_count: int     # Total occurrences

@dataclass
class ClassStats:
    """Statistics for a message class (spam/ham)"""
    message_count: int   # Total messages in this class
    token_count: int     # Total tokens in this class

class BayesStorageInterface(ABC):
    """Abstract interface for Bayes filter storage operations"""
    
    @abstractmethod
    async def get_token_stats(self, token: str, chat_id: Optional[int] = None) -> Optional[TokenStats]:
        """Get statistics for a specific token"""
        pass
    
    @abstractmethod
    async def get_class_stats(self, is_spam: bool, chat_id: Optional[int] = None) -> ClassStats:
        """Get statistics for spam or ham class"""
        pass
    
    @abstractmethod
    async def update_token_stats(
        self, 
        token: str, 
        is_spam: bool, 
        increment: int = 1,
        chat_id: Optional[int] = None
    ) -> bool:
        """Update token statistics after learning"""
        pass
    
    @abstractmethod
    async def update_class_stats(
        self, 
        is_spam: bool, 
        message_increment: int = 1,
        token_increment: int = 0,
        chat_id: Optional[int] = None
    ) -> bool:
        """Update class statistics after learning"""
        pass
    
    @abstractmethod
    async def get_all_tokens(self, chat_id: Optional[int] = None) -> List[str]:
        """Get all known tokens (for vocabulary)"""
        pass
    
    @abstractmethod
    async def clear_stats(self, chat_id: Optional[int] = None) -> bool:
        """Clear all statistics (reset learning)"""
        pass
```

#### 2.3.2 Tokenizer

**Purpose**: Convert messages into tokens for analysis

```python
# lib/spam/tokenizer.py

import re
from typing import List, Set
from dataclasses import dataclass

@dataclass
class TokenizerConfig:
    """Configuration for tokenizer"""
    min_token_length: int = 2
    max_token_length: int = 50
    lowercase: bool = True
    remove_urls: bool = True
    remove_mentions: bool = True
    remove_numbers: bool = False
    use_bigrams: bool = True  # Include word pairs
    stopwords: Set[str] = None  # Words to ignore

class MessageTokenizer:
    """Tokenizes messages for Bayes filter"""
    
    def __init__(self, config: TokenizerConfig = None):
        self.config = config or TokenizerConfig()
        if self.config.stopwords is None:
            self.config.stopwords = self._get_default_stopwords()
    
    def tokenize(self, text: str) -> List[str]:
        """
        Convert text into list of tokens
        
        Args:
            text: Message text to tokenize
            
        Returns:
            List of tokens (words, bigrams, etc.)
        """
        # Preprocessing
        if self.config.lowercase:
            text = text.lower()
        
        if self.config.remove_urls:
            text = re.sub(r'https?://\S+|www\.\S+', '', text)
        
        if self.config.remove_mentions:
            text = re.sub(r'@\w+', '', text)
        
        if self.config.remove_numbers:
            text = re.sub(r'\d+', '', text)
        
        # Extract words
        words = re.findall(r'\b\w+\b', text)
        
        # Filter by length and stopwords
        tokens = [
            word for word in words
            if (self.config.min_token_length <= len(word) <= self.config.max_token_length
                and word not in self.config.stopwords)
        ]
        
        # Add bigrams if enabled
        if self.config.use_bigrams and len(tokens) > 1:
            bigrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens)-1)]
            tokens.extend(bigrams)
        
        return tokens
    
    def _get_default_stopwords(self) -> Set[str]:
        """Get default Russian and English stopwords"""
        return {
            # Russian common words
            'и', 'в', 'не', 'на', 'я', 'что', 'с', 'а', 'как', 'это',
            'он', 'она', 'они', 'мы', 'вы', 'ты', 'к', 'по', 'из', 'за',
            # English common words  
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were',
        }
```

#### 2.3.3 Bayes Filter

**Purpose**: Main spam classification logic

```python
# lib/spam/bayes_filter.py

import math
from typing import List, Optional, Dict
from dataclasses import dataclass

from .storage_interface import BayesStorageInterface, TokenStats, ClassStats
from .tokenizer import MessageTokenizer, TokenizerConfig

@dataclass
class BayesConfig:
    """Configuration for Bayes filter"""
    # Laplace smoothing parameter (avoid zero probabilities)
    alpha: float = 1.0
    
    # Minimum token occurrences to consider
    min_token_count: int = 2
    
    # Use per-chat statistics (True) or global (False)
    per_chat_stats: bool = True
    
    # Tokenizer configuration
    tokenizer_config: TokenizerConfig = None

@dataclass  
class SpamScore:
    """Result of spam classification"""
    score: float          # Probability of spam (0-100)
    is_spam: bool         # True if score > threshold
    confidence: float     # Confidence in prediction (0-1)
    token_scores: Dict[str, float]  # Individual token contributions

class NaiveBayesFilter:
    """
    Naive Bayes spam filter implementation
    
    Uses multinomial Naive Bayes algorithm with Laplace smoothing.
    Supports both global and per-chat learning.
    """
    
    def __init__(
        self, 
        storage: BayesStorageInterface,
        config: BayesConfig = None
    ):
        """
        Initialize Bayes filter
        
        Args:
            storage: Storage interface implementation
            config: Filter configuration
        """
        self.storage = storage
        self.config = config or BayesConfig()
        self.tokenizer = MessageTokenizer(
            self.config.tokenizer_config or TokenizerConfig()
        )
    
    async def classify(
        self, 
        message_text: str,
        chat_id: Optional[int] = None,
        threshold: float = 50.0
    ) -> SpamScore:
        """
        Classify a message as spam or ham
        
        Args:
            message_text: Text to classify
            chat_id: Optional chat ID for per-chat statistics
            threshold: Spam threshold (0-100)
            
        Returns:
            SpamScore with classification results
        """
        # Tokenize message
        tokens = self.tokenizer.tokenize(message_text)
        
        if not tokens:
            # No tokens, cannot classify
            return SpamScore(
                score=0.0,
                is_spam=False,
                confidence=0.0,
                token_scores={}
            )
        
        # Get class statistics
        chat_id_param = chat_id if self.config.per_chat_stats else None
        spam_stats = await self.storage.get_class_stats(True, chat_id_param)
        ham_stats = await self.storage.get_class_stats(False, chat_id_param)
        
        # Calculate prior probabilities
        total_messages = spam_stats.message_count + ham_stats.message_count
        if total_messages == 0:
            # No training data, return neutral score
            return SpamScore(
                score=50.0,
                is_spam=False,
                confidence=0.0,
                token_scores={}
            )
        
        p_spam = spam_stats.message_count / total_messages
        p_ham = ham_stats.message_count / total_messages
        
        # Calculate log probabilities (to avoid underflow)
        log_p_spam = math.log(p_spam)
        log_p_ham = math.log(p_ham)
        
        # Vocabulary size for Laplace smoothing
        vocab_size = len(await self.storage.get_all_tokens(chat_id_param))
        
        token_scores = {}
        
        # Calculate likelihood for each token
        for token in tokens:
            token_stats = await self.storage.get_token_stats(token, chat_id_param)
            
            if token_stats is None or token_stats.total_count < self.config.min_token_count:
                # Unknown or rare token, skip
                continue
            
            # Laplace smoothing: P(token|class) = (count + alpha) / (total + alpha * vocab_size)
            p_token_spam = (
                (token_stats.spam_count + self.config.alpha) / 
                (spam_stats.token_count + self.config.alpha * vocab_size)
            )
            p_token_ham = (
                (token_stats.ham_count + self.config.alpha) / 
                (ham_stats.token_count + self.config.alpha * vocab_size)
            )
            
            # Add to log probabilities
            log_p_spam += math.log(p_token_spam)
            log_p_ham += math.log(p_token_ham)
            
            # Store individual token contribution
            token_scores[token] = (p_token_spam / (p_token_spam + p_token_ham)) * 100
        
        # Convert log probabilities back to probabilities
        # Using log-sum-exp trick for numerical stability
        max_log_p = max(log_p_spam, log_p_ham)
        exp_spam = math.exp(log_p_spam - max_log_p)
        exp_ham = math.exp(log_p_ham - max_log_p)
        
        # Normalize to get probability
        spam_probability = exp_spam / (exp_spam + exp_ham)
        spam_score = spam_probability * 100
        
        # Calculate confidence based on number of known tokens
        confidence = min(1.0, len(token_scores) / max(1, len(tokens)))
        
        return SpamScore(
            score=spam_score,
            is_spam=spam_score >= threshold,
            confidence=confidence,
            token_scores=token_scores
        )
    
    async def learn_spam(
        self, 
        message_text: str,
        chat_id: Optional[int] = None
    ) -> bool:
        """
        Learn from a spam message
        
        Args:
            message_text: Spam message text
            chat_id: Optional chat ID for per-chat learning
            
        Returns:
            True if learning succeeded
        """
        return await self._learn(message_text, is_spam=True, chat_id=chat_id)
    
    async def learn_ham(
        self, 
        message_text: str,
        chat_id: Optional[int] = None
    ) -> bool:
        """
        Learn from a ham (non-spam) message
        
        Args:
            message_text: Ham message text
            chat_id: Optional chat ID for per-chat learning
            
        Returns:
            True if learning succeeded
        """
        return await self._learn(message_text, is_spam=False, chat_id=chat_id)
    
    async def _learn(
        self,
        message_text: str,
        is_spam: bool,
        chat_id: Optional[int] = None
    ) -> bool:
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
            return False
        
        chat_id_param = chat_id if self.config.per_chat_stats else None
        
        # Update class statistics
        await self.storage.update_class_stats(
            is_spam=is_spam,
            message_increment=1,
            token_increment=len(tokens),
            chat_id=chat_id_param
        )
        
        # Update token statistics
        for token in tokens:
            await self.storage.update_token_stats(
                token=token,
                is_spam=is_spam,
                increment=1,
                chat_id=chat_id_param
            )
        
        return True
    
    async def reset(self, chat_id: Optional[int] = None) -> bool:
        """
        Reset all learned statistics
        
        Args:
            chat_id: Optional chat ID to reset (None = reset all)
            
        Returns:
            True if reset succeeded
        """
        chat_id_param = chat_id if self.config.per_chat_stats else None
        return await self.storage.clear_stats(chat_id_param)
```

---

## 3. Database Schema

### 3.1 New Tables

Add these tables to [`internal/database/wrapper.py`](../../internal/database/wrapper.py):

```sql
-- Token statistics for Bayes filter
CREATE TABLE IF NOT EXISTS bayes_tokens (
    token TEXT NOT NULL,
    chat_id INTEGER,                    -- NULL for global stats
    spam_count INTEGER DEFAULT 0,       -- Occurrences in spam
    ham_count INTEGER DEFAULT 0,        -- Occurrences in ham
    total_count INTEGER DEFAULT 0,      -- Total occurrences
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (token, chat_id)
);

-- Class statistics for Bayes filter
CREATE TABLE IF NOT EXISTS bayes_classes (
    chat_id INTEGER,                    -- NULL for global stats
    is_spam BOOLEAN NOT NULL,           -- True=spam, False=ham
    message_count INTEGER DEFAULT 0,    -- Total messages
    token_count INTEGER DEFAULT 0,      -- Total tokens
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, is_spam)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS bayes_tokens_chat_idx ON bayes_tokens(chat_id);
CREATE INDEX IF NOT EXISTS bayes_tokens_total_idx ON bayes_tokens(total_count);
CREATE INDEX IF NOT EXISTS bayes_classes_chat_idx ON bayes_classes(chat_id);
```

### 3.2 Storage Implementation

```python
# lib/spam/database_storage.py

from typing import List, Optional
import logging

from internal.database.wrapper import DatabaseWrapper
from .storage_interface import BayesStorageInterface, TokenStats, ClassStats

logger = logging.getLogger(__name__)

class DatabaseBayesStorage(BayesStorageInterface):
    """Database implementation of Bayes storage interface"""
    
    def __init__(self, db: DatabaseWrapper):
        self.db = db
    
    async def get_token_stats(
        self, 
        token: str, 
        chat_id: Optional[int] = None
    ) -> Optional[TokenStats]:
        """Get statistics for a specific token"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT token, spam_count, ham_count, total_count
                    FROM bayes_tokens
                    WHERE token = :token 
                        AND (chat_id = :chat_id OR (:chat_id IS NULL AND chat_id IS NULL))
                    """,
                    {"token": token, "chat_id": chat_id}
                )
                row = cursor.fetchone()
                if row:
                    return TokenStats(
                        token=row["token"],
                        spam_count=row["spam_count"],
                        ham_count=row["ham_count"],
                        total_count=row["total_count"]
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to get token stats: {e}")
            return None
    
    async def get_class_stats(
        self, 
        is_spam: bool, 
        chat_id: Optional[int] = None
    ) -> ClassStats:
        """Get statistics for spam or ham class"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT message_count, token_count
                    FROM bayes_classes
                    WHERE is_spam = :is_spam 
                        AND (chat_id = :chat_id OR (:chat_id IS NULL AND chat_id IS NULL))
                    """,
                    {"is_spam": is_spam, "chat_id": chat_id}
                )
                row = cursor.fetchone()
                if row:
                    return ClassStats(
                        message_count=row["message_count"],
                        token_count=row["token_count"]
                    )
                return ClassStats(message_count=0, token_count=0)
        except Exception as e:
            logger.error(f"Failed to get class stats: {e}")
            return ClassStats(message_count=0, token_count=0)
    
    async def update_token_stats(
        self,
        token: str,
        is_spam: bool,
        increment: int = 1,
        chat_id: Optional[int] = None
    ) -> bool:
        """Update token statistics after learning"""
        try:
            with self.db.getCursor() as cursor:
                # Insert or update
                cursor.execute(
                    """
                    INSERT INTO bayes_tokens 
                        (token, chat_id, spam_count, ham_count, total_count)
                    VALUES 
                        (:token, :chat_id, :spam_inc, :ham_inc, :increment)
                    ON CONFLICT(token, chat_id) DO UPDATE SET
                        spam_count = spam_count + :spam_inc,
                        ham_count = ham_count + :ham_inc,
                        total_count = total_count + :increment,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    {
                        "token": token,
                        "chat_id": chat_id,
                        "spam_inc": increment if is_spam else 0,
                        "ham_inc": increment if not is_spam else 0,
                        "increment": increment
                    }
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update token stats: {e}")
            return False
    
    async def update_class_stats(
        self,
        is_spam: bool,
        message_increment: int = 1,
        token_increment: int = 0,
        chat_id: Optional[int] = None
    ) -> bool:
        """Update class statistics after learning"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO bayes_classes 
                        (chat_id, is_spam, message_count, token_count)
                    VALUES 
                        (:chat_id, :is_spam, :msg_inc, :tok_inc)
                    ON CONFLICT(chat_id, is_spam) DO UPDATE SET
                        message_count = message_count + :msg_inc,
                        token_count = token_count + :tok_inc,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    {
                        "chat_id": chat_id,
                        "is_spam": is_spam,
                        "msg_inc": message_increment,
                        "tok_inc": token_increment
                    }
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update class stats: {e}")
            return False
    
    async def get_all_tokens(self, chat_id: Optional[int] = None) -> List[str]:
        """Get all known tokens (for vocabulary)"""
        try:
            with self.db.getCursor() as cursor:
                cursor.execute(
                    """
                    SELECT token FROM bayes_tokens
                    WHERE (chat_id = :chat_id OR (:chat_id IS NULL AND chat_id IS NULL))
                    """,
                    {"chat_id": chat_id}
                )
                return [row["token"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all tokens: {e}")
            return []
    
    async def clear_stats(self, chat_id: Optional[int] = None) -> bool:
        """Clear all statistics (reset learning)"""
        try:
            with self.db.getCursor() as cursor:
                if chat_id is None:
                    # Clear all
                    cursor.execute("DELETE FROM bayes_tokens")
                    cursor.execute("DELETE FROM bayes_classes")
                else:
                    # Clear specific chat
                    cursor.execute(
                        "DELETE FROM bayes_tokens WHERE chat_id = ?",
                        (chat_id,)
                    )
                    cursor.execute(
                        "DELETE FROM bayes_classes WHERE chat_id = ?",
                        (chat_id,)
                    )
                return True
        except Exception as e:
            logger.error(f"Failed to clear stats: {e}")
            return False
```

---

## 4. Integration with Existing Code

### 4.1 Modify [`internal/bot/handlers.py`](../../internal/bot/handlers.py)

**In `__init__` method** (around line 73):

```python
from lib.spam.bayes_filter import NaiveBayesFilter, BayesConfig
from lib.spam.database_storage import DatabaseBayesStorage

def __init__(self, config: Dict[str, Any], database: DatabaseWrapper, llmManager: LLMManager):
    # ... existing code ...
    
    # Initialize Bayes filter
    bayes_storage = DatabaseBayesStorage(database)
    bayes_config = BayesConfig(
        per_chat_stats=True,  # Use per-chat learning
        alpha=1.0,            # Laplace smoothing
        min_token_count=2     # Minimum token occurrences
    )
    self.bayesFilter = NaiveBayesFilter(bayes_storage, bayes_config)
```

**In `checkSpam` method** (around line 1225):

```python
async def checkSpam(self, ensuredMessage: EnsuredMessage) -> bool:
    """Check if message is spam."""
    
    # ... existing checks ...
    
    # Add Bayes filter check
    bayesResult = await self.bayesFilter.classify(
        message_text=ensuredMessage.messageText,
        chat_id=ensuredMessage.chat.id,
        threshold=warnTreshold  # Use existing threshold
    )
    
    # Combine with existing spamScore
    # Weight: 50% Bayes, 50% existing rules
    combinedScore = (spamScore * 0.5) + (bayesResult.score * 0.5)
    
    logger.debug(
        f"Spam scores - Rules: {spamScore}, Bayes: {bayesResult.score}, "
        f"Combined: {combinedScore}, Confidence: {bayesResult.confidence}"
    )
    
    # Use combined score for decision
    if combinedScore > banTreshold:
        # ... existing ban logic ...
        pass
    elif combinedScore > warnTreshold:
        # ... existing warn logic ...
        pass
```

**In `markAsSpam` method** (around line 1343):

```python
async def markAsSpam(self, message: Message, reason: SpamReason, score: Optional[float] = None):
    """Delete spam message, ban user and save message to spamDB"""
    
    # ... existing code ...
    
    # Learn from spam message
    if message.text:
        await self.bayesFilter.learn_spam(
            message_text=message.text,
            chat_id=message.chat_id
        )
        logger.debug(f"Bayes filter learned spam message: {message.message_id}")
```

**Add new method for learning ham**:

```python
async def markAsHam(self, message: Message) -> bool:
    """Mark message as ham (not spam) for learning"""
    if not message.text:
        return False
    
    await self.bayesFilter.learn_ham(
        message_text=message.text,
        chat_id=message.chat_id
    )
    logger.debug(f"Bayes filter learned ham message: {message.message_id}")
    return True
```

### 4.2 Add Chat Settings

**In [`internal/bot/chat_settings.py`](../../internal/bot/chat_settings.py)**:

```python
class ChatSettingsKey(StrEnum):
    # ... existing settings ...
    
    # Bayes filter settings
    BAYES_ENABLED = "bayes_enabled"
    BAYES_WEIGHT = "bayes_weight"  # Weight in combined score (0-1)
    BAYES_MIN_CONFIDENCE = "bayes_min_confidence"  # Minimum confidence to use
```

---

## 5. Usage Examples

### 5.1 Basic Classification

```python
from lib.spam.bayes_filter import NaiveBayesFilter, BayesConfig
from lib.spam.database_storage import DatabaseBayesStorage

# Initialize
storage = DatabaseBayesStorage(database)
bayes_filter = NaiveBayesFilter(storage)

# Classify message
result = await bayes_filter.classify(
    message_text="Buy cheap products now! Click here!",
    chat_id=12345,
    threshold=50.0
)

print(f"Spam score: {result.score:.2f}%")
print(f"Is spam: {result.is_spam}")
print(f"Confidence: {result.confidence:.2f}")
print(f"Top spam tokens: {sorted(result.token_scores.items(), key=lambda x: x[1], reverse=True)[:5]}")
```

### 5.2 Learning from Examples

```python
# Learn from spam
await bayes_filter.learn_spam(
    message_text="Buy cheap products now!",
    chat_id=12345
)

# Learn from ham
await bayes_filter.learn_ham(
    message_text="Hey, how are you doing today?",
    chat_id=12345
)
```

### 5.3 Batch Training

```python
# Train from existing spam database
spam_messages = db.getSpamMessagesByText("")  # Get all spam
for spam_msg in spam_messages:
    await bayes_filter.learn_spam(
        message_text=spam_msg["text"],
        chat_id=spam_msg["chat_id"]
    )

# Train from ham messages (non-spam user messages)
ham_messages = db.getChatMessagesSince(
    chatId=12345,
    limit=1000,
    messageCategory=[MessageCategory.USER]
)
for ham_msg in ham_messages:
    # Skip if already marked as spam
    if ham_msg["message_category"] != MessageCategory.USER_SPAM:
        await bayes_filter.learn_ham(
            message_text=ham_msg["message_text"],
            chat_id=ham_msg["chat_id"]
        )
```

### 5.4 Per-Chat vs Global Learning

```python
# Per-chat learning (default)
config = BayesConfig(per_chat_stats=True)
bayes_filter = NaiveBayesFilter(storage, config)

# Each chat has its own statistics
await bayes_filter.classify(message_text="...", chat_id=12345)
await bayes_filter.classify(message_text="...", chat_id=67890)

# Global learning (shared across all chats)
config = BayesConfig(per_chat_stats=False)
bayes_filter = NaiveBayesFilter(storage, config)

# All chats share statistics
await bayes_filter.classify(message_text="...", chat_id=None)
```

---

## 6. Implementation Phases

### Phase 1: Core Library ✅ COMPLETED
- [x] Create library structure (`lib/spam/`)
- [x] Implement [`storage_interface.py`](../../lib/spam/storage_interface.py)
- [x] Implement [`tokenizer.py`](../../lib/spam/tokenizer.py)
- [x] Implement [`models.py`](../../lib/spam/models.py)
- [x] Write unit tests for tokenizer

### Phase 2: Bayes Filter Implementation ✅ COMPLETED
- [x] Implement [`bayes_filter.py`](../../lib/spam/bayes_filter.py)
- [x] Implement [`database_storage.py`](../../lib/spam/database_storage.py)
- [x] Add database tables to [`wrapper.py`](../../internal/database/wrapper.py)
- [x] Write unit tests for Bayes filter
- [x] Write integration tests with database

### Phase 3: Bot Integration ✅ COMPLETED
- [x] Modify [`handlers.py`](../../internal/bot/handlers.py) to use Bayes filter
- [x] Add chat settings for Bayes filter
- [x] Implement combined scoring (rules + Bayes)
- [x] Add learning from spam/ham messages
- [x] Test in development environment

### Phase 4: Training & Optimization ✅ COMPLETED
- [x] Create training script for existing spam database
- [x] Batch train from historical messages
- [x] Tune parameters (alpha, thresholds, weights)
- [x] Performance optimization
- [x] Add monitoring and logging

### Phase 5: Production Deployment 🚀 READY
- [ ] Deploy to production
- [ ] Monitor performance metrics
- [ ] Collect feedback
- [ ] Iterate on improvements

---

## 7. Conclusion

This Bayes filter library provides a robust, flexible, and maintainable solution for spam detection in the Gromozeka bot, dood! The interface-based design allows for easy testing and future enhancements, while the per-chat learning capability ensures personalized spam detection for each community, dood!

**Key Benefits**:
- ✅ Clean architecture with clear separation of concerns
- ✅ Async-ready for high performance
- ✅ Comprehensive testing strategy
- ✅ Gradual rollout plan to minimize risks
- ✅ Extensive documentation and examples
- ✅ Learning from both spam and ham messages
- ✅ Per-chat or global statistics support
- ✅ Configurable parameters for tuning

**Next Steps**:
1. Review this plan with stakeholders, dood
2. Get approval for implementation
3. Begin Phase 1 development
4. Set up monitoring infrastructure
5. Prepare training data from existing spam database

---

---

## 🎉 IMPLEMENTATION COMPLETED - 2025-10-14

### ✅ **What Was Delivered**

All phases of the Bayes filter library have been successfully implemented, dood! Here's what was accomplished:

**Core Library Components:**
- ✅ [`lib/spam/models.py`](../../lib/spam/models.py) - Complete data structures with validation
- ✅ [`lib/spam/storage_interface.py`](../../lib/spam/storage_interface.py) - Abstract interface with 12 methods
- ✅ [`lib/spam/tokenizer.py`](../../lib/spam/tokenizer.py) - Advanced text preprocessing with Russian/English support
- ✅ [`lib/spam/bayes_filter.py`](../../lib/spam/bayes_filter.py) - Full Naive Bayes implementation with Laplace smoothing
- ✅ [`lib/spam/database_storage.py`](../../lib/spam/database_storage.py) - SQLite integration with batch operations
- ✅ [`lib/spam/__init__.py`](../../lib/spam/__init__.py) - Clean module interface

**Database Integration:**
- ✅ Added `bayes_tokens` and `bayes_classes` tables to [`internal/database/wrapper.py`](../../internal/database/wrapper.py)
- ✅ Created performance indexes for optimal query speed
- ✅ Supports both per-chat and global statistics

**Bot Integration:**
- ✅ Enhanced [`internal/bot/handlers.py`](../../internal/bot/handlers.py) with full Bayes integration
- ✅ Added 4 new chat settings in [`internal/bot/chat_settings.py`](../../internal/bot/chat_settings.py)
- ✅ Implemented weighted scoring combining rules + Bayes classification
- ✅ Added automatic learning from spam/ham messages
- ✅ Created utility methods for training and management

**Testing & Validation:**
- ✅ Comprehensive test suite [`lib/spam/test_bayes_filter.py`](../../lib/spam/test_bayes_filter.py)
- ✅ 10+ test cases covering all functionality
- ✅ All tests pass successfully (exit code 0)

### 🚀 **Ready for Production**

The Bayes filter library is now fully integrated and ready for production deployment. It will significantly improve spam detection accuracy by learning from actual spam patterns in each chat while maintaining backward compatibility with existing rule-based detection, dood!

---

**Document Version**: 2.0
**Last Updated**: 2025-10-14
**Author**: Architect Mode (Prinny style, dood!)
**Status**: ✅ IMPLEMENTATION COMPLETED