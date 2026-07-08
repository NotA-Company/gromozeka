"""Tests for :func:`internal.bot.common.memory_embedding_utils.embedAndSaveMemory`.

The helper owns the never-crash recipe shared by the ``add_memory`` LLM
tool and the regeneration worker: resolve the model, generate the
embedding, persist it via ``db.userMemories.saveMemoryEmbedding``. Every
failure path returns ``False`` (never raises) so a transient embedding
outage can never break a chat turn or a refinement run.

These tests mirror the mocking shape of
``tests/bot/common/handlers/test_message_preprocessor.py::TestEmbedMessage``
(which covers the sibling ``embedAndSaveMessage`` helper): the autouse
``resetLlmServiceSingleton`` fixture gives each test a fresh
``LLMService`` singleton, and each test injects a mock ``LLMManager``
whose ``getModel`` controls model resolution. Unlike the
``embedAndSaveMessage`` tests (which mock ``db.chatEmbeddings``), these
use the REAL ``testDatabase`` so the success path exercises the full
vec0 write + provenance-column update end-to-end.
"""

import array
import uuid
from unittest.mock import AsyncMock, Mock, patch

from internal.bot.common.memory_embedding_utils import embedAndSaveMemory
from internal.bot.models.memory_type import MemoryType
from internal.database import Database
from internal.database.providers.sqlite3 import _SQLITE_VEC_AVAILABLE
from internal.database.repositories.user_memories import UserMemoriesRepository, UserMemoryDict
from internal.services.llm.service import LLMService

CHAT_ID = 1
USER_ID = 100
MODEL_NAME = "test-embed-model"


def _newMemoryId() -> str:
    """Generate a fresh app-side memory id (UUID hex, mirroring the migration).

    Returns:
        A 32-char hex string suitable for the ``memory_id`` column.
    """
    return uuid.uuid4().hex


def _injectMockManager(model: Mock | None) -> Mock:
    """Inject a mock ``LLMManager`` into the (autouse-reset) LLMService singleton.

    The autouse ``resetLlmServiceSingleton`` fixture has already cleared
    ``LLMService._instance`` before each test, so ``getInstance()``
    constructs a fresh singleton here. The mock manager is injected via
    the real ``injectLLMManager`` accessor so that
    ``embedAndSaveMemory``'s ``LLMService.getInstance().getLLMManager()``
    resolves to it.

    Args:
        model: The model mock for ``manager.getModel`` to return, or
            ``None`` to simulate "model not found".

    Returns:
        The mock ``LLMManager`` (in case a test wants to reconfigure it).
    """
    llmService = LLMService.getInstance()
    mockManager = Mock()
    mockManager.getModel = Mock(return_value=model)
    llmService.injectLLMManager(mockManager)
    return mockManager


async def _addMemory(db: Database, *, content: str = "remembers peanuts", memoryId: str | None = None) -> str:
    """Insert a memory row and return its id.

    Args:
        db: Real database wrapper.
        content: Memory body text.
        memoryId: Optional explicit id; generated when ``None``.

    Returns:
        The inserted memory's id.
    """
    mid = memoryId if memoryId is not None else _newMemoryId()
    await db.userMemories.addMemory(
        chatId=CHAT_ID,
        userId=USER_ID,
        memoryId=mid,
        type=MemoryType.FACT,
        content=content,
        tags=[],
        permanent=False,
        threadId=5,
        source="refinement",
    )
    return mid


async def _fetchMemory(db: Database, memoryId: str) -> UserMemoryDict:
    """Fetch a single memory row by id (for post-call column assertions).

    Args:
        db: Real database wrapper.
        memoryId: Memory id to look up.

    Returns:
        The matching :class:`UserMemoryDict`.
    """
    rows = await db.userMemories.getLatestMemories(CHAT_ID, USER_ID, threadId=5)
    return next(r for r in rows if r["memory_id"] == memoryId)


