"""
Keyboard models for Max Messenger Bot API.

This module contains keyboard-related dataclasses including Keyboard, Button,
InlineKeyboardAttachment, and ReplyKeyboardAttachment models.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


class ButtonType(StrEnum):
    """
    Button type enum
    """

    CALLBACK = "callback"
    LINK = "link"
    REQUEST_CONTACT = "request_contact"
    REQUEST_GEO_LOCATION = "request_geo_location"
    CHAT = "chat"
    OPEN_APP = "open_app"
    MESSAGE = "message"
    REPLY = "reply"


@dataclass(slots=True)
class Button:
    """
    Base button class for all button types
    """

    type: ButtonType
    """Type of the button"""
    text: str
    """Text displayed on the button"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Button":
        """Create Button instance from API response dictionary."""
        return cls(
            type=ButtonType(data.get("type", "callback")),
            text=data.get("text", ""),
        )


@dataclass(slots=True)
class CallbackButton(Button):
    """
    Callback button that sends a callback query when pressed
    """

    callback_data: str
    """Data to be sent in the callback query"""

    def __post_init__(self):
        """Set the button type to callback."""
        self.type = ButtonType.CALLBACK

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallbackButton":
        """Create CallbackButton instance from API response dictionary."""
        return cls(
            type=ButtonType.CALLBACK,
            text=data.get("text", ""),
            callback_data=data.get("callback_data", ""),
        )


@dataclass(slots=True)
class LinkButton(Button):
    """
    Link button that opens a URL when pressed
    """

    url: str
    """URL to open when the button is pressed"""

    def __post_init__(self):
        """Set the button type to link."""
        self.type = ButtonType.LINK

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkButton":
        """Create LinkButton instance from API response dictionary."""
        return cls(
            type=ButtonType.LINK,
            text=data.get("text", ""),
            url=data.get("url", ""),
        )


@dataclass(slots=True)
class RequestContactButton(Button):
    """
    Button that requests the user's contact information when pressed
    """

    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the button type to request_contact."""
        self.type = ButtonType.REQUEST_CONTACT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestContactButton":
        """Create RequestContactButton instance from API response dictionary."""
        return cls(
            type=ButtonType.REQUEST_CONTACT,
            text=data.get("text", ""),
        )


@dataclass(slots=True)
class RequestGeoLocationButton(Button):
    """
    Button that requests the user's location when pressed
    """

    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the button type to request_geo_location."""
        self.type = ButtonType.REQUEST_GEO_LOCATION

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestGeoLocationButton":
        """Create RequestGeoLocationButton instance from API response dictionary."""
        return cls(
            type=ButtonType.REQUEST_GEO_LOCATION,
            text=data.get("text", ""),
        )


@dataclass(slots=True)
class ChatButton(Button):
    """
    Button that opens a chat when pressed
    """

    chat_id: int
    """ID of the chat to open"""

    def __post_init__(self):
        """Set the button type to chat."""
        self.type = ButtonType.CHAT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatButton":
        """Create ChatButton instance from API response dictionary."""
        return cls(
            type=ButtonType.CHAT,
            text=data.get("text", ""),
            chat_id=data.get("chat_id", 0),
        )


@dataclass(slots=True)
class OpenAppButton(Button):
    """
    Button that opens an app when pressed
    """

    app_id: str
    """ID of the app to open"""
    app_data: Optional[str] = None
    """Data to pass to the app"""

    def __post_init__(self):
        """Set the button type to open_app."""
        self.type = ButtonType.OPEN_APP

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAppButton":
        """Create OpenAppButton instance from API response dictionary."""
        return cls(
            type=ButtonType.OPEN_APP,
            text=data.get("text", ""),
            app_id=data.get("app_id", ""),
            app_data=data.get("app_data"),
        )


@dataclass(slots=True)
class MessageButton(Button):
    """
    Button that sends a message when pressed
    """

    message: str
    """Message to send when the button is pressed"""

    def __post_init__(self):
        """Set the button type to message."""
        self.type = ButtonType.MESSAGE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageButton":
        """Create MessageButton instance from API response dictionary."""
        return cls(
            type=ButtonType.MESSAGE,
            text=data.get("text", ""),
            message=data.get("message", ""),
        )


@dataclass(slots=True)
class ReplyButton(Button):
    """
    Reply button that sends a reply when pressed
    """

    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the button type to reply."""
        self.type = ButtonType.REPLY

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplyButton":
        """Create ReplyButton instance from API response dictionary."""
        return cls(
            type=ButtonType.REPLY,
            text=data.get("text", ""),
        )


@dataclass(slots=True)
class Keyboard:
    """
    Keyboard layout for organizing buttons
    """

    buttons: List[List[Button]]
    """2D array of buttons representing the keyboard layout"""
    resize_keyboard: bool = False
    """Whether to resize the keyboard to fit the buttons"""
    one_time_keyboard: bool = False
    """Whether to hide the keyboard after a button is pressed"""
    selective: bool = False
    """Whether to show the keyboard only to specific users"""
    remove_keyboard: Optional[bool] = None
    """Whether to remove the keyboard after a button is pressed"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Keyboard":
        """Create Keyboard instance from API response dictionary."""
        buttons_data = data.get("buttons", [])
        buttons = []

        for row_data in buttons_data:
            row = []
            for button_data in row_data:
                button_type = button_data.get("type", "callback")

                # Create appropriate button type based on the type field
                if button_type == "callback":
                    row.append(CallbackButton.from_dict(button_data))
                elif button_type == "link":
                    row.append(LinkButton.from_dict(button_data))
                elif button_type == "request_contact":
                    row.append(RequestContactButton.from_dict(button_data))
                elif button_type == "request_geo_location":
                    row.append(RequestGeoLocationButton.from_dict(button_data))
                elif button_type == "chat":
                    row.append(ChatButton.from_dict(button_data))
                elif button_type == "open_app":
                    row.append(OpenAppButton.from_dict(button_data))
                elif button_type == "message":
                    row.append(MessageButton.from_dict(button_data))
                elif button_type == "reply":
                    row.append(ReplyButton.from_dict(button_data))
                else:
                    row.append(Button.from_dict(button_data))

            buttons.append(row)

        return cls(
            buttons=buttons,
            resize_keyboard=data.get("resize_keyboard", False),
            one_time_keyboard=data.get("one_time_keyboard", False),
            selective=data.get("selective", False),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"buttons", "resize_keyboard", "one_time_keyboard", "selective"}
            },
        )
