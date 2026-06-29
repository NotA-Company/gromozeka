"""Tests for :class:`ChatEmbeddingsRepository`.

End-to-end behavioural coverage of the embeddings table CRUD methods
(``saveMessageEmbedding``, ``getMessageEmbedding``,
``deleteChatEmbeddings``) and the backfill helper
(``getMessagesWithoutEmbeddings``).

Embedding CRUD was split out of :class:`ChatMessagesRepository` so
that embeddings live in a focused module. The semantic-search path
itself (loading embeddings, applying pre-filters, computing cosine
similarity, fetching the top-K messages) was further split out into
:class:`ChatSearchRepository` (``chat_search.py``) so the search
surface is cohesive and free of cross-repository back-references.
That dispatcher is covered in
``tests/database/repositories/test_chat_search.py`` and exercised
end-to-end via the handler tests in
``tests/bot/common/handlers/test_chat_search.py``.

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
applied — no mocks.
"""

# pyright: reportTypedDictNotRequiredAccess=false

import datetime

import pytest

from internal.database import Database
from internal.database.models import MessageCategory
from internal.models import MessageId


class TestEmbeddingAndSearch:
    """End-to-end tests for embedding CRUD on the ``message_embeddings`` table.

    Covers ``saveMessageEmbedding`` / ``getMessageEmbedding`` /
    ``deleteChatEmbeddings`` (the ``message_embeddings`` table) and the
    backfill helper ``getMessagesWithoutEmbeddings`` (used by
    :class:`ChatSearchHandler`).
    """

    @staticmethod
    async def _seedUser(db: Database, chatId: int, userId: int) -> None:
        """Insert a chat_users row so JOINs to chat_messages succeed."""
        await db.chatUsers.updateChatUser(
            chatId=chatId,
            userId=userId,
            username=f"user{userId}",
            fullName=f"User {userId}",
        )

    @staticmethod
    async def _seedMessage(
        db: Database,
        chatId: int,
        userId: int,
        messageId: int,
        messageText: str,
        *,
        messageCategory: MessageCategory = MessageCategory.UNSPECIFIED,
    ) -> None:
        """Insert a chat_users row and a chat_messages row for the test seed."""
        await TestEmbeddingAndSearch._seedUser(db, chatId=chatId, userId=userId)
        await db.chatMessages.saveChatMessage(
            date=datetime.datetime.now(datetime.timezone.utc),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(messageId),
            messageText=messageText,
            messageCategory=messageCategory,
        )

    async def test_save_and_get_embedding(self, testDatabase: Database) -> None:
        """Round-trip an embedding: store it then read it back unchanged.

        Asserts the :class:`MessageEmbeddingDict` shape — ``message_id``
        and the embedding-side fields from ``message_embeddings`` only.
        No JOIN against ``chat_messages`` is performed, so the returned
        dict does not include ``message_text``.
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="hi")
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=1,
            messageId=MessageId(1),
            embedding=[1.0, 0.5, 0.25],
            model="m1",
        )

        result = await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=1, messageId=MessageId(1))

        assert result is not None
        assert result["message_id"] == MessageId(1)
        assert result["dimensions"] == 3
        assert result["model"] == "m1"
        # Values chosen to be exactly representable in float32 — the BLOB
        # round-trip through array.array('f') preserves them bit-for-bit.
        assert result["embedding"] == pytest.approx([1.0, 0.5, 0.25])
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    async def test_get_embedding_not_found(self, testDatabase: Database) -> None:
        """Looking up an embedding that was never stored returns ``None``."""
        result = await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=1, messageId=MessageId(999))
        assert result is None

    async def test_save_embedding_upsert(self, testDatabase: Database) -> None:
        """Saving the same (chat, message) twice updates the model column."""
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="hi")
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=1,
            messageId=MessageId(1),
            embedding=[1.0, 0.0, 0.0],
            model="m1",
        )
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=1,
            messageId=MessageId(1),
            embedding=[1.0, 0.0, 0.0],
            model="m2",
        )

        result = await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=1, messageId=MessageId(1))

        assert result is not None
        assert result["model"] == "m2"

    async def test_delete_chat_embeddings(self, testDatabase: Database) -> None:
        """``deleteChatEmbeddings`` removes every embedding for a chat."""
        for mid in (1, 2, 3):
            await self._seedMessage(
                testDatabase,
                chatId=1,
                userId=100,
                messageId=mid,
                messageText=f"m{mid}",
            )
            await testDatabase.chatEmbeddings.saveMessageEmbedding(
                chatId=1,
                messageId=MessageId(mid),
                embedding=[1.0, 0.0, 0.0],
                model="m1",
            )

        await testDatabase.chatEmbeddings.deleteChatEmbeddings(chatId=1)

        for mid in (1, 2, 3):
            assert await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=1, messageId=MessageId(mid)) is None

    async def test_getMessagesWithoutEmbeddings(self, testDatabase: Database) -> None:
        """Messages with no embedding row are returned as full :class:`ChatMessageDict` rows.

        The backfill helper no longer surfaces embedding-side fields
        (``embedding``/``dimensions``/``model``/``created_at``/
        ``updated_at``) — it only returns the message shape that the
        backfill consumer (``ChatSearchHandler._dtCronJob``) actually
        reads: ``message_id``, ``message_text``, and the user info
        joined from ``chat_users`` (``username``, ``full_name``).
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="needs-vec")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="also-needs-vec")

        results = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1)

        assert len(results) == 2
        returnedMessageIds = {r["message_id"] for r in results}
        assert returnedMessageIds == {MessageId(1), MessageId(2)}
        # ChatMessageDict shape: message + joined user fields are present.
        textByMessageId = {r["message_id"].asMessageId(): r["message_text"] for r in results}
        assert textByMessageId[1] == "needs-vec"
        assert textByMessageId[2] == "also-needs-vec"
        for r in results:
            assert r["chat_id"] == 1
            assert r["user_id"] == 100
            assert r["username"] == "user100"
            assert r["full_name"] == "User 100"

    async def test_getMessagesWithoutEmbeddings_existing(self, testDatabase: Database) -> None:
        """When every message already has an embedding, the helper returns ``[]``."""
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="a")
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=2, messageText="b")
        for mid in (1, 2):
            await testDatabase.chatEmbeddings.saveMessageEmbedding(
                chatId=1,
                messageId=MessageId(mid),
                embedding=[1.0, 0.0, 0.0],
                model="m1",
            )

        results = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1)

        assert results == []

    async def test_getMessagesWithoutEmbeddings_model_mismatch(self, testDatabase: Database) -> None:
        """``modelName`` re-surfaces messages whose stored embedding was made by a different model.

        Switching the ``EMBEDDING_MODEL`` chat setting from A → B must
        cause the backfill to re-embed rows that still have an A-side
        embedding. Same model → not surfaced; different model →
        surfaced as a :class:`ChatMessageDict` (the backfill consumer
        only reads ``message_id`` / ``message_text`` / user fields).
        """
        await self._seedMessage(testDatabase, chatId=1, userId=100, messageId=1, messageText="stale-vec")
        # Embedding exists, but the chat has switched model A → B.
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=1,
            messageId=MessageId(1),
            embedding=[1.0, 0.0, 0.0],
            model="A",
        )

        # Same model → message is NOT surfaced (the current model already covers it).
        sameModel = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1, modelName="A")
        assert sameModel == []

        # Different model → the row is surfaced so the backfill regenerates it.
        differentModel = await testDatabase.chatEmbeddings.getMessagesWithoutEmbeddings(chatId=1, modelName="B")
        assert len(differentModel) == 1
        assert differentModel[0]["message_id"] == MessageId(1)
        assert differentModel[0]["message_text"] == "stale-vec"
        # ChatMessageDict shape: chat + message + joined user fields are present.
        assert differentModel[0]["chat_id"] == 1
        assert differentModel[0]["user_id"] == 100
        assert differentModel[0]["username"] == "user100"
        assert differentModel[0]["full_name"] == "User 100"

    async def test_deleteObsoleteModelEmbeddings_vec0ShadowTables(self, testDatabase: Database) -> None:
        """deleteObsoleteModelEmbeddings does not fail on vec0 shadow tables.

        Regression: ``listTables("vec_message_embeddings_%")`` matches
        sqlite-vec internal shadow tables (``_info``, ``_chunks``,
        ``_rowids``, ``_vector_chunks00``, ``_metadatachunks00``, etc.)
        alongside the real vec0 virtual table. A DELETE on a shadow table
        with a WHERE clause referencing ``chat_id`` (a partition key column
        that exists on the real table but not on the shadow tables) raises
        ``sqlite3.OperationalError: no such column: chat_id``.

        The fix filters the ``listTables`` result to only real vec0 tables
        (names matching ``vec_message_embeddings_{N}`` where *N* is a
        positive integer). This test verifies that the method completes
        successfully even when shadow tables exist.
        """
        from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE

        if not _SQLITE_VEC_AVAILABLE:
            pytest.skip("sqlite-vec not installed")

        chatId = 1
        currentModel = "model-current"
        oldModel = "model-old"
        dimensions = 3

        # 1. Save embeddings under the old model to lazily create the
        #    vec0 table (and its shadow tables).
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId,
            messageId=MessageId(100),
            embedding=[1.0, 0.0, 0.0],
            model=oldModel,
        )
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId,
            messageId=MessageId(101),
            embedding=[0.0, 1.0, 0.0],
            model=oldModel,
        )
        # Save one embedding under the current model — this row must survive.
        await testDatabase.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId,
            messageId=MessageId(200),
            embedding=[0.0, 0.0, 1.0],
            model=currentModel,
        )

        # Verify the provider reports vector search support (no-op without it).
        sqlProvider = await testDatabase.manager.getProvider(chatId=chatId, readonly=False)
        if not await sqlProvider.isVectorSearchSupported():
            pytest.skip("sqlite-vec extension not loaded by provider")

        # Verify vec0 tables (including shadow tables) exist.
        vecTables = await sqlProvider.listTables("vec_message_embeddings_%")
        assert vecTables, "Expected vec0 tables to exist after saveMessageEmbedding"
        # The real table must be present.
        expectedTable = f"vec_message_embeddings_{dimensions}"
        assert expectedTable in vecTables, f"Expected {expectedTable} in vec0 tables"
        # Shadow tables must also exist (this is the condition that triggers the bug).
        shadowTables = [t for t in vecTables if t != expectedTable]
        assert shadowTables, "Expected vec0 shadow tables to exist"

        # 2. Call deleteObsoleteModelEmbeddings — must succeed without errors.
        success = await testDatabase.chatEmbeddings.deleteObsoleteModelEmbeddings(
            chatId=chatId,
            currentModel=currentModel,
            currentDimensions=dimensions,
        )
        assert success, "deleteObsoleteModelEmbeddings should return True"

        # 3. Verify cleanup: old-model embeddings were deleted from
        #    message_embeddings, current-model embedding survived.
        old1 = await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=chatId, messageId=MessageId(100))
        old2 = await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=chatId, messageId=MessageId(101))
        current = await testDatabase.chatEmbeddings.getMessageEmbedding(chatId=chatId, messageId=MessageId(200))
        assert old1 is None, "Old-model embedding for msg 100 should be deleted"
        assert old2 is None, "Old-model embedding for msg 101 should be deleted"
        assert current is not None, "Current-model embedding for msg 200 should survive"
        assert current["model"] == currentModel
