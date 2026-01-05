"""
Text formatting module for converting between different markup formats.

This module provides classes and functions for handling text formatting entities
and converting between different markup formats such as Markdown, Telegram markup,
and Max messenger markup.
"""

import logging
import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Dict, List, Optional, Self

import telegram

import lib.max_bot.models as maxModels
from lib import utils

logger = logging.getLogger(__name__)


class FormatType(StrEnum):
    """Enumeration of supported text formatting types.

    This enum defines all the supported text formatting types that can be used
    for converting between different markup formats.
    """

    # NO markup
    UNSPECIFIED = "UNSPECIFIED"
    NORMAL = "normal"
    """
    Just normal text without formatting
    (Used for unused markup like BOT_COMMAND)
    """

    # Block Markups
    HEADING = "heading"
    """# Heading"""
    QUOTE = "quote"
    """
    >quote
    >text
    """
    CODE_BLOCK = "code-block"
    """
    ```codeLang
    block of code
    ```"""

    # Inline Markups
    BOLD = "bold"
    """**bold text**"""
    ITALIC = "italic"
    """*italic text*"""
    INLINE_CODE = "code"
    """`inline code block`"""
    STRIKETHROUGH = "strikethrough"
    """~strikethrough text~"""
    UNDERLINE = "underline"
    """_underline text_"""
    SPOILER = "spoiler"
    """||spoiler text||"""

    # Special markup
    LINK = "link"
    """
    [Link text](url)
    or
    http://auto-link.tld
    """
    USER_MENTION = "user_mention"
    """
    @user_mention
    or
    [!user_mention](with link to user)
    """

    def getIndex(self) -> int:
        """Get the index of the format type.

        Returns:
            The index of the format type in its value string
        """
        return self.value.index(self.value)


class OutputFormat(StrEnum):
    """Enumeration of supported output formats for text formatting.

    This enum defines the supported output formats that can be used
    when converting text to different markup formats.
    """

    MARKDOWN = "markdown"
    MARKDOWN_TG = "markdown-telegram"
    MARKDOWN_MAX = "markdown-max"


