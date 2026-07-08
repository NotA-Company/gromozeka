"""Shared embedding generation + persistence for user memories.

Single recipe shared by the ``add_memory`` LLM tool (chat-time and
refinement-time) and the regeneration worker
(``UserDataHandler._dtCronJob`` re-embedding stale-model rows):

1. Resolve the model via ``LLMService.getInstance().getLLMManager().getModel(name)``.
2. Generate the vector via ``model.generateEmbeddings(text)``.
3. Persist via ``db.userMemories.saveMemoryEmbedding(...)`` — which
   lazy-upserts the vec0 table AND sets ``embedding_model`` /
   ``embedding_dimensions`` on the ``user_memories`` row. No BLOB table
   (§5.1 of the user-memories plan); vec0 is the sole embedding store.

Never raises — every failure path returns ``False`` so a transient
embedding outage can never break a chat turn or a refinement run.
Mirrors ``embedding_utils.embedAndSaveMessage``.

Note on the cyclic-dep import: ``LLMService`` is imported INSIDE
:func:`embedAndSaveMemory` (not at module top) because the LLM service
graph depends back into ``internal.bot.common``. This is the documented
AGENTS.md exception: *"Imports inside methods are only acceptable when a
cyclic dependency makes it unavoidable"* — the exact precedent lives at
``embedding_utils.py:67-69``.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internal.database import Database

logger = logging.getLogger(__name__)


async def embedAndSaveMemory(
    chatId: int,
    userId: int,
    memoryId: str,
    content: str,
    modelName: str,
    db: "Database",
) -> bool:
    """Generate an embedding for a memory's content and persist it.

    Resolves the model by name via the LLM service singleton, generates
    the vector, and saves it through ``db.userMemories.saveMemoryEmbedding``.
    Never raises — the caller treats ``False`` as "skip and continue".

    Args:
        chatId: Chat the memory belongs to.
        userId: User the memory is about.
        memoryId: ULID/UUID hex of the memory row.
        content: Text to embed (the memory's ``content`` field).
        modelName: Embedding model name (the CALLER resolves this from
            the chat's ``EMBEDDING_MODEL`` setting via ``getChatSettings``
            — mirrors ``embedAndSaveMessage`` which also takes
            ``modelName`` as a param rather than re-reading config inside
            the helper).
        db: Database wrapper providing ``userMemories``.

    Returns:
        True on success, False on any failure (missing model, embedding
        API error, DB write error).
    """
    # Imported here (rather than at module scope) to avoid a circular
    # import: LLMService -> ... -> memory_embedding_utils -> LLMService.
    # This is the documented cyclic-dep exception to the "imports at file
    # top" rule in AGENTS.md; see embedding_utils.py:67-69 for the
    # established precedent.
    from internal.services.llm.service import LLMService

    try:
        llmService = LLMService.getInstance()
        model = llmService.getLLMManager().getModel(modelName)
    except Exception:
        logger.exception(
            "Failed to resolve embedding model %r for memory %s in chat %d",
            modelName,
            memoryId,
            chatId,
        )
        return False

    if model is None or not model.supportsEmbedding:
        logger.warning(
            "Embedding model %r not found or does not support embeddings; " "skipping memory %s in chat %d",
            modelName,
            memoryId,
            chatId,
        )
        return False

    try:
        embedding = await model.generateEmbeddings(content)
    except Exception:
        logger.exception(
            "Failed to generate embedding for memory %s in chat %d with model %r",
            memoryId,
            chatId,
            modelName,
        )
        return False

    try:
        await db.userMemories.saveMemoryEmbedding(
            chatId=chatId,
            userId=userId,
            memoryId=memoryId,
            embedding=embedding,
            model=modelName,
        )
    except Exception:
        logger.exception(
            "Failed to save embedding for memory %s in chat %d with model %r",
            memoryId,
            chatId,
            modelName,
        )
        return False

    return True
