"""Tests for :class:`ChatUsersRepository`.

Behavioural coverage of the per-chat user listing helper
``getChatUsers``, which returns ``ChatUserDict`` rows for a single chat
ordered by ``updated_at`` descending. Optional filters narrow the
result set: ``lastActiveDays`` and ``seenSince`` apply a time cutoff on
``updated_at``; ``limit`` caps the row count.

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
applied — no mocks.
"""

import datetime

from internal.database import Database


class TestGetChatUsersDefaultMode:
    """No filters, ordered by ``updated_at`` DESC — the base contract.

    ``seenSince`` and ``lastActiveDays`` are recognised as optional
    activity filters; both translate to a time cutoff on ``updated_at``.
    """

    @staticmethod
    async def _seedUser(db: Database, chatId: int, userId: int) -> None:
        """Insert a chat_users row."""
        await db.chatUsers.updateChatUser(
            chatId=chatId,
            userId=userId,
            username=f"user{userId}",
            fullName=f"User {userId}",
        )

    async def test_getChatUsers_default_returnsAllUsers(self, testDatabase: Database) -> None:
        """With no filters and no limit, every chat user is returned."""
        for uid in (100, 200, 300):
            await self._seedUser(testDatabase, chatId=1, userId=uid)

        users = await testDatabase.chatUsers.getChatUsers(chatId=1)

        assert sorted(u["user_id"] for u in users) == [100, 200, 300]

    async def test_getChatUsers_default_limitCapsResults(self, testDatabase: Database) -> None:
        """``limit`` caps the number of returned users in default mode."""
        for uid in range(100, 110):
            await self._seedUser(testDatabase, chatId=1, userId=uid)

        users = await testDatabase.chatUsers.getChatUsers(chatId=1, limit=3)

        assert len(users) == 3

    async def test_getChatUsers_default_seenSince(self, testDatabase: Database) -> None:
        """``seenSince`` filters to users updated after the cutoff."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = now - datetime.timedelta(days=30)

        for uid in (100, 200):
            await self._seedUser(testDatabase, chatId=1, userId=uid)

        # Push user 200's updated_at back.
        provider = await testDatabase.manager.getProvider(chatId=1, readonly=False)
        await provider.execute(
            "UPDATE chat_users SET updated_at = :ts WHERE chat_id = :chatId AND user_id = :userId",
            {"ts": old, "chatId": 1, "userId": 200},
        )

        users = await testDatabase.chatUsers.getChatUsers(chatId=1, seenSince=now - datetime.timedelta(days=1))

        # Only user 100 is "recent" enough.
        assert [u["user_id"] for u in users] == [100]

    async def test_getChatUsers_default_lastActiveDays(self, testDatabase: Database) -> None:
        """``lastActiveDays`` keeps only users whose ``updated_at`` is within the last N days."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = now - datetime.timedelta(days=30)

        for uid in (100, 200):
            await self._seedUser(testDatabase, chatId=1, userId=uid)

        # Push user 200's updated_at back.
        provider = await testDatabase.manager.getProvider(chatId=1, readonly=False)
        await provider.execute(
            "UPDATE chat_users SET updated_at = :ts WHERE chat_id = :chatId AND user_id = :userId",
            {"ts": old, "chatId": 1, "userId": 200},
        )

        # Ask for users active in the last 7 days.
        users = await testDatabase.chatUsers.getChatUsers(chatId=1, lastActiveDays=7)

        # Only user 100 is "recent" enough.
        assert [u["user_id"] for u in users] == [100]

    async def test_getChatUsers_default_minMessages(self, testDatabase: Database) -> None:
        """``minMessages`` filters users by ``messages_count``.

        Users with fewer messages than the threshold are excluded from
        the result.
        """
        await self._seedUser(testDatabase, chatId=1, userId=100)
        await self._seedUser(testDatabase, chatId=1, userId=200)

        # Set distinct messages_count values.
        provider = await testDatabase.manager.getProvider(chatId=1, readonly=False)
        await provider.execute(
            "UPDATE chat_users SET messages_count = :count WHERE chat_id = :chatId AND user_id = :userId",
            {"count": 50, "chatId": 1, "userId": 100},
        )
        await provider.execute(
            "UPDATE chat_users SET messages_count = :count WHERE chat_id = :chatId AND user_id = :userId",
            {"count": 5, "chatId": 1, "userId": 200},
        )

        users = await testDatabase.chatUsers.getChatUsers(chatId=1, minMessages=10)

        assert [u["user_id"] for u in users] == [100]

    async def test_getChatUsers_default_lastActiveDaysWinsOverSeenSince(self, testDatabase: Database) -> None:
        """When both ``lastActiveDays`` and ``seenSince`` are passed, ``lastActiveDays`` wins.

        ``lastActiveDays`` overwrites ``seenSince`` in the repository so the
        relative-day window takes precedence over the absolute datetime.
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        await self._seedUser(testDatabase, chatId=1, userId=100)
        await self._seedUser(testDatabase, chatId=1, userId=200)

        # User 100: updated_at = now - 3 days.  User 200: updated_at = now - 30 days.
        provider = await testDatabase.manager.getProvider(chatId=1, readonly=False)
        await provider.execute(
            "UPDATE chat_users SET updated_at = :ts WHERE chat_id = :chatId AND user_id = :userId",
            {"ts": now - datetime.timedelta(days=3), "chatId": 1, "userId": 100},
        )
        await provider.execute(
            "UPDATE chat_users SET updated_at = :ts WHERE chat_id = :chatId AND user_id = :userId",
            {"ts": now - datetime.timedelta(days=30), "chatId": 1, "userId": 200},
        )

        # Both lastActiveDays=7 (cutoff = now - 7) and seenSince (cutoff = now - 1)
        # are passed.  If seenSince won, user 100 (now - 3) would be excluded.
        # Since lastActiveDays wins, user 100 is included.
        users = await testDatabase.chatUsers.getChatUsers(
            chatId=1,
            lastActiveDays=7,
            seenSince=now - datetime.timedelta(days=1),
        )

        assert [u["user_id"] for u in users] == [100]


class TestDictKeysIterationSafety:
    """Regression: live ``dict_keys`` views must be materialised before iteration.

    The old multi-source aggregation pattern used
    ``self.manager._providers.keys()`` — a live view of the dict.  If
    ``getProvider`` initialises a new provider during the ``await`` inside
    the loop body, the underlying dict mutates and Python raises
    ``RuntimeError: dictionary changed size during iteration``.  The fix
    wraps the call with ``list(...)`` so the keys are snapshotted before
    the first iteration step.

    ``DatabaseManager`` uses ``__slots__`` so the monkey-patch must be
    applied at the *class* level and restored in a ``finally`` block.
    """

    @staticmethod
    def _installMutatingGetProvider(db: Database):
        """Replace ``getProvider`` (class-level) with one that adds a dummy provider on every call.

        Returns a ``(cleanup, fakeCount)`` pair.  The caller **must** invoke
        ``cleanup()`` to restore the original method.
        """
        from internal.database.manager import DatabaseManager

        original = DatabaseManager.getProvider
        fakeCount = 0

        async def getProviderThatMutates(managerSelf, *args, **kwargs):
            nonlocal fakeCount
            result = await original(managerSelf, *args, **kwargs)
            fakeCount += 1
            managerSelf._providers[f"extra_{fakeCount}"] = result
            return result

        DatabaseManager.getProvider = getProviderThatMutates  # type: ignore[method-assign]

        def cleanup():
            DatabaseManager.getProvider = original

        return cleanup

    async def test_getUserIdByUserName_dictKeysIterationSafe(self, testDatabase: Database) -> None:
        """``getUserIdByUserName`` with ``dataSource=None`` must not raise RuntimeError.

        Seeds a single user with the target username, then calls the method
        with a mutating ``getProvider`` that simulates lazy provider
        initialisation during the iteration.  Before the fix this raised
        ``RuntimeError``; after the fix it completes normally.
        """
        # ``getUserIdByUserName`` queries ``chat_info.username``, not
        # ``chat_users.username``, so seed both tables.
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            """INSERT INTO chat_info (chat_id, username, type, created_at, updated_at)
               VALUES (:chatId, :username, 'private', :now, :now)""",
            {"chatId": 12345, "username": "botowner", "now": "2026-01-01T00:00:00"},
        )
        await testDatabase.chatUsers.updateChatUser(
            chatId=12345,
            userId=100,
            username="botowner",
            fullName="Bot Owner",
        )

        cleanup = self._installMutatingGetProvider(testDatabase)
        try:
            # This must not raise RuntimeError
            userIds = await testDatabase.chatUsers.getUserIdByUserName("botowner")
            assert 12345 in userIds
        finally:
            cleanup()

    async def test_getUserChats_dictKeysIterationSafe(self, testDatabase: Database) -> None:
        """``getUserChats`` with ``dataSource=None`` must not raise RuntimeError."""
        # Create a chat_info row so the JOIN produces results
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            """INSERT INTO chat_info (chat_id, username, type, created_at, updated_at)
               VALUES (:chatId, :username, 'private', :now, :now)""",
            {"chatId": 12345, "username": "botowner", "now": "2026-01-01T00:00:00"},
        )
        await testDatabase.chatUsers.updateChatUser(
            chatId=12345,
            userId=100,
            username="botowner",
            fullName="Bot Owner",
        )

        cleanup = self._installMutatingGetProvider(testDatabase)
        try:
            chats = await testDatabase.chatUsers.getUserChats(userId=100)
            assert any(c["chat_id"] == 12345 for c in chats)
        finally:
            cleanup()

    async def test_getAllGroupChats_dictKeysIterationSafe(self, testDatabase: Database) -> None:
        """``getAllGroupChats`` with ``dataSource=None`` must not raise RuntimeError."""
        cleanup = self._installMutatingGetProvider(testDatabase)
        try:
            chats = await testDatabase.chatUsers.getAllGroupChats()
            assert isinstance(chats, list)
        finally:
            cleanup()
