"""File upload models for Max Bot API.

This module provides model classes for handling file uploads in the Max Messenger Bot API,
including photo uploads, upload endpoints, and attachment requests.
"""

from enum import StrEnum
from typing import Any, Dict, Optional, Self

from lib.max_bot.models.keyboard import Keyboard

from .attachment import Attachment, AttachmentType, InlineKeyboardAttachment
from .base import BaseMaxBotModel


class UploadType(StrEnum):
    """Тип загружаемого файла"""

    IMAGE = "image"
    """Image file type."""
    VIDEO = "video"
    """Video file type."""
    AUDIO = "audio"
    """Audio file type."""
    FILE = "file"
    """Generic file type."""


class AttachmentRequest(Attachment):
    """Attachment request model for Max Bot API.

    Represents an attachment that can be sent in a message request.
    Inherits all functionality from the base Attachment class.
    """

    __slots__ = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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


class UploadEndpoint(BaseMaxBotModel):
    """Точка доступа, куда следует загружать ваши бинарные файлы"""

    __slots__ = ("url", "token")

    def __init__(self, *, url: str, token: Optional[str], api_kwargs: Dict[str, Any] | None = None):
        """Initialize UploadEndpoint with URL and token.

        Args:
            url: URL endpoint for file upload
            token: Optional video or audio token for sending messages
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url
        """URL для загрузки файла"""
        self.token: Optional[str] = token
        """Видео- или аудио-токен для отправки сообщения"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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
        """Upload endpoint information for the uploaded file."""

    def toAttachmentRequest(self) -> AttachmentRequest:
        """Convert uploaded attachment to attachment request.

        Returns:
            AttachmentRequest object for sending the uploaded attachment

        Raises:
            RuntimeError: Always raised as base class cannot be converted
        """
        raise RuntimeError("Base class UploadedAttachment cannot be converted to Attachment request")


