"""
Media handling module for Gromozeka Telegram bot.

This module provides handlers for media-related operations including:
- Image generation via AI models (/draw command)
- Media analysis with custom prompts (/analyze command)
- Media content retrieval ("что там" message handler)
- LLM tool integration for image generation

The module integrates with LLM services to provide AI-powered media
generation and analysis capabilities with fallback support.
"""

import logging
from typing import Any, Dict, List, Optional, Union

import magic
import telegram
from telegram.constants import MessageLimit

import lib.max_bot.models as maxModels
import lib.utils as utils
from internal.bot import constants
from internal.bot.common.models import TypingAction, UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    ChatSettingsKey,
    ChatType,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    LLMMessageFormat,
    MessageType,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MessageCategory
from internal.services.llm import LLMService
from lib.ai import (
    LLMFunctionParameter,
    LLMManager,
    LLMParameterType,
    ModelImageMessage,
    ModelMessage,
    ModelResultStatus,
)

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MediaHandler(BaseBotHandler):
    """
    Handler class for media-related bot operations.

    This class manages all media-related functionality including:
    - AI-powered image generation with fallback support
    - Media analysis using vision-capable LLM models
    - Media content retrieval from database
    - LLM tool registration for image generation

    The handler integrates with the LLM service to provide tool-calling
    capabilities, allowing AI assistants to generate images on demand.

    Attributes:
        llmService: Singleton instance of LLMService for tool registration

    Inherits from:
        BaseBotHandler: Provides base functionality for message handling,
                       chat settings, and database operations
    """

    def __init__(
        self, configManager: ConfigManager, database: Database, llmManager: LLMManager, botProvider: BotProvider
    ) -> None:
        """
        Initialize the MediaHandler with required dependencies.

        Sets up the handler by initializing the base class and registering
        the image generation tool with the LLM service. This allows AI
        assistants to generate images through tool-calling.

        Args:
            configManager: Configuration manager for accessing bot settings
            database: Database wrapper for storing and retrieving messages
            llmManager: LLM manager for accessing AI models
            botProvider: Bot provider (Telegram or Max)

        Side Effects:
            - Registers 'generate_and_send_image' tool with LLMService
            - Initializes base handler functionality
        """
        # Initialize the mixin (discovers handlers)
        super().__init__(configManager=configManager, database=database, llmManager=llmManager, botProvider=botProvider)

        self.llmService = LLMService.getInstance()

        self.llmService.registerTool(
            name="generate_and_send_image",
            description=(
                "Generate and send an image. ALWAYS use it if user ask to " "generate/paint/draw an image/picture/photo"
            ),
            parameters=[
                LLMFunctionParameter(
                    name="image_prompt",
                    description="Detailed prompt to generate the image from",
                    type=LLMParameterType.STRING,
                    required=True,
                ),
                LLMFunctionParameter(
                    name="image_description",
                    description="The description of the image if any",
                    type=LLMParameterType.STRING,
                    required=False,
                ),
            ],
            handler=self._llmToolGenerateAndSendImage,
        )

    ###
    # LLM Tool-Calling handlers
    ###

    async def _llmToolGenerateAndSendImage(
        self, extraData: Optional[Dict[str, Any]], image_prompt: str, image_description: Optional[str] = None, **kwargs
    ) -> str:
        """
        LLM tool handler for generating and sending images.

        This method is registered as an LLM tool and can be called by the AI assistant
        when users request image generation. It uses the configured image generation
        model with fallback support.

        Args:
            extraData: Dictionary containing context data, must include 'ensuredMessage' and 'typingManager'
            image_prompt: Detailed prompt describing the image to generate
            image_description: Optional caption/description for the generated image
            **kwargs: Additional keyword arguments (ignored)

        Returns:
            JSON string with generation result: {"done": bool, "errorMessage": str (optional)}

        Raises:
            RuntimeError: If extraData is None, missing ensuredMessage/typingManager, or
                         ensuredMessage/typingManager are not of correct type
        """
        if extraData is None:
            raise RuntimeError("extraData should be provided")
        if "ensuredMessage" not in extraData:
            raise RuntimeError("ensuredMessage should be provided")
        ensuredMessage = extraData["ensuredMessage"]
        if not isinstance(ensuredMessage, EnsuredMessage):
            raise RuntimeError(
                f"ensuredMessage should be instance of EnsuredMessage but got {type(ensuredMessage).__name__}"
            )
        if "typingManager" not in extraData:
            raise RuntimeError("typingManager should be provided")
        typingManager = extraData["typingManager"]
        if not isinstance(typingManager, TypingManager):
            raise RuntimeError(
                f"typingManager should be instance of TypingManager, but got {type(typingManager).__name__}"
            )

        # Show that we are sending photo + increase timeout as it could take long...
        originalAction = typingManager.action
        typingManager.action = TypingAction.UPLOAD_PHOTO
        typingManager.addTimeout(300)
        await typingManager.sendTypingAction()
        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
        logger.debug(
            f"Generating image: {image_prompt}. Image description: {image_description}, "
            f"mcID: {ensuredMessage.recipient.id}:{ensuredMessage.messageId}"
        )

        mlRet = await self.llmService.generateImage(
            image_prompt,
            chatId=ensuredMessage.recipient.id,
            chatSettings=chatSettings,
            llmManager=self.llmManager,
        )
        logger.debug(
            f"Generated image Data: {mlRet} for mcID: " f"{ensuredMessage.recipient.id}:{ensuredMessage.messageId}"
        )
        if mlRet.status != ModelResultStatus.FINAL:
            ret = await self.sendMessage(
                ensuredMessage,
                messageText=(
                    f"Не удалось сгенерировать изображение.\n```\n{mlRet.status}\n{str(mlRet.resultText)}\n```\n"
                    f"Prompt:\n```\n{image_prompt}\n```"
                ),
            )
            return utils.jsonDumps({"done": False, "errorMessage": mlRet.resultText})

        if mlRet.mediaData is None:
            logger.error(f"No image generated for {image_prompt}")
            return '{"done": false}'

        imgAddPrefix = ""
        if mlRet.isFallback:
            imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        ret = await self.sendMessage(
            ensuredMessage,
            photoData=mlRet.mediaData,
            messageText=image_description,
            mediaPrompt=image_prompt,
            addMessagePrefix=imgAddPrefix,
        )

        # Return original typing action (Probably - TypingAction.TYPING)
        typingManager.action = originalAction
        await typingManager.sendTypingAction()

        return utils.jsonDumps({"done": ret is not None})

    ###
    # Handling messages
    ###

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """
        Handle "what's there?" (что там) messages to retrieve media content.

        This handler responds to messages that mention the bot with "что там" phrase
        when replying to another message. It retrieves and returns the parsed content
        of the replied message from the database.

        For text messages, it delegates to the next handler. For media messages,
        it returns the stored media content (e.g., image description, transcription).

        Args:
            ensuredMessage: Wrapped message object with additional metadata
            updateObj: Update object containing the message

        Returns:
            HandlerResultStatus indicating how the message was processed:
                - SKIPPED: Message doesn't match criteria (not a mention, wrong phrase, etc.)
                - ERROR: Message matched but couldn't be processed (non-reply message)
                - NEXT: Text message, should be processed by next handler
                - FINAL: Successfully retrieved and sent media content
        """

        chatType = ensuredMessage.recipient.chatType

        if chatType not in [ChatType.PRIVATE, ChatType.GROUP]:
            return HandlerResultStatus.SKIPPED

        chatSettings = await self.getChatSettings(ensuredMessage.recipient.id)
        if not chatSettings[ChatSettingsKey.ALLOW_MENTION].toBool():
            return HandlerResultStatus.SKIPPED

        mentionedMe = await self.checkEMMentionsMe(ensuredMessage)
        if not mentionedMe.restText or (
            not mentionedMe.byNick and (not mentionedMe.byName or mentionedMe.byName[0] > 0)
        ):
            return HandlerResultStatus.SKIPPED
        # Proceed only if there is restText
        #  + mentioned at begin of message (byNick is always at begin of message, so not separate check needed)

        restText = mentionedMe.restText
        restTextLower = restText.lower()

        ###
        # what is prompt? Return prompt of replied message (if any)
        ###
        getPromptList = ["что за промпт", "как промпт", "what prompt"]
        isGetPrompt = False
        for getPrompt in getPromptList:
            if restTextLower.startswith(getPrompt):
                tail = restTextLower[len(getPrompt) :].strip()

                # Match only whole message
                if not tail.rstrip("?.").strip():
                    isGetPrompt = True
                    break

        ###
        # what there? Return parsed media content of replied message (if any)
        ###
        whatThereList = ["что там"]

        isWhatThere = False
        for whatThere in whatThereList:
            if restTextLower.startswith(whatThere):
                tail = restTextLower[len(whatThere) :].strip()

                # Match only whole message
                if not tail.rstrip("?.").strip():
                    isWhatThere = True
                    break

        if not isWhatThere and not isGetPrompt:
            return HandlerResultStatus.SKIPPED

        if not ensuredMessage.isReply:
            logger.warning(
                "WhatsThere\\getPrompt triggered on non-reply message "
                f"{ensuredMessage.recipient.id}:{ensuredMessage.messageId}"
            )
            return HandlerResultStatus.ERROR

        ensuredReply: Optional[EnsuredMessage] = ensuredMessage.getEnsuredRepliedToMessage()
        # logger.debug(f"ensuredReply: {ensuredReply}")
        if ensuredReply is None:
            logger.error("ensuredReply is None, but should be EnsuredMessage()")
            return HandlerResultStatus.ERROR

        response = constants.DUNNO_EMOJI
        if ensuredReply.messageType == MessageType.TEXT:
            logger.debug("WhatsThere triggered on TEXT message")
            await self.sendMessage(
                ensuredMessage,
                constants.ROBOT_EMOJI,
            )
            # Process further
            return HandlerResultStatus.NEXT

        async with await self.startTyping(ensuredMessage) as typingManager:
            # Not text message, try to get it's content from DB
            storedReply = await self.db.chatMessages.getChatMessageByMessageId(
                chatId=ensuredReply.recipient.id,
                messageId=ensuredReply.messageId,
            )
            if storedReply is None:
                logger.error(f"Failed to get parent message #{ensuredReply.recipient.id}:{ensuredReply.messageId}")
            else:
                # logger.debug(f"storedReply: {storedReply}")
                eStoredMsg = await EnsuredMessage.fromDBChatMessage(storedReply, self.db)
                # logger.debug(f"eStoredMsg: {eStoredMsg}")
                await eStoredMsg.updateMediaContent(self.db)
                # logger.debug(f"eStoredMsg V2: {eStoredMsg}")
                if isWhatThere:
                    if len(eStoredMsg.mediaList) == 1:
                        response = eStoredMsg.mediaList[0].content
                    elif eStoredMsg.mediaList:
                        response = "\n\n===========================\n\n".join(
                            [str(m.content) for m in eStoredMsg.mediaList]
                        )
                    else:
                        response = eStoredMsg.mediaContent
                elif isGetPrompt:
                    response = eStoredMsg.mediaPrompt
                    if response:
                        response = f"```\n{response}\n```"

                if response is None or response == "":
                    response = constants.DUNNO_EMOJI

            await self.sendMessage(
                ensuredMessage,
                messageText=response,
                typingManager=typingManager,
            )

        return HandlerResultStatus.FINAL

    ###
    # COMMANDS Handlers
    ###

    @commandHandlerV2(
        commands=("analyze",),
        shortDescription="<prompt> - Analyse answered media with given prompt",
        helpMessage=" `<prompt>`: Проанализировать медиа используя указанный промпт "
        "(на данный момент доступен только анализ картинок и статических стикеров).",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def analyze_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Handle /analyze <prompt> command to analyze media with AI.

        This command analyzes images or stickers from a replied message using the
        configured image parsing LLM model. The user provides a custom prompt
        describing what they want to know about the media.

        Command must be used as a reply to a message containing supported media.
        Currently supports: images (photos) and static stickers.

        Usage:
            /analyze <prompt> (as reply to message with media)

        Example:
            Reply to an image with: /analyze What objects are in this image?

        Args:
            ensuredMessage: Wrapped message object with additional metadata
            command: Command name (e.g., "analyze")
            args: Command arguments (the analysis prompt)
            UpdateObj: Update object containing the command message
            typingManager: Optional typing manager for showing typing status

        Returns:
            None. Sends analysis result or error message to the chat.

        Permissions:
            Requires ALLOW_ANALYZE setting enabled or admin privileges.
        """
        # Analyse media with given prompt. Should be reply to message with media.

        chatSettings = await self.getChatSettings(chatId=ensuredMessage.recipient.id)

        if not ensuredMessage.isReply:
            await self.sendMessage(
                ensuredMessage,
                messageText="Команда должна быть ответом на сообщение с медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        parentEnsuredMessage: Optional[EnsuredMessage] = ensuredMessage.getEnsuredRepliedToMessage()
        parentMessage: Optional[Union[telegram.Message, maxModels.Message]] = None
        if parentEnsuredMessage:
            parentMessage = parentEnsuredMessage.getBaseMessage()

        if parentEnsuredMessage is None or parentMessage is None:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не удалось определить родительское сообщение.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        prompt = args.strip()
        logger.debug(f"Command string: '{command}', prompt: '{prompt}'")

        if not prompt:
            await self.sendMessage(
                ensuredMessage,
                messageText="Необходимо указать запрос для анализа медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        mediaDataList: List[bytes] = []

        if (
            self.botProvider == BotProvider.TELEGRAM
            and isinstance(parentMessage, telegram.Message)
            and self._bot is not None
        ):
            fileId: Optional[str] = None
            match parentEnsuredMessage.messageType:
                case MessageType.IMAGE:
                    if not parentMessage.photo:
                        raise ValueError("Photo is empty")

                    fileId = parentMessage.photo[-1].file_id
                case MessageType.STICKER:
                    if parentMessage.sticker is None:
                        raise ValueError("Sticker is None")
                    fileId = parentMessage.sticker.file_id
                    # Removed unused variable fileUniqueId
                case _:
                    await self.sendMessage(
                        ensuredMessage,
                        messageText=f"Неподдерживаемый тип медиа: {parentEnsuredMessage.messageType}",
                        messageCategory=MessageCategory.BOT_ERROR,
                        typingManager=typingManager,
                    )
                    return

            mediaData = await self._bot.downloadAttachment(mediaId="", fileId=fileId)
            if mediaData is not None:
                mediaDataList.append(bytes(mediaData))
        elif (
            self.botProvider == BotProvider.MAX
            and isinstance(parentMessage, maxModels.Message)
            and self._bot is not None
            and parentMessage.body.attachments
        ):
            for attachment in parentMessage.body.attachments:
                mediaData = None
                if isinstance(attachment, maxModels.PhotoAttachment):
                    mediaData = await self._bot.downloadAttachment(
                        mediaId=attachment.payload.token, fileId=attachment.payload.url
                    )
                elif isinstance(attachment, maxModels.StickerAttachment):
                    mediaData = await self._bot.downloadAttachment(
                        mediaId=attachment.payload.code, fileId=attachment.payload.url
                    )

                if mediaData is not None:
                    mediaDataList.append(bytes(mediaData))

        if not mediaDataList:
            await self.sendMessage(
                ensuredMessage,
                messageText="Не удалось получить данные медиа.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        maxMediaIdx = len(mediaDataList) - 1
        for i, mediaData in enumerate(mediaDataList):
            if typingManager:
                await typingManager.sendTypingAction()
            mimeType = magic.from_buffer(bytes(mediaData), mime=True)
            logger.debug(f"Mime type: {mimeType}")
            if not mimeType.startswith("image/"):
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Неподдерживаемый MIME-тип медиа: {mimeType}.",
                    messageCategory=MessageCategory.BOT_ERROR,
                    typingManager=typingManager if i == maxMediaIdx else None,
                )
                continue

            reqMessages = [
                ModelMessage(
                    role="system",
                    content=prompt,
                ),
                ModelImageMessage(
                    role="user",
                    # content="",
                    image=bytearray(mediaData),
                ),
            ]

            llmRet = await self.llmService.generateText(
                reqMessages,
                chatId=ensuredMessage.recipient.id,
                chatSettings=chatSettings,
                llmManager=self.llmManager,
                modelKey=ChatSettingsKey.IMAGE_PARSING_MODEL,
                fallbackKey=ChatSettingsKey.IMAGE_PARSING_FALLBACK_MODEL,
            )
            if typingManager:
                await typingManager.sendTypingAction()
            logger.debug(f"LLM result: {llmRet}")
            if llmRet.status != ModelResultStatus.FINAL:
                await self.sendMessage(
                    ensuredMessage,
                    messageText=f"Не удалось проанализировать медиа:\n```\n{llmRet.status}\n{llmRet.error}\n```",
                    messageCategory=MessageCategory.BOT_ERROR,
                    typingManager=typingManager if i == maxMediaIdx else None,
                )
                return

            await self.sendMessage(
                ensuredMessage,
                messageText=llmRet.resultText,
                messageCategory=MessageCategory.BOT_COMMAND_REPLY,
                typingManager=typingManager if i == maxMediaIdx else None,
            )

    @commandHandlerV2(
        commands=("draw",),
        shortDescription="[<prompt>] - Draw image with given prompt " "(use qoute or replied message as prompt if any)",
        helpMessage=" `[<prompt>]`: Сгенерировать изображение, используя указанный промпт. "
        "Так же может быть ответом на сообщение или цитированием.",
        visibility={CommandPermission.PRIVATE},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
        typingAction=TypingAction.UPLOAD_PHOTO,
    )
    async def draw_command(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        UpdateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """
        Handle /draw [<prompt>] command to generate images with AI.

        This command generates images using the configured image generation LLM model
        with fallback support. The prompt can be provided in three ways:
        1. Directly after the command: /draw a beautiful sunset
        2. As a quoted text when replying to a message
        3. As the full text of a replied message

        The command uses the primary image generation model and automatically falls
        back to the secondary model if the primary fails.

        Usage:
            /draw <prompt>
            /draw (as reply to message with text)
            /draw (as reply with quoted text)

        Examples:
            /draw a cat wearing a hat
            Reply to text message with: /draw
            Reply with quote and send: /draw

        Args:
            ensuredMessage: Wrapped message object with additional metadata
            command: Command name (e.g., "draw")
            args: Command arguments (optional image prompt)
            UpdateObj: Update object containing the command message
            typingManager: Optional typing manager for showing typing status

        Returns:
            None. Sends generated image or error message to the chat.

        Permissions:
            Requires ALLOW_DRAW setting enabled or admin privileges.
        """
        # Draw picture with given prompt. If this is reply to message, use quote or full message as prompt
        chatSettings = await self.getChatSettings(chatId=ensuredMessage.recipient.id)

        prompt = ensuredMessage.messageText

        if ensuredMessage.isQuote and ensuredMessage.quoteText:
            prompt = ensuredMessage.quoteText

        elif ensuredMessage.isReply and ensuredMessage.replyText:
            prompt = ensuredMessage.replyText

        elif args:
            prompt = args
        else:
            logger.warning(f"No prompt found in message: {ensuredMessage}")
            # Get last messages from this user in chat and generate image, based on them

            # prompt = (
            #     f"Draw image for user `{ensuredMessage.sender.name}` based on"
            #     f" his/her latest messages: {utils.jsonDumps(lastMessages)}"
            # )

            # TODO: Move prompt to chat settings
            latestMessages: List[ModelMessage] = [
                ModelMessage(
                    content="Write prompt for generating image for user, based on his/ner latest messages. "
                    "Print ONLY prompt.",
                    role="system",
                ),
            ]
            for msg in reversed(
                await self.db.chatMessages.getChatMessagesByUser(
                    ensuredMessage.recipient.id,
                    ensuredMessage.sender.id,
                    limit=10,
                )
            ):
                eMsg = await EnsuredMessage.fromDBChatMessage(msg, self.db)
                await self._updateEMessageUserData(eMsg)
                latestMessages.append(
                    await eMsg.toModelMessage(
                        self.db,
                        format=LLMMessageFormat(
                            chatSettings[ChatSettingsKey.LLM_MESSAGE_FORMAT].toStr(),
                        ),
                    )
                )

            llmRet = await self.llmService.generateText(
                latestMessages,
                chatId=ensuredMessage.recipient.id,
                chatSettings=chatSettings,
                llmManager=self.llmManager,
                modelKey=ChatSettingsKey.CHAT_MODEL,
                fallbackKey=ChatSettingsKey.FALLBACK_MODEL,
            )
            # Should I check llmRet.status? do not wanna for now
            if llmRet.resultText:
                prompt = llmRet.resultText
            else:
                # Fallback to something static
                chatInfo = await self.getChatInfo(ensuredMessage.recipient.id)
                chatTitle = chatInfo["title"] if chatInfo is not None else str(ensuredMessage.recipient)
                prompt = f"Draw image of {ensuredMessage.sender} in chat `{chatTitle}`"

        logger.debug(f"Prompt: '{prompt}'")

        if not prompt:
            # Fixed f-string missing placeholders
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    "Необходимо указать запрос для генерации изображения. "
                    "Или послать команду ответом на сообщение с текстом "
                    "(можно цитировать при необходимости)."
                ),
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        mlRet = await self.llmService.generateImage(
            prompt,
            chatId=ensuredMessage.recipient.id,
            chatSettings=chatSettings,
            llmManager=self.llmManager,
        )
        logger.debug(
            f"Generated image Data: {mlRet} for mcID: " f"{ensuredMessage.recipient.id}:{ensuredMessage.messageId}"
        )
        if mlRet.status != ModelResultStatus.FINAL:
            await self.sendMessage(
                ensuredMessage,
                messageText=(
                    f"Не удалось сгенерировать изображение.\n```\n{mlRet.status}\n"
                    f"{str(mlRet.resultText)}\n```\nPrompt:\n```\n{prompt}\n```"
                ),
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        if mlRet.mediaData is None:
            logger.error(f"No image generated for {prompt}")
            await self.sendMessage(
                ensuredMessage,
                messageText="Ошибка генерации изображения, попробуйте позже.",
                messageCategory=MessageCategory.BOT_ERROR,
                typingManager=typingManager,
            )
            return

        logger.debug(f"Media data len: {len(mlRet.mediaData)}")

        imgAddPrefix = ""
        if mlRet.isFallback:
            imgAddPrefix = chatSettings[ChatSettingsKey.FALLBACK_HAPPENED_PREFIX].toStr()
        await self.sendMessage(
            ensuredMessage,
            photoData=mlRet.mediaData,
            messageText=(
                "Сгенерировал изображение по Вашему запросу:\n```\n"
                f"{prompt[:MessageLimit.CAPTION_LENGTH - 60]}"
                "\n```"
            ),
            mediaPrompt=prompt,
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
            addMessagePrefix=imgAddPrefix,
            typingManager=typingManager,
        )
