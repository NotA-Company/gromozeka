"""Tests for ChatUsersRepository bot_status filtering.

Pins the behavior of getUserChats() and getAllGroupChats() with botStatus
filtering. Both methods accept an optional botStatus parameter that defaults
to ChatBotStatus.ACTIVE, which excludes inaccessible chats. When botStatus
is None, all chats are returned regardless of their bot_status value.
"""

from internal.database.models import ChatBotStatus


class TestChatUsersBotStatusFiltering:
    """Tests for getUserChats and getAllGroupChats botStatus filtering behavior."""

    async def test_getUserChats_defaultActive_filtersInaccessibleChats(self, testDatabase) -> None:
        """getUserChats with default botStatus=ACTIVE excludes inaccessible chats.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        # Create chat_info entries with different bot_status values
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(100, 'Active Chat', 'active_chat', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(200, 'Inaccessible Chat', 'inaccessible_chat', 'group', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(300, 'Another Active Chat', 'another_active', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )

        # Create chat_users entries for user 100
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(100, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(200, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(300, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )

        # Call getUserChats with default botStatus (should be ACTIVE)
        chats = await testDatabase.chatUsers.getUserChats(userId=100)

        # Should only return chats with bot_status='active'
        assert len(chats) == 2
        chatIds = [chat["chat_id"] for chat in chats]
        assert 100 in chatIds
        assert 300 in chatIds
        assert 200 not in chatIds  # Inaccessible chat should be filtered out

    async def test_getUserChats_botStatusNone_returnsAllChats(self, testDatabase) -> None:
        """getUserChats with botStatus=None returns all chats including inaccessible.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        # Create chat_info entries with different bot_status values
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(100, 'Active Chat', 'active_chat', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(200, 'Inaccessible Chat', 'inaccessible_chat', 'group', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(300, 'Another Active Chat', 'another_active', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )

        # Create chat_users entries for user 100
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(100, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(200, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(300, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )

        # Call getUserChats with botStatus=None (should return all)
        chats = await testDatabase.chatUsers.getUserChats(userId=100, botStatus=None)

        # Should return all chats regardless of bot_status
        assert len(chats) == 3
        chatIds = [chat["chat_id"] for chat in chats]
        assert 100 in chatIds
        assert 200 in chatIds
        assert 300 in chatIds

    async def test_getUserChats_botStatusINACCESSIBLE_returnsOnlyInaccessible(self, testDatabase) -> None:
        """getUserChats with botStatus=INACCESSIBLE returns only inaccessible chats.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        # Create chat_info entries with different bot_status values
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(100, 'Active Chat', 'active_chat', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(200, 'Inaccessible Chat', 'inaccessible_chat', 'group', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(300, 'Another Inaccessible Chat', 'another_inaccessible', 'group', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )

        # Create chat_users entries for user 100
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(100, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(200, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(300, 100, 'user100', 'User 100', datetime('now'), datetime('now'))"
        )

        # Call getUserChats with botStatus=INACCESSIBLE
        chats = await testDatabase.chatUsers.getUserChats(userId=100, botStatus=ChatBotStatus.INACCESSIBLE)

        # Should only return chats with bot_status='inaccessible'
        assert len(chats) == 2
        chatIds = [chat["chat_id"] for chat in chats]
        assert 200 in chatIds
        assert 300 in chatIds
        assert 100 not in chatIds  # Active chat should be filtered out

    async def test_getAllGroupChats_defaultActive_filtersInaccessibleChats(self, testDatabase) -> None:
        """getAllGroupChats with default botStatus=ACTIVE excludes inaccessible chats.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        # Create chat_info entries for groups with different bot_status values
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-100, 'Active Group', 'active_group', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-200, 'Inaccessible Group', 'inaccessible_group', 'supergroup', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )
        provider = await testDatabase.manager.getProvider(readonly=False)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-300, 'Another Active Group', 'another_active', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )

        # Call getAllGroupChats with default botStatus (should be ACTIVE)
        chats = await testDatabase.chatUsers.getAllGroupChats()

        # Should only return groups with bot_status='active'
        assert len(chats) == 2
        chatIds = [chat["chat_id"] for chat in chats]
        assert -100 in chatIds
        assert -300 in chatIds
        assert -200 not in chatIds  # Inaccessible group should be filtered out

    async def test_getAllGroupChats_botStatusNone_returnsAllGroups(self, testDatabase) -> None:
        """getAllGroupChats with botStatus=None returns all groups including inaccessible.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        provider = await testDatabase.manager.getProvider(readonly=False)

        # Create chat_info entries for groups with different bot_status values
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-100, 'Active Group', 'active_group', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-200, 'Inaccessible Group', 'inaccessible_group', 'supergroup', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-300, 'Another Active Group', 'another_active', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )

        # Call getAllGroupChats with botStatus=None (should return all)
        chats = await testDatabase.chatUsers.getAllGroupChats(botStatus=None)

        # Should return all groups regardless of bot_status
        assert len(chats) == 3
        chatIds = [chat["chat_id"] for chat in chats]
        assert -100 in chatIds
        assert -200 in chatIds
        assert -300 in chatIds

    async def test_getAllGroupChats_botStatusINACCESSIBLE_returnsOnlyInaccessible(self, testDatabase) -> None:
        """getAllGroupChats with botStatus=INACCESSIBLE returns only inaccessible groups.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        provider = await testDatabase.manager.getProvider(readonly=False)

        # Create chat_info entries for groups with different bot_status values
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-100, 'Active Group', 'active_group', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-200, 'Inaccessible Group', 'inaccessible_group', 'supergroup', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-300, 'Another Inaccessible Group', 'another_inaccessible', 'group', 0, "
            "'inaccessible', datetime('now'), datetime('now'))"
        )

        # Call getAllGroupChats with botStatus=INACCESSIBLE
        chats = await testDatabase.chatUsers.getAllGroupChats(botStatus=ChatBotStatus.INACCESSIBLE)

        # Should only return groups with bot_status='inaccessible'
        assert len(chats) == 2
        chatIds = [chat["chat_id"] for chat in chats]
        assert -200 in chatIds
        assert -300 in chatIds
        assert -100 not in chatIds  # Active group should be filtered out

    async def test_getAllGroupChats_excludesPrivateAndChannels(self, testDatabase) -> None:
        """getAllGroupChats excludes private chats and channels regardless of botStatus.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        provider = await testDatabase.manager.getProvider(readonly=False)

        # Create chat_info entries for different chat types
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(100, 'Private Chat', 'private', 'private', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-100, 'Group', 'group_chat', 'group', 0, 'active', datetime('now'), "
            "datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(-200, 'Channel', 'channel', 'channel', 0, 'active', datetime('now'), "
            "datetime('now'))"
        )

        # Call getAllGroupChats with botStatus=None (should still only return groups)
        chats = await testDatabase.chatUsers.getAllGroupChats(botStatus=None)

        # Should only return groups (not private or channels)
        assert len(chats) == 1
        assert chats[0]["chat_id"] == -100

    async def test_getUserChats_emptyResultSet(self, testDatabase) -> None:
        """getUserChats returns empty list when user has no chats.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        # Don't create any chat_users entries for user 999

        # Call getUserChats with default botStatus
        chats = await testDatabase.chatUsers.getUserChats(userId=999)

        # Should return empty list
        assert chats == []

    async def test_getAllGroupChats_emptyResultSet(self, testDatabase) -> None:
        """getAllGroupChats returns empty list when no groups exist.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        # Don't create any group chat_info entries

        # Call getAllGroupChats with default botStatus
        chats = await testDatabase.chatUsers.getAllGroupChats()

        # Should return empty list
        assert chats == []

    async def test_getUserChats_returnsMessagesCount(self, testDatabase) -> None:
        """getUserChats returns messages_count field for each chat.

        Tests the U1 addendum: getUserChats should return the user's message
        count per chat via the chat_users table.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        provider = await testDatabase.manager.getProvider(readonly=False)

        # Create chat_info entries
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(100, 'Chat 1', 'chat1', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, bot_status, created_at, updated_at) "
            "VALUES "
            "(200, 'Chat 2', 'chat2', 'group', 0, 'active', "
            "datetime('now'), datetime('now'))"
        )

        # Create chat_users entries with different messages_count values
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, messages_count, created_at, updated_at) "
            "VALUES "
            "(100, 100, 'user100', 'User 100', 42, datetime('now'), datetime('now'))"
        )
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, messages_count, created_at, updated_at) "
            "VALUES "
            "(200, 100, 'user100', 'User 100', 17, datetime('now'), datetime('now'))"
        )

        # Call getUserChats
        chats = await testDatabase.chatUsers.getUserChats(userId=100)

        # Should return both chats with messages_count populated
        assert len(chats) == 2

        # Verify messages_count field is present and correct
        chatById = {chat["chat_id"]: chat for chat in chats}
        assert "messages_count" in chatById[100]
        assert chatById[100]["messages_count"] == 42
        assert "messages_count" in chatById[200]
        assert chatById[200]["messages_count"] == 17

    async def test_getUserChats_userIdJoinQualification(self, testDatabase) -> None:
        """getUserChats properly qualifies user_id in JOIN (I3-7).

        Behavior test for cu.user_id JOIN qualification: ensures that user_id
        references in the SELECT clause are properly qualified to avoid
        column ambiguity, since chat_info and chat_users are joined and
        both reference users but only chat_users has a user_id column.

        This test seeds chat_info and chat_users data, then verifies
        getUserChats returns correct rows with properly qualified columns.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        provider = await testDatabase.manager.getProvider(readonly=False)

        # Create chat_info entries (no user_id column in chat_info)
        await provider.execute(
            "INSERT INTO chat_info "
            "(chat_id, title, username, type, is_forum, created_at, updated_at) "
            "VALUES "
            "(100, 'Chat 1', 'chat1', 'group', 0, "
            "datetime('now'), datetime('now')), "
            "(200, 'Chat 2', 'chat2', 'group', 0, "
            "datetime('now'), datetime('now'))"
        )

        # Create chat_users entries with user_id = 100
        # This creates the JOIN condition linking chats to user 100
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, messages_count, created_at, updated_at) "
            "VALUES "
            "(100, 100, 'user100', 'User 100', 42, datetime('now'), datetime('now')), "
            "(200, 100, 'user100', 'User 100', 17, datetime('now'), datetime('now'))"
        )

        # Call getUserChats - this should NOT crash with "ambiguous column name: user_id"
        chats = await testDatabase.chatUsers.getUserChats(userId=100)

        # Should return both chats successfully
        assert len(chats) == 2
        chatIds = [chat["chat_id"] for chat in chats]
        assert 100 in chatIds
        assert 200 in chatIds

    async def test_getChatUserByUsername_twoRowsSameUsername_returnsMostRecent(self, testDatabase) -> None:
        """getChatUserByUsername returns the most-recent row when multiple rows have same username.

        Regression test: When two chat_users rows exist for the same username with different
        updated_at timestamps, getChatUserByUsername should return the most recent one.

        Args:
            testDatabase: Database fixture with initialized tables.
        """
        provider = await testDatabase.manager.getProvider(readonly=False)

        # Create two chat_users rows with the same username but different users and timestamps
        # Older entry (earlier updated_at)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(100, 100, '@testuser', 'Test User 100', "
            "datetime('now', '-1 hour'), datetime('now', '-1 hour'))"
        )

        # Newer entry (more recent updated_at)
        await provider.execute(
            "INSERT INTO chat_users "
            "(chat_id, user_id, username, full_name, created_at, updated_at) "
            "VALUES "
            "(100, 200, '@testuser', 'Test User 200', "
            "datetime('now'), datetime('now'))"
        )

        # Call getChatUserByUsername - should return the most recent entry
        user = await testDatabase.chatUsers.getChatUserByUsername(chatId=100, username="@testuser")

        # Should return a user
        assert user is not None

        # Should be the most recent user (user_id 200)
        assert user["user_id"] == 200
        assert user["full_name"] == "Test User 200"
