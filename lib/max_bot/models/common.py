"""
Common models for Max Messenger Bot API.

This module contains common dataclasses that are used across multiple parts of the API,
including Image, PhotoToken, VideoToken, AudioToken, FileToken, and UploadEndpoint models.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class Image:
    """
    Image model with dimensions and URL
    """

    url: str
    """URL of the image"""
    width: Optional[int] = None
    """Width of the image in pixels"""
    height: Optional[int] = None
    """Height of the image in pixels"""
    size: Optional[int] = None
    """Size of the image in bytes"""
    mime_type: Optional[str] = None
    """MIME type of the image"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Image":
        """Create Image instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            width=data.get("width"),
            height=data.get("height"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            api_kwargs={k: v for k, v in data.items() if k not in {"url", "width", "height", "size", "mime_type"}},
        )


@dataclass(slots=True)
class PhotoToken:
    """
    Token for accessing a photo
    """

    token: str
    """Token for accessing the photo"""
    url: Optional[str] = None
    """URL for accessing the photo (if available)"""
    width: Optional[int] = None
    """Width of the photo in pixels"""
    height: Optional[int] = None
    """Height of the photo in pixels"""
    size: Optional[int] = None
    """Size of the photo in bytes"""
    mime_type: Optional[str] = None
    """MIME type of the photo"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PhotoToken":
        """Create PhotoToken instance from API response dictionary."""
        return cls(
            token=data.get("token", ""),
            url=data.get("url"),
            width=data.get("width"),
            height=data.get("height"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"token", "url", "width", "height", "size", "mime_type"}
            },
        )


@dataclass(slots=True)
class VideoToken:
    """
    Token for accessing a video
    """

    token: str
    """Token for accessing the video"""
    url: Optional[str] = None
    """URL for accessing the video (if available)"""
    width: Optional[int] = None
    """Width of the video in pixels"""
    height: Optional[int] = None
    """Height of the video in pixels"""
    duration: Optional[int] = None
    """Duration of the video in seconds"""
    size: Optional[int] = None
    """Size of the video in bytes"""
    mime_type: Optional[str] = None
    """MIME type of the video"""
    thumbnail: Optional[str] = None
    """Token for the video thumbnail"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoToken":
        """Create VideoToken instance from API response dictionary."""
        return cls(
            token=data.get("token", ""),
            url=data.get("url"),
            width=data.get("width"),
            height=data.get("height"),
            duration=data.get("duration"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            thumbnail=data.get("thumbnail"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"token", "url", "width", "height", "duration", "size", "mime_type", "thumbnail"}
            },
        )


@dataclass(slots=True)
class AudioToken:
    """
    Token for accessing an audio file
    """

    token: str
    """Token for accessing the audio"""
    url: Optional[str] = None
    """URL for accessing the audio (if available)"""
    duration: Optional[int] = None
    """Duration of the audio in seconds"""
    size: Optional[int] = None
    """Size of the audio in bytes"""
    mime_type: Optional[str] = None
    """MIME type of the audio"""
    title: Optional[str] = None
    """Title of the audio"""
    artist: Optional[str] = None
    """Artist of the audio"""
    thumbnail: Optional[str] = None
    """Token for the audio thumbnail"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioToken":
        """Create AudioToken instance from API response dictionary."""
        return cls(
            token=data.get("token", ""),
            url=data.get("url"),
            duration=data.get("duration"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            title=data.get("title"),
            artist=data.get("artist"),
            thumbnail=data.get("thumbnail"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"token", "url", "duration", "size", "mime_type", "title", "artist", "thumbnail"}
            },
        )


@dataclass(slots=True)
class FileToken:
    """
    Token for accessing a file
    """

    token: str
    """Token for accessing the file"""
    url: Optional[str] = None
    """URL for accessing the file (if available)"""
    filename: Optional[str] = None
    """Original filename of the file"""
    size: Optional[int] = None
    """Size of the file in bytes"""
    mime_type: Optional[str] = None
    """MIME type of the file"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileToken":
        """Create FileToken instance from API response dictionary."""
        return cls(
            token=data.get("token", ""),
            url=data.get("url"),
            filename=data.get("filename"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
            api_kwargs={k: v for k, v in data.items() if k not in {"token", "url", "filename", "size", "mime_type"}},
        )


@dataclass(slots=True)
class UploadEndpoint:
    """
    Upload endpoint information
    """

    url: str
    """URL for uploading files"""
    method: str = "POST"
    """HTTP method for uploading files"""
    headers: Optional[Dict[str, str]] = None
    """Headers to include in the upload request"""
    max_file_size: Optional[int] = None
    """Maximum file size in bytes"""
    allowed_types: Optional[List[str]] = None
    """List of allowed MIME types"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadEndpoint":
        """Create UploadEndpoint instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            method=data.get("method", "POST"),
            headers=data.get("headers"),
            max_file_size=data.get("max_file_size"),
            allowed_types=data.get("allowed_types"),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"url", "method", "headers", "max_file_size", "allowed_types"}
            },
        )


@dataclass(slots=True)
class TokenInfo:
    """
    Generic token information
    """

    token: str
    """Token string"""
    type: str
    """Type of the token"""
    expires_at: Optional[int] = None
    """Expiration time in Unix timestamp"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenInfo":
        """Create TokenInfo instance from API response dictionary."""
        return cls(
            token=data.get("token", ""),
            type=data.get("type", ""),
            expires_at=data.get("expires_at"),
            api_kwargs={k: v for k, v in data.items() if k not in {"token", "type", "expires_at"}},
        )


@dataclass(slots=True)
class FileInfo:
    """
    Generic file information
    """

    filename: str
    """Name of the file"""
    size: int
    """Size of the file in bytes"""
    mime_type: str
    """MIME type of the file"""
    created_at: Optional[int] = None
    """Creation time in Unix timestamp"""
    updated_at: Optional[int] = None
    """Last update time in Unix timestamp"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileInfo":
        """Create FileInfo instance from API response dictionary."""
        return cls(
            filename=data.get("filename", ""),
            size=data.get("size", 0),
            mime_type=data.get("mime_type", ""),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"filename", "size", "mime_type", "created_at", "updated_at"}
            },
        )


@dataclass(slots=True)
class PaginationInfo:
    """
    Pagination information for list responses
    """

    total: int
    """Total number of items"""
    limit: int
    """Number of items per page"""
    offset: int
    """Number of items to skip"""
    has_next: bool = False
    """Whether there are more items"""
    has_prev: bool = False
    """Whether there are previous items"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PaginationInfo":
        """Create PaginationInfo instance from API response dictionary."""
        return cls(
            total=data.get("total", 0),
            limit=data.get("limit", 0),
            offset=data.get("offset", 0),
            has_next=data.get("has_next", False),
            has_prev=data.get("has_prev", False),
            api_kwargs={k: v for k, v in data.items() if k not in {"total", "limit", "offset", "has_next", "has_prev"}},
        )
