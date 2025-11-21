"""File upload models for Max Bot API.

This module provides model classes for handling file uploads in the Max Messenger Bot API,
including photo uploads, upload endpoints, and attachment requests.
"""

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
        """Create AttachmentRequest instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            AttachmentRequest: New AttachmentRequest instance
        """
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
        """Create InlineKeyboardAttachmentRequest instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            InlineKeyboardAttachmentRequest: New InlineKeyboardAttachmentRequest instance
        """
        from .keyboard import Keyboard

        return cls(
            payload=Keyboard.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoToken(BaseMaxBotModel):
    """Represents a token for an uploaded photo in Max Bot API.

    Contains the token identifier that can be used to reference an uploaded photo.
    """

    __slots__ = ("token",)

    def __init__(self, *, token: str, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.token = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoToken":
        """Create PhotoToken instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            PhotoToken: New PhotoToken instance
        """
        return cls(
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoTokens(Dict[str, PhotoToken]):
    """Dictionary mapping photo identifiers to PhotoToken objects.

    Used to manage multiple uploaded photos with their corresponding tokens.
    """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoTokens":
        """Create PhotoTokens instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            PhotoTokens: New PhotoTokens instance
        """
        return cls({str(k): PhotoToken.from_dict(v) for k, v in data.items()})

    def to_dict(self, recursive: bool = False) -> Dict[str, Any]:
        """Convert PhotoTokens to dictionary.

        Args:
            recursive: Whether to recursively convert nested objects

        Returns:
            Dict[str, Any]: Dictionary representation of PhotoTokens
        """
        return {k: v.to_dict(recursive=recursive) for k, v in self.items()}


class PhotoAttachmentRequestPayload(BaseMaxBotModel):
    """Payload for photo attachment requests in Max Bot API.

    Contains photo data that can be specified via URL, token, or photos dictionary.
    Only one of these options should be provided as they are mutually exclusive.
    """

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
            raise ValueError("One of: url, token or photos should be not None")
        elif noneCount != 2:
            raise ValueError("url, token and photos are mutualy exclusive")

        self.url: Optional[str] = url
        self.token: Optional[str] = token
        self.photos: Optional[PhotoTokens] = photos

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoAttachmentRequestPayload":
        """Create PhotoAttachmentRequestPayload instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            PhotoAttachmentRequestPayload: New PhotoAttachmentRequestPayload instance
        """
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
    """Result of a photo upload operation in Max Bot API.

    Contains the uploaded photos with their corresponding tokens for later reference.
    """

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
        """Create PhotoUploadResult instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            PhotoUploadResult: New PhotoUploadResult instance
        """
        return cls(
            photos=PhotoTokens.from_dict(data.get("photos", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoAttachmentRequest(AttachmentRequest):
    """Request for sending a photo attachment in Max Bot API.

    Extends AttachmentRequest specifically for photo attachments with proper payload structure.
    """

    __slots__ = ("payload",)

    def __init__(self, *, payload: PhotoAttachmentRequestPayload, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=AttachmentType.IMAGE, api_kwargs=api_kwargs)
        self.payload: PhotoAttachmentRequestPayload = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Attachment:
        """Create PhotoAttachmentRequest instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            Attachment: New Attachment instance
        """
        return super().from_dict(data)


class UploadEndpoint(BaseMaxBotModel):
    """Точка доступа, куда следует загружать ваши бинарные файлы"""

    __slots__ = ("url", "token")

    def __init__(self, *, url: str, token: Optional[str], api_kwargs: Dict[str, Any] | None = None):
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url
        """URL для загрузки файла"""
        self.token: Optional[str] = token
        """Видео- или аудио-токен для отправки сообщения"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadEndpoint":
        """Create UploadEndpoint instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            UploadEndpoint: New UploadEndpoint instance
        """
        return cls(
            url=data.get("url", ""),
            token=data.get("token", None),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UploadedAttachment(BaseMaxBotModel):
    """Base class for uploaded attachments in Max Bot API.

    Contains the upload endpoint information for files that have been uploaded
    and can be referenced in messages.
    """

    __slots__ = ("uploadEndpoint",)

    def __init__(self, *, uploadEndpoint: UploadEndpoint, api_kwargs: Dict[str, Any] | None = None):
        """Initialize UploadedAttachment with upload endpoint.

        Args:
            uploadEndpoint: The endpoint information for the uploaded file
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(api_kwargs=api_kwargs)
        self.uploadEndpoint: UploadEndpoint = uploadEndpoint

    def toAttachmentRequest(self) -> AttachmentRequest:
        """Convert uploaded attachment to attachment request.

        Returns:
            AttachmentRequest object for sending the uploaded attachment

        Raises:
            RuntimeError: Always raised as base class cannot be converted
        """
        raise RuntimeError("Base class UploadedAttachment cannot be converted to Attachment request")


class UploadedPhoto(UploadedAttachment):
    """Result of uploading a photo attachment in Max Bot API.

    Contains both the upload endpoint and the photo upload result with tokens.
    """

    __slots__ = ("uploadEndpoint", "payload")

    def __init__(
        self, *, uploadEndpoint: UploadEndpoint, payload: PhotoUploadResult, api_kwargs: Optional[Dict[str, Any]] = None
    ):
        """Initialize UploadedPhoto with endpoint and payload.

        Args:
            uploadEndpoint: The endpoint information for the uploaded photo
            payload: The photo upload result containing tokens
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(uploadEndpoint=uploadEndpoint, api_kwargs=api_kwargs)

        self.payload: PhotoUploadResult = payload

    def toAttachmentRequest(self) -> PhotoAttachmentRequest:
        """Convert uploaded photo to photo attachment request.

        Returns:
            PhotoAttachmentRequest object for sending the uploaded photo
        """
        return PhotoAttachmentRequest(payload=PhotoAttachmentRequestPayload(photos=self.payload.photos))
