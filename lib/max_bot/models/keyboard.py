"""
Keyboard models for Max Messenger Bot API.

This module provides data models for keyboard layouts and button types used in
the Max Messenger Bot API. It includes base button classes and specialized button
types for various actions (callback, link, request contact, request location,
chat, open app, message, reply), as well as the Keyboard model that organizes
buttons in a two-dimensional grid.

Key classes:
    Button: Base class for all button types
    CallbackButton: Button that sends a callback query when pressed
    LinkButton: Button that opens a URL when pressed
    RequestContactButton: Button that requests user's contact information
    RequestGeoLocationButton: Button that requests user's location
    ChatButton: Button that opens a chat
    OpenAppButton: Button that opens an app
    MessageButton: Button that sends a message
    ReplyButton: Button that sends a reply
    Keyboard: Two-dimensional array of buttons
"""

from typing import Any, Dict, List, Optional

from .base import BaseMaxBotModel
from .enums import ButtonType


class Button(BaseMaxBotModel):
    """Base button class for all button types in Max Messenger Bot API.

    This class provides the foundation for all button types, containing the
    essential type and text fields. Specific button behaviors are implemented
    in subclasses.

    Attributes:
        type: The type of button (e.g., CALLBACK, LINK, REPLY)
        text: The visible text displayed on the button
    """

    __slots__ = ("type", "text")

    def __init__(self, *, type: ButtonType, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a Button instance.

        Args:
            type: The type of button from ButtonType enum
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(api_kwargs=api_kwargs)
        self.type: ButtonType = type
        self.text: str = text
        """Видимый текст кнопки"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Button":
        """Create Button instance from API response dictionary.

        Args:
            data: Dictionary containing button data from API response

        Returns:
            Button instance populated with data from the dictionary
        """
        return cls(
            type=ButtonType(data.get("type", ButtonType.UNSPECIFIED)),
            text=data.get("text", ""),
        )


class CallbackButton(Button):
    """Button that sends a callback query when pressed.

    This button type is used for inline keyboards and triggers a callback
    event that can be handled by the bot. The payload is sent back to the
    bot when the button is pressed.

    Attributes:
        type: Button type (always CALLBACK)
        text: The visible text displayed on the button
        payload: Token/callback data sent when button is pressed
        intent: Button intent affecting client display (positive, negative, default)
    """

    __slots__ = ("payload", "intent")

    def __init__(
        self, *, payload: str, intent: Optional[str] = None, text: str, api_kwargs: Dict[str, Any] | None = None
    ):
        """Initialize a CallbackButton instance.

        Args:
            payload: Token/callback data sent when button is pressed
            intent: Button intent affecting client display. Valid values:
                "positive", "negative", "default". Defaults to None.
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
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
        """Create CallbackButton instance from API response dictionary.

        Args:
            data: Dictionary containing callback button data from API response

        Returns:
            CallbackButton instance populated with data from the dictionary
        """
        return cls(
            payload=data.get("payload", ""),
            intent=data.get("intent", None),
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LinkButton(Button):
    """Button that opens a URL when pressed.

    This button type opens a web page or deep link when the user taps it.
    Commonly used for linking to external resources, websites, or app deep links.

    Attributes:
        type: Button type (always LINK)
        text: The visible text displayed on the button
        url: URL to open when the button is pressed
    """

    __slots__ = ("url",)

    def __init__(self, *, url: str, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a LinkButton instance.

        Args:
            url: URL to open when the button is pressed
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.LINK, text=text, api_kwargs=api_kwargs)
        self.url: str = url
        """URL to open when the button is pressed"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkButton":
        """Create LinkButton instance from API response dictionary.

        Args:
            data: Dictionary containing link button data from API response

        Returns:
            LinkButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class RequestContactButton(Button):
    """Button that requests the user's contact information when pressed.

    When the user taps this button, the client will prompt them to share
    their contact information (phone number) with the bot.

    Attributes:
        type: Button type (always REQUEST_CONTACT)
        text: The visible text displayed on the button
    """

    __slots__ = ()

    def __init__(self, *, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a RequestContactButton instance.

        Args:
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.REQUEST_CONTACT, text=text, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestContactButton":
        """Create RequestContactButton instance from API response dictionary.

        Args:
            data: Dictionary containing request contact button data from API response

        Returns:
            RequestContactButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class RequestGeoLocationButton(Button):
    """Button that requests the user's location when pressed.

    When the user taps this button, the client will prompt them to share
    their geographical location (latitude and longitude) with the bot.

    Attributes:
        type: Button type (always REQUEST_GEO_LOCATION)
        text: The visible text displayed on the button
    """

    __slots__ = ()

    def __init__(self, *, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a RequestGeoLocationButton instance.

        Args:
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.REQUEST_GEO_LOCATION, text=text, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestGeoLocationButton":
        """Create RequestGeoLocationButton instance from API response dictionary.

        Args:
            data: Dictionary containing request geo location button data from API response

        Returns:
            RequestGeoLocationButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ChatButton(Button):
    """Button that opens a chat when pressed.

    This button type opens a specific chat when the user taps it. The chat
    is identified by its unique chat_id.

    Attributes:
        type: Button type (always CHAT)
        text: The visible text displayed on the button
        chat_id: ID of the chat to open
    """

    __slots__ = ("chat_id",)

    def __init__(self, *, chat_id: int, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a ChatButton instance.

        Args:
            chat_id: ID of the chat to open
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.CHAT, text=text, api_kwargs=api_kwargs)
        self.chat_id: int = chat_id
        """ID of the chat to open"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatButton":
        """Create ChatButton instance from API response dictionary.

        Args:
            data: Dictionary containing chat button data from API response

        Returns:
            ChatButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            chat_id=data.get("chat_id", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class OpenAppButton(Button):
    """Button that opens an app when pressed.

    This button type opens a specific app when the user taps it. The app
    is identified by its app_id, and optional app_data can be passed to
    the app when it opens.

    Attributes:
        type: Button type (always OPEN_APP)
        text: The visible text displayed on the button
        app_id: ID of the app to open
        app_data: Optional data to pass to the app when it opens
    """

    __slots__ = ("app_id", "app_data")

    def __init__(
        self, *, app_id: str, app_data: Optional[str] = None, text: str, api_kwargs: Dict[str, Any] | None = None
    ):
        """Initialize an OpenAppButton instance.

        Args:
            app_id: ID of the app to open
            app_data: Optional data to pass to the app when it opens
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.OPEN_APP, text=text, api_kwargs=api_kwargs)
        self.app_id: str = app_id
        """ID of the app to open"""
        self.app_data: Optional[str] = app_data
        """Data to pass to the app"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpenAppButton":
        """Create OpenAppButton instance from API response dictionary.

        Args:
            data: Dictionary containing open app button data from API response

        Returns:
            OpenAppButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            app_id=data.get("app_id", ""),
            app_data=data.get("app_data"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MessageButton(Button):
    """Button that sends a message when pressed.

    This button type sends a predefined message when the user taps it.
    The message is sent as if the user typed it themselves.

    Attributes:
        type: Button type (always MESSAGE)
        text: The visible text displayed on the button
        message: Message to send when the button is pressed
    """

    __slots__ = ("message",)

    def __init__(self, *, message: str, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a MessageButton instance.

        Args:
            message: Message to send when the button is pressed
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.MESSAGE, text=text, api_kwargs=api_kwargs)
        self.message: str = message
        """Message to send when the button is pressed"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageButton":
        """Create MessageButton instance from API response dictionary.

        Args:
            data: Dictionary containing message button data from API response

        Returns:
            MessageButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            message=data.get("message", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ReplyButton(Button):
    """Button that sends a reply when pressed.

    This button type sends a reply when the user taps it. It's commonly
    used in reply keyboards to provide quick response options.

    Attributes:
        type: Button type (always REPLY)
        text: The visible text displayed on the button
    """

    __slots__ = ()

    def __init__(self, *, text: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a ReplyButton instance.

        Args:
            text: The visible text displayed on the button
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(type=ButtonType.REPLY, text=text, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplyButton":
        """Create ReplyButton instance from API response dictionary.

        Args:
            data: Dictionary containing reply button data from API response

        Returns:
            ReplyButton instance populated with data from the dictionary
        """
        return cls(
            text=data.get("text", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class Keyboard(BaseMaxBotModel):
    """Keyboard model representing a two-dimensional array of buttons.

    The Keyboard class organizes buttons in a grid layout where each row
    is a list of buttons. This structure is used for both inline keyboards
    and reply keyboards in the Max Messenger Bot API.

    Attributes:
        buttons: Two-dimensional list of buttons (rows of buttons)
    """

    __slots__ = ("buttons",)

    def __init__(self, *, buttons: List[List[Button]], api_kwargs: Dict[str, Any] | None = None):
        """Initialize a Keyboard instance.

        Args:
            buttons: Two-dimensional list of buttons (rows of buttons)
            api_kwargs: Additional API keyword arguments not covered by the model
        """
        super().__init__(api_kwargs=api_kwargs)
        self.buttons: List[List[Button]] = buttons

    def to_dict(self, includePrivate: bool = False, recursive: bool = False) -> Dict[str, Any]:
        """Convert keyboard to dictionary representation.

        This method overrides the base implementation to properly handle
        the two-dimensional list of buttons.

        Args:
            includePrivate: Whether to include private attributes in output
            recursive: Whether to recursively convert nested models to dicts

        Returns:
            Dictionary representation of the keyboard with properly formatted buttons
        """
        # We need to specify our own to_dict to properly handle list of lists
        return {"buttons": [[button.to_dict(includePrivate, recursive) for button in row] for row in self.buttons]}
        # return super().to_dict(includePrivate, recursive)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Keyboard":
        """Create Keyboard instance from API response dictionary.

        This method creates the appropriate button type for each button
        based on its type field, allowing for polymorphic button creation.

        Args:
            data: Dictionary containing keyboard data from API response

        Returns:
            Keyboard instance populated with buttons from the dictionary
        """
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
