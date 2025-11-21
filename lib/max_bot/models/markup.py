"""
Markup models for Max Messenger Bot API.

This module contains markup-related dataclasses including MarkupElement and all
markup types for formatting text in messages.
"""

import logging
from enum import StrEnum
from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel

logger = logging.getLogger(__name__)


class MarkupType(StrEnum):
    """
    Markup type enum
    """

    UNSPECIFIED = "UNSPECIIFED"

    STRONG = "strong"
    """StrongMarkup"""
    EMPHASIZED = "emphasized"
    """EmphasizedMarkup"""
    MONOSPACED = "monospaced"
    """MonospacedMarkup"""
    STRIKETHROUGH = "strikethrough"
    """StrikethroughMarkup"""
    UNDERLINE = "underline"
    """UnderlineMarkup"""
    LINK = "link"
    """LinkMarkup"""
    USER_MENTION = "user_mention"
    """UserMentionMarkup"""
    # Those are not present in Swagger, but has classes for it =\
    HEADING = "heading"
    """HeadingMarkup"""
    HIGHLIGHTED = "highlighted"
    """HighlightedMarkup"""

    @classmethod
    def fromStr(cls, value: str) -> "MarkupType":
        if value in cls.__members__.values():
            return cls(value)
        else:
            logger.warning(f"{cls.__name__} does not have '{value}' value, returning UNSPECIFIED")
            return cls.UNSPECIFIED


class MarkupElement(BaseMaxBotModel):
    """
    Base markup element for text formatting
    """

    __slots__ = ("type", "fromField", "length")

    def __init__(self, *, type: MarkupType, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
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
        ret = super().to_dict(includePrivate, recursive)
        if "fromField" in ret:
            ret["from"] = ret.pop("fromField")
        return ret

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarkupElement":
        """Create MarkupElement instance from API response dictionary."""
        return cls(
            type=MarkupType.fromStr(data.get("type", MarkupType.UNSPECIFIED)),
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StrongMarkup(MarkupElement):
    """Представляет **жирный** текст"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.STRONG, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrongMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class EmphasizedMarkup(MarkupElement):
    """Представляет *курсив*"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.EMPHASIZED, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmphasizedMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MonospacedMarkup(MarkupElement):
    """Представляет `моноширинный` или блок ```код``` в тексте"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.MONOSPACED, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonospacedMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StrikethroughMarkup(MarkupElement):
    """Представляет ~зачекрнутый~ текст"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.STRIKETHROUGH, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrikethroughMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UnderlineMarkup(MarkupElement):
    """Представляет <ins>подчеркнутый</ins> текст"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.UNDERLINE, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnderlineMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class HeadingMarkup(MarkupElement):
    """Представляет заголовок текста"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.HEADING, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeadingMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class HighlightedMarkup(MarkupElement):
    """Представляет выделенную часть текста"""

    __slots__ = ()

    def __init__(self, *, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.HIGHLIGHTED, fromField=fromField, length=length, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HighlightedMarkup":
        return cls(
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LinkMarkup(MarkupElement):
    """Представляет ссылку в тексте"""

    __slots__ = ("url",)

    def __init__(self, *, url: str, fromField: int, length: int, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=MarkupType.LINK, fromField=fromField, length=length, api_kwargs=api_kwargs)
        self.url: str = url
        """URL ссылки"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkMarkup":
        return cls(
            url=data.get("url", ""),
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UserMentionMarkup(MarkupElement):
    """
    Представляет упоминание пользователя в тексте.
    Упоминание может быть как по имени пользователя,
    так и по ID, если у пользователя нет имени
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
        super().__init__(type=MarkupType.USER_MENTION, fromField=fromField, length=length, api_kwargs=api_kwargs)
        self.user_link: Optional[str] = user_link
        """`@username` упомянутого пользователя"""
        self.user_id: Optional[int] = user_id
        """ID упомянутого пользователя без имени"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMentionMarkup":
        return cls(
            user_link=data.get("user_link", None),
            user_id=data.get("user_id", None),
            fromField=data.get("from", 0),
            length=data.get("length", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


def markupListFromList(dataList: List[Dict[str, Any]]) -> List[MarkupElement]:
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
