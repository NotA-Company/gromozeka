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
