"""Phase 1 tests for the write-through ``chat_users`` cache layer.

Covers the five new ``CacheService`` methods (``getChatUser``,
``updateChatUser``, ``getUserMetadata``, ``updateUserMetadata``,
``invalidateChatUser``) against a real in-memory database via the
``testDatabase`` fixture. The ``CacheService`` singleton is reset around every
test by the local autouse fixture (the global ``resetLlmServiceSingleton`` in
``tests/conftest.py`` does not reset the cache singleton).

Spies patch ``ChatUsersRepository`` at the **class** level rather than the
instance because the repository declares ``__slots__ = ()``, which forbids
setting instance attributes that ``patch.object`` requires.

Test areas:

* cold miss / warm hit / refresh semantics of ``getChatUser`` (incl. the
  absent-row-does-not-cache behaviour: an absent row returns None and leaves
  the cache cold so the next call re-queries the DB)
* defensive-copy invariant (``getChatUser`` returns a shallow copy)
* skip-when-unchanged optimisation + in-place cache mutation of
  ``updateChatUser``
* cold-path of ``updateChatUser`` leaves the cache cold (no re-read warming)
* parse round-trip of ``getUserMetadata`` / ``updateUserMetadata``
* cold-write posture of ``updateUserMetadata`` (cache left cold)
* nested-write safety (option (i) dumb primitives do not reintroduce the
  shallow-merge trap when callers compose correctly)
* ``invalidateChatUser`` drops ONLY ``userInfo``, preserving the ``data`` blob
"""

import json
from typing import Generator, cast
from unittest.mock import AsyncMock, patch

import pytest

from internal.bot.models.user_metadata import UserMetadataDict
from internal.database import Database
from internal.database.repositories.chat_users import ChatUsersRepository
from internal.services.cache import CacheService

# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetCacheServiceSingleton() -> Generator[None, None, None]:
    """Reset the ``CacheService`` singleton around every test in this module.

    The closed in-memory database of one test must not leak into the next via
    the ``CacheService`` singleton (which is not reset by
    ``tests/conftest.py``).

    Yields:
        None.
    """
    CacheService._instance = None
    yield
    CacheService._instance = None


@pytest.fixture
async def cacheService(testDatabase: Database) -> CacheService:
    """Build a ``CacheService`` singleton wired to the real in-memory DB.

    Args:
        testDatabase: Fresh in-memory :class:`Database` (``testDatabase``
            fixture).

    Returns:
        A ``CacheService`` whose ``database`` is *testDatabase*.
    """
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)
    return cache


async def _seedRow(testDatabase: Database, chatId: int, userId: int, username: str, fullName: str) -> None:
    """Insert a ``chat_users`` row directly via the repository (bypassing the cache).

    Args:
        testDatabase: Real in-memory database.
        chatId: Chat id.
        userId: User id.
        username: Username to store.
        fullName: Full name to store.
    """
    await testDatabase.chatUsers.updateChatUser(chatId=chatId, userId=userId, username=username, fullName=fullName)


# ---------------------------------------------------------------------------
# getChatUser
# ---------------------------------------------------------------------------


async def test_getChatUser_coldMissFetchesDbAndPopulatesCache(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """Cold miss falls back to DB, caches the row, returns it.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")

    row = await cacheService.getChatUser(chatId=1, userId=2)

    assert row is not None
    assert row["chat_id"] == 1
    assert row["user_id"] == 2
    assert row["username"] == "bob"
    assert row["full_name"] == "Bob"
    # Cache populated.
    userKey = cacheService._getChatUserKey(1, 2)
    assert "userInfo" in cacheService.chatUsers.get(userKey, {})


async def test_getChatUser_warmHitDoesNotCallDb(testDatabase: Database, cacheService: CacheService) -> None:
    """Warm hit returns the cached row without touching the DB.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    # Warm the cache.
    await cacheService.getChatUser(chatId=1, userId=2)

    with patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(return_value=None)) as spy:
        row = await cacheService.getChatUser(chatId=1, userId=2)
        spy.assert_not_called()

    assert row is not None
    assert row["username"] == "bob"


