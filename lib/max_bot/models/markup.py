"""
Markup models for Max Messenger Bot API.

This module contains markup-related dataclasses including MarkupElement and all
markup types for formatting text in messages. It provides a comprehensive set of
classes for representing various text formatting elements such as bold, italic,
monospace, strikethrough, underline, links, and user mentions.
"""

import logging
from enum import StrEnum
from typing import Any, Dict, List, Optional, Self

from .base import BaseMaxBotModel

logger = logging.getLogger(__name__)


class MarkupType(StrEnum):
    """Enumeration of available markup types for text formatting in Max Messenger.

    This enum defines all supported markup types that can be applied to text
    messages, including standard formatting options and additional types not
    present in the official Swagger specification.
    """

    UNSPECIFIED = "UNSPECIIFED"
    """Unspecified or unknown markup type."""

    STRONG = "strong"
    """Bold text markup (StrongMarkup)."""
    EMPHASIZED = "emphasized"
    """Italic text markup (EmphasizedMarkup)."""
    MONOSPACED = "monospaced"
    """Monospace text markup (MonospacedMarkup)."""
    STRIKETHROUGH = "strikethrough"
    """Strikethrough text markup (StrikethroughMarkup)."""
    UNDERLINE = "underline"
    """Underlined text markup (UnderlineMarkup)."""
    LINK = "link"
    """Hyperlink markup (LinkMarkup)."""
    USER_MENTION = "user_mention"
    """User mention markup (UserMentionMarkup)."""
    # Those are not present in Swagger, but has classes for it =\
    HEADING = "heading"
    """Heading text markup (HeadingMarkup)."""
    HIGHLIGHTED = "highlighted"
    """Highlighted text markup (HighlightedMarkup)."""

    @classmethod
    def fromStr(cls, value: str) -> "MarkupType":
        """Convert a string value to a MarkupType enum member.

        Args:
            value: The string representation of the markup type.

        Returns:
            The corresponding MarkupType enum member, or UNSPECIFIED if the
            value is not found in the enum.
        """
        if value in cls.__members__.values():
            return cls(value)
        else:
            logger.warning(f"{cls.__name__} does not have '{value}' value, returning UNSPECIFIED")
            return cls.UNSPECIFIED


