"""
TODO
"""

import logging
from typing import Any, Dict, Optional

from .base import BaseMaxBotModel
from .message import NewMessageBody
from .user import User

logger = logging.getLogger(__name__)


class Callback(BaseMaxBotModel):
    """
    Объект, отправленный боту, когда пользователь нажимает кнопку
    """

    __slots__ = ("timestamp", "callback_id", "payload", "user")

    # timestamp: int
    # """Unix-время, когда пользователь нажал кнопку"""
    # callback_id: str
    # """Текущий ID клавиатуры"""
    # payload: Optional[str]
    # """Токен кнопки"""
    # user: User
    # """Пользователь, нажавший на кнопку"""

    def __init__(
        self,
        *,
        timestamp: int,
        callback_id: str,
        payload: Optional[str] = None,
        user: User,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.timestamp: int = timestamp
        self.callback_id: str = callback_id
        self.payload: Optional[str] = payload
        self.user: User = user

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "Callback":
        return cls(
            timestamp=data.get("timestamp", 0),
            callback_id=data.get("callback_id", ""),
            payload=data.get("payload", None),
            user=User.from_dict(data.get("user", {})),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )


class CallbackAnswer(BaseMaxBotModel):
    """
    Отправьте этот объект, когда ваш бот хочет отреагировать на нажатие кнопки
    """

    __slots__ = ("message", "notification")

    # message: Optional[NewMessageBody] = None
    # """Заполните, если хотите изменить текущее сообщение"""
    # notification: Optional[str] = None
    # """Заполните, если хотите просто отправить одноразовое уведомление пользователю"""

    def __init__(
        self,
        *,
        message: Optional[NewMessageBody] = None,
        notification: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.message: Optional[NewMessageBody] = message
        self.notification: Optional[str] = notification

    @classmethod
    def from_dict(cls, data: Dict[str, Any], store_api_kwargs: bool = False) -> "CallbackAnswer":
        message: Optional[NewMessageBody] = None
        if data.get("message", None) is not None:
            message = NewMessageBody.from_dict(data.get("message", {}))
        return cls(
            message=message,
            notification=data.get("notification", None),
            api_kwargs=data.copy() if store_api_kwargs else None,
        )