async def test_getChatUser_returnsDefensiveShallowCopy(testDatabase: Database, cacheService: CacheService) -> None:
    """Mutating the returned dict must not corrupt the cached row.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    first = await cacheService.getChatUser(chatId=1, userId=2)
    assert first is not None

    # Mutate the returned copy.
    first["username"] = "TAMPERED"
    first["full_name"] = "TAMPERED"

    second = await cacheService.getChatUser(chatId=1, userId=2)
    assert second is not None
    assert second["username"] == "bob"
    assert second["full_name"] == "Bob"


async def test_getChatUser_refreshReFetchesEvenWhenWarm(testDatabase: Database, cacheService: CacheService) -> None:
    """``refresh=True`` bypasses the cache read and overwrites the cached value.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    await cacheService.getChatUser(chatId=1, userId=2)  # warm

    original = testDatabase.chatUsers.getChatUser  # capture bound method before patching
    with patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(wraps=original)) as spy:
        row = await cacheService.getChatUser(chatId=1, userId=2, refresh=True)
        spy.assert_called_once()

    assert row is not None
    assert row["username"] == "bob"


async def test_getChatUser_absentRowReturnsNoneAndDoesNotCache(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """A non-existent row returns None and leaves the cache cold (absence not memoized).

    An absent row indicates something went wrong upstream and is not worth memoizing:
    the cache is left cold so the next call re-queries the DB. This replaces the old
    None-sentinel contract that cached the absence to suppress repeat queries.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    row = await cacheService.getChatUser(chatId=1, userId=999)
    assert row is None

    # Cache left cold: no userInfo key set on the cached entry.
    userKey = cacheService._getChatUserKey(1, 999)
    cachedEntry = cacheService.chatUsers.get(userKey, {})
    assert "userInfo" not in cachedEntry

    # Second call re-queries the DB (absence is not memoized).
    with patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(return_value=None)) as spy:
        row2 = await cacheService.getChatUser(chatId=1, userId=999)
        spy.assert_called_once()
    assert row2 is None


# ---------------------------------------------------------------------------
# updateChatUser
# ---------------------------------------------------------------------------


async def test_updateChatUser_warmUnchangedSkipsDb(testDatabase: Database, cacheService: CacheService) -> None:
    """When the cached row already matches, no DB upsert occurs.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    await cacheService.getChatUser(chatId=1, userId=2)  # warm

    original = testDatabase.chatUsers.updateChatUser
    with patch.object(ChatUsersRepository, "updateChatUser", new=AsyncMock(wraps=original)) as spy:
        await cacheService.updateChatUser(chatId=1, userId=2, username="bob", fullName="Bob")
        spy.assert_not_called()


async def test_updateChatUser_warmChangedMutatesCacheInPlace(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """A changed value triggers the DB upsert and mutates the cached row in place.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    originalRow = await cacheService.getChatUser(chatId=1, userId=2)
    assert originalRow is not None
    originalUpdatedAt = originalRow["updated_at"]

    original = testDatabase.chatUsers.updateChatUser
    with patch.object(ChatUsersRepository, "updateChatUser", new=AsyncMock(wraps=original)) as spy:
        await cacheService.updateChatUser(chatId=1, userId=2, username="bobby", fullName="Bobby Q")
        spy.assert_called_once()

    row = await cacheService.getChatUser(chatId=1, userId=2)
    assert row is not None
    assert row["username"] == "bobby"
    assert row["full_name"] == "Bobby Q"
    # updated_at bumped in the cached row.
    assert row["updated_at"] >= originalUpdatedAt


async def test_updateChatUser_coldUpsertsAndLeavesCacheCold(testDatabase: Database, cacheService: CacheService) -> None:
    """Cold path performs the upsert but intentionally leaves the cache cold (no re-read).

    The row may never be read again, so a warming re-read would be a wasted query on
    the write path; the next ``getChatUser`` lazy-loads if ever needed. Asserts the DB
    upsert fires exactly once AND ``getChatUser`` is NOT called by the setter AND no
    ``userInfo`` is populated.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    repo = testDatabase.chatUsers
    originalUpsert = repo.updateChatUser
    originalGet = repo.getChatUser
    with (
        patch.object(ChatUsersRepository, "updateChatUser", new=AsyncMock(wraps=originalUpsert)) as upsertSpy,
        patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(wraps=originalGet)) as getSpy,
    ):
        await cacheService.updateChatUser(chatId=1, userId=2, username="alice", fullName="Alice")
        upsertSpy.assert_called_once()
        getSpy.assert_not_called()  # cold path does NOT re-read to warm

    # Cache still cold.
    userKey = cacheService._getChatUserKey(1, 2)
    cachedEntry = cacheService.chatUsers.get(userKey, {})
    assert "userInfo" not in cachedEntry

    # But the row landed in the DB, so a subsequent getChatUser lazy-loads it.
    row = await cacheService.getChatUser(chatId=1, userId=2)
    assert row is not None
    assert row["username"] == "alice"
    assert row["full_name"] == "Alice"


async def test_updateChatUser_leavesCacheUntouchedOnDbFailure(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """A DB-write failure must NOT mutate the cache.

    ``ChatUsersRepository.updateChatUser`` returns ``False`` (and swallows the
    error) on any DB failure; the cache setter must bail before mutating the
    cached row so the cache never advances past a write that never landed.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="old", fullName="old")
    # Pre-warm the cache so userInfo holds the original row.
    warmed = await cacheService.getChatUser(chatId=1, userId=2)
    assert warmed is not None
    assert warmed["username"] == "old"

    with patch.object(ChatUsersRepository, "updateChatUser", new=AsyncMock(return_value=False)) as spy:
        await cacheService.updateChatUser(chatId=1, userId=2, username="new", fullName="new")
        spy.assert_called_once()

    # Cache still holds the original row (unmutated).
    row = await cacheService.getChatUser(chatId=1, userId=2)
    assert row is not None
    assert row["username"] == "old"
    assert row["full_name"] == "old"


# ---------------------------------------------------------------------------
# getUserMetadata
# ---------------------------------------------------------------------------


async def test_getUserMetadata_parsesPopulatedAndReturnsEmptyForAbsent(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """``getUserMetadata`` parses a populated column and returns ``{}`` when absent/empty.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    # Absent row -> {}.
    assert await cacheService.getUserMetadata(chatId=1, userId=999) == {}

    # Existing row, default empty metadata -> {}.
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    assert await cacheService.getUserMetadata(chatId=1, userId=2) == {}

    # Populated metadata.
    await testDatabase.chatUsers.updateUserMetadata(chatId=1, userId=2, metadata='{"isSpammer": true}')
    # Invalidate so the next read picks up the new metadata.
    cacheService.invalidateChatUser(chatId=1, userId=2)
    parsed = await cacheService.getUserMetadata(chatId=1, userId=2)
    assert parsed.get("isSpammer") is True


# ---------------------------------------------------------------------------
# updateUserMetadata
# ---------------------------------------------------------------------------


async def test_updateUserMetadata_writeThroughAndUpdatesCache(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """``updateUserMetadata`` writes the DB and updates the cached row in place.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    await cacheService.getChatUser(chatId=1, userId=2)  # warm

    original = testDatabase.chatUsers.updateUserMetadata
    with patch.object(ChatUsersRepository, "updateUserMetadata", new=AsyncMock(wraps=original)) as spy:
        await cacheService.updateUserMetadata(chatId=1, userId=2, metadata={"isSpammer": True})
        spy.assert_called_once()

    # A subsequent getUserMetadata reflects the new value (cache + DB consistent).
    parsed = await cacheService.getUserMetadata(chatId=1, userId=2)
    assert parsed.get("isSpammer") is True


async def test_updateUserMetadata_coldLeavesCacheCold(testDatabase: Database, cacheService: CacheService) -> None:
    """On cold ``userInfo`` the DB is written but the cache stays cold; next read lazy-loads.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    # Seed the DB row directly (cache stays cold — never called getChatUser).
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")

    original = testDatabase.chatUsers.updateUserMetadata
    with patch.object(ChatUsersRepository, "updateUserMetadata", new=AsyncMock(wraps=original)) as spy:
        await cacheService.updateUserMetadata(chatId=1, userId=2, metadata={"isSpammer": True})
        spy.assert_called_once()

    # Cache still cold.
    userKey = cacheService._getChatUserKey(1, 2)
    assert "userInfo" not in cacheService.chatUsers.get(userKey, {})

    # Next getChatUser lazy-loads the freshly-written row.
    row = await cacheService.getChatUser(chatId=1, userId=2)
    assert row is not None
    assert json.loads(row["metadata"]).get("isSpammer") is True


async def test_updateUserMetadata_leavesCacheUntouchedOnDbFailure(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """A DB-write failure must NOT mutate the cached metadata.

    ``ChatUsersRepository.updateUserMetadata`` returns ``False`` (and swallows
    the error) on any DB failure; the cache setter must bail before writing the
    new metadata string into the cached row, otherwise the cache would diverge
    from the unchanged DB row.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    # Seed metadata directly via the repo, then load it into the cache.
    await testDatabase.chatUsers.updateUserMetadata(chatId=1, userId=2, metadata='{"existing": "value"}')
    await cacheService.getChatUser(chatId=1, userId=2, refresh=True)

    with patch.object(ChatUsersRepository, "updateUserMetadata", new=AsyncMock(return_value=False)) as spy:
        await cacheService.updateUserMetadata(chatId=1, userId=2, metadata=cast(UserMetadataDict, {"new": "value"}))
        spy.assert_called_once()

    # Cache still holds the original metadata (unmutated).
    parsed = await cacheService.getUserMetadata(chatId=1, userId=2)
    assert parsed.get("existing") == "value"
    assert "new" not in parsed


# ---------------------------------------------------------------------------
# Nested-write safety (option (i) dumb primitives)
# ---------------------------------------------------------------------------


async def test_nestedWriteSafety_shallowMergeDoesNotWipeNested(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """A nested mutate then a separate shallow top-level merge coexist safely.

    Proves option (i) (dumb read/write primitives) does not reintroduce the
    shallow-merge trap when callers read the FULL metadata, mutate a single
    nested key, and write the FULL metadata back.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")

    # 1) _persistMemoryEntry-style nested write.
    metadata = await cacheService.getUserMetadata(chatId=1, userId=2)
    threadId = 5
    metadata.setdefault("memoryRefinement", {})[str(threadId)] = {"summary": "hello"}
    await cacheService.updateUserMetadata(chatId=1, userId=2, metadata=metadata)

    # 2) setUserMetadata(isUpdate=True)-style shallow top-level merge.
    existing = await cacheService.getUserMetadata(chatId=1, userId=2)
    merged = cast(UserMetadataDict, {**existing, "isSpammer": True})
    await cacheService.updateUserMetadata(chatId=1, userId=2, metadata=merged)

    # 3) The nested memoryRefinement survived the shallow merge.
    final = await cacheService.getUserMetadata(chatId=1, userId=2)
    assert final.get("isSpammer") is True
    refinement = final.get("memoryRefinement") or {}
    entry = refinement.get(str(threadId)) or {}
    assert entry.get("summary") == "hello"


# ---------------------------------------------------------------------------
# invalidateChatUser
# ---------------------------------------------------------------------------


async def test_invalidateChatUser_dropsOnlyUserInfoPreservingData(
    testDatabase: Database, cacheService: CacheService
) -> None:
    """``invalidateChatUser`` drops only ``userInfo``, preserving the ``data`` blob.

    Args:
        testDatabase: Real in-memory database.
        cacheService: Cache wired to *testDatabase*.
    """
    await _seedRow(testDatabase, chatId=1, userId=2, username="bob", fullName="Bob")
    # Populate the user_data blob (the ``data`` field) via setChatUserData.
    await cacheService.setChatUserData(chatId=1, userId=2, key="k", value="v")
    # Warm userInfo.
    await cacheService.getChatUser(chatId=1, userId=2)

    # Invalidate userInfo only.
    cacheService.invalidateChatUser(chatId=1, userId=2)

    # The data blob survives.
    userData = await cacheService.getChatUserData(chatId=1, userId=2)
    assert userData.get("k") == "v"

    # userInfo was dropped -> next getChatUser re-fetches from DB.
    original = testDatabase.chatUsers.getChatUser
    with patch.object(ChatUsersRepository, "getChatUser", new=AsyncMock(wraps=original)) as spy:
        row = await cacheService.getChatUser(chatId=1, userId=2)
        spy.assert_called_once()
    assert row is not None
    assert row["username"] == "bob"
