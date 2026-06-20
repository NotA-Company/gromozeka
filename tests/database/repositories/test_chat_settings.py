"""Tests for :class:`ChatSettingsRepository` discovery helpers.

Covers :meth:`ChatSettingsRepository.listChatsBySetting`, the
cross-source-aggregating helper that backs the embedding backfill
chat discovery. The method returns a ``Dict[int, str]`` mapping
``chat_id -> value`` verbatim (no SQL-level boolean coercion) and
lets the caller filter the ``value`` with
:meth:`ChatSettingsValue.toBool` — that contract is what
``ChatSearchHandler._dtCronJob`` depends on, and what this
test guards against regressing.

Uses the shared ``testDatabase`` fixture from ``tests/conftest.py`` so
each test gets a fresh in-memory SQLite database with all migrations
applied — no mocks.
"""

from internal.bot.models.chat_settings import ChatSettingsValue
from internal.database import Database


class TestListChatsBySetting:
    """End-to-end tests for ``ChatSettingsRepository.listChatsBySetting``.

    Regression coverage for the ``Dict[int, str]`` return contract: the
    helper used to return ``List[Dict[str, Any]]`` rows with
    ``{chat_id, value}`` keys (Fix 6, June 2026), then transitioned to
    a flat ``Dict[chat_id, value]`` so callers can iterate
    ``.items()`` and apply ``ChatSettingsValue.toBool()`` directly
    without a per-row dict lookup. The tests below pin both the
    value shape and the caller-side filtering pattern.
    """

    @staticmethod
    async def _seedSetting(
        db: Database,
        chatId: int,
        key: str,
        value: str,
    ) -> None:
        """Insert a single ``chat_settings`` row for the test seed.

        Args:
            db: Database instance (in-memory test fixture).
            chatId: Chat identifier.
            key: Setting key (e.g. ``"regenerate-embeddings"``).
            value: Setting value (e.g. ``"true"``).
        """
        await db.chatSettings.setChatSetting(
            chatId=chatId,
            key=key,
            value=value,
            updatedBy=0,
        )

    async def test_returnsChatIdToValueDict(self, testDatabase: Database) -> None:
        """The return value is a ``Dict[int, str]`` mapping ``chat_id -> value``.

        Args:
            testDatabase: In-memory database fixture.
        """
        await self._seedSetting(testDatabase, chatId=1, key="regenerate-embeddings", value="true")
        await self._seedSetting(testDatabase, chatId=2, key="regenerate-embeddings", value="false")

        result = await testDatabase.chatSettings.listChatsBySetting(key="regenerate-embeddings")

        # Both rows are returned regardless of value — the helper is
        # a discovery query, not a filter. The caller
        # (``ChatSearchHandler._dtCronJob``) applies
        # ``ChatSettingsValue.toBool()`` to discriminate.
        assert isinstance(result, dict)
        assert set(result.keys()) == {1, 2}
        assert result[1] == "true"
        assert result[2] == "false"
        assert all(isinstance(k, int) for k in result.keys())
        assert all(isinstance(v, str) for v in result.values())

    async def test_doesNotCoerceBooleansInSql(self, testDatabase: Database) -> None:
        """A stored ``"True"`` (capitalised) is still returned — SQL does not coerce.

        Regression: the old implementation normalised through
        ``ChatSettingsValue.toBool()`` and silently dropped rows whose
        stored value did not match the query value bit-for-bit. The new
        implementation returns every row that has the key set, leaving
        the boolean interpretation to the caller — which is what lets
        ``ChatSearchHandler._dtCronJob`` accept ``"True"``, ``"TRUE"``, ``"1"`` etc.

        Args:
            testDatabase: In-memory database fixture.
        """
        await self._seedSetting(testDatabase, chatId=10, key="embeddings-enabled", value="True")
        await self._seedSetting(testDatabase, chatId=11, key="embeddings-enabled", value="1")
        await self._seedSetting(testDatabase, chatId=12, key="embeddings-enabled", value="false")

        result = await testDatabase.chatSettings.listChatsBySetting(key="embeddings-enabled")

        # All three rows come back, including the falsy one — the
        # helper does not filter by value.
        assert set(result.keys()) == {10, 11, 12}

    async def test_callerFilteringReplicatesOldContract(self, testDatabase: Database) -> None:
        """Filtering ``value`` with ``ChatSettingsValue.toBool()`` reproduces the old contract.

        This is the pattern ``ChatSearchHandler._dtCronJob``
        uses — iterate ``.items()`` and apply
        ``ChatSettingsValue(value).toBool()`` to each value. The test
        pins it down so a future refactor of the repository does not
        silently break the backfill.

        Args:
            testDatabase: In-memory database fixture.
        """
        # Mixed casing — the whole reason filtering moved to Python.
        await self._seedSetting(testDatabase, chatId=20, key="regenerate-embeddings", value="true")
        await self._seedSetting(testDatabase, chatId=21, key="regenerate-embeddings", value="True")
        await self._seedSetting(testDatabase, chatId=22, key="regenerate-embeddings", value="1")
        await self._seedSetting(testDatabase, chatId=23, key="regenerate-embeddings", value="false")
        await self._seedSetting(testDatabase, chatId=24, key="regenerate-embeddings", value="0")

        chatMap = await testDatabase.chatSettings.listChatsBySetting(key="regenerate-embeddings")
        truthyChatIds = {chatId for chatId, value in chatMap.items() if ChatSettingsValue(value).toBool()}

        # All three truthy variants (case-insensitive + "1") match;
        # both falsy variants are filtered out.
        assert truthyChatIds == {20, 21, 22}

    async def test_returnsEmptyDictWhenKeyAbsent(self, testDatabase: Database) -> None:
        """No rows for the key → empty dict, not an error.

        Args:
            testDatabase: In-memory database fixture.
        """
        await self._seedSetting(testDatabase, chatId=1, key="some-other-key", value="true")

        result = await testDatabase.chatSettings.listChatsBySetting(key="regenerate-embeddings")

        assert result == {}

    async def test_doesNotIncludeRowsForOtherKeys(self, testDatabase: Database) -> None:
        """Rows with a different key are not returned.

        Args:
            testDatabase: In-memory database fixture.
        """
        await self._seedSetting(testDatabase, chatId=1, key="regenerate-embeddings", value="true")
        await self._seedSetting(testDatabase, chatId=2, key="embeddings-enabled", value="true")
        await self._seedSetting(testDatabase, chatId=3, key="unrelated-setting", value="true")

        result = await testDatabase.chatSettings.listChatsBySetting(key="regenerate-embeddings")

        assert set(result.keys()) == {1}
