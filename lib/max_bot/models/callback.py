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
    """
    Объект, отправленный боту, когда пользователь нажимает кнопку
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
    """
    Отправьте этот объект, когда ваш бот хочет отреагировать на нажатие кнопки
    """

    __slots__ = ("message", "notification")

    def __init__(
        self,
        *,
        message: Optional[NewMessageBody] = None,
        notification: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
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
