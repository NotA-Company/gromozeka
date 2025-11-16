"""
Media attachment models for Max Messenger Bot API.

This module contains media attachment dataclasses including Photo, Video, Audio,
and File models that extend the base MediaAttachment class.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .attachment import AttachmentType, MediaAttachment


@dataclass(slots=True)
class Photo(MediaAttachment):
    """
    Photo attachment
    """

    width: Optional[int] = None
    """Width of the photo in pixels"""
    height: Optional[int] = None
    """Height of the photo in pixels"""
    caption: Optional[str] = None
    """Caption for the photo"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the attachment type to photo."""
        self.type = AttachmentType.PHOTO

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Photo":
        """Create Photo instance from API response dictionary."""
        return cls(
            type=AttachmentType.PHOTO,
            token=data.get("token", ""),
            filename=data.get("filename"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            width=data.get("width"),
            height=data.get("height"),
            caption=data.get("caption"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"type", "token", "filename", "size", "mime_type", "width", "height", "caption"}
            },
        )


@dataclass(slots=True)
class Video(MediaAttachment):
    """
    Video attachment
    """

    width: Optional[int] = None
    """Width of the video in pixels"""
    height: Optional[int] = None
    """Height of the video in pixels"""
    duration: Optional[int] = None
    """Duration of the video in seconds"""
    thumbnail: Optional[str] = None
    """Token for the video thumbnail"""
    caption: Optional[str] = None
    """Caption for the video"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the attachment type to video."""
        self.type = AttachmentType.VIDEO

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Video":
        """Create Video instance from API response dictionary."""
        return cls(
            type=AttachmentType.VIDEO,
            token=data.get("token", ""),
            filename=data.get("filename"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            width=data.get("width"),
            height=data.get("height"),
            duration=data.get("duration"),
            thumbnail=data.get("thumbnail"),
            caption=data.get("caption"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "type",
                    "token",
                    "filename",
                    "size",
                    "mime_type",
                    "width",
                    "height",
                    "duration",
                    "thumbnail",
                    "caption",
                }
            },
        )


@dataclass(slots=True)
class Audio(MediaAttachment):
    """
    Audio attachment
    """

    duration: Optional[int] = None
    """Duration of the audio in seconds"""
    title: Optional[str] = None
    """Title of the audio"""
    artist: Optional[str] = None
    """Artist of the audio"""
    thumbnail: Optional[str] = None
    """Token for the audio thumbnail"""
    caption: Optional[str] = None
    """Caption for the audio"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the attachment type to audio."""
        self.type = AttachmentType.AUDIO

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Audio":
        """Create Audio instance from API response dictionary."""
        return cls(
            type=AttachmentType.AUDIO,
            token=data.get("token", ""),
            filename=data.get("filename"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            duration=data.get("duration"),
            title=data.get("title"),
            artist=data.get("artist"),
            thumbnail=data.get("thumbnail"),
            caption=data.get("caption"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "type",
                    "token",
                    "filename",
                    "size",
                    "mime_type",
                    "duration",
                    "title",
                    "artist",
                    "thumbnail",
                    "caption",
                }
            },
        )


@dataclass(slots=True)
class File(MediaAttachment):
    """
    File attachment
    """

    caption: Optional[str] = None
    """Caption for the file"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the attachment type to file."""
        self.type = AttachmentType.FILE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "File":
        """Create File instance from API response dictionary."""
        return cls(
            type=AttachmentType.FILE,
            token=data.get("token", ""),
            filename=data.get("filename"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            caption=data.get("caption"),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"type", "token", "filename", "size", "mime_type", "caption"}
            },
        )


@dataclass(slots=True)
class PhotoUploadRequest:
    """
    Request for uploading a photo
    """

    filename: str
    """Name of the photo file"""
    data: bytes
    """Binary data of the photo"""
    width: Optional[int] = None
    """Width of the photo in pixels"""
    height: Optional[int] = None
    """Height of the photo in pixels"""
    caption: Optional[str] = None
    """Caption for the photo"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoUploadRequest":
        """Create PhotoUploadRequest instance from API response dictionary."""
        return cls(
            filename=data.get("filename", ""),
            data=data.get("data", b""),
            width=data.get("width"),
            height=data.get("height"),
            caption=data.get("caption"),
            api_kwargs={k: v for k, v in data.items() if k not in {"filename", "data", "width", "height", "caption"}},
        )


@dataclass(slots=True)
class VideoUploadRequest:
    """
    Request for uploading a video
    """

    filename: str
    """Name of the video file"""
    data: bytes
    """Binary data of the video"""
    width: Optional[int] = None
    """Width of the video in pixels"""
    height: Optional[int] = None
    """Height of the video in pixels"""
    duration: Optional[int] = None
    """Duration of the video in seconds"""
    caption: Optional[str] = None
    """Caption for the video"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoUploadRequest":
        """Create VideoUploadRequest instance from API response dictionary."""
        return cls(
            filename=data.get("filename", ""),
            data=data.get("data", b""),
            width=data.get("width"),
            height=data.get("height"),
            duration=data.get("duration"),
            caption=data.get("caption"),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"filename", "data", "width", "height", "duration", "caption"}
            },
        )


@dataclass(slots=True)
class AudioUploadRequest:
    """
    Request for uploading an audio file
    """

    filename: str
    """Name of the audio file"""
    data: bytes
    """Binary data of the audio"""
    duration: Optional[int] = None
    """Duration of the audio in seconds"""
    title: Optional[str] = None
    """Title of the audio"""
    artist: Optional[str] = None
    """Artist of the audio"""
    caption: Optional[str] = None
    """Caption for the audio"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioUploadRequest":
        """Create AudioUploadRequest instance from API response dictionary."""
        return cls(
            filename=data.get("filename", ""),
            data=data.get("data", b""),
            duration=data.get("duration"),
            title=data.get("title"),
            artist=data.get("artist"),
            caption=data.get("caption"),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"filename", "data", "duration", "title", "artist", "caption"}
            },
        )


@dataclass(slots=True)
class FileUploadRequest:
    """
    Request for uploading a file
    """

    filename: str
    """Name of the file"""
    data: bytes
    """Binary data of the file"""
    caption: Optional[str] = None
    """Caption for the file"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileUploadRequest":
        """Create FileUploadRequest instance from API response dictionary."""
        return cls(
            filename=data.get("filename", ""),
            data=data.get("data", b""),
            caption=data.get("caption"),
            api_kwargs={k: v for k, v in data.items() if k not in {"filename", "data", "caption"}},
        )
