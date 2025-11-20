from enum import StrEnum
from typing import Any, Dict, Optional

from lib.max_bot.models.keyboard import Keyboard

from .attachment import Attachment, AttachmentType, InlineKeyboardAttachment
from .base import BaseMaxBotModel


class UploadType(StrEnum):
    """Тип загружаемого файла"""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"


class AttachmentRequest(Attachment):
    """The same as Attachment"""

    __slots__ = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachmentRequest":
        return cls(
            type=AttachmentType(data.get("type", AttachmentType.UNSPECIFIED)),
            api_kwargs=cls._getExtraKwargs(data),
        )


class InlineKeyboardAttachmentRequest(InlineKeyboardAttachment, AttachmentRequest):
    __slots__ = ()

    def __init__(self, *, payload: Keyboard, api_kwargs: Dict[str, Any] | None = None):
        InlineKeyboardAttachment.__init__(self, payload=payload, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InlineKeyboardAttachmentRequest":
        """Create InlineKeyboardAttachment instance from API response dictionary."""
        from .keyboard import Keyboard

        return cls(
            payload=Keyboard.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoToken(BaseMaxBotModel):
    """TODO"""

    __slots__ = ("token",)

    def __init__(self, *, token: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.token = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoToken":
        return cls(
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoTokens(Dict[str, PhotoToken]):
    """TODO"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoTokens":
        return cls({str(k): PhotoToken.from_dict(v) for k, v in data.items()})

    def to_dict(self, recursive: bool = False) -> Dict[str, Any]:
        return {k: v.to_dict(recursive=recursive) for k, v in self.items()}


class PhotoAttachmentRequestPayload(BaseMaxBotModel):
    """TODO"""

    __slots__ = ("url", "token", "photos")

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        token: Optional[str] = None,
        photos: Optional[PhotoTokens] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        noneCount = 0
        if url is None:
            noneCount += 1
        if token is None:
            noneCount += 1
        if photos is None:
            noneCount += 1
        if noneCount == 3:
            ValueError("One of: url, token or photos should be not None")
        elif noneCount != 2:
            ValueError("url, token and photos are mutualy exclusive")

        self.url: Optional[str] = url
        self.token: Optional[str] = token
        self.photos: Optional[PhotoTokens] = photos

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoAttachmentRequestPayload":
        photos: Optional[PhotoTokens] = None
        photosData = data.get("photos", None)
        if photosData is not None:
            photos = PhotoTokens.from_dict(photosData)

        return cls(
            url=data.get("url", None),
            token=data.get("token", None),
            photos=photos,
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoUploadResult(BaseMaxBotModel):
    """TODO"""

    __slots__ = ("photos",)

    def __init__(
        self,
        *,
        photos: PhotoTokens,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.photos: PhotoTokens = photos

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoUploadResult":

        return cls(
            photos=PhotoTokens.from_dict(data.get("photos", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoAttachmentRequest(AttachmentRequest):
    """TODO"""

    __slots__ = ("payload",)

    def __init__(self, *, payload: PhotoAttachmentRequestPayload, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=AttachmentType.IMAGE, api_kwargs=api_kwargs)
        self.payload: PhotoAttachmentRequestPayload = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Attachment:
        return super().from_dict(data)


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


class UploadedAttachment(BaseMaxBotModel):
    __slots__ = ("uploadEndpoint",)

    def __init__(self, *, uploadEndpoint: UploadEndpoint, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.uploadEndpoint: UploadEndpoint = uploadEndpoint

    def toAttachmentRequest(self) -> AttachmentRequest:
        raise RuntimeError("Base class UploadedAttachment cannot be converted to Attachment request")


class UploadedPhoto(UploadedAttachment):
    """Result of uploading Attachment"""

    __slots__ = ("uploadEndpoint", "payload")

    def __init__(
        self, *, uploadEndpoint: UploadEndpoint, payload: PhotoUploadResult, api_kwargs: Optional[Dict[str, Any]] = None
    ):
        super().__init__(uploadEndpoint=uploadEndpoint, api_kwargs=api_kwargs)

        self.payload: PhotoUploadResult = payload

    def toAttachmentRequest(self) -> PhotoAttachmentRequest:
        return PhotoAttachmentRequest(payload=PhotoAttachmentRequestPayload(photos=self.payload.photos))