class FormatEntity:
    """Represents a text formatting entity with position and formatting information.

    This class encapsulates information about a text formatting entity, including
    its type, position (offset and length), and additional metadata like URLs,
    user mentions, or code language information.
    """

    __slots__ = ("type", "offset", "length", "url", "userId", "userName", "codeLanguage")

    def __init__(
        self,
        type: FormatType,
        offset: int,
        length: int,
        *,
        url: Optional[str] = None,
        userId: Optional[int] = None,
        userName: Optional[str] = None,
        codeLanguage: Optional[str] = None,
    ):
        """Initialize a FormatEntity instance.

        Args:
            type: The type of formatting to apply
            offset: The starting position of the entity in the text
            length: The length of the text to be formatted
            url: Optional URL for link entities
            userId: Optional user ID for mention entities
            userName: Optional username for mention entities
            codeLanguage: Optional language specification for code blocks
        """
        self.type = FormatType(type)
        self.offset = offset
        self.length = length
        self.url = url
        self.userId = userId
        self.userName = userName
        self.codeLanguage = codeLanguage

    @classmethod
    def fromMax(cls, entity: maxModels.MarkupElement) -> Self:
        """Create a FormatEntity from a Max markup element.

        Args:
            entity: The Max markup element to convert

        Returns:
            A new FormatEntity instance representing the Max markup element

        Raises:
            ValueError: If the entity is not an instance of MarkupElement
        """
        if not isinstance(entity, maxModels.MarkupElement):
            raise ValueError("entity must be an instance of MarkupElement")

        entityType = FormatType.UNSPECIFIED
        url: Optional[str] = None
        userId: Optional[int] = None
        userName: Optional[str] = None

        match entity.type:
            case maxModels.MarkupType.UNSPECIFIED:
                logger.warning("Meet UNSPECIFIED markup element")
                entityType = FormatType.UNSPECIFIED
            case maxModels.MarkupType.STRONG:
                entityType = FormatType.BOLD
            case maxModels.MarkupType.EMPHASIZED:
                entityType = FormatType.ITALIC
            case maxModels.MarkupType.MONOSPACED:
                entityType = FormatType.INLINE_CODE
            case maxModels.MarkupType.STRIKETHROUGH:
                entityType = FormatType.STRIKETHROUGH
            case maxModels.MarkupType.UNDERLINE:
                entityType = FormatType.UNDERLINE
            case maxModels.MarkupType.LINK:
                entityType = FormatType.LINK
                if isinstance(entity, maxModels.LinkMarkup):
                    url = entity.url
                else:
                    logger.error(
                        f"Meet LINK markup element, but it is not an instance of LinkMarkup, but a {type(entity)}"
                    )
            case maxModels.MarkupType.USER_MENTION:
                entityType = FormatType.USER_MENTION
                if isinstance(entity, maxModels.UserMentionMarkup):
                    userId = entity.user_id
                    userName = entity.user_link
                else:
                    logger.error(
                        "Meet USER_MENTION markup element, but it is not an instance of UserMentionMarkup,"
                        f" but a {type(entity)}"
                    )
            case maxModels.MarkupType.HEADING:
                entityType = FormatType.HEADING
            case maxModels.MarkupType.HIGHLIGHTED:
                entityType = FormatType.NORMAL
            case _:
                logger.error(f"Unknown markup type: {entity.type}, use FormatType.UNSPECIFIED")
                entityType = FormatType.UNSPECIFIED
                # raise ValueError("Invalid markup type")

        return cls(
            type=entityType,
            offset=entity.fromField,
            length=entity.length,
            url=url,
            userId=userId,
            userName=userName,
            codeLanguage=None,
        )

    @classmethod
    def fromTelegram(cls, entity: telegram.MessageEntity) -> Self:
        """Create a FormatEntity from a Telegram message entity.

        Args:
            entity: The Telegram message entity to convert

        Returns:
            A new FormatEntity instance representing the Telegram message entity

        Raises:
            ValueError: If the entity is not an instance of MessageEntity
        """
        if not isinstance(entity, telegram.MessageEntity):
            raise ValueError("entity must be an instance of MessageEntity")

        entityType = FormatType.UNSPECIFIED
        userId: Optional[int] = None
        userName: Optional[str] = None
        if entity.user:
            userId = entity.user.id
            userName = entity.user.username

        match entity.type:
            case (
                telegram.constants.MessageEntityType.BOT_COMMAND
                | telegram.constants.MessageEntityType.CASHTAG
                | telegram.constants.MessageEntityType.HASHTAG
                | telegram.constants.MessageEntityType.EMAIL
                | telegram.constants.MessageEntityType.PHONE_NUMBER
                | telegram.constants.MessageEntityType.CUSTOM_EMOJI
            ):
                entityType = FormatType.NORMAL
            case (
                telegram.constants.MessageEntityType.BLOCKQUOTE
                | telegram.constants.MessageEntityType.EXPANDABLE_BLOCKQUOTE
            ):
                entityType = FormatType.QUOTE
            case telegram.constants.MessageEntityType.BOLD:
                entityType = FormatType.BOLD
            case telegram.constants.MessageEntityType.CODE:
                entityType = FormatType.INLINE_CODE
            case telegram.constants.MessageEntityType.ITALIC:
                entityType = FormatType.ITALIC
            case telegram.constants.MessageEntityType.SPOILER:
                entityType = FormatType.SPOILER
            case telegram.constants.MessageEntityType.STRIKETHROUGH:
                entityType = FormatType.STRIKETHROUGH
            case telegram.constants.MessageEntityType.UNDERLINE:
                entityType = FormatType.UNDERLINE
            case telegram.constants.MessageEntityType.PRE:
                entityType = FormatType.CODE_BLOCK
                entity.BLOCKQUOTE
            case telegram.constants.MessageEntityType.TEXT_LINK | telegram.constants.MessageEntityType.URL:
                entityType = FormatType.LINK
            case telegram.constants.MessageEntityType.TEXT_MENTION | telegram.constants.MessageEntityType.MENTION:
                entityType = FormatType.USER_MENTION
            case _:
                logger.error(f"Unknown markup type: {entity.type} in {entity}, use FormatType.UNSPECIFIED")
                entityType = FormatType.UNSPECIFIED
                # raise ValueError("Invalid markup type")

        return cls(
            type=entityType,
            offset=entity.offset,
            length=entity.length,
            url=entity.url,
            userId=userId,
            userName=userName,
            codeLanguage=entity.language,
        )

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> Self:
        """Create a FormatEntity from a dictionary.

        Args:
            data: Dictionary containing the entity data

        Returns:
            A new FormatEntity instance representing the data
        """
        return cls(
            type=FormatType(data.get("type", FormatType.UNSPECIFIED)),
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            url=data.get("url", None),
            userId=data.get("userId", None),
            userName=data.get("userName", None),
            codeLanguage=data.get("codeLanguage", None),
        )

    def toDict(self) -> Dict[str, Any]:
        """Convert the FormatEntity to a dictionary.

        Returns:
            A dictionary representation of the FormatEntity
        """
        ret = {
            "type": self.type.value,
            "offset": self.offset,
            "length": self.length,
            "url": self.url,
            "userId": self.userId,
            "userName": self.userName,
            "codeLanguage": self.codeLanguage,
        }
        return {k: v for k, v in ret.items() if v is not None}

    def __str__(self) -> str:
        """Return a string representation of the FormatEntity.

        Returns:
            A JSON string representation of the FormatEntity
        """
        return utils.jsonDumps(self.toDict())

    def __repr__(self) -> str:
        """Return a detailed string representation of the FormatEntity.

        Returns:
            A string representation of the FormatEntity constructor
        """
        return f"FormatEntity({self.toDict()})"

    @classmethod
    def fromList(cls, entities: Sequence[telegram.MessageEntity | maxModels.MarkupElement]) -> List[Self]:
        """Create a list of FormatEntity instances from a list of markup entities.

        Args:
            entities: A sequence of Telegram MessageEntity or Max MarkupElement instances

        Returns:
            A list of FormatEntity instances

        Raises:
            ValueError: If an entity is not a supported type
        """
        ret: List[Self] = []

        for entity in entities:
            newEntity: Optional[Self] = None
            if isinstance(entity, telegram.MessageEntity):
                newEntity = cls.fromTelegram(entity)
            elif isinstance(entity, maxModels.MarkupElement):
                newEntity = cls.fromMax(entity)
            else:
                raise ValueError(f"Invalid entity type: {type(entity)}")
            if not newEntity:
                logger.error("New Entity is None")
                continue
            elif newEntity.type == FormatType.UNSPECIFIED:
                logger.error(f"New Entity is UNSPECIFIED: {newEntity}")
                continue
            elif newEntity.type == FormatType.NORMAL:
                continue
            else:
                ret.append(newEntity)

        return ret

    @classmethod
    def fromDictList(cls, entities: Sequence[Dict[str, Any]]) -> List[Self]:
        """Create a list of FormatEntity instances from a list of dictionaries.

        Args:
            entities: A sequence of dictionaries containing entity data

        Returns:
            A list of FormatEntity instances
        """
        return [cls.fromDict(entity) for entity in entities]

    @classmethod
    def toDictList(cls, entities: Sequence[Self]) -> List[Dict[str, Any]]:
        """Convert a list of FormatEntity instances to a list of dictionaries.

        Args:
            entities: A sequence of FormatEntity instances

        Returns:
            A list of dictionaries representing the entities
        """
        return [entity.toDict() for entity in entities]

    def formatText(self, text: str, outputFormat: OutputFormat = OutputFormat.MARKDOWN) -> str:
        """Format text according to the entity's type and the specified output format.

        Args:
            text: The text to format
            outputFormat: The output format to use (default: OutputFormat.MARKDOWN)

        Returns:
            The formatted text

        Raises:
            ValueError: If the format type is unsupported or invalid user mention data
        """
        prefix = ""
        body = text
        suffix = ""
        # If text starts\ends with whitespace, do not decorate it with inline markup
        match = re.match(r"^(\s*)(.*?)(\s*)$", text)
        if match:
            prefix = match.group(1)
            body = match.group(2)
            suffix = match.group(3)

        markupWith = ""
        match self.type:
            case FormatType.UNSPECIFIED:
                logger.error("Format type is UNSPECIFIED, no formatting possible")
                return text
            case FormatType.NORMAL:
                return text
            case FormatType.BOLD:
                markupWith = "**"
            case FormatType.ITALIC:
                markupWith = "_"
            case FormatType.INLINE_CODE:
                markupWith = "`"
            case FormatType.STRIKETHROUGH:
                markupWith = "~~"
            case FormatType.UNDERLINE:
                markupWith = "++"
            case FormatType.HEADING:
                return "".join(map(lambda x: f"# {x}", text.splitlines(keepends=True)))
            case FormatType.QUOTE:
                ret = "".join(map(lambda x: f"> {x}", text.splitlines(keepends=True)))
                if outputFormat == OutputFormat.MARKDOWN_MAX:
                    ret = f"\n{ret}\n"
                return ret
            case FormatType.SPOILER:
                markupWith = "||"
            case FormatType.CODE_BLOCK:
                return f"```{self.codeLanguage if self.codeLanguage else ''}\n{text}\n```"
            case FormatType.LINK:
                url = self.url if self.url else text
                return f"[{text}]({url})"
            case FormatType.USER_MENTION:
                if self.userId is None and self.userId is None:
                    return text
                elif self.userName is not None:
                    # Ensure it starts with @
                    return f"@{self.userName.lstrip('@')}"
                elif self.userId is not None:
                    match outputFormat:
                        case OutputFormat.MARKDOWN:
                            logger.warning("User mention without username is not supported in pure Markdown")
                            return f"[{text}]({self.userId})"
                        case OutputFormat.MARKDOWN_TG:
                            return f"[{text}](tg://user?id={self.userId})"
                        case OutputFormat.MARKDOWN_MAX:
                            return f"[{text}](max://max.ru/{self.userId})"
                        case _:
                            raise ValueError(f"Unsupported output format: {outputFormat}")
                else:
                    raise ValueError("Invalid user mention")
            case _:
                raise ValueError(f"Unsupported format type: {self.type}")

        # Do not add format to empty body
        if body:
            return f"{prefix}{markupWith}{body}{markupWith}{suffix}"
        else:
            return text

    @classmethod
    def parseText(
        cls,
        text: str | bytes,
        entities: Sequence[Self],
        outputFormat: OutputFormat = OutputFormat.MARKDOWN,
        _initialOffset: int = 0,
    ) -> str:
        """Parse text with formatting entities and convert to the specified output format.

        Args:
            text: The text to parse (string or bytes)
            entities: A sequence of FormatEntity instances describing the formatting
            outputFormat: The output format to use (default: OutputFormat.MARKDOWN)
            _initialOffset: Internal parameter for handling nested entities (default: 0)

        Returns:
            The parsed and formatted text
        """
        # TODO: Somehow escape markup, which already present in text

        # Use negative length as we want to sort from longer to shorter in case of same offset
        entities = sorted(entities, key=lambda v: (v.offset, -v.length, v.type.getIndex()))
        # Use UTF-16 to get fixed-length characters
        # if text is bytes, suppose it was already converted to UTF-16
        utf16Text = text.encode("utf-16-le") if isinstance(text, str) else text
        ret: str = ""

        # logger.debug(f"Parsing text: '{text}' -> '{utf16Text}' with ({entities})")
        # logger.debug(f"Parsing text: '{text}' with ({entities})")

        entitiesCount = len(entities)
        # We'll manipulate `i` so we have to use while cycle
        i = 0
        lastPos = 0
        while i < entitiesCount:
            entity = entities[i]
            # Increase `i` here as we'll use it later for searching for nested entities
            i += 1
            offset = (entity.offset - _initialOffset) * 2
            length = entity.length * 2
            # Add the text before the entity if any
            ret += utf16Text[lastPos:offset].decode("utf-16-le")

            utf16MatchedText = utf16Text[offset : offset + length]

            # logger.debug(f" entity: {entity}, o:{offset}, l:{length}, text:'{utf16MatchedText}'")

            # Find all nested entities
            _endPos = entity.offset + entity.length
            nestedEntities: List[Self] = []
            while i < entitiesCount and entities[i].offset < _endPos:
                nestedEntities.append(entities[i])
                i += 1

            matchedText = (
                cls.parseText(utf16MatchedText, nestedEntities, outputFormat, entity.offset)
                if nestedEntities
                else utf16MatchedText.decode("utf-16-le")
            )
            ret += entity.formatText(matchedText, outputFormat)
            lastPos = offset + length

        ret += utf16Text[lastPos:].decode("utf-16-le")
        return ret
