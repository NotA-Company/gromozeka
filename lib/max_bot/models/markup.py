"""
Markup models for Max Messenger Bot API.

This module contains markup-related dataclasses including MarkupElement and all
markup types for formatting text in messages.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class MarkupType(str, Enum):
    """
    Markup type enum
    """

    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKETHROUGH = "strikethrough"
    CODE = "code"
    PRE = "pre"
    TEXT_LINK = "text_link"
    MENTION = "mention"
    HASHTAG = "hashtag"
    CASHTAG = "cashtag"
    BOT_COMMAND = "bot_command"
    URL = "url"
    EMAIL = "email"
    PHONE = "phone"


@dataclass(slots=True)
class MarkupElement:
    """
    Base markup element for text formatting
    """

    type: MarkupType
    """Type of the markup element"""
    offset: int
    """Offset in UTF-16 code units to the start of the entity"""
    length: int
    """Length of the entity in UTF-16 code units"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarkupElement":
        """Create MarkupElement instance from API response dictionary."""
        return cls(
            type=MarkupType(data.get("type", "bold")),
            offset=data.get("offset", 0),
            length=data.get("length", 0),
        )


@dataclass(slots=True)
class BoldMarkup(MarkupElement):
    """
    Bold text markup
    """

    def __post_init__(self):
        """Set the markup type to bold."""
        self.type = MarkupType.BOLD

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoldMarkup":
        """Create BoldMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.BOLD,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
        )


@dataclass(slots=True)
class ItalicMarkup(MarkupElement):
    """
    Italic text markup
    """

    def __post_init__(self):
        """Set the markup type to italic."""
        self.type = MarkupType.ITALIC

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ItalicMarkup":
        """Create ItalicMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.ITALIC,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
        )


@dataclass(slots=True)
class UnderlineMarkup(MarkupElement):
    """
    Underlined text markup
    """

    def __post_init__(self):
        """Set the markup type to underline."""
        self.type = MarkupType.UNDERLINE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnderlineMarkup":
        """Create UnderlineMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.UNDERLINE,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
        )


@dataclass(slots=True)
class StrikethroughMarkup(MarkupElement):
    """
    Strikethrough text markup
    """

    def __post_init__(self):
        """Set the markup type to strikethrough."""
        self.type = MarkupType.STRIKETHROUGH

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrikethroughMarkup":
        """Create StrikethroughMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.STRIKETHROUGH,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
        )


@dataclass(slots=True)
class CodeMarkup(MarkupElement):
    """
    Inline code markup
    """

    def __post_init__(self):
        """Set the markup type to code."""
        self.type = MarkupType.CODE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeMarkup":
        """Create CodeMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.CODE,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
        )


@dataclass(slots=True)
class PreMarkup(MarkupElement):
    """
    Preformatted code block markup
    """

    language: Optional[str] = None
    """Programming language of the code block"""

    def __post_init__(self):
        """Set the markup type to pre."""
        self.type = MarkupType.PRE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreMarkup":
        """Create PreMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.PRE,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            language=data.get("language"),
        )


@dataclass(slots=True)
class TextLinkMarkup(MarkupElement):
    """
    Text link markup
    """

    url: str
    """URL that will be opened after user taps on the text"""

    def __post_init__(self):
        """Set the markup type to text_link."""
        self.type = MarkupType.TEXT_LINK

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextLinkMarkup":
        """Create TextLinkMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.TEXT_LINK,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            url=data.get("url", ""),
        )


@dataclass(slots=True)
class MentionMarkup(MarkupElement):
    """
    Mention markup
    """

    user_id: int
    """ID of the mentioned user"""

    def __post_init__(self):
        """Set the markup type to mention."""
        self.type = MarkupType.MENTION

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MentionMarkup":
        """Create MentionMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.MENTION,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            user_id=data.get("user_id", 0),
        )


