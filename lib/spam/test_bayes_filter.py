#!/usr/bin/env python3
"""
Simple test for Bayes spam filter, dood!

This test verifies that the basic functionality of the Bayes filter works correctly.
"""

import asyncio
import logging
import os
import sys
import tempfile
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from internal.database.wrapper import DatabaseWrapper  # noqa:E402
from lib.spam import NaiveBayesFilter, BayesConfig  # noqa:E402
from internal.database.bayes_storage import DatabaseBayesStorage  # noqa:E402

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_bayes_filter():
    """Test basic Bayes filter functionality, dood!"""

    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        db_path = tmp_db.name

    db: Optional[DatabaseWrapper] = None
    try:
        # Initialize database and storage
        db = DatabaseWrapper(db_path)
        storage = DatabaseBayesStorage(db)

        # Create tables
        # db._initDatabase()

        # Initialize Bayes filter
        config = BayesConfig(per_chat_stats=True, alpha=1.0, min_token_count=1, debug_logging=True)  # Lower for testing
        bayes_filter = NaiveBayesFilter(storage, config)

        logger.info("=== Testing Bayes Filter, dood! ===")

        # Test 1: Classification without training (should return neutral)
        logger.info("Test 1: Classification without training")
        result = await bayes_filter.classify("Buy cheap products now!", chatId=12345)
        logger.info(f"Score: {result.score:.2f}%, Is spam: {result.is_spam}, Confidence: {result.confidence:.3f}")
        assert result.score == 50.0, f"Expected neutral score 50.0, got {result.score}"

        # Test 2: Learn some spam messages
        logger.info("Test 2: Learning spam messages")
        spam_messages = [
            "Buy cheap products now!",
            "Click here for amazing deals!",
            "Free money! Click now!",
            "Urgent! Limited time offer!",
            "Make money fast online!",
        ]

        for msg in spam_messages:
            success = await bayes_filter.learnSpam(msg, chatId=12345)
            assert success, f"Failed to learn spam message: {msg}"

        logger.info(f"Learned {len(spam_messages)} spam messages")

        # Test 3: Learn some ham messages
        logger.info("Test 3: Learning ham messages")
        ham_messages = [
            "Hey, how are you doing today?",
            "Let's meet for coffee tomorrow",
            "The weather is nice today",
            "I finished my homework",
            "What time is the meeting?",
        ]

        for msg in ham_messages:
            success = await bayes_filter.learnHam(msg, chatId=12345)
            assert success, f"Failed to learn ham message: {msg}"

        logger.info(f"Learned {len(ham_messages)} ham messages")

        # Test 4: Get model statistics
        logger.info("Test 4: Model statistics")
        stats = await bayes_filter.getModelInfo(chat_id=12345)
        logger.info(
            f"Stats: {stats.total_spam_messages} spam, {stats.total_ham_messages} ham, vocab: {stats.vocabulary_size}"
        )
        assert stats.total_spam_messages == len(spam_messages)
        assert stats.total_ham_messages == len(ham_messages)
        assert stats.vocabulary_size > 0

        # Test 5: Classify spam-like message
        logger.info("Test 5: Classify spam-like message")
        result = await bayes_filter.classify("Buy cheap deals now!", chatId=12345, threshold=50.0)
        logger.info(
            f"Spam-like message - Score: {result.score:.2f}%, Is spam: {result.is_spam}, "
            f"Confidence: {result.confidence:.3f}"
        )
        logger.info(f"Top tokens: {sorted(result.token_scores.items(), key=lambda x: x[1], reverse=True)[:3]}")

        # Test 6: Classify ham-like message
        logger.info("Test 6: Classify ham-like message")
        result = await bayes_filter.classify("How are you today?", chatId=12345, threshold=50.0)
        logger.info(
            f"Ham-like message - Score: {result.score:.2f}%, Is spam: {result.is_spam}, "
            f"Confidence: {result.confidence:.3f}"
        )
        logger.info(f"Top tokens: {sorted(result.token_scores.items(), key=lambda x: x[1], reverse=True)[:3]}")

        # Test 7: Test per-chat isolation
        logger.info("Test 7: Per-chat isolation")
        result_other_chat = await bayes_filter.classify("Buy cheap products now!", chatId=67890)
        logger.info(
            f"Other chat - Score: {result_other_chat.score:.2f}%, Confidence: {result_other_chat.confidence:.3f}"
        )
        assert result_other_chat.score == 50.0, "Per-chat isolation failed"

        # Test 8: Batch learning
        logger.info("Test 8: Batch learning")
        batch_messages = [
            ("More spam content here", True, 12345),
            ("Another normal message", False, 12345),
            ("Yet another spam", True, 12345),
        ]

        batch_stats = await bayes_filter.batch_learn(batch_messages)
        logger.info(f"Batch learning stats: {batch_stats}")
        assert batch_stats["success"] == 3
        assert batch_stats["spam_learned"] == 2
        assert batch_stats["ham_learned"] == 1

        # Test 9: Storage interface methods
        logger.info("Test 9: Storage interface methods")

        # Get top spam tokens
        top_spam = await storage.getTopSpamTokens(limit=5, chat_id=12345)
        logger.info(f"Top spam tokens: {[(t.token, t.spam_count, t.ham_count) for t in top_spam[:3]]}")

        # Get top ham tokens
        top_ham = await storage.getTopHamTokens(limit=5, chat_id=12345)
        logger.info(f"Top ham tokens: {[(t.token, t.spam_count, t.ham_count) for t in top_ham[:3]]}")

        # Test 10: Cleanup rare tokens
        logger.info("Test 10: Cleanup rare tokens")
        removed = await bayes_filter.cleanup_rare_tokens(min_count=2, chat_id=12345)
        logger.info(f"Removed {removed} rare tokens")

        logger.info("=== All tests passed! Bayes filter is working correctly, dood! ===")

    finally:
        # Cleanup
        if db is not None:
            db.close()
        try:
            os.unlink(db_path)
        except Exception:
            pass


async def test_tokenizer():
    """Test tokenizer functionality, dood!"""
    from lib.spam.tokenizer import MessageTokenizer, TokenizerConfig

    logger.info("=== Testing Tokenizer, dood! ===")

    # Test basic tokenization
    tokenizer = MessageTokenizer()

    test_text = "Buy cheap products now! Visit https://example.com @user123"
    tokens = tokenizer.tokenize(test_text)
    logger.info(f"Original: {test_text}")
    logger.info(f"Tokens: {tokens}")

    # Test with different config
    config = TokenizerConfig(remove_urls=False, remove_mentions=False, use_bigrams=False)
    tokenizer2 = MessageTokenizer(config)
    tokens2 = tokenizer2.tokenize(test_text)
    logger.info(f"With URLs/mentions: {tokens2}")

    # Test spam indicators
    indicators = tokenizer.estimate_spam_indicators(test_text)
    logger.info(f"Spam indicators: {indicators}")

    logger.info("=== Tokenizer tests passed, dood! ===")


async def main():
    """Run all tests, dood!"""
    try:
        await test_tokenizer()
        await test_bayes_filter()
        logger.info("🎉 All tests completed successfully, dood!")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