class UploadedInfo(BaseMaxBotModel):
    """Information about an uploaded file in Max Bot API.

    Contains the token identifier for referencing the uploaded file.
    """

    __slots__ = ("token",)

    def __init__(self, *, token: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize UploadedInfo with token.

        Args:
            token: Token identifier for the uploaded file
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(api_kwargs=api_kwargs)
        self.token: str = token
        """Token identifier for the uploaded file."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create UploadedInfo instance from API response dictionary.

        Args:
            data: Dictionary containing API response data

        Returns:
            UploadedInfo: New UploadedInfo instance
        """
        return cls(
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class InlineKeyboardAttachmentRequest(InlineKeyboardAttachment, AttachmentRequest):
    """Request for sending an inline keyboard attachment in Max Bot API.

    Combines InlineKeyboardAttachment and AttachmentRequest functionality.
    """

    __slots__ = ()

    def __init__(self, *, payload: Keyboard, api_kwargs: Dict[str, Any] | None = None):
        """Initialize InlineKeyboardAttachmentRequest with keyboard payload.

        Args:
            payload: Keyboard object containing button layout
            api_kwargs: Additional API keyword arguments
        """
        InlineKeyboardAttachment.__init__(self, payload=payload, api_kwargs=api_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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
        """Initialize PhotoToken with token.

        Args:
            token: Token identifier for the uploaded photo
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(api_kwargs=api_kwargs)
        self.token: str = token
        """Token identifier for the uploaded photo."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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
    def from_dict(cls, data: Dict[str, Any]) -> Self:
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
        # TODO: dunno
        return super().from_dict(data)


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


class FileAttachmentRequest(AttachmentRequest):
    """TODO: write docstring"""

    __slots__ = ("payload",)

    def __init__(self, *, payload: UploadedInfo, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=AttachmentType.FILE, api_kwargs=api_kwargs)
        self.payload: UploadedInfo = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """TODO: write docstring"""
        return cls(
            payload=UploadedInfo.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class FileUploadResult(BaseMaxBotModel):
    """Result of a file upload operation in Max Bot API.

    Contains the uploaded file with its corresponding token for later reference.
    """

    __slots__ = (
        "fileId",
        "token",
    )

    def __init__(
        self,
        *,
        fileId: int,
        token: str,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.fileId: int = fileId
        self.token: str = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """TODO: write docstring"""
        return cls(
            fileId=int(data.get("fileId", 0)),
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UploadedFile(UploadedAttachment):
    """Result of uploading a file attachment in Max Bot API.

    Contains both the upload endpoint and the file upload result with token.
    """

    __slots__ = ("uploadEndpoint", "payload")

    def __init__(
        self, *, uploadEndpoint: UploadEndpoint, payload: FileUploadResult, api_kwargs: Optional[Dict[str, Any]] = None
    ):
        """Initialize UploadedFile with endpoint and payload.

        Args:
            uploadEndpoint: The endpoint information for the uploaded file
            payload: The file upload result containing token
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(uploadEndpoint=uploadEndpoint, api_kwargs=api_kwargs)

        self.payload: FileUploadResult = payload

    def toAttachmentRequest(self) -> FileAttachmentRequest:
        """TODO: write docstring"""
        if self.uploadEndpoint.token is None:
            raise ValueError("Upload endpoint token is None")

        return FileAttachmentRequest(payload=UploadedInfo(token=self.uploadEndpoint.token))


class VideoAttachmentRequest(AttachmentRequest):
    """TODO: write docstring"""

    __slots__ = ("payload",)

    def __init__(self, *, payload: UploadedInfo, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=AttachmentType.VIDEO, api_kwargs=api_kwargs)
        self.payload: UploadedInfo = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """TODO: write docstring"""
        return cls(
            payload=UploadedInfo.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UploadedVideo(UploadedAttachment):
    """Result of uploading a video attachment in Max Bot API.

    Contains both the upload endpoint and the video upload result with token.
    """

    __slots__ = ("uploadEndpoint", "payload")

    def __init__(
        self, *, uploadEndpoint: UploadEndpoint, payload: Dict[str, Any], api_kwargs: Optional[Dict[str, Any]] = None
    ):
        """Initialize UploadedVideo with endpoint and payload.

        Args:
            uploadEndpoint: The endpoint information for the uploaded video
            payload: The video upload result containing token
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(uploadEndpoint=uploadEndpoint, api_kwargs=api_kwargs)

        self.payload: Dict[str, Any] = payload

    def toAttachmentRequest(self) -> VideoAttachmentRequest:
        """TODO: write docstring"""
        if self.uploadEndpoint.token is None:
            raise ValueError("Upload endpoint token is None")

        return VideoAttachmentRequest(payload=UploadedInfo(token=self.uploadEndpoint.token))


class AudioAttachmentRequest(AttachmentRequest):
    """TODO: write docstring"""

    __slots__ = ("payload",)

    def __init__(self, *, payload: UploadedInfo, api_kwargs: Dict[str, Any] | None = None):
        super().__init__(type=AttachmentType.AUDIO, api_kwargs=api_kwargs)
        self.payload: UploadedInfo = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """TODO: write docstring"""
        return cls(
            payload=UploadedInfo.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class UploadedAudio(UploadedAttachment):
    """Result of uploading an audio attachment in Max Bot API.

    Contains both the upload endpoint and the audio upload result with token.
    """

    __slots__ = ("uploadEndpoint", "payload")

    def __init__(
        self, *, uploadEndpoint: UploadEndpoint, payload: Dict[str, Any], api_kwargs: Optional[Dict[str, Any]] = None
    ):
        """Initialize UploadedAudio with endpoint and payload.

        Args:
            uploadEndpoint: The endpoint information for the uploaded audio
            payload: The audio upload result containing token
            api_kwargs: Additional API keyword arguments
        """
        super().__init__(uploadEndpoint=uploadEndpoint, api_kwargs=api_kwargs)

        self.payload: Dict[str, Any] = payload

    def toAttachmentRequest(self) -> AudioAttachmentRequest:
        """TODO: write docstring"""
        if self.uploadEndpoint.token is None:
            raise ValueError("Upload endpoint token is None")

        return AudioAttachmentRequest(payload=UploadedInfo(token=self.uploadEndpoint.token))