@dataclass(slots=True)
class HashtagMarkup(MarkupElement):
    """
    Hashtag markup
    """

    hashtag: str
    """Hashtag text"""

    def __post_init__(self):
        """Set the markup type to hashtag."""
        self.type = MarkupType.HASHTAG

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HashtagMarkup":
        """Create HashtagMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.HASHTAG,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            hashtag=data.get("hashtag", ""),
        )


@dataclass(slots=True)
class CashtagMarkup(MarkupElement):
    """
    Cashtag markup
    """

    cashtag: str
    """Cashtag text"""

    def __post_init__(self):
        """Set the markup type to cashtag."""
        self.type = MarkupType.CASHTAG

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CashtagMarkup":
        """Create CashtagMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.CASHTAG,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            cashtag=data.get("cashtag", ""),
        )


@dataclass(slots=True)
class BotCommandMarkup(MarkupElement):
    """
    Bot command markup
    """

    command: str
    """Bot command text"""
    bot_id: Optional[int] = None
    """ID of the bot"""

    def __post_init__(self):
        """Set the markup type to bot_command."""
        self.type = MarkupType.BOT_COMMAND

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotCommandMarkup":
        """Create BotCommandMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.BOT_COMMAND,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            command=data.get("command", ""),
            bot_id=data.get("bot_id"),
        )


@dataclass(slots=True)
class UrlMarkup(MarkupElement):
    """
    URL markup
    """

    url: str
    """URL text"""

    def __post_init__(self):
        """Set the markup type to url."""
        self.type = MarkupType.URL

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UrlMarkup":
        """Create UrlMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.URL,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            url=data.get("url", ""),
        )


@dataclass(slots=True)
class EmailMarkup(MarkupElement):
    """
    Email markup
    """

    email: str
    """Email address"""

    def __post_init__(self):
        """Set the markup type to email."""
        self.type = MarkupType.EMAIL

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmailMarkup":
        """Create EmailMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.EMAIL,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            email=data.get("email", ""),
        )


@dataclass(slots=True)
class PhoneMarkup(MarkupElement):
    """
    Phone number markup
    """

    phone: str
    """Phone number"""

    def __post_init__(self):
        """Set the markup type to phone."""
        self.type = MarkupType.PHONE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhoneMarkup":
        """Create PhoneMarkup instance from API response dictionary."""
        return cls(
            type=MarkupType.PHONE,
            offset=data.get("offset", 0),
            length=data.get("length", 0),
            phone=data.get("phone", ""),
        )


@dataclass(slots=True)
class MarkupList:
    """
    List of markup elements
    """

    markup: List[MarkupElement]
    """Array of markup elements"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarkupList":
        """Create MarkupList instance from API response dictionary."""
        markup_data = data.get("markup", [])
        markup = []

        for element_data in markup_data:
            markup_type = element_data.get("type", "bold")

            # Create appropriate markup type based on the type field
            if markup_type == "bold":
                markup.append(BoldMarkup.from_dict(element_data))
            elif markup_type == "italic":
                markup.append(ItalicMarkup.from_dict(element_data))
            elif markup_type == "underline":
                markup.append(UnderlineMarkup.from_dict(element_data))
            elif markup_type == "strikethrough":
                markup.append(StrikethroughMarkup.from_dict(element_data))
            elif markup_type == "code":
                markup.append(CodeMarkup.from_dict(element_data))
            elif markup_type == "pre":
                markup.append(PreMarkup.from_dict(element_data))
            elif markup_type == "text_link":
                markup.append(TextLinkMarkup.from_dict(element_data))
            elif markup_type == "mention":
                markup.append(MentionMarkup.from_dict(element_data))
            elif markup_type == "hashtag":
                markup.append(HashtagMarkup.from_dict(element_data))
            elif markup_type == "cashtag":
                markup.append(CashtagMarkup.from_dict(element_data))
            elif markup_type == "bot_command":
                markup.append(BotCommandMarkup.from_dict(element_data))
            elif markup_type == "url":
                markup.append(UrlMarkup.from_dict(element_data))
            elif markup_type == "email":
                markup.append(EmailMarkup.from_dict(element_data))
            elif markup_type == "phone":
                markup.append(PhoneMarkup.from_dict(element_data))
            else:
                markup.append(MarkupElement.from_dict(element_data))

        return cls(markup=markup)
