"""Tests for DatabaseBayesStorage.cleanupOldTokens.

This module tests the age+count-based token cleanup of
``DatabaseBayesStorage.cleanupOldTokens``, covering individual rules, cumulative
multi-rule sweeps, empty-rule no-ops, and the bool return contract.
"""

import datetime

import pytest

from internal.database import Database
from internal.database import utils as dbUtils
from internal.database.bayes_storage import DatabaseBayesStorage
from internal.database.manager import DatabaseManagerConfig


@pytest.fixture
async def db():
    """Create an in-memory Database instance for testing.

    Yields:
        A Database wired to an in-memory SQLite provider, torn down after the test.
    """
    config: DatabaseManagerConfig = {
        "default": "default",
        "chatMapping": {},
        "providers": {
            "default": {
                "provider": "sqlite3",
                "parameters": {
                    "dbPath": ":memory:",
                },
            }
        },
    }
    db = Database(config)
    # Initialize database by getting a provider (triggers migration)
    await db.manager.getProvider()
    yield db
    await db.manager.closeAll()


async def _insertToken(db: Database, storage: DatabaseBayesStorage, token: str, totalCount: int, ageDays: int) -> None:
    """Insert a global token then override its total_count and updated_at.

    The repository's ``updateTokenStats`` always stamps ``updated_at`` to now,
    so after inserting we issue a raw SQL UPDATE to pin ``total_count`` and
    back-date ``updated_at`` to the desired age.

    Args:
        db: Database instance for raw provider access.
        storage: DatabaseBayesStorage used to insert the token.
        token: Token string to insert.
        totalCount: Desired total_count value to set.
        ageDays: How many days in the past to set updated_at.
    """
    await storage.updateTokenStats(token, is_spam=True, increment=1)
    provider = await db.manager.getProvider()
    oldTimestamp = dbUtils.getCurrentTimestamp() - datetime.timedelta(days=ageDays)
    await provider.execute(
        "UPDATE bayes_tokens SET total_count = :count, updated_at = :ts WHERE token = :token",
        {"count": totalCount, "ts": oldTimestamp, "token": token},
    )


class TestCleanupOldTokens:
    """Tests for DatabaseBayesStorage.cleanupOldTokens."""

    @pytest.mark.asyncio
    async def testRuleDeletesOldRareToken(self, db):
        """Rule (90d, count<=1) deletes a token older than 90d with total_count 1.

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)
        await _insertToken(db, storage, "oldrare", totalCount=1, ageDays=100)

        result = await storage.cleanupOldTokens([(90 * 86400, 1)])

        assert result is True
        stats = await storage.getTokenStats(["oldrare"])
        assert "oldrare" not in stats

    @pytest.mark.asyncio
    async def testRuleSparesRecentToken(self, db):
        """Rule (90d, count<=1) spares a token only 30 days old.

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)
        await _insertToken(db, storage, "recent", totalCount=1, ageDays=30)

        result = await storage.cleanupOldTokens([(90 * 86400, 1)])

        assert result is True
        stats = await storage.getTokenStats(["recent"])
        assert "recent" in stats

    @pytest.mark.asyncio
    async def testRuleSparesHighCountToken(self, db):
        """Rule (90d, count<=1) spares a token with total_count=5 even at 200d old.

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)
        await _insertToken(db, storage, "frequent", totalCount=5, ageDays=200)

        result = await storage.cleanupOldTokens([(90 * 86400, 1)])

        assert result is True
        stats = await storage.getTokenStats(["frequent"])
        assert "frequent" in stats

    @pytest.mark.asyncio
    async def testRuleDeletesOldLessRareToken(self, db):
        """Rule (180d, count<=2) deletes a token with total_count=2 older than 180d.

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)
        await _insertToken(db, storage, "lessrare", totalCount=2, ageDays=200)

        result = await storage.cleanupOldTokens([(180 * 86400, 2)])

        assert result is True
        stats = await storage.getTokenStats(["lessrare"])
        assert "lessrare" not in stats

    @pytest.mark.asyncio
    async def testMultipleRulesCumulative(self, db):
        """Two rules applied together purge matching tokens and spare the rest.

        Inserts four tokens:
            A (count=1, 100d)  — matches rule 1 (90d, <=1)
            B (count=2, 200d)  — matches rule 2 (180d, <=2)
            C (count=1, 30d)   — too recent
            D (count=5, 300d)  — too frequent

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)
        await _insertToken(db, storage, "tokenA", totalCount=1, ageDays=100)
        await _insertToken(db, storage, "tokenB", totalCount=2, ageDays=200)
        await _insertToken(db, storage, "tokenC", totalCount=1, ageDays=30)
        await _insertToken(db, storage, "tokenD", totalCount=5, ageDays=300)

        result = await storage.cleanupOldTokens([(90 * 86400, 1), (180 * 86400, 2)])

        assert result is True
        stats = await storage.getTokenStats(["tokenA", "tokenB", "tokenC", "tokenD"])
        assert "tokenA" not in stats
        assert "tokenB" not in stats
        assert "tokenC" in stats
        assert "tokenD" in stats

    @pytest.mark.asyncio
    async def testEmptyRulesDeletesNothing(self, db):
        """An empty rules list is a no-op; no tokens are removed.

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)
        await _insertToken(db, storage, "alpha", totalCount=1, ageDays=100)
        await _insertToken(db, storage, "beta", totalCount=2, ageDays=200)

        countBefore = await storage.getVocabularySize()

        result = await storage.cleanupOldTokens([])

        assert result is True
        countAfter = await storage.getVocabularySize()
        assert countAfter == countBefore

    @pytest.mark.asyncio
    async def testReturnsTrueOnSuccess(self, db):
        """cleanupOldTokens returns True on a successful sweep.

        Args:
            db: In-memory Database fixture.
        """
        storage = DatabaseBayesStorage(db)

        result = await storage.cleanupOldTokens([(90 * 86400, 1)])

        assert result is True
