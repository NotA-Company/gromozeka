"""
Attachment base models and infrastructure for Max Messenger Bot API.

This module contains the base attachment classes and enums that form the foundation
for all attachment types in the Max Messenger Bot API.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


class AttachmentType(StrEnum):
    """
    Base attachment type enum
    """

    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    CONTACT = "contact"
    LOCATION = "location"
    SHARE = "share"
    STICKER = "sticker"
    INLINE_KEYBOARD = "inline_keyboard"
    REPLY_KEYBOARD = "reply_keyboard"


@dataclass(slots=True)
class Attachment:
    """
    Base attachment class for all attachment types
    """

    type: AttachmentType
    """Type of the attachment"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Attachment":
        """Create Attachment instance from API response dictionary."""
        return cls(
            type=AttachmentType(data.get("type", "file")),
        )


@dataclass(slots=True)
class MediaAttachment(Attachment):
    """
    Base class for media attachments (photo, video, audio, file)
    """

    token: str
    """Token for accessing the media file"""
    filename: Optional[str] = None
    """Original filename of the media file"""
    size: Optional[int] = None
    """Size of the media file in bytes"""
    mime_type: Optional[str] = None
    """MIME type of the media file"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaAttachment":
        """Create MediaAttachment instance from API response dictionary."""
        return cls(
            type=AttachmentType(data.get("type", "file")),
            token=data.get("token", ""),
            filename=data.get("filename"),
            size=data.get("size"),
            mime_type=data.get("mime_type"),
        )


@dataclass(slots=True)
class InteractiveAttachment(Attachment):
    """
    Base class for interactive attachments (contact, location, share, sticker)
    """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractiveAttachment":
        """Create InteractiveAttachment instance from API response dictionary."""
        return cls(
            type=AttachmentType(data.get("type", "contact")),
        )


@dataclass(slots=True)
class KeyboardAttachment(Attachment):
    """
    Base class for keyboard attachments (inline_keyboard, reply_keyboard)
    """

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeyboardAttachment":
        """Create KeyboardAttachment instance from API response dictionary."""
        return cls(
            type=AttachmentType(data.get("type", "inline_keyboard")),
        )


@dataclass(slots=True)
class AttachmentList:
    """
    List of attachments
    """

    attachments: List[Attachment]
    """List of attachment objects"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttachmentList":
        """Create AttachmentList instance from API response dictionary."""
        attachments_data = data.get("attachments", [])
        attachments = []

        for attachment_data in attachments_data:
            attachment_type = attachment_data.get("type", "file")

            # Create appropriate attachment type based on the type field
            if attachment_type in ["photo", "video", "audio", "file"]:
                attachments.append(MediaAttachment.from_dict(attachment_data))
            elif attachment_type in ["contact", "location", "share", "sticker"]:
                attachments.append(InteractiveAttachment.from_dict(attachment_data))
            elif attachment_type in ["inline_keyboard", "reply_keyboard"]:
                attachments.append(KeyboardAttachment.from_dict(attachment_data))
            else:
                attachments.append(Attachment.from_dict(attachment_data))

        return cls(attachments=attachments, api_kwargs={k: v for k, v in data.items() if k not in {"attachments"}})


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
