"""
Keyboard models for Max Messenger Bot API.

This module contains keyboard-related dataclasses including Keyboard, Button,
InlineKeyboardAttachment, and ReplyKeyboardAttachment models.
"""

from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel
from .enums import ButtonType


class Button(BaseMaxBotModel):
    """
    Base button class for all button types
    """

    __slots__ = ("type", "text")

    def __init__(self, *, type: ButtonType, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.type: ButtonType = type
        self.text: str = text
        """Видимый текст кнопки"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Button":
        """Create Button instance from API response dictionary."""
        return cls(
            type=ButtonType(data.get("type", ButtonType.UNSPECIFIED)),
            text=data.get("text", ""),
        )


class CallbackButton(Button):
    """
    Callback button that sends a callback query when pressed
    """

    __slots__ = ("payload", "intent")

    def __init__(
        self, *, payload: str, intent: Optional[str] = None, text: str, api_kwargs: Dict[str, Any] | None = None
    ):
        super().__init__(type=ButtonType.CALLBACK, text=text, api_kwargs=api_kwargs)
        self.payload: str = payload
        """Токен кнопки"""
        self.intent: Optional[str] = intent
        """
        Намерение кнопки. Влияет на отображение клиентом:
          "positive",
          "negative",
          "default"
        """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallbackButton":
        """Create CallbackButton instance from API response dictionary."""
        return cls(
            payload=data.get("payload", ""),
            intent=data.get("intent", None),
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LinkButton(Button):
    """
    Link button that opens a URL when pressed
    """

    __slots__ = ("url",)

    def __init__(self, *, url: str, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=ButtonType.LINK, text=text, api_kwargs=api_kwargs)
        self.url: str = url
        """URL to open when the button is pressed"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkButton":
        """Create LinkButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class RequestContactButton(Button):
    """
    Button that requests the user's contact information when pressed
    """

    __slots__ = ()

    def __init__(self, *, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=ButtonType.REQUEST_CONTACT, text=text, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestContactButton":
        """Create RequestContactButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class RequestGeoLocationButton(Button):
    """
    Button that requests the user's location when pressed
    """

    __slots__ = ()

    def __init__(self, *, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=ButtonType.REQUEST_GEO_LOCATION, text=text, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestGeoLocationButton":
        """Create RequestGeoLocationButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatButton(Button):
    """
    Button that opens a chat when pressed
    """

    __slots__ = ("chat_id",)

    def __init__(self, *, chat_id: int, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=ButtonType.CHAT, text=text, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID of the chat to open"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatButton":
        """Create ChatButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            chat_id=data.get("chat_id", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class OpenAppButton(Button):
    """
    Button that opens an app when pressed
    """

    __slots__ = ("app_id", "app_data")

    def __init__(
        self, *, app_id: str, app_data: Optional[str] = None, text: str, api_kwargs: Dict[str, Any] | None = None
    ):
        super().__init__(type=ButtonType.OPEN_APP, text=text, api_kwargs=api_kwargs)
        self.app_id: str = app_id
        """ID of the app to open"""
        self.app_data: Optional[str] = app_data
        """Data to pass to the app"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAppButton":
        """Create OpenAppButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            app_id=data.get("app_id", ""),
            app_data=data.get("app_data"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageButton(Button):
    """
    Button that sends a message when pressed
    """

    __slots__ = ("message",)

    def __init__(self, *, message: str, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=ButtonType.MESSAGE, text=text, api_kwargs=api_kwargs)
        self.message: str = message
        """Message to send when the button is pressed"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageButton":
        """Create MessageButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            message=data.get("message", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ReplyButton(Button):
    """
    Reply button that sends a reply when pressed
    """

    __slots__ = ()

    def __init__(self, *, text: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=ButtonType.REPLY, text=text, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplyButton":
        """Create ReplyButton instance from API response dictionary."""
        return cls(
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class Keyboard(BaseMaxBotModel):
    """
    Клавиатура - это двумерный массив кнопок
    """

    __slots__ = ("buttons",)

    def __init__(self, *, buttons: List[List[Button]], api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.buttons: List[List[Button]] = buttons

    def to_dict(self, includePrivate: bool = False, recursive: bool = False) -> Dict[str, Any]:
        # We need to specify our own to_dict to properly handle list of lists
        return {"buttons": [[button.to_dict(includePrivate, recursive) for button in row] for row in self.buttons]}
        # return super().to_dict(includePrivate, recursive)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Keyboard":
        """Create Keyboard instance from API response dictionary."""
        buttonsData: List[List[Dict[str, Any]]] = data.get("buttons", [])
        buttons = []
        for rowData in buttonsData:
            row = []
            for singleButtonData in rowData:
                buttonType = ButtonType(singleButtonData.get("type", ButtonType.UNSPECIFIED))

                # Create appropriate button type based on the type field
                if buttonType == ButtonType.CALLBACK:
                    row.append(CallbackButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.LINK:
                    row.append(LinkButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.REQUEST_CONTACT:
                    row.append(RequestContactButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.REQUEST_GEO_LOCATION:
                    row.append(RequestGeoLocationButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.CHAT:
                    row.append(ChatButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.OPEN_APP:
                    row.append(OpenAppButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.MESSAGE:
                    row.append(MessageButton.from_dict(singleButtonData))
                elif buttonType == ButtonType.REPLY:
                    row.append(ReplyButton.from_dict(singleButtonData))
                else:
                    row.append(Button.from_dict(singleButtonData))

            buttons.append(row)

        return cls(
            buttons=buttons,
            api_kwargs=cls._getExtraKwargs(data),
        )
