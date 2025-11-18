from enum import StrEnum
from typing import Any, Dict, Optional

from .base import BaseMaxBotModel


class UploadType(StrEnum):
    """Тип загружаемого файла"""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"


class UploadEndpoint(BaseMaxBotModel):
    """Точка доступа, куда следует загружать ваши бинарные файлы"""

    __slots__ = ("url", "token")

    # url: str
    # """URL для загрузки файла"""
    # token: Optional[str]
    # """Видео- или аудио-токен для отправки сообщения"""

    def __init__(self, *, url: str, token: Optional[str], api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url
        self.token: Optional[str] = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadEndpoint":
        return cls(
            url=data.get("url", ""),
            token=data.get("token", None),
            api_kwargs=cls._getExtraKwargs(data),
        )
