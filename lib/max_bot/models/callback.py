"""
Callback query models for Max Bot interactive button handling.

Provides Callback and CallbackAnswer classes for handling user button interactions
in Max Messenger Bot API. Callback represents incoming button press events,
while CallbackAnswer is used to respond with message updates or notifications.
"""

import logging
from typing import Any, Dict, Optional

from .base import BaseMaxBotModel
from .message import NewMessageBody
from .user import UserWithPhoto

logger = logging.getLogger(__name__)


class Callback(BaseMaxBotModel):
    """Represents a callback query sent to the bot when a user presses a button.

    This model encapsulates the data received from Max Messenger Bot API when a user
    interacts with an inline keyboard button. It includes the timestamp, callback ID,
    optional payload data, and user information.

    Attributes:
        timestamp: Unix timestamp when the user pressed the button.
        callback_id: Current keyboard ID for the callback.
        payload: Optional button token/payload data.
        user: User who pressed the button.
    """

    __slots__ = ("timestamp", "callback_id", "payload", "user")

    def __init__(
        self,
        *,
        timestamp: int,
        callback_id: str,
        payload: Optional[str] = None,
        user: UserWithPhoto,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a Callback instance.

        Args:
            timestamp: Unix timestamp when the user pressed the button.
            callback_id: Current keyboard ID for the callback.
            payload: Optional button token/payload data.
            user: User who pressed the button.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.timestamp: int = timestamp
        """Unix-время, когда пользователь нажал кнопку"""
        self.callback_id: str = callback_id
        """Текущий ID клавиатуры"""
        self.payload: Optional[str] = payload
        """Токен кнопки"""
        self.user: UserWithPhoto = user
        """Пользователь, нажавший на кнопку"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Callback":
        """Create Callback instance from API response dictionary.

        Args:
            data: Dictionary containing callback data from API response.

        Returns:
            Callback: New instance created from the provided data.
        """
        return cls(
            timestamp=data.get("timestamp", 0),
            callback_id=data.get("callback_id", ""),
            payload=data.get("payload", None),
            user=UserWithPhoto.from_dict(data.get("user", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class CallbackAnswer(BaseMaxBotModel):
    """Represents a response to a callback query from the bot.

    This model is used to send a response to a user's button press. The bot can either
    update the current message with new content or send a one-time notification to the user.

    Attributes:
        message: Optional new message body to replace the current message.
        notification: Optional one-time notification text to send to the user.
    """

    __slots__ = ("message", "notification")

    def __init__(
        self,
        *,
        message: Optional[NewMessageBody] = None,
        notification: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a CallbackAnswer instance.

        Args:
            message: Optional new message body to replace the current message.
            notification: Optional one-time notification text to send to the user.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.message: Optional[NewMessageBody] = message
        """Заполните, если хотите изменить текущее сообщение"""
        self.notification: Optional[str] = notification
        """Заполните, если хотите просто отправить одноразовое уведомление пользователю"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallbackAnswer":
        """Create CallbackAnswer instance from API response dictionary.

        Args:
            data: Dictionary containing callback answer data from API response.

        Returns:
            CallbackAnswer: New instance created from the provided data.
        """
        message: Optional[NewMessageBody] = None
        if data.get("message", None) is not None:
            message = NewMessageBody.from_dict(data.get("message", {}))
        return cls(
            message=message,
            notification=data.get("notification", None),
            api_kwargs=cls._getExtraKwargs(data),
        )