class MarkupElement(BaseMaxBotModel):
    """Base class for markup elements used in text formatting.

    This class represents a generic markup element that can be applied to text
    in Max Messenger messages. It stores the type of markup, the starting position
    in the text, and the length of the formatted segment.

    Attributes:
        type: The type of markup element (e.g., bold, italic, link).
        fromField: The zero-based index where the markup element starts in the text.
        length: The length of the text segment covered by this markup element.
    """

    __slots__ = ("type", "fromField", "length")

    def __init__(self, *, type: MarkupType, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a MarkupElement instance.

        Args:
            type: The type of markup element to apply.
            fromField: The zero-based starting index of the markup in the text.
            length: The length of the text segment to format.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.type: MarkupType = type
        """
        Тип элемента разметки.
        Может быть:
          **жирный**,
          *курсив*,
          ~зачеркнутый~,
          <ins>подчеркнутый</ins>,
          `моноширинный`,
          ссылка или упоминание пользователя
        """
        self.fromField: int = fromField  # NOTE: Actually `from` but it is reserver word
        """Индекс начала элемента разметки в тексте. Нумерация с нуля"""
        self.length: int = length
        """Длина элемента разметки"""

    def to_dict(self, includePrivate: bool = False, recursive: bool = False) -> Dict[str, Any]:
        """Convert the markup element to a dictionary representation.

        Args:
            includePrivate: Whether to include private attributes in the output.
            recursive: Whether to recursively convert nested objects.

        Returns:
            A dictionary representation of the markup element with the `fromField`
            key renamed to `from` for API compatibility.
        """
        ret = super().to_dict(includePrivate, recursive)
        if "fromField" in ret:
            ret["from"] = ret.pop("fromField")
        return ret

    @classmethod
    def _getExtraKwargs(cls, api_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Extract extra keyword arguments from API response data.

        Args:
            api_kwargs: The raw API response dictionary.

        Returns:
            A dictionary containing extra keyword arguments with the `from` key
            removed (as it's handled separately as `fromField`).
        """
        ret = super()._getExtraKwargs(api_kwargs)
        ret.pop("from", None)
        return ret

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create a MarkupElement instance from an API response dictionary.

        Args:
            data: The API response dictionary containing markup element data.

        Returns:
            A new MarkupElement instance populated with data from the dictionary.
        """
        return cls(
            type=MarkupType.fromStr(data.get("type", MarkupType.UNSPECIFIED)),
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StrongMarkup(MarkupElement):
    """Represents bold (**жирный**) text formatting.

    This markup type is used to make text appear bold in messages.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a StrongMarkup instance.

        Args:
            fromField: The zero-based starting index of the bold text.
            length: The length of the bold text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.STRONG, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrongMarkup":
        """Create a StrongMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing strong markup data.

        Returns:
            A new StrongMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class EmphasizedMarkup(MarkupElement):
    """Represents italic (*курсив*) text formatting.

    This markup type is used to make text appear italic in messages.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize an EmphasizedMarkup instance.

        Args:
            fromField: The zero-based starting index of the italic text.
            length: The length of the italic text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.EMPHASIZED, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmphasizedMarkup":
        """Create an EmphasizedMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing emphasized markup data.

        Returns:
            A new EmphasizedMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MonospacedMarkup(MarkupElement):
    """Represents monospace (`моноширинный`) or code block (```код```) formatting.

    This markup type is used to display text in a monospace font, typically for
    code snippets or technical content.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a MonospacedMarkup instance.

        Args:
            fromField: The zero-based starting index of the monospace text.
            length: The length of the monospace text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.MONOSPACED, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonospacedMarkup":
        """Create a MonospacedMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing monospaced markup data.

        Returns:
            A new MonospacedMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StrikethroughMarkup(MarkupElement):
    """Represents strikethrough (~зачеркнутый~) text formatting.

    This markup type is used to display text with a horizontal line through it,
    typically to indicate deleted or crossed-out content.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a StrikethroughMarkup instance.

        Args:
            fromField: The zero-based starting index of the strikethrough text.
            length: The length of the strikethrough text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.STRIKETHROUGH, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrikethroughMarkup":
        """Create a StrikethroughMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing strikethrough markup data.

        Returns:
            A new StrikethroughMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UnderlineMarkup(MarkupElement):
    """Represents underlined (<ins>подчеркнутый</ins>) text formatting.

    This markup type is used to display text with an underline, typically for
    emphasis or to indicate links.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize an UnderlineMarkup instance.

        Args:
            fromField: The zero-based starting index of the underlined text.
            length: The length of the underlined text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.UNDERLINE, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnderlineMarkup":
        """Create an UnderlineMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing underline markup data.

        Returns:
            A new UnderlineMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class HeadingMarkup(MarkupElement):
    """Represents heading text formatting.

    This markup type is used to display text as a heading or title.
    Note: This type is not present in the official Swagger specification.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a HeadingMarkup instance.

        Args:
            fromField: The zero-based starting index of the heading text.
            length: The length of the heading text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.HEADING, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeadingMarkup":
        """Create a HeadingMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing heading markup data.

        Returns:
            A new HeadingMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class HighlightedMarkup(MarkupElement):
    """Represents highlighted text formatting.

    This markup type is used to display text with a highlight or background color,
    typically for emphasis or to draw attention to specific content.
    Note: This type is not present in the official Swagger specification.
    """

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a HighlightedMarkup instance.

        Args:
            fromField: The zero-based starting index of the highlighted text.
            length: The length of the highlighted text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.HIGHLIGHTED, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HighlightedMarkup":
        """Create a HighlightedMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing highlighted markup data.

        Returns:
            A new HighlightedMarkup instance populated with data from the dictionary.
        """
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LinkMarkup(MarkupElement):
    """Represents a hyperlink in text.

    This markup type is used to create clickable links within messages.
    The link is applied to a specific segment of text defined by its position
    and length.

    Attributes:
        url: The URL that the link points to.
    """

    __slots__ = ("url",)

    def __init__(self, *, url: str, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a LinkMarkup instance.

        Args:
            url: The URL that the link should point to.
            fromField: The zero-based starting index of the link text.
            length: The length of the link text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.LINK, fromField=fromField, length=length, api_kwargs=api_kwargs)
        self.url: str = url
        """URL ссылки"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkMarkup":
        """Create a LinkMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing link markup data.

        Returns:
            A new LinkMarkup instance populated with data from the dictionary.
        """
        return cls(
            url=data.get("url", ""),
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UserMentionMarkup(MarkupElement):
    """Represents a user mention in text.

    This markup type is used to mention users in messages. Mentions can be made
    either by username (e.g., @username) or by user ID (for users without a username).

    Attributes:
        user_link: The username of the mentioned user (e.g., @username).
        user_id: The ID of the mentioned user (used when no username is available).
    """

    __slots__ = ("user_link", "user_id")

    def __init__(
        self,
        *,
        user_link: Optional[str] = None,
        user_id: Optional[int] = None,
        fromField: int,
        length: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a UserMentionMarkup instance.

        Args:
            user_link: The username of the mentioned user (e.g., @username).
            user_id: The ID of the mentioned user (used when no username is available).
            fromField: The zero-based starting index of the mention text.
            length: The length of the mention text segment.
            api_kwargs: Additional API keyword arguments to store.
        """
        super().__init__(type=MarkupType.USER_MENTION, fromField=fromField, length=length, api_kwargs=api_kwargs)
        self.user_link: Optional[str] = user_link
        """`@username` упомянутого пользователя"""
        self.user_id: Optional[int] = user_id
        """ID упомянутого пользователя без имени"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMentionMarkup":
        """Create a UserMentionMarkup instance from an API response dictionary.

        Args:
            data: The API response dictionary containing user mention markup data.

        Returns:
            A new UserMentionMarkup instance populated with data from the dictionary.
        """
        return cls(
            user_link=data.get("user_link", None),
            user_id=data.get("user_id", None),
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


def markupListFromList(dataList: List[Dict[str, Any]]) -> List[MarkupElement]:
    """Convert a list of markup dictionaries to a list of MarkupElement objects.

    This function processes a list of dictionaries representing markup elements
    from the API and converts them to the appropriate MarkupElement subclass
    instances based on their type.

    Args:
        dataList: A list of dictionaries containing markup element data from the API.

    Returns:
        A list of MarkupElement objects (or their subclasses) corresponding to the
        input data. Unsupported markup types are logged and converted to generic
        MarkupElement instances.
    """
    ret: List[MarkupElement] = []
    for v in dataList:
        elemType = MarkupType.fromStr(v.get("type", MarkupType.UNSPECIFIED))
        match elemType:
            case MarkupType.STRONG:
                ret.append(StrongMarkup.from_dict(v))
            case MarkupType.EMPHASIZED:
                ret.append(EmphasizedMarkup.from_dict(v))
            case MarkupType.MONOSPACED:
                ret.append(MonospacedMarkup.from_dict(v))
            case MarkupType.STRIKETHROUGH:
                ret.append(StrikethroughMarkup.from_dict(v))
            case MarkupType.UNDERLINE:
                ret.append(UnderlineMarkup.from_dict(v))
            case MarkupType.LINK:
                ret.append(LinkMarkup.from_dict(v))
            case MarkupType.USER_MENTION:
                ret.append(UserMentionMarkup.from_dict(v))
            # Those are not present in Swagger, but has classes for it =\
            case MarkupType.HEADING:
                ret.append(HeadingMarkup.from_dict(v))
            case MarkupType.HIGHLIGHTED:
                ret.append(HighlightedMarkup.from_dict(v))
            case MarkupType.UNSPECIFIED:
                ret.append(MarkupElement.from_dict(v))
            case _:
                logger.error(f"Unsupported markup type: {elemType}")
                ret.append(MarkupElement.from_dict(v))

    return ret
