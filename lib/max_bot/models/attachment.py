"""Attachment models for Max Messenger Bot API.

This module provides data models for various attachment types supported by the
Max Messenger Bot API, including photos, videos, audio, files, stickers, contacts,
locations, keyboards, and shares. Each attachment type has a corresponding model
class with appropriate payload and metadata fields.

Key Components:
    - AttachmentType: Enum defining all supported attachment types
    - Attachment: Base class for all attachment types
    - Payload classes: Data containers for attachment content
    - Specific attachment classes: PhotoAttachment, VideoAttachment, etc.
    - attachmentFromDict: Factory function to create attachments from API data
"""

import logging
from enum import StrEnum
from typing import Any, Dict, Optional

from .base import BaseMaxBotModel
from .keyboard import Keyboard
from .user import User

logger = logging.getLogger(__name__)


class AttachmentType(StrEnum):
    """Enum defining all supported attachment types in Max Messenger Bot API.

    Each attachment type corresponds to a specific attachment class that handles
    the data structure and parsing for that type of content.
    """

    UNSPECIFIED = "UNSPECIFIED"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    STICKER = "sticker"
    CONTACT = "contact"
    INLINE_KEYBOARD = "inline_keyboard"
    SHARE = "share"
    LOCATION = "location"
    REPLY_KEYBOARD = "reply_keyboard"
    DATA = "data"


