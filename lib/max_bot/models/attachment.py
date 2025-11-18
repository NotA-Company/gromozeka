"""
Attachment base models and infrastructure for Max Messenger Bot API.

This module contains the base attachment classes and enums that form the foundation
for all attachment types in the Max Messenger Bot API.
"""

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, Optional

from .base import BaseMaxBotModel
from .keyboard import Keyboard
from .user import User

logger = logging.getLogger(__name__)


class AttachmentType(StrEnum):
    """
    Base attachment type enum
    """

    UNSPECIFIED = "UNSPECIFIED"

    IMAGE = "image"  # PhotoAttachment
    VIDEO = "video"  # VideoAttachment
    AUDIO = "audio"  # AudioAttachment
    FILE = "file"  # FileAttachment
    STICKER = "sticker"  # StickerAttachment
    CONTACT = "contact"  # ContactAttachment
    INLINE_KEYBOARD = "inline_keyboard"  # InlineKeyboardAttachment
    SHARE = "share"  # ShareAttachment
    LOCATION = "location"  # LocationAttachment
    REPLY_KEYBOARD = "reply_keyboard"  # ReplyKeyboardAttachment
    DATA = "data"  # DataAttachment


class Attachment(BaseMaxBotModel):
    """
    Base attachment class for all attachment types
    """

    __slots__ = ("type",)

    # type: AttachmentType
    # """Type of the attachment"""

    def __init__(self, *, type: AttachmentType, api_kwargs: Optional[Dict[str, Any]] = None):
        super().__init__(api_kwargs=api_kwargs)
        self.type = type

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Attachment":
        """Create Attachment instance from API response dictionary."""
        return cls(
            type=AttachmentType(data.get("type", "file")),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoAttachmentPayload(BaseMaxBotModel):
    """TODO"""

    # photo_id: int
    # """Уникальный ID этого изображения"""
    # "token": str
    # """
    #  Используйте `token`, если вы пытаетесь
    #  повторно использовать одно и то же вложение в другом сообщении.
    # """
    # url: str
    # """URL изображения"""

    __slots__ = ("photo_id", "token", "url")

    def __init__(self, *, photo_id: int, token: str, url: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.photo_id: int = photo_id
        self.token: str = token
        self.url: str = url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoAttachmentPayload":
        """Create PhotoAttachmentPayload instance from API response dictionary."""
        return cls(
            photo_id=data.get("photo_id", 0),
            token=data.get("token", ""),
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class AttachmentPayload(BaseMaxBotModel):
    """Base payload class for attachments with URL field."""

    __slots__ = ("url",)

    def __init__(self, *, url: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachmentPayload":
        """Create AttachmentPayload instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MediaAttachmentPayload(AttachmentPayload):
    """Media attachment payload with token field for reusing attachments."""

    __slots__ = ("token",)

    def __init__(self, *, url: str, token: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.token: str = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaAttachmentPayload":
        """Create MediaAttachmentPayload instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class FileAttachmentPayload(AttachmentPayload):
    """File attachment payload with token field for reusing attachments."""

    __slots__ = ("token",)

    def __init__(self, *, url: str, token: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.token: str = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileAttachmentPayload":
        """Create FileAttachmentPayload instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoAttachment(Attachment):
    """TODO"""

    __slots__ = ("payload",)

    def __init__(self, *, payload: PhotoAttachmentPayload, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=AttachmentType.IMAGE, api_kwargs=api_kwargs)
        self.payload: PhotoAttachmentPayload = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoAttachment":
        """Create PhotoAttachment instance from API response dictionary."""
        return cls(
            payload=PhotoAttachmentPayload.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LocationAttachment(Attachment):
    """Location attachment with latitude and longitude coordinates."""

    __slots__ = ("latitude", "longitude")

    def __init__(
        self,
        *,
        latitude: float,
        longitude: float,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.LOCATION, api_kwargs=api_kwargs)
        self.latitude: float = latitude
        self.longitude: float = longitude

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocationAttachment":
        """Create LocationAttachment instance from API response dictionary."""
        return cls(
            latitude=data.get("latitude", 0.0),
            longitude=data.get("longitude", 0.0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class AudioAttachment(Attachment):
    """Audio attachment with media payload and optional transcription."""

    __slots__ = ("payload", "transcription")

    def __init__(
        self,
        *,
        payload: MediaAttachmentPayload,
        transcription: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.AUDIO, api_kwargs=api_kwargs)
        self.payload: MediaAttachmentPayload = payload
        self.transcription: Optional[str] = transcription

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioAttachment":
        """Create AudioAttachment instance from API response dictionary."""
        return cls(
            payload=MediaAttachmentPayload.from_dict(data.get("payload", {})),
            transcription=data.get("transcription"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class FileAttachment(Attachment):
    """File attachment with file payload, filename and size."""

    __slots__ = ("payload", "filename", "size")

    def __init__(
        self,
        *,
        payload: FileAttachmentPayload,
        filename: str,
        size: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.FILE, api_kwargs=api_kwargs)
        self.payload: FileAttachmentPayload = payload
        self.filename: str = filename
        self.size: int = size

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileAttachment":
        """Create FileAttachment instance from API response dictionary."""
        return cls(
            payload=FileAttachmentPayload.from_dict(data.get("payload", {})),
            filename=data.get("filename", ""),
            size=data.get("size", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StickerAttachmentPayload(AttachmentPayload):
    """Sticker attachment payload with code field."""

    __slots__ = ("code",)

    def __init__(self, *, url: str, code: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.code: str = code

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StickerAttachmentPayload":
        """Create StickerAttachmentPayload instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            code=data.get("code", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StickerAttachment(Attachment):
    """Sticker attachment with payload and dimensions."""

    __slots__ = ("payload", "width", "height")

    def __init__(
        self,
        *,
        payload: StickerAttachmentPayload,
        width: int,
        height: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.STICKER, api_kwargs=api_kwargs)
        self.payload: StickerAttachmentPayload = payload
        self.width: int = width
        self.height: int = height

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StickerAttachment":
        """Create StickerAttachment instance from API response dictionary."""
        return cls(
            payload=StickerAttachmentPayload.from_dict(data.get("payload", {})),
            width=data.get("width", 0),
            height=data.get("height", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ShareAttachmentPayload(BaseMaxBotModel):
    """Share attachment payload with URL and token fields."""

    __slots__ = ("url", "token")

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        token: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.url: Optional[str] = url
        self.token: Optional[str] = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShareAttachmentPayload":
        """Create ShareAttachmentPayload instance from API response dictionary."""
        return cls(
            url=data.get("url"),
            token=data.get("token"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ShareAttachment(Attachment):
    """Share attachment with payload and preview information."""

    __slots__ = ("payload", "title", "description", "image_url")

    def __init__(
        self,
        *,
        payload: ShareAttachmentPayload,
        title: Optional[str] = None,
        description: Optional[str] = None,
        image_url: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.SHARE, api_kwargs=api_kwargs)
        self.payload: ShareAttachmentPayload = payload
        self.title: Optional[str] = title
        self.description: Optional[str] = description
        self.image_url: Optional[str] = image_url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShareAttachment":
        """Create ShareAttachment instance from API response dictionary."""
        return cls(
            payload=ShareAttachmentPayload.from_dict(data.get("payload", {})),
            title=data.get("title"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ContactAttachmentPayload(BaseMaxBotModel):
    """Contact attachment payload with VCF and Max user info."""

    __slots__ = ("vcf_info", "max_info")

    def __init__(
        self,
        *,
        vcf_info: Optional[str] = None,
        max_info: Optional["User"] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.vcf_info: Optional[str] = vcf_info
        self.max_info: Optional["User"] = max_info

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactAttachmentPayload":
        """Create ContactAttachmentPayload instance from API response dictionary."""
        max_info = None
        if data.get("max_info") is not None:
            from .user import User

        max_info = User.from_dict(data.get("max_info", {}))

        return cls(
            vcf_info=data.get("vcf_info"),
            max_info=max_info,
            api_kwargs=cls._getExtraKwargs(data),
        )


class ContactAttachment(Attachment):
    """Contact attachment with payload containing contact information."""

    __slots__ = ("payload",)

    def __init__(
        self,
        *,
        payload: ContactAttachmentPayload,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.CONTACT, api_kwargs=api_kwargs)
        self.payload: ContactAttachmentPayload = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactAttachment":
        """Create ContactAttachment instance from API response dictionary."""
        return cls(
            payload=ContactAttachmentPayload.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class VideoThumbnail(BaseMaxBotModel):
    """Video thumbnail with URL field."""

    __slots__ = ("url",)

    def __init__(self, *, url: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoThumbnail":
        """Create VideoThumbnail instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class VideoUrls(BaseMaxBotModel):
    """Video URLs for different quality levels."""

    __slots__ = (
        "mp4_1080",
        "mp4_720",
        "mp4_480",
        "mp4_360",
        "mp4_240",
        "mp4_144",
        "hls",
    )

    def __init__(
        self,
        *,
        mp4_1080: Optional[str] = None,
        mp4_720: Optional[str] = None,
        mp4_480: Optional[str] = None,
        mp4_360: Optional[str] = None,
        mp4_240: Optional[str] = None,
        mp4_144: Optional[str] = None,
        hls: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.mp4_1080: Optional[str] = mp4_1080
        self.mp4_720: Optional[str] = mp4_720
        self.mp4_480: Optional[str] = mp4_480
        self.mp4_360: Optional[str] = mp4_360
        self.mp4_240: Optional[str] = mp4_240
        self.mp4_144: Optional[str] = mp4_144
        self.hls: Optional[str] = hls

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoUrls":
        """Create VideoUrls instance from API response dictionary."""
        return cls(
            mp4_1080=data.get("mp4_1080"),
            mp4_720=data.get("mp4_720"),
            mp4_480=data.get("mp4_480"),
            mp4_360=data.get("mp4_360"),
            mp4_240=data.get("mp4_240"),
            mp4_144=data.get("mp4_144"),
            hls=data.get("hls"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class VideoAttachmentDetails(BaseMaxBotModel):
    """Video attachment details with token, URLs, thumbnail and dimensions."""

    __slots__ = ("token", "urls", "thumbnail", "width", "height", "duration")

    def __init__(
        self,
        *,
        token: str,
        width: int,
        height: int,
        duration: int,
        urls: Optional[VideoUrls] = None,
        thumbnail: Optional[PhotoAttachmentPayload] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.token: str = token
        self.urls: Optional[VideoUrls] = urls
        self.thumbnail: Optional[PhotoAttachmentPayload] = thumbnail
        self.width: int = width
        self.height: int = height
        self.duration: int = duration

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoAttachmentDetails":
        """Create VideoAttachmentDetails instance from API response dictionary."""
        urls = None
        if data.get("urls") is not None:
            urls = VideoUrls.from_dict(data.get("urls", {}))

        thumbnail = None
        if data.get("thumbnail") is not None:
            thumbnail = PhotoAttachmentPayload.from_dict(data.get("thumbnail", {}))

        return cls(
            token=data.get("token", ""),
            urls=urls,
            thumbnail=thumbnail,
            width=data.get("width", 0),
            height=data.get("height", 0),
            duration=data.get("duration", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class VideoAttachment(Attachment):
    """Video attachment with media payload and video details."""

    __slots__ = ("payload", "thumbnail", "width", "height", "duration")

    def __init__(
        self,
        *,
        payload: MediaAttachmentPayload,
        thumbnail: Optional[VideoThumbnail] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration: Optional[int] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.VIDEO, api_kwargs=api_kwargs)
        self.payload: MediaAttachmentPayload = payload
        self.thumbnail: Optional[VideoThumbnail] = thumbnail
        self.width: Optional[int] = width
        self.height: Optional[int] = height
        self.duration: Optional[int] = duration

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoAttachment":
        """Create VideoAttachment instance from API response dictionary."""
        thumbnail = None
        if data.get("thumbnail") is not None:
            thumbnail = VideoThumbnail.from_dict(data.get("thumbnail", {}))

        return cls(
            payload=MediaAttachmentPayload.from_dict(data.get("payload", {})),
            thumbnail=thumbnail,
            width=data.get("width"),
            height=data.get("height"),
            duration=data.get("duration"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class KeyboardAttachment(Attachment):
    """Base keyboard attachment class for interactive keyboards."""

    __slots__ = ()

    def __init__(self, *, type: AttachmentType, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=type, api_kwargs=api_kwargs)


class InlineKeyboardAttachment(KeyboardAttachment):
    """Inline keyboard attachment that appears below a message."""

    __slots__ = ("payload",)

    def __init__(
        self,
        *,
        payload: "Keyboard",
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.INLINE_KEYBOARD, api_kwargs=api_kwargs)
        self.payload: "Keyboard" = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InlineKeyboardAttachment":
        """Create InlineKeyboardAttachment instance from API response dictionary."""
        from .keyboard import Keyboard

        return cls(
            payload=Keyboard.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ReplyKeyboardAttachment(KeyboardAttachment):
    """Reply keyboard attachment that replaces the user's keyboard."""

    __slots__ = ("payload",)

    def __init__(
        self,
        *,
        payload: "Keyboard",
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.REPLY_KEYBOARD, api_kwargs=api_kwargs)
        self.payload: "Keyboard" = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplyKeyboardAttachment":
        """Create ReplyKeyboardAttachment instance from API response dictionary."""
        from .keyboard import Keyboard

        return cls(
            payload=Keyboard.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class DataAttachment(Attachment):
    """Data attachment with raw data field."""

    __slots__ = ("data",)

    def __init__(
        self,
        *,
        data: str,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(type=AttachmentType.DATA, api_kwargs=api_kwargs)
        self.data: str = data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataAttachment":
        """Create DataAttachment instance from API response dictionary."""
        return cls(
            data=data.get("data", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


@dataclass(slots=True)
class UploadRequest:
    """
    Base upload request for attachments
    """

    filename: str
    """Name of the file to upload"""
    content_type: str
    """MIME type of the file"""
    data: bytes
    """Binary data of the file"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadRequest":
        """Create UploadRequest instance from API response dictionary."""
        return cls(
            filename=data.get("filename", ""),
            content_type=data.get("content_type", "application/octet-stream"),
            data=data.get("data", b""),
            api_kwargs={k: v for k, v in data.items() if k not in {"filename", "content_type", "data"}},
        )


@dataclass(slots=True)
class UploadResult:
    """
    Result of an upload operation
    """

    token: str
    """Token for accessing the uploaded file"""
    url: Optional[str] = None
    """URL for accessing the uploaded file (if available)"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadResult":
        """Create UploadResult instance from API response dictionary."""
        return cls(
            token=data.get("token", ""),
            url=data.get("url"),
            api_kwargs={k: v for k, v in data.items() if k not in {"token", "url"}},
        )


def attachmentFromDict(data: Dict[str, Any]) -> Attachment:
    attachmentType = AttachmentType(data.get("type", AttachmentType.UNSPECIFIED))

    match attachmentType:
        case AttachmentType.IMAGE:
            return PhotoAttachment.from_dict(data)
        case AttachmentType.VIDEO:
            return VideoAttachment.from_dict(data)
        case AttachmentType.AUDIO:
            return AudioAttachment.from_dict(data)
        case AttachmentType.FILE:
            return FileAttachment.from_dict(data)
        case AttachmentType.LOCATION:
            return LocationAttachment.from_dict(data)
        case AttachmentType.STICKER:
            return StickerAttachment.from_dict(data)
        case AttachmentType.CONTACT:
            return ContactAttachment.from_dict(data)
        case AttachmentType.SHARE:
            return ShareAttachment.from_dict(data)
        case AttachmentType.INLINE_KEYBOARD:
            return InlineKeyboardAttachment.from_dict(data)
        case AttachmentType.REPLY_KEYBOARD:
            return ReplyKeyboardAttachment.from_dict(data)
        case AttachmentType.DATA:
            return DataAttachment.from_dict(data)
        case _:
            logger.error(f"Unknown attachment type: {attachmentType} in {data}")
            return Attachment.from_dict(data)
