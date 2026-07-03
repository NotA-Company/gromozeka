"""Tests for :class:`DeleteFromUserMessageHandler`.

The handler is a Telegram-only auto-deleter: it reads the per-chat
``ChatSettingsKey.DELETE_AUTHOR_LIST`` setting (a JSON array of user IDs
and/or usernames) and deletes any incoming message whose author — by ID
or lowercased username — is in that list. Forwarded messages are matched
against the forward origin's author rather than the reposter.

This module covers the two layers of the handler in isolation:

* ``newMessageHandler`` — the per-message decision pipeline (provider
  gate → list lookup → author extraction → delete / skip / error).
* ``_getAuthorList`` — the JSON parser behind the list setting, including
  type filtering (bool/float/dict/None dropped), invalid JSON, and the
  non-list (e.g. dict) shape.

All deps are stubbed at the instance level so the tests never touch a
real bot, cache, or database. The handler is constructed with the real
singletons (the autouse ``resetLlmServiceSingleton`` /
``resetProxyHelperSingleton`` fixtures keep them fresh per test), then
``getChatSettings`` and ``deleteMessage`` are replaced with
``AsyncMock`` instances.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
import telegram

from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.common.handlers.delete_from_user import DeleteFromUserMessageHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
)
from internal.database.models import MessageCategory

# Module under test for log capture.
_HANDLER_LOGGER_NAME = "internal.bot.common.handlers.delete_from_user"

# Chat id used by every test's ensured message; arbitrary but >0 so PRIVATE.
_DEFAULT_CHAT_ID = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager() -> Mock:
    """Build a minimal ``ConfigManager`` stub for the handler constructor.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` returning a token/owners dict
        (the only field ``BaseBotHandler.__init__`` reads from the config).
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    return cm


def _makeDatabase() -> Mock:
    """Build a ``Database`` stub.

    The delete/list paths exercised here override ``getChatSettings`` and
    ``deleteMessage`` at the instance level, so the database itself is
    never reached; a bare ``Mock`` is sufficient.

    Returns:
        ``Mock`` with no pre-wired repositories (tests that need them
        assign attributes directly).
    """
    return Mock()


def _chatSettingsWithAuthorList(authorListJson: str) -> ChatSettingsDict:
    """Build a chat-settings dict carrying a ``DELETE_AUTHOR_LIST`` value.

    Args:
        authorListJson: Raw JSON string stored as the setting value
            (e.g. ``'[12345]'``, ``''``, ``'not json'``).

    Returns:
        Mapping with the single key the handler reads.
    """
    return {ChatSettingsKey.DELETE_AUTHOR_LIST: ChatSettingsValue(authorListJson)}


def _makeHandler(
    *,
    authorListJson: Optional[str] = None,
    botProvider: BotProvider = BotProvider.TELEGRAM,
) -> Tuple[DeleteFromUserMessageHandler, Dict[str, Any]]:
    """Construct a :class:`DeleteFromUserMessageHandler` with stubbed deps.

    ``getChatSettings`` is stubbed to return a settings dict whose
    ``DELETE_AUTHOR_LIST`` is *authorListJson* (empty string when
    ``None``). ``deleteMessage`` is stubbed as a no-op ``AsyncMock`` so
    tests can both drive the success path and assert on call counts.

    Args:
        authorListJson: Raw JSON for ``DELETE_AUTHOR_LIST`` (default
            ``""`` meaning "not configured").
        botProvider: Provider to construct the handler with (default
            ``TELEGRAM``). Tests that exercise the provider gate can
            either pass ``BotProvider.MAX`` here or reassign
            ``handler.botProvider`` after construction.

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` exposes the injected
        ``getChatSettings`` and ``deleteMessage`` stubs plus the
        underlying config/database mocks for direct access.
    """
    handler = DeleteFromUserMessageHandler(  # type: ignore[call-arg]
        configManager=_makeConfigManager(),
        database=_makeDatabase(),
        botProvider=botProvider,
    )

    settingsJson = authorListJson if authorListJson is not None else ""
    getChatSettingsMock = AsyncMock(return_value=_chatSettingsWithAuthorList(settingsJson))
    cast(Any, handler).getChatSettings = getChatSettingsMock

    deleteMessageMock = AsyncMock(return_value=True)
    cast(Any, handler).deleteMessage = deleteMessageMock  # type: ignore[method-assign]

    mocks: Dict[str, Any] = {
        "getChatSettings": getChatSettingsMock,
        "deleteMessage": deleteMessageMock,
    }
    return handler, mocks


def _makeTelegramMessage(
    *,
    fromUserId: int = 0,
    fromUserFullName: str = "",
    fromUserName: str = "",
    senderChat: Optional[Mock] = None,
    forwardOrigin: Optional[Mock] = None,
) -> MagicMock:
    """Build a mock Telegram :class:`telegram.Message` for author extraction.

    The mock is ``spec``-restricted to ``telegram.Message`` so the
    handler's ``isinstance(message, telegram.Message)`` guard passes.
    ``_getMessageAuthor`` checks ``forward_origin`` first (must be truthy
    for the forward path) and only then falls back to ``sender_chat`` /
    ``from_user``.

    * Forward path — pass *forwardOrigin*: it is assigned to
      ``msg.forward_origin`` and ``from_user`` / ``sender_chat`` are left
      untouched (the handler returns early on a truthy ``forward_origin``
      so they are never read).
    * Non-forward path — *forwardOrigin* stays ``None`` so
      ``forward_origin`` is forced falsy; *senderChat* / *from_user* then
      drive the sender branch.

    ``MessageSender.fromTelegramUser`` reads ``user.id``, ``user.full_name``
    and ``user.name`` — *not* ``user.username`` — so the *fromUserName*
    argument controls the resulting ``sender.username`` (which the handler
    lowercases before matching). Setting ``fromUserId = 0`` makes the
    resulting ``sender.id`` falsy so the ID branch of the match is
    skipped and the username branch is exercised in isolation.

    Args:
        fromUserId: ``from_user.id`` (default 0 → falsy → ID branch skipped).
        fromUserFullName: ``from_user.full_name`` (default empty).
        fromUserName: ``from_user.name`` → becomes ``sender.username``
            (default empty → falsy → username branch skipped).
        senderChat: When provided (and no *forwardOrigin*), ``sender_chat``
            is set to this mock and ``from_user`` to ``None`` so the
            chat-author branch runs.
        forwardOrigin: When provided, ``forward_origin`` is set to this
            truthy mock and the sender branches are bypassed entirely —
            build it with one of the ``_makeOrigin*`` helpers below.

    Returns:
        ``MagicMock`` restricted to the ``telegram.Message`` interface.
    """
    msg = MagicMock(spec=telegram.Message)

    if forwardOrigin is not None:
        # Forward path: handler inspects forward_origin and returns early,
        # so from_user / sender_chat are never accessed.
        msg.forward_origin = forwardOrigin
        return msg

    # Non-forwarded message: forward_origin must be falsy.
    msg.forward_origin = None

    if senderChat is not None:
        msg.sender_chat = senderChat
        msg.from_user = None
    else:
        msg.sender_chat = None
        userMock = MagicMock()
        userMock.id = fromUserId
        userMock.full_name = fromUserFullName
        # ``fromTelegramUser`` reads ``user.name`` (not ``user.username``).
        userMock.name = fromUserName
        msg.from_user = userMock

    return msg


# ---------------------------------------------------------------------------
# Forward-origin builders
# ---------------------------------------------------------------------------


def _makeOriginUser(*, userId: int, username: str = "") -> MagicMock:
    """Build a mock :class:`telegram.MessageOriginUser`.

    The handler reads ``sender_user.id`` and ``sender_user.name`` (the
    python-telegram-bot ``User.name`` property, which returns
    ``"@{username}"`` when a username is set, else the display name). The
    username-branch of the match only fires for the ``@``-prefixed form, so
    we mirror that here. Pass *userId=0* to keep the id falsy so only the
    username branch of the match is exercised.

    Args:
        userId: ``sender_user.id``.
        username: ``sender_user.username`` (default empty). Mirrored into
            ``sender_user.name`` as ``"@{username}"`` to match PTB semantics.

    Returns:
        ``MagicMock`` spec'd to ``telegram.MessageOriginUser``.
    """
    origin = MagicMock(spec=telegram.MessageOriginUser)
    origin.sender_user = MagicMock()
    origin.sender_user.id = userId
    origin.sender_user.username = username
    origin.sender_user.name = f"@{username}" if username else ""
    return origin


def _makeOriginChat(*, chatId: int, username: str = "") -> MagicMock:
    """Build a mock :class:`telegram.MessageOriginChat`.

    The handler reads ``sender_chat.id`` and ``sender_chat.username``.

    Args:
        chatId: ``sender_chat.id``.
        username: ``sender_chat.username`` (default empty).

    Returns:
        ``MagicMock`` spec'd to ``telegram.MessageOriginChat``.
    """
    origin = MagicMock(spec=telegram.MessageOriginChat)
    origin.sender_chat = MagicMock()
    origin.sender_chat.id = chatId
    origin.sender_chat.username = username
    return origin


def _makeOriginChannel(*, chatId: int, username: str = "") -> MagicMock:
    """Build a mock :class:`telegram.MessageOriginChannel`.

    The handler reads ``chat.id`` and ``chat.username``.

    Args:
        chatId: ``chat.id``.
        username: ``chat.username`` (default empty).

    Returns:
        ``MagicMock`` spec'd to ``telegram.MessageOriginChannel``.
    """
    origin = MagicMock(spec=telegram.MessageOriginChannel)
    origin.chat = MagicMock()
    origin.chat.id = chatId
    origin.chat.username = username
    return origin


def _makeOriginHiddenUser(*, username: str) -> MagicMock:
    """Build a mock :class:`telegram.MessageOriginHiddenUser`.

    The handler reads only ``sender_user_name`` (the id stays 0), so a
    hidden forward can only ever match by username.

    Args:
        username: ``sender_user_name`` exposed by the origin.

    Returns:
        ``MagicMock`` spec'd to ``telegram.MessageOriginHiddenUser``.
    """
    origin = MagicMock(spec=telegram.MessageOriginHiddenUser)
    origin.sender_user_name = username
    return origin


def _makeReplyMessage(
    *,
    fromUserId: int = 0,
    fromUserName: str = "",
    fromUserFullName: str = "",
    senderChatId: int = 0,
    senderChatUsername: str = "",
    forwardOrigin: Optional[Mock] = None,
) -> MagicMock:
    """Build a mock Telegram message suitable as a reply-to target.

    Thin convenience wrapper around :func:`_makeTelegramMessage` that accepts
    primitives (ids / names) instead of pre-built chat / user mocks. When
    *senderChatId* is non-zero the sender-chat branch is selected; when
    *forwardOrigin* is provided the forward path runs; otherwise the
    *from_user* branch is used. The returned mock is ``spec``-restricted to
    ``telegram.Message`` so ``isinstance`` checks pass.

    Args:
        fromUserId: ``from_user.id`` (default 0 → falsy).
        fromUserName: ``from_user.name`` → becomes ``sender.username``
            (default empty).
        fromUserFullName: ``from_user.full_name`` → becomes ``sender.name``
            (default empty).
        senderChatId: When non-zero, builds a ``sender_chat`` with this id.
        senderChatUsername: ``sender_chat.username`` **without** the ``@``
            prefix (:meth:`MessageSender.fromTelegramChat` adds it).
        forwardOrigin: When provided, the forward path is selected and the
            sender branches are bypassed.

    Returns:
        ``MagicMock`` restricted to the ``telegram.Message`` interface.
    """
    if forwardOrigin is not None:
        return _makeTelegramMessage(forwardOrigin=forwardOrigin)

    if senderChatId:
        chat = MagicMock()
        chat.id = senderChatId
        chat.username = senderChatUsername
        chat.effective_name = senderChatUsername or "Chat"
        return _makeTelegramMessage(senderChat=chat)

    return _makeTelegramMessage(
        fromUserId=fromUserId,
        fromUserName=fromUserName,
        fromUserFullName=fromUserFullName,
    )


def _makeEnsuredMessage(tgMessage: Any, *, chatId: int = _DEFAULT_CHAT_ID) -> Mock:
    """Build a mock :class:`EnsuredMessage` carrying a base Telegram message.

    Args:
        tgMessage: Object returned by ``getBaseMessage()`` (a
            ``telegram.Message`` spec'd mock, or a plain ``Mock`` for the
            non-Telegram-base-message tests).
        chatId: Recipient chat id (default 100, >0 so PRIVATE).

    Returns:
        ``Mock`` with ``recipient`` and ``getBaseMessage`` wired up.
    """
    em = Mock(spec=EnsuredMessage)
    em.recipient = MessageRecipient(id=chatId, chatType=ChatType.PRIVATE)
    em.getBaseMessage = Mock(return_value=tgMessage)
    return em


def _makeCommandMessage(replyMessage: Optional[Any] = None) -> MagicMock:
    """Build a mock Telegram command message with a reply-to target.

    The returned mock is ``spec``-restricted to ``telegram.Message`` so the
    handler's ``isinstance`` guard passes. Only ``reply_to_message`` is
    set to *replyMessage* (``None`` for the non-reply case); the command
    message's own sender attributes are irrelevant since the command
    extracts the author from the *reply*.

    Args:
        replyMessage: The mock message to assign to ``reply_to_message``,
            or ``None`` for the no-reply case.

    Returns:
        ``MagicMock`` restricted to the ``telegram.Message`` interface.
    """
    msg = _makeTelegramMessage()
    msg.reply_to_message = replyMessage
    return msg


def _makeCommandHandler(
    *,
    authorListJson: Optional[str] = None,
    isAdmin: bool = True,
    botProvider: BotProvider = BotProvider.TELEGRAM,
) -> Tuple[DeleteFromUserMessageHandler, Dict[str, Any]]:
    """Construct a handler pre-wired for command-handler tests.

    Extends :func:`_makeHandler` by also stubbing the instance methods the
    command methods call — ``isAdmin``, ``setChatSetting``, and
    ``sendMessage`` — so tests can drive the happy path and assert on call
    args without touching a real bot.

    Args:
        authorListJson: Raw JSON for ``DELETE_AUTHOR_LIST`` (default ``""``).
        isAdmin: Return value for the ``isAdmin`` stub (default ``True``).
        botProvider: Provider to construct the handler with (default
            ``TELEGRAM``).

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` exposes the inherited
        ``getChatSettings`` / ``deleteMessage`` stubs plus ``isAdmin``,
        ``setChatSetting``, and ``sendMessage``.
    """
    handler, mocks = _makeHandler(authorListJson=authorListJson, botProvider=botProvider)

    isAdminMock = AsyncMock(return_value=isAdmin)
    setChatSettingMock = AsyncMock()
    sendMessageMock = AsyncMock(return_value=[])

    cast(Any, handler).isAdmin = isAdminMock  # type: ignore[method-assign]
    cast(Any, handler).setChatSetting = setChatSettingMock  # type: ignore[method-assign]
    cast(Any, handler).sendMessage = sendMessageMock  # type: ignore[method-assign]

    mocks["isAdmin"] = isAdminMock
    mocks["setChatSetting"] = setChatSettingMock
    mocks["sendMessage"] = sendMessageMock
    return handler, mocks


# ---------------------------------------------------------------------------
# Tests: newMessageHandler
# ---------------------------------------------------------------------------


class TestNewMessageHandler:
    """Tests for :meth:`DeleteFromUserMessageHandler.newMessageHandler`."""

    async def test_deleteWhenAuthorIdMatches(self) -> None:
        """Sender's user ID is in the list → message deleted, FINAL returned.

        The author list contains the numeric user id; ``_getMessageAuthor``
        extracts ``sender.id`` from ``from_user`` and the ID branch of the
        match fires. ``deleteMessage`` must be awaited exactly once and
        the handler returns ``FINAL`` so no further handler runs.
        """
        handler, mocks = _makeHandler(authorListJson="[12345]")
        tgMessage = _makeTelegramMessage(fromUserId=12345, fromUserName="someoneElse")
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.FINAL
        mocks["deleteMessage"].assert_awaited_once_with(ensured)

    async def test_deleteWhenAuthorUsernameMatches(self) -> None:
        """Sender's lowercased username is in the list → deleted, FINAL.

        ``from_user.name`` is ``"TestUser"`` (becomes ``sender.username``);
        the list stores ``"testuser"``. The handler lowercases the
        username before matching so the comparison is case-insensitive.
        The user id (0) is deliberately absent from the list so only the
        username branch is exercised.
        """
        handler, mocks = _makeHandler(authorListJson='["testuser"]')
        tgMessage = _makeTelegramMessage(fromUserId=0, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.FINAL
        mocks["deleteMessage"].assert_awaited_once_with(ensured)

    async def test_skipWhenAuthorNotInList(self) -> None:
        """Sender id and username are both absent from the list → SKIPPED.

        No deletion must occur. Guards against the handler deleting a
        message merely because a (non-empty) list exists.
        """
        handler, mocks = _makeHandler(authorListJson="[99999]")
        tgMessage = _makeTelegramMessage(fromUserId=12345, fromUserName="testuser")
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mocks["deleteMessage"].assert_not_called()

    async def test_skipWhenAuthorListEmpty(self) -> None:
        """An empty JSON array ``[]`` → SKIPPED, no deletion.

        A configured-but-empty list must short-circuit before author
        extraction rather than attempting to match against nothing.
        """
        handler, mocks = _makeHandler(authorListJson="[]")
        tgMessage = _makeTelegramMessage(fromUserId=12345, fromUserName="testuser")
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mocks["deleteMessage"].assert_not_called()

    async def test_skipWhenSettingEmptyString(self) -> None:
        """A blank ``delete-author-list`` value → SKIPPED, no deletion.

        The "not configured" state is stored as an empty string;
        ``_getAuthorList`` returns ``[]`` for it and the handler skips.
        """
        handler, mocks = _makeHandler(authorListJson="")
        tgMessage = _makeTelegramMessage(fromUserId=12345, fromUserName="testuser")
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mocks["deleteMessage"].assert_not_called()

    async def test_skipWhenNonTelegramProvider(self, caplog: pytest.LogCaptureFixture) -> None:
        """Bot provider is MAX → SKIPPED immediately, no deletion.

        The handler is Telegram-only; the provider gate fires before any
        list lookup or deletion, logging a warning. The base message is
        still a real ``telegram.Message`` mock so the gate that triggers
        is specifically the provider check.
        """
        handler, mocks = _makeHandler(authorListJson="[12345]")
        # Flip provider after construction to isolate the provider gate.
        handler.botProvider = BotProvider.MAX  # type: ignore[attr-defined]
        tgMessage = _makeTelegramMessage(fromUserId=12345, fromUserName="testuser")
        ensured = _makeEnsuredMessage(tgMessage)

        with caplog.at_level(logging.WARNING, logger=_HANDLER_LOGGER_NAME):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mocks["deleteMessage"].assert_not_called()
        assert any("supports Telegram only for now" in rec.message for rec in caplog.records)

    async def test_skipWhenBaseMessageIsNotTelegramMessage(self) -> None:
        """``getBaseMessage()`` returns a non-``telegram.Message`` → SKIPPED.

        Distinct from the provider gate: the provider is Telegram but the
        base message is not a ``telegram.Message`` instance (e.g. a Max
        message object slipped through). The ``isinstance`` guard must
        fire and the handler must skip without touching the list.
        """
        handler, mocks = _makeHandler(authorListJson="[12345]")
        # A plain Mock is not an instance of telegram.Message.
        ensured = _makeEnsuredMessage(Mock())

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mocks["deleteMessage"].assert_not_called()

    async def test_returnErrorWhenDeletionFails(self, caplog: pytest.LogCaptureFixture) -> None:
        """``deleteMessage`` raises → ERROR returned, exception swallowed.

        Deletion failures (permissions, already-deleted, network) must be
        caught and surfaced as ``HandlerResultStatus.ERROR`` rather than
        propagating into the message pipeline, with the failure logged at
        ERROR level.
        """
        handler, mocks = _makeHandler(authorListJson="[12345]")
        mocks["deleteMessage"] = AsyncMock(side_effect=RuntimeError("test deletion failure"))
        cast(Any, handler).deleteMessage = mocks["deleteMessage"]  # type: ignore[method-assign]
        tgMessage = _makeTelegramMessage(fromUserId=12345, fromUserName="someoneElse")
        ensured = _makeEnsuredMessage(tgMessage)

        with caplog.at_level(logging.ERROR, logger=_HANDLER_LOGGER_NAME):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.ERROR
        mocks["deleteMessage"].assert_awaited_once_with(ensured)
        assert any("Error while deleting message" in rec.message for rec in caplog.records)

    async def test_deleteWhenSenderChatIdMatches(self) -> None:
        """A message authored by ``sender_chat`` → matched by chat id.

        No ``from_user`` and no ``forward_origin``; the author comes from
        ``sender_chat`` via :meth:`MessageSender.fromTelegramChat`. The
        list holds the numeric chat id (77777), so the id branch of the
        match fires and the message is deleted.
        """
        handler, mocks = _makeHandler(authorListJson="[77777]")
        chat = MagicMock()
        chat.id = 77777
        chat.username = "TestChannel"
        chat.effective_name = "Test Channel"
        tgMessage = _makeTelegramMessage(senderChat=chat)
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.FINAL
        mocks["deleteMessage"].assert_awaited_once_with(ensured)

    async def test_deleteWhenSenderChatUsernameMatches(self) -> None:
        """A ``sender_chat`` author matched by its ``@``-prefixed username.

        ``fromTelegramChat`` prefixes the chat username with ``@``, so a
        chat whose ``username`` is ``"TestChannel"`` yields
        ``sender.username == "@TestChannel"``; lowercased, that is
        ``"@testchannel"`` which is what the list stores. The chat id
        (88888) is deliberately absent from the list so the id branch is
        skipped and the username branch is exercised in isolation.
        """
        handler, mocks = _makeHandler(authorListJson='["@testchannel"]')
        chat = MagicMock()
        chat.id = 88888
        chat.username = "TestChannel"
        chat.effective_name = "Test Channel"
        tgMessage = _makeTelegramMessage(senderChat=chat)
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.FINAL
        mocks["deleteMessage"].assert_awaited_once_with(ensured)


# ---------------------------------------------------------------------------
# Tests: forward-origin author extraction (_getMessageAuthor forward path)
# ---------------------------------------------------------------------------


class TestForwardOriginAuthorMatching:
    """Forward-origin author extraction via ``_getMessageAuthor``.

    For forwarded messages the handler matches the *original* author (read
    from ``forward_origin``) rather than the reposter. Each origin flavour
    exposes id/username on a different attribute; the parametrised cases
    below drive every flavour through ``newMessageHandler`` and assert
    delete/FINAL when the origin author is in the list and SKIPPED
    otherwise.
    """

    @pytest.mark.parametrize(
        "originBuilder, authorListJson, expectedResult",
        [
            # --- MessageOriginUser ---
            pytest.param(
                lambda: _makeOriginUser(userId=12345, username="testuser"),
                "[12345]",
                HandlerResultStatus.FINAL,
                id="originUser-matchById",
            ),
            pytest.param(
                lambda: _makeOriginUser(userId=99999, username="testuser"),
                '["@testuser"]',
                HandlerResultStatus.FINAL,
                id="originUser-matchByUsername",
            ),
            pytest.param(
                lambda: _makeOriginUser(userId=99999, username="other"),
                "[12345]",
                HandlerResultStatus.SKIPPED,
                id="originUser-skip",
            ),
            # --- MessageOriginChat ---
            pytest.param(
                lambda: _makeOriginChat(chatId=67890, username="chatuser"),
                "[67890]",
                HandlerResultStatus.FINAL,
                id="originChat-matchById",
            ),
            pytest.param(
                lambda: _makeOriginChat(chatId=99999, username="chatuser"),
                '["@chatuser"]',
                HandlerResultStatus.FINAL,
                id="originChat-matchByUsername",
            ),
            pytest.param(
                lambda: _makeOriginChat(chatId=99999, username="other"),
                "[67890]",
                HandlerResultStatus.SKIPPED,
                id="originChat-skip",
            ),
            # --- MessageOriginChannel ---
            pytest.param(
                lambda: _makeOriginChannel(chatId=11111, username="channeluser"),
                "[11111]",
                HandlerResultStatus.FINAL,
                id="originChannel-matchById",
            ),
            pytest.param(
                lambda: _makeOriginChannel(chatId=99999, username="channeluser"),
                '["@channeluser"]',
                HandlerResultStatus.FINAL,
                id="originChannel-matchByUsername",
            ),
            pytest.param(
                lambda: _makeOriginChannel(chatId=99999, username="other"),
                "[11111]",
                HandlerResultStatus.SKIPPED,
                id="originChannel-skip",
            ),
            # --- MessageOriginHiddenUser (id is always 0 → username-only) ---
            pytest.param(
                lambda: _makeOriginHiddenUser(username="hiddenuser"),
                '["hiddenuser"]',
                HandlerResultStatus.FINAL,
                id="originHiddenUser-matchByUsername",
            ),
            pytest.param(
                lambda: _makeOriginHiddenUser(username="other"),
                '["hiddenuser"]',
                HandlerResultStatus.SKIPPED,
                id="originHiddenUser-skip",
            ),
        ],
    )
    async def test_forwardOriginAuthorMatching(
        self,
        originBuilder: Any,
        authorListJson: str,
        expectedResult: HandlerResultStatus,
    ) -> None:
        """Forwarded-message author is matched against the delete list.

        The mock message carries the parametrised ``forward_origin``; the
        handler must extract the original author from it (ignoring
        ``from_user`` / ``sender_chat``) and delete iff that author is in
        the list.

        Args:
            originBuilder: Zero-arg callable producing the forward-origin mock.
            authorListJson: Raw JSON stored as ``DELETE_AUTHOR_LIST``.
            expectedResult: Expected :class:`HandlerResultStatus`.

        Returns:
            None.
        """
        handler, mocks = _makeHandler(authorListJson=authorListJson)
        tgMessage = _makeTelegramMessage(forwardOrigin=originBuilder())
        ensured = _makeEnsuredMessage(tgMessage)

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is expectedResult
        if expectedResult is HandlerResultStatus.FINAL:
            mocks["deleteMessage"].assert_awaited_once_with(ensured)
        else:
            mocks["deleteMessage"].assert_not_called()

    async def test_unknownForwardOriginReturnsSkipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unrecognised ``forward_origin`` type → SKIPPED + error logged.

        The origin is a plain :class:`MagicMock` (no spec), so it is not an
        instance of any known ``telegram.MessageOrigin*`` class: the
        ``else`` branch logs an error and ``_getMessageAuthor`` returns an
        empty ``MessageSender(0, "", "")``. With a falsy id and username
        nothing can match, so the handler skips without deleting.
        """
        handler, mocks = _makeHandler(authorListJson="[12345]")
        tgMessage = _makeTelegramMessage(forwardOrigin=MagicMock())
        ensured = _makeEnsuredMessage(tgMessage)

        with caplog.at_level(logging.ERROR, logger=_HANDLER_LOGGER_NAME):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mocks["deleteMessage"].assert_not_called()
        assert any("Unknown forwardOrigin" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Tests: _getAuthorList
# ---------------------------------------------------------------------------


class TestGetAuthorList:
    """Tests for :meth:`DeleteFromUserMessageHandler._getAuthorList`."""

    async def test_validMixedTypesPreserved(self) -> None:
        """A JSON array of ints and strs is returned verbatim.

        ``int`` entries stay ``int`` and ``str`` entries stay ``str``;
        both are valid author identifiers and pass the type filter.
        """
        handler, _mocks = _makeHandler(authorListJson='[123, "user"]')

        result = await handler._getAuthorList(_DEFAULT_CHAT_ID)  # type: ignore[attr-defined]

        assert result == [123, "user"]
        assert isinstance(result[0], int)
        assert isinstance(result[1], str)

    async def test_invalidTypesFilteredAndWarned(self, caplog: pytest.LogCaptureFixture) -> None:
        """bool / float / dict / None entries are dropped and a warning logged.

        The JSON ``[123, {"key": "val"}, true, null, 45.0]`` contains
        exactly one valid entry (``123``). ``bool`` is explicitly excluded
        even though ``isinstance(True, int)`` is ``True`` in Python, so
        ``true`` is filtered. A warning must be emitted because the
        filtered length differs from the parsed length.
        """
        handler, _mocks = _makeHandler(authorListJson='[123, {"key": "val"}, true, null, 45.0]')

        with caplog.at_level(logging.WARNING, logger=_HANDLER_LOGGER_NAME):
            result = await handler._getAuthorList(_DEFAULT_CHAT_ID)  # type: ignore[attr-defined]

        assert result == [123]
        assert any("contained invalid entries" in rec.message for rec in caplog.records)

    async def test_invalidJsonReturnsEmptyAndLogsError(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unparseable JSON → empty list and an error logged.

        A ``json.JSONDecodeError`` is caught (not propagated); the handler
        treats a corrupt setting as "no authors" so it never blocks the
        message pipeline.
        """
        handler, _mocks = _makeHandler(authorListJson="not a valid json string")

        with caplog.at_level(logging.ERROR, logger=_HANDLER_LOGGER_NAME):
            result = await handler._getAuthorList(_DEFAULT_CHAT_ID)  # type: ignore[attr-defined]

        assert result == []
        assert any("is not a valid JSON" in rec.message for rec in caplog.records)

    async def test_dictShapeReturnsEmptyAndLogsError(self, caplog: pytest.LogCaptureFixture) -> None:
        """A JSON object (not an array) → empty list and an error logged.

        The setting must be a JSON array; a dict shape raises a
        ``ValueError`` internally which is caught by the generic
        ``except Exception`` branch and logged.
        """
        handler, _mocks = _makeHandler(authorListJson='{"123": "user"}')

        with caplog.at_level(logging.ERROR, logger=_HANDLER_LOGGER_NAME):
            result = await handler._getAuthorList(_DEFAULT_CHAT_ID)  # type: ignore[attr-defined]

        assert result == []
        assert any("not a list" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Tests: command handlers (set / unset / dump)
# ---------------------------------------------------------------------------


async def _callCommand(
    handler: DeleteFromUserMessageHandler,
    method: str,
    ensured: Mock,
    args: str = "",
) -> None:
    """Invoke a decorated command method past pyright's unbound-signature view.

    ``commandHandlerV2`` resolves the method's type to a ``Callable[…]``
    alias that pyright treats as positional-only, so keyword-argument calls
    flag as errors. The bound method itself works fine at runtime; routing
    through ``cast(Any, …)`` silences the false positive. The *command*
    argument is derived from *method* by stripping the ``_command`` suffix.

    Args:
        handler: Handler under test.
        method: Name of the command method (e.g. ``"set_delete_author_command"``).
        ensured: The ensured message to pass as ``ensuredMessage``.
        args: Raw command-arguments string (default ``""``).

    Returns:
        None.
    """
    command = method.removesuffix("_command")
    boundMethod = getattr(cast(Any, handler), method)
    await boundMethod(
        ensuredMessage=ensured,
        command=command,
        args=args,
        UpdateObj=MagicMock(),
        typingManager=None,
    )


class TestCommandHandlers:
    """Tests for the three ``@commandHandlerV2`` command methods.

    Covers ``set_delete_author_command``, ``unset_delete_author_command``,
    and ``dump_delete_authors_command`` — the admin-facing configuration
    surface. Each test builds a handler via :func:`_makeCommandHandler`
    (which stubs ``isAdmin`` / ``setChatSetting`` / ``sendMessage`` in
    addition to the ``getChatSettings`` / ``deleteMessage`` stubs from
    :func:`_makeHandler`) and drives the command through
    :func:`_callCommand`.
    """

    # ------------------------------------------------------------------
    # set_delete_author_command
    # ------------------------------------------------------------------

    async def test_setAuthor_replyWithFromUser(self) -> None:
        """Reply authored by ``from_user`` → both id and username stored.

        The reply message has ``from_user.id=12345`` and
        ``from_user.name="TestUser"``; ``_getMessageAuthor`` extracts
        ``MessageSender(12345, …, "TestUser")``. The command appends the
        numeric id and the lowercased username to the (empty) list, so the
        stored setting is ``[12345, "testuser"]`` and the reply is "Готово".
        """
        handler, mocks = _makeCommandHandler()
        replyMessage = _makeReplyMessage(fromUserId=12345, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "set_delete_author_command", ensured)

        setCall = mocks["setChatSetting"].await_args
        assert setCall.args[0] == _DEFAULT_CHAT_ID
        assert setCall.args[1] == ChatSettingsKey.DELETE_AUTHOR_LIST
        storedList = json.loads(setCall.args[2].value)
        assert storedList == [12345, "testuser"]

        sendCall = mocks["sendMessage"].await_args
        assert sendCall.kwargs["messageText"] == "Готово"

    async def test_setAuthor_replyWithSenderChat(self) -> None:
        """Reply authored by ``sender_chat`` → chat id and @-username stored.

        The reply has ``sender_chat.id=77777`` and
        ``sender_chat.username="TestChannel"`` (without ``@`` —
        ``fromTelegramChat`` adds the prefix). The stored list is
        ``[77777, "@testchannel"]``.
        """
        handler, mocks = _makeCommandHandler()
        replyMessage = _makeReplyMessage(senderChatId=77777, senderChatUsername="TestChannel")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "set_delete_author_command", ensured)

        setCall = mocks["setChatSetting"].await_args
        storedList = json.loads(setCall.args[2].value)
        assert storedList == [77777, "@testchannel"]

        sendCall = mocks["sendMessage"].await_args
        assert sendCall.kwargs["messageText"] == "Готово"

    async def test_setAuthor_nonReply(self) -> None:
        """No ``reply_to_message`` → error, ``setChatSetting`` not called.

        The command must be invoked as a reply; without a target message
        the handler bails immediately with a usage error.
        """
        handler, mocks = _makeCommandHandler()
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage=None))

        await _callCommand(handler, "set_delete_author_command", ensured)

        sendCall = mocks["sendMessage"].await_args
        assert "Команда должна быть ответом на сообщение." in sendCall.kwargs["messageText"]
        mocks["setChatSetting"].assert_not_called()

    async def test_setAuthor_nonAdmin(self) -> None:
        """Caller is not an admin → permission error, no setting change.

        ``isAdmin`` returns False; the handler must reject before touching
        the author list.
        """
        handler, mocks = _makeCommandHandler(isAdmin=False)
        replyMessage = _makeReplyMessage(fromUserId=12345, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "set_delete_author_command", ensured)

        sendCall = mocks["sendMessage"].await_args
        assert "У Вас нет прав" in sendCall.kwargs["messageText"]
        mocks["setChatSetting"].assert_not_called()

    async def test_setAuthor_nonTelegramProvider(self) -> None:
        """MAX provider → "not supported" error, no setting change.

        The commands are Telegram-only; a non-Telegram provider triggers
        the platform guard before any reply / admin / list logic.
        """
        handler, mocks = _makeCommandHandler(botProvider=BotProvider.MAX)
        replyMessage = _makeReplyMessage(fromUserId=12345, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "set_delete_author_command", ensured)

        sendCall = mocks["sendMessage"].await_args
        assert "не поддержана на данной платформе" in sendCall.kwargs["messageText"]
        mocks["setChatSetting"].assert_not_called()

    async def test_setAuthor_explicitChatIdArg(self) -> None:
        """Explicit ``chatId`` arg targets a different chat.

        ``args="12345"`` overrides the recipient's chat id; ``isAdmin`` is
        called with a :class:`MessageRecipient` whose id is 12345, and
        ``setChatSetting`` stores against that same id.
        """
        handler, mocks = _makeCommandHandler()
        replyMessage = _makeReplyMessage(fromUserId=12345, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "set_delete_author_command", ensured, args="12345")

        adminCall = mocks["isAdmin"].await_args
        assert adminCall.kwargs["chat"].id == 12345
        assert adminCall.kwargs["chat"].chatType == ChatType.PRIVATE

        setCall = mocks["setChatSetting"].await_args
        assert setCall.args[0] == 12345

    async def test_setAuthor_emptyAuthorRespondsWithError(self) -> None:
        """Reply yields an empty author → error instead of silent "Готово".

        The reply carries an unrecognised ``forward_origin`` (a plain
        ``MagicMock`` that matches none of the known
        ``telegram.MessageOrigin*`` types). ``_getMessageAuthor`` returns
        ``MessageSender(0, "", "")``; the handler must detect this and
        respond with an error rather than appending nothing and claiming
        success.
        """
        handler, mocks = _makeCommandHandler()
        replyMessage = _makeReplyMessage(forwardOrigin=MagicMock())
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "set_delete_author_command", ensured)

        sendCall = mocks["sendMessage"].await_args
        assert "Не удалось определить автора" in sendCall.kwargs["messageText"]
        assert sendCall.kwargs["messageCategory"] == MessageCategory.BOT_ERROR
        mocks["setChatSetting"].assert_not_called()

    # ------------------------------------------------------------------
    # unset_delete_author_command
    # ------------------------------------------------------------------

    async def test_unsetAuthor_inListRemovedById(self) -> None:
        """Author id is in the list → removed, empty list, "Готово".

        The list holds ``[12345]``; the reply author's id is 12345. After
        removal the stored list is ``[]``.
        """
        handler, mocks = _makeCommandHandler(authorListJson="[12345]")
        replyMessage = _makeReplyMessage(fromUserId=12345, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "unset_delete_author_command", ensured)

        setCall = mocks["setChatSetting"].await_args
        storedList = json.loads(setCall.args[2].value)
        assert storedList == []

        sendCall = mocks["sendMessage"].await_args
        assert sendCall.kwargs["messageText"] == "Готово"

    async def test_unsetAuthor_notInList(self) -> None:
        """Author not in the list → list unchanged, "Готово (Не было …)".

        The list holds ``[99999]``; the reply author's id (12345) and
        username are absent. The command still writes the unchanged list
        back (preserving existing behaviour) and reports that the author
        was not present.
        """
        handler, mocks = _makeCommandHandler(authorListJson="[99999]")
        replyMessage = _makeReplyMessage(fromUserId=12345, fromUserName="TestUser")
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "unset_delete_author_command", ensured)

        setCall = mocks["setChatSetting"].await_args
        storedList = json.loads(setCall.args[2].value)
        assert storedList == [99999]

        sendCall = mocks["sendMessage"].await_args
        assert sendCall.kwargs["messageText"] == "Готово (Не было в списке на удаление)"

    async def test_unsetAuthor_emptyAuthorRespondsWithError(self) -> None:
        """Reply yields an empty author → error instead of silent removal.

        Mirror of :meth:`test_setAuthor_emptyAuthorRespondsWithError` for
        the unset path. The reply carries an unrecognised
        ``forward_origin`` (a plain ``MagicMock`` that matches none of the
        known ``telegram.MessageOrigin*`` types).
        ``_getMessageAuthor`` returns ``MessageSender(0, "", "")``; the
        handler must detect this and respond with an error rather than
        running the (no-op) removal and claiming success. The list is
        seeded with ``[12345]`` to prove the guard fires before any
        mutation.
        """
        handler, mocks = _makeCommandHandler(authorListJson="[12345]")
        replyMessage = _makeReplyMessage(forwardOrigin=MagicMock())
        ensured = _makeEnsuredMessage(_makeCommandMessage(replyMessage))

        await _callCommand(handler, "unset_delete_author_command", ensured)

        sendCall = mocks["sendMessage"].await_args
        assert "Не удалось определить автора" in sendCall.kwargs["messageText"]
        assert sendCall.kwargs["messageCategory"] == MessageCategory.BOT_ERROR
        mocks["setChatSetting"].assert_not_called()

    # ------------------------------------------------------------------
    # dump_delete_authors_command
    # ------------------------------------------------------------------

    async def test_dumpAuthors_withEntries(self) -> None:
        """Dump outputs the list as a fenced JSON code block.

        The list ``[123, "user"]`` is serialised with ``indent=2`` and
        wrapped in `` ```json `` fences. The message text must contain
        both values and the fence marker.
        """
        handler, mocks = _makeCommandHandler(authorListJson='[123, "user"]')
        ensured = _makeEnsuredMessage(_makeCommandMessage())

        await _callCommand(handler, "dump_delete_authors_command", ensured)

        sendCall = mocks["sendMessage"].await_args
        messageText = sendCall.kwargs["messageText"]
        assert "```json" in messageText
        assert "123" in messageText
        assert '"user"' in messageText