class Attachment(BaseMaxBotModel):
    """Base class for all attachment types in Max Messenger Bot API.

    This class provides the foundation for all specific attachment types,
    including the attachment type field and common functionality for
    parsing API responses.

    Attributes:
        type: The type identifier for this attachment.
    """

    __slots__ = ("type",)

    def __init__(self, *, type: AttachmentType, api_kwargs: Optional[Dict[str, Any]] = None):
        """Initialize an Attachment instance.

        Args:
            type: The type identifier for this attachment.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.type = type

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Attachment":
        """Create Attachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            Attachment: An Attachment instance with data from the dictionary.
        """
        return cls(
            type=AttachmentType(data.get("type", "file")),
            api_kwargs=cls._getExtraKwargs(data),
        )


class AttachmentPayload(BaseMaxBotModel):
    """Base payload class for attachments with URL field.

    This class provides the common structure for attachment payloads that
    include a URL to the attachment content.

    Attributes:
        url: The URL where the attachment content can be accessed.
    """

    __slots__ = ("url",)

    def __init__(self, *, url: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize an AttachmentPayload instance.

        Args:
            url: The URL where the attachment content can be accessed.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachmentPayload":
        """Create AttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            AttachmentPayload: An AttachmentPayload instance with data from the dictionary.
        """
        return cls(
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class MediaAttachmentPayload(AttachmentPayload):
    """Media attachment payload with token for reusing attachments.

    This payload extends AttachmentPayload to include a token that can be used
    to reference the same media attachment in multiple messages without re-uploading.

    Attributes:
        url: The URL where the media content can be accessed.
        token: Token for reusing this attachment in other messages.
    """

    __slots__ = ("token",)

    def __init__(self, *, url: str, token: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a MediaAttachmentPayload instance.

        Args:
            url: The URL where the media content can be accessed.
            token: Token for reusing this attachment in other messages.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.token: str = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaAttachmentPayload":
        """Create MediaAttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            MediaAttachmentPayload: A MediaAttachmentPayload instance with data from the dictionary.
        """
        return cls(
            url=data.get("url", ""),
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoAttachmentPayload(AttachmentPayload):
    """Photo attachment payload with photo ID and token for reusing attachments.

    This payload provides additional metadata for photo attachments, including
    a unique photo ID and a token for reusing the attachment.

    Attributes:
        url: The URL where the photo can be accessed.
        photo_id: Unique identifier for this photo.
        token: Token for reusing this attachment in other messages.
    """

    __slots__ = ("photo_id", "token")

    def __init__(self, *, photo_id: int, token: str, url: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a PhotoAttachmentPayload instance.

        Args:
            photo_id: Unique identifier for this photo.
            token: Token for reusing this attachment in other messages.
            url: The URL where the photo can be accessed.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.photo_id: int = photo_id
        self.token: str = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoAttachmentPayload":
        """Create PhotoAttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            PhotoAttachmentPayload: A PhotoAttachmentPayload instance with data from the dictionary.
        """
        return cls(
            photo_id=data.get("photo_id", 0),
            token=data.get("token", ""),
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class FileAttachmentPayload(AttachmentPayload):
    """File attachment payload with token for reusing attachments.

    This payload extends AttachmentPayload to include a token that can be used
    to reference the same file attachment in multiple messages without re-uploading.

    Attributes:
        url: The URL where the file can be accessed.
        token: Token for reusing this attachment in other messages.
    """

    __slots__ = ("token",)

    def __init__(self, *, url: str, token: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a FileAttachmentPayload instance.

        Args:
            url: The URL where the file can be accessed.
            token: Token for reusing this attachment in other messages.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.token: str = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileAttachmentPayload":
        """Create FileAttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            FileAttachmentPayload: A FileAttachmentPayload instance with data from the dictionary.
        """
        return cls(
            url=data.get("url", ""),
            token=data.get("token", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class PhotoAttachment(Attachment):
    """Photo attachment with payload containing photo information.

    This attachment type represents a photo sent or received in a message,
    including metadata such as photo ID and access token.

    Attributes:
        type: The attachment type (IMAGE).
        payload: Photo attachment payload with URL, photo ID, and token.
    """

    __slots__ = ("payload",)

    def __init__(self, *, payload: PhotoAttachmentPayload, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a PhotoAttachment instance.

        Args:
            payload: Photo attachment payload with URL, photo ID, and token.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.IMAGE, api_kwargs=api_kwargs)
        self.payload: PhotoAttachmentPayload = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoAttachment":
        """Create PhotoAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            PhotoAttachment: A PhotoAttachment instance with data from the dictionary.
        """
        return cls(
            payload=PhotoAttachmentPayload.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class LocationAttachment(Attachment):
    """Location attachment with latitude and longitude coordinates.

    This attachment type represents a geographic location shared in a message,
    specified by latitude and longitude coordinates.

    Attributes:
        type: The attachment type (LOCATION).
        latitude: The latitude coordinate of the location.
        longitude: The longitude coordinate of the location.
    """

    __slots__ = ("latitude", "longitude")

    def __init__(
        self,
        *,
        latitude: float,
        longitude: float,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a LocationAttachment instance.

        Args:
            latitude: The latitude coordinate of the location.
            longitude: The longitude coordinate of the location.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.LOCATION, api_kwargs=api_kwargs)
        self.latitude: float = latitude
        self.longitude: float = longitude

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocationAttachment":
        """Create LocationAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            LocationAttachment: A LocationAttachment instance with data from the dictionary.
        """
        return cls(
            latitude=data.get("latitude", 0.0),
            longitude=data.get("longitude", 0.0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class AudioAttachment(Attachment):
    """Audio attachment with media payload and optional transcription.

    This attachment type represents an audio file sent or received in a message,
    which may include an optional text transcription of the audio content.

    Attributes:
        type: The attachment type (AUDIO).
        payload: Media attachment payload with URL and token.
        transcription: Optional text transcription of the audio content.
    """

    __slots__ = ("payload", "transcription")

    def __init__(
        self,
        *,
        payload: MediaAttachmentPayload,
        transcription: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize an AudioAttachment instance.

        Args:
            payload: Media attachment payload with URL and token.
            transcription: Optional text transcription of the audio content.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.AUDIO, api_kwargs=api_kwargs)
        self.payload: MediaAttachmentPayload = payload
        self.transcription: Optional[str] = transcription

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioAttachment":
        """Create AudioAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            AudioAttachment: An AudioAttachment instance with data from the dictionary.
        """
        return cls(
            payload=MediaAttachmentPayload.from_dict(data.get("payload", {})),
            transcription=data.get("transcription"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class FileAttachment(Attachment):
    """File attachment with file payload, filename and size.

    This attachment type represents a generic file sent or received in a message,
    including metadata such as filename and file size.

    Attributes:
        type: The attachment type (FILE).
        payload: File attachment payload with URL and token.
        filename: The name of the file.
        size: The size of the file in bytes.
    """

    __slots__ = ("payload", "filename", "size")

    def __init__(
        self,
        *,
        payload: FileAttachmentPayload,
        filename: str,
        size: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a FileAttachment instance.

        Args:
            payload: File attachment payload with URL and token.
            filename: The name of the file.
            size: The size of the file in bytes.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.FILE, api_kwargs=api_kwargs)
        self.payload: FileAttachmentPayload = payload
        self.filename: str = filename
        self.size: int = size

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileAttachment":
        """Create FileAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            FileAttachment: A FileAttachment instance with data from the dictionary.
        """
        return cls(
            payload=FileAttachmentPayload.from_dict(data.get("payload", {})),
            filename=data.get("filename", ""),
            size=data.get("size", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StickerAttachmentPayload(AttachmentPayload):
    """Sticker attachment payload with code field.

    This payload provides additional metadata for sticker attachments, including
    a code that identifies the sticker.

    Attributes:
        url: The URL where the sticker can be accessed.
        code: The code identifying this sticker.
    """

    __slots__ = ("code",)

    def __init__(self, *, url: str, code: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a StickerAttachmentPayload instance.

        Args:
            url: The URL where the sticker can be accessed.
            code: The code identifying this sticker.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(url=url, api_kwargs=api_kwargs)
        self.code: str = code

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StickerAttachmentPayload":
        """Create StickerAttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            StickerAttachmentPayload: A StickerAttachmentPayload instance with data from the dictionary.
        """
        return cls(
            url=data.get("url", ""),
            code=data.get("code", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class StickerAttachment(Attachment):
    """Sticker attachment with payload and dimensions.

    This attachment type represents a sticker sent or received in a message,
    including the sticker's dimensions for proper display.

    Attributes:
        type: The attachment type (STICKER).
        payload: Sticker attachment payload with URL and code.
        width: The width of the sticker in pixels.
        height: The height of the sticker in pixels.
    """

    __slots__ = ("payload", "width", "height")

    def __init__(
        self,
        *,
        payload: StickerAttachmentPayload,
        width: int,
        height: int,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a StickerAttachment instance.

        Args:
            payload: Sticker attachment payload with URL and code.
            width: The width of the sticker in pixels.
            height: The height of the sticker in pixels.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.STICKER, api_kwargs=api_kwargs)
        self.payload: StickerAttachmentPayload = payload
        self.width: int = width
        self.height: int = height

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StickerAttachment":
        """Create StickerAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            StickerAttachment: A StickerAttachment instance with data from the dictionary.
        """
        return cls(
            payload=StickerAttachmentPayload.from_dict(data.get("payload", {})),
            width=data.get("width", 0),
            height=data.get("height", 0),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ShareAttachmentPayload(BaseMaxBotModel):
    """Share attachment payload with URL and token fields.

    This payload provides the data for a shared link attachment, including
    the URL and an optional token for accessing the shared content.

    Attributes:
        url: The URL of the shared content.
        token: Optional token for accessing the shared content.
    """

    __slots__ = ("url", "token")

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        token: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a ShareAttachmentPayload instance.

        Args:
            url: The URL of the shared content.
            token: Optional token for accessing the shared content.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.url: Optional[str] = url
        self.token: Optional[str] = token

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShareAttachmentPayload":
        """Create ShareAttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            ShareAttachmentPayload: A ShareAttachmentPayload instance with data from the dictionary.
        """
        return cls(
            url=data.get("url"),
            token=data.get("token"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ShareAttachment(Attachment):
    """Share attachment with payload and preview information.

    This attachment type represents a shared link with preview metadata,
    including title, description, and optional preview image.

    Attributes:
        type: The attachment type (SHARE).
        payload: Share attachment payload with URL and token.
        title: Optional title of the shared content.
        description: Optional description of the shared content.
        image_url: Optional URL of a preview image for the shared content.
    """

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
        """Initialize a ShareAttachment instance.

        Args:
            payload: Share attachment payload with URL and token.
            title: Optional title of the shared content.
            description: Optional description of the shared content.
            image_url: Optional URL of a preview image for the shared content.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.SHARE, api_kwargs=api_kwargs)
        self.payload: ShareAttachmentPayload = payload
        self.title: Optional[str] = title
        self.description: Optional[str] = description
        self.image_url: Optional[str] = image_url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShareAttachment":
        """Create ShareAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            ShareAttachment: A ShareAttachment instance with data from the dictionary.
        """
        return cls(
            payload=ShareAttachmentPayload.from_dict(data.get("payload", {})),
            title=data.get("title"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ContactAttachmentPayload(BaseMaxBotModel):
    """Contact attachment payload with VCF and Max user info.

    This payload provides contact information, which can be in VCF format
    or as a Max Messenger user object.

    Attributes:
        vcf_info: Optional VCF (vCard) format contact information.
        max_info: Optional Max Messenger user information.
    """

    __slots__ = ("vcf_info", "max_info")

    def __init__(
        self,
        *,
        vcf_info: Optional[str] = None,
        max_info: Optional["User"] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a ContactAttachmentPayload instance.

        Args:
            vcf_info: Optional VCF (vCard) format contact information.
            max_info: Optional Max Messenger user information.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.vcf_info: Optional[str] = vcf_info
        self.max_info: Optional["User"] = max_info

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactAttachmentPayload":
        """Create ContactAttachmentPayload instance from API response dictionary.

        Args:
            data: Dictionary containing payload data from API response.

        Returns:
            ContactAttachmentPayload: A ContactAttachmentPayload instance with data from the dictionary.
        """
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
    """Contact attachment with payload containing contact information.

    This attachment type represents a contact shared in a message, which can
    be in VCF format or as a Max Messenger user.

    Attributes:
        type: The attachment type (CONTACT).
        payload: Contact attachment payload with VCF info and/or Max user info.
    """

    __slots__ = ("payload",)

    def __init__(
        self,
        *,
        payload: ContactAttachmentPayload,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a ContactAttachment instance.

        Args:
            payload: Contact attachment payload with VCF info and/or Max user info.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.CONTACT, api_kwargs=api_kwargs)
        self.payload: ContactAttachmentPayload = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactAttachment":
        """Create ContactAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            ContactAttachment: A ContactAttachment instance with data from the dictionary.
        """
        return cls(
            payload=ContactAttachmentPayload.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class VideoThumbnail(BaseMaxBotModel):
    """Video thumbnail with URL field.

    This class represents a thumbnail image for a video attachment.

    Attributes:
        url: The URL where the thumbnail image can be accessed.
    """

    __slots__ = ("url",)

    def __init__(self, *, url: str, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a VideoThumbnail instance.

        Args:
            url: The URL where the thumbnail image can be accessed.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.url: str = url

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoThumbnail":
        """Create VideoThumbnail instance from API response dictionary.

        Args:
            data: Dictionary containing thumbnail data from API response.

        Returns:
            VideoThumbnail: A VideoThumbnail instance with data from the dictionary.
        """
        return cls(
            url=data.get("url", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


class VideoUrls(BaseMaxBotModel):
    """Video URLs for different quality levels.

    This class provides URLs for accessing a video at various quality levels,
    including different MP4 resolutions and an HLS streaming URL.

    Attributes:
        mp4_1080: Optional URL for 1080p MP4 video.
        mp4_720: Optional URL for 720p MP4 video.
        mp4_480: Optional URL for 480p MP4 video.
        mp4_360: Optional URL for 360p MP4 video.
        mp4_240: Optional URL for 240p MP4 video.
        mp4_144: Optional URL for 144p MP4 video.
        hls: Optional URL for HLS streaming format.
    """

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
        """Initialize a VideoUrls instance.

        Args:
            mp4_1080: Optional URL for 1080p MP4 video.
            mp4_720: Optional URL for 720p MP4 video.
            mp4_480: Optional URL for 480p MP4 video.
            mp4_360: Optional URL for 360p MP4 video.
            mp4_240: Optional URL for 240p MP4 video.
            mp4_144: Optional URL for 144p MP4 video.
            hls: Optional URL for HLS streaming format.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
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
        """Create VideoUrls instance from API response dictionary.

        Args:
            data: Dictionary containing video URLs data from API response.

        Returns:
            VideoUrls: A VideoUrls instance with data from the dictionary.
        """
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
    """Video attachment details with token, URLs, thumbnail and dimensions.

    This class provides detailed information about a video attachment, including
    access token, URLs for different quality levels, thumbnail, dimensions, and duration.

    Attributes:
        token: Token for accessing the video.
        urls: Optional URLs for different video quality levels.
        thumbnail: Optional thumbnail image for the video.
        width: The width of the video in pixels.
        height: The height of the video in pixels.
        duration: The duration of the video in seconds.
    """

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
        """Initialize a VideoAttachmentDetails instance.

        Args:
            token: Token for accessing the video.
            width: The width of the video in pixels.
            height: The height of the video in pixels.
            duration: The duration of the video in seconds.
            urls: Optional URLs for different video quality levels.
            thumbnail: Optional thumbnail image for the video.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(api_kwargs=api_kwargs)
        self.token: str = token
        self.urls: Optional[VideoUrls] = urls
        self.thumbnail: Optional[PhotoAttachmentPayload] = thumbnail
        self.width: int = width
        self.height: int = height
        self.duration: int = duration

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoAttachmentDetails":
        """Create VideoAttachmentDetails instance from API response dictionary.

        Args:
            data: Dictionary containing video details data from API response.

        Returns:
            VideoAttachmentDetails: A VideoAttachmentDetails instance with data from the dictionary.
        """
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
    """Video attachment with media payload and video details.

    This attachment type represents a video sent or received in a message,
    including metadata such as dimensions, duration, and optional thumbnail.

    Attributes:
        type: The attachment type (VIDEO).
        payload: Media attachment payload with URL and token.
        thumbnail: Optional thumbnail image for the video.
        width: Optional width of the video in pixels.
        height: Optional height of the video in pixels.
        duration: Optional duration of the video in seconds.
    """

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
        """Initialize a VideoAttachment instance.

        Args:
            payload: Media attachment payload with URL and token.
            thumbnail: Optional thumbnail image for the video.
            width: Optional width of the video in pixels.
            height: Optional height of the video in pixels.
            duration: Optional duration of the video in seconds.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.VIDEO, api_kwargs=api_kwargs)
        self.payload: MediaAttachmentPayload = payload
        self.thumbnail: Optional[VideoThumbnail] = thumbnail
        self.width: Optional[int] = width
        self.height: Optional[int] = height
        self.duration: Optional[int] = duration

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoAttachment":
        """Create VideoAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            VideoAttachment: A VideoAttachment instance with data from the dictionary.
        """
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
    """Base keyboard attachment class for interactive keyboards.

    This class serves as the base for keyboard attachments that provide
    interactive elements in messages, such as inline keyboards and reply keyboards.

    Attributes:
        type: The attachment type (INLINE_KEYBOARD or REPLY_KEYBOARD).
    """

    __slots__ = ()

    def __init__(self, *, type: AttachmentType, api_kwargs: Dict[str, Any] | None = None):
        """Initialize a KeyboardAttachment instance.

        Args:
            type: The attachment type (INLINE_KEYBOARD or REPLY_KEYBOARD).
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=type, api_kwargs=api_kwargs)


class InlineKeyboardAttachment(KeyboardAttachment):
    """Inline keyboard attachment that appears below a message.

    This attachment type represents an inline keyboard with interactive buttons
    that appear below a message and trigger callback actions when pressed.

    Attributes:
        type: The attachment type (INLINE_KEYBOARD).
        payload: The keyboard layout with buttons and their actions.
        callback_id: Optional callback ID for tracking button interactions.
    """

    __slots__ = ("payload", "callback_id")

    def __init__(
        self,
        *,
        payload: Keyboard,
        callback_id: Optional[str] = None,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize an InlineKeyboardAttachment instance.

        Args:
            payload: The keyboard layout with buttons and their actions.
            callback_id: Optional callback ID for tracking button interactions.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.INLINE_KEYBOARD, api_kwargs=api_kwargs)
        self.payload: Keyboard = payload
        self.callback_id: Optional[str] = callback_id

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InlineKeyboardAttachment":
        """Create InlineKeyboardAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            InlineKeyboardAttachment: An InlineKeyboardAttachment instance with data from the dictionary.
        """
        from .keyboard import Keyboard

        return cls(
            payload=Keyboard.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class ReplyKeyboardAttachment(KeyboardAttachment):
    """Reply keyboard attachment that replaces the user's keyboard.

    This attachment type represents a custom keyboard that replaces the user's
    default keyboard, providing quick access to predefined actions or responses.

    Attributes:
        type: The attachment type (REPLY_KEYBOARD).
        payload: The keyboard layout with buttons and their actions.
    """

    __slots__ = ("payload",)

    def __init__(
        self,
        *,
        payload: Keyboard,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a ReplyKeyboardAttachment instance.

        Args:
            payload: The keyboard layout with buttons and their actions.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.REPLY_KEYBOARD, api_kwargs=api_kwargs)
        self.payload: Keyboard = payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplyKeyboardAttachment":
        """Create ReplyKeyboardAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            ReplyKeyboardAttachment: A ReplyKeyboardAttachment instance with data from the dictionary.
        """
        return cls(
            payload=Keyboard.from_dict(data.get("payload", {})),
            api_kwargs=cls._getExtraKwargs(data),
        )


class DataAttachment(Attachment):
    """Data attachment with raw data field.

    This attachment type represents arbitrary data sent or received in a message,
    stored as a raw string.

    Attributes:
        type: The attachment type (DATA).
        data: The raw data content as a string.
    """

    __slots__ = ("data",)

    def __init__(
        self,
        *,
        data: str,
        api_kwargs: Dict[str, Any] | None = None,
    ):
        """Initialize a DataAttachment instance.

        Args:
            data: The raw data content as a string.
            api_kwargs: Additional API keyword arguments not covered by the model.
        """
        super().__init__(type=AttachmentType.DATA, api_kwargs=api_kwargs)
        self.data: str = data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataAttachment":
        """Create DataAttachment instance from API response dictionary.

        Args:
            data: Dictionary containing attachment data from API response.

        Returns:
            DataAttachment: A DataAttachment instance with data from the dictionary.
        """
        return cls(
            data=data.get("data", ""),
            api_kwargs=cls._getExtraKwargs(data),
        )


def attachmentFromDict(data: Dict[str, Any]) -> Attachment:
    """Create appropriate Attachment instance from API response dictionary.

    This factory function determines the attachment type from the data and
    returns an instance of the appropriate attachment subclass.

    Args:
        data: Dictionary containing attachment data from API response.

    Returns:
        Attachment: Appropriate attachment instance based on type. Returns a
            base Attachment instance for unknown types and logs an error.
    """
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
