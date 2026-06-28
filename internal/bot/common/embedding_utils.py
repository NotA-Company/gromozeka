"""Shared embedding generation and save logic.

This module houses helpers that the chat-search backfill worker
(``ChatSearchHandler._dtCronJob``) and the per-message embedding
dispatcher (``MessagePreprocessorHandler.newMessageHandler``) both need.
Both code paths share the same three-step recipe:

1. Resolve the model name via ``LLMService.getLLMManager().getModel(...)``.
2. Generate the embedding vector via ``model.generateEmbeddings(text)``.
3. Persist the vector via
   ``db.chatEmbeddings.saveMessageEmbedding(chatId, messageId, vector, model)``.

Extracting the recipe into a single helper keeps the per-message
error-isolation contract (``return False on any failure, never raise``)
in one place and avoids drift between the two call sites when the
recipe grows (e.g. telemetry, cache invalidation, retry policy).
"""

import logging
from typing import TYPE_CHECKING

from internal.bot.models import LLMMessageFormat
from internal.models import MessageId

if TYPE_CHECKING:
    from internal.bot.models import EnsuredMessage
    from internal.database import Database

logger = logging.getLogger(__name__)


async def embedAndSaveMessage(
    ensuredMessage: "EnsuredMessage",
    modelName: str,
    db: "Database",
) -> bool:
    """Generate an embedding for a message and persist it.

    Accepts the full ``EnsuredMessage`` (rather than individual fields)
    so the helper also has access to attachment data that will be needed
    for embedding multi-modal content in the future. Resolves
    ``modelName`` through ``LLMService.getInstance()``'s LLM manager,
    reads the message text and identifiers from ``ensuredMessage``,
    generates the vector, and saves it via
    ``db.chatEmbeddings.saveMessageEmbedding``. The LLM service is
    fetched via its singleton accessor so callers don't have to thread
    the dependency through.

    Every error path is caught and logged so a transient embedding
    outage (missing model, LLM API failure, DB write failure) can never
    propagate out of this helper — the caller treats ``False`` as
    "skip and continue". This is the same never-crash contract the
    background task schedulers in this module rely on.

    Args:
        ensuredMessage: The persisted message object carrying chat id,
            message id, and text for embedding.
        modelName: Embedding model name (per-chat ``EMBEDDING_MODEL``
            setting).
        db: Database wrapper providing ``chatEmbeddings``.

    Returns:
        True when the embedding was generated and saved successfully,
        False on any failure (missing model, embedding API error, DB
        write error).
    """
    # Imported here (rather than at module scope) to avoid a circular
    # import: LLMService -> ... -> embedding_utils -> LLMService.
    from internal.services.llm.service import LLMService

    chatId: int = ensuredMessage.recipient.id
    messageId: MessageId = ensuredMessage.messageId
    messageText: str = await ensuredMessage.formatForLLM(db, format=LLMMessageFormat.TEXT, useSingleMedia=False)

    try:
        llmService = LLMService.getInstance()
        model = llmService.getLLMManager().getModel(modelName)
    except Exception:
        logger.exception(
            "Failed to resolve embedding model %r for message %s in chat %d",
            modelName,
            messageId,
            chatId,
        )
        return False

    if model is None or not model.supportsEmbedding:
        logger.warning(
            "Embedding model %r not found or does not support embeddings; skipping message %s in chat %d",
            modelName,
            messageId,
            chatId,
        )
        return False

    try:
        embedding = await model.generateEmbeddings(messageText)
    except Exception:
        logger.exception(
            "Failed to generate embedding for message %s in chat %d with model %r",
            messageId,
            chatId,
            modelName,
        )
        return False

    try:
        await db.chatEmbeddings.saveMessageEmbedding(
            chatId=chatId,
            messageId=messageId,
            embedding=embedding,
            model=modelName,
        )
    except Exception:
        logger.exception(
            "Failed to save embedding for message %s in chat %d with model %r",
            messageId,
            chatId,
            modelName,
        )
        return False

    return True