class TestEmbedAndSaveMemory:
    """Covers the four contract cases of :func:`embedAndSaveMemory`.

    1. Success — model resolves, embedding generated, persisted (vec0
       row + provenance columns), returns ``True``.
    2. Model not found — ``getModel`` returns ``None``, returns ``False``,
       no DB write, never raises.
    3. Generation error — ``generateEmbeddings`` raises, returns ``False``,
       no DB write, never raises.
    4. No embedding support — ``model.supportsEmbedding`` is ``False``,
       returns ``False``.
    """

    async def test_success_persistsEmbeddingAndSetsColumns(self, testDatabase: Database) -> None:
        """Happy path: embedding generated, saveMemoryEmbedding called with right args, columns set.

        Spies on ``saveMemoryEmbedding`` so the call args can be asserted
        while still exercising the real DB write (provenance columns +
        vec0 row). The vec0-row-written assertion runs only when
        sqlite-vec is available (the test environment has it; CI without
        it would skip that branch).

        Args:
            testDatabase: Real in-memory database fixture.
        """
        memoryId = await _addMemory(testDatabase, content="remembers peanuts")

        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2, 0.3])
        _injectMockManager(mockModel)

        # Spy on saveMemoryEmbedding: assert call args AND let the real
        # method run so the provenance columns + vec0 row are written.
        # Patched on the CLASS (not the instance) because
        # ``UserMemoriesRepository`` declares ``__slots__ = ()``, which
        # forbids per-instance attribute overrides.
        originalSave = testDatabase.userMemories.saveMemoryEmbedding
        saveSpy = AsyncMock(side_effect=originalSave)
        with patch.object(UserMemoriesRepository, "saveMemoryEmbedding", saveSpy):
            ok = await embedAndSaveMemory(
                chatId=CHAT_ID,
                userId=USER_ID,
                memoryId=memoryId,
                content="remembers peanuts",
                modelName=MODEL_NAME,
                db=testDatabase,
            )

        assert ok is True

        # saveMemoryEmbedding was invoked with the helper's args.
        saveSpy.assert_awaited_once()
        assert saveSpy.await_args is not None
        callKwargs = saveSpy.await_args.kwargs
        assert callKwargs["chatId"] == CHAT_ID
        assert callKwargs["userId"] == USER_ID
        assert callKwargs["memoryId"] == memoryId
        assert callKwargs["embedding"] == [0.1, 0.2, 0.3]
        assert callKwargs["model"] == MODEL_NAME

        # Provenance columns set on the user_memories row.
        row = await _fetchMemory(testDatabase, memoryId)
        assert row["embedding_model"] == MODEL_NAME
        assert row["embedding_dimensions"] == 3

        # vec0 row written → semantic search surfaces the memory (vec0 only).
        if _SQLITE_VEC_AVAILABLE:
            queryBytes = array.array("f", [0.1, 0.2, 0.3]).tobytes()
            results = await testDatabase.userMemories.searchMemories(
                CHAT_ID, USER_ID, queryEmbedding=queryBytes, limit=5
            )
            assert any(r["memory_id"] == memoryId for r in results)

    async def test_modelNotFound_returnsFalse(self, testDatabase: Database) -> None:
        """``getModel`` returns None → returns False, no DB write, never raises.

        Args:
            testDatabase: Real in-memory database fixture.
        """
        memoryId = await _addMemory(testDatabase, content="unembedded")

        # getModel returns None → "model not found" guard fires.
        _injectMockManager(None)

        ok = await embedAndSaveMemory(
            chatId=CHAT_ID,
            userId=USER_ID,
            memoryId=memoryId,
            content="unembedded",
            modelName="missing-model",
            db=testDatabase,
        )

        assert ok is False
        # No provenance write occurred.
        row = await _fetchMemory(testDatabase, memoryId)
        assert row["embedding_model"] is None
        assert row["embedding_dimensions"] is None

    async def test_generationError_returnsFalse(self, testDatabase: Database) -> None:
        """``generateEmbeddings`` raises → returns False, no DB write, never raises.

        Args:
            testDatabase: Real in-memory database fixture.
        """
        memoryId = await _addMemory(testDatabase, content="unembedded")

        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(side_effect=RuntimeError("embedding API down"))
        _injectMockManager(mockModel)

        ok = await embedAndSaveMemory(
            chatId=CHAT_ID,
            userId=USER_ID,
            memoryId=memoryId,
            content="unembedded",
            modelName=MODEL_NAME,
            db=testDatabase,
        )

        assert ok is False
        # No provenance write occurred.
        row = await _fetchMemory(testDatabase, memoryId)
        assert row["embedding_model"] is None
        assert row["embedding_dimensions"] is None

    async def test_noEmbeddingSupport_returnsFalse(self, testDatabase: Database) -> None:
        """``model.supportsEmbedding`` is False → returns False, no DB write.

        The model resolves but advertises no embedding capability, so the
        helper must short-circuit before generation.

        Args:
            testDatabase: Real in-memory database fixture.
        """
        memoryId = await _addMemory(testDatabase, content="unembedded")

        mockModel = Mock()
        mockModel.supportsEmbedding = False
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2, 0.3])
        _injectMockManager(mockModel)

        ok = await embedAndSaveMemory(
            chatId=CHAT_ID,
            userId=USER_ID,
            memoryId=memoryId,
            content="unembedded",
            modelName=MODEL_NAME,
            db=testDatabase,
        )

        assert ok is False
        # generateEmbeddings must not have run.
        mockModel.generateEmbeddings.assert_not_called()
        # No provenance write occurred.
        row = await _fetchMemory(testDatabase, memoryId)
        assert row["embedding_model"] is None
        assert row["embedding_dimensions"] is None

    async def test_saveMemoryEmbeddingRaises_returnsFalse(self, testDatabase: Database) -> None:
        """Regression (Gate-1 Fix 7): saveMemoryEmbedding raising → returns False, never raises.

        The helper wraps the save call in try/except so a DB-level
        failure (e.g. provider unavailable, connection dropped)
        propagates as ``False`` rather than breaking the chat turn or
        the refinement run that invoked it.

        Args:
            testDatabase: Real in-memory database fixture.
        """
        memoryId = await _addMemory(testDatabase, content="x")

        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2])
        _injectMockManager(mockModel)

        # Patched on the CLASS (not the instance) because
        # ``UserMemoriesRepository`` declares ``__slots__ = ()``, which
        # forbids per-instance attribute overrides (mirrors the spy in
        # ``test_success_persistsEmbeddingAndSetsColumns``).
        with patch.object(
            UserMemoriesRepository,
            "saveMemoryEmbedding",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            ok = await embedAndSaveMemory(
                chatId=CHAT_ID,
                userId=USER_ID,
                memoryId=memoryId,
                content="x",
                modelName=MODEL_NAME,
                db=testDatabase,
            )

        assert ok is False
