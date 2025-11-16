"""
Interactive attachment models for Max Messenger Bot API.

This module contains interactive attachment dataclasses including Contact, Location,
Share, and Sticker models that extend the base InteractiveAttachment class.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .attachment import AttachmentType, InteractiveAttachment


@dataclass(slots=True)
class Contact(InteractiveAttachment):
    """
    Contact attachment
    """

    first_name: str
    """First name of the contact"""
    user_id: Optional[int] = None
    """ID of the user"""
    last_name: Optional[str] = None
    """Last name of the contact"""
    phone: Optional[str] = None
    """Phone number of the contact"""
    email: Optional[str] = None
    """Email address of the contact"""
    company: Optional[str] = None
    """Company of the contact"""
    position: Optional[str] = None
    """Position of the contact"""
    about: Optional[str] = None
    """About information of the contact"""
    photo: Optional[str] = None
    """Token for the contact's photo"""

    def __post_init__(self):
        """Set the attachment type to contact."""
        self.type = AttachmentType.CONTACT

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Contact":
        """Create Contact instance from API response dictionary."""
        return cls(
            type=AttachmentType.CONTACT,
            user_id=data.get("user_id"),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            phone=data.get("phone"),
            email=data.get("email"),
            company=data.get("company"),
            position=data.get("position"),
            about=data.get("about"),
            photo=data.get("photo"),
        )


@dataclass(slots=True)
class Location(InteractiveAttachment):
    """
    Location attachment
    """

    latitude: float
    """Latitude of the location"""
    longitude: float
    """Longitude of the location"""
    title: Optional[str] = None
    """Title of the location"""
    address: Optional[str] = None
    """Address of the location"""
    provider: Optional[str] = None
    """Provider of the location data"""
    venue_id: Optional[str] = None
    """ID of the venue"""
    foursquare_id: Optional[str] = None
    """Foursquare ID of the venue"""
    foursquare_type: Optional[str] = None
    """Foursquare type of the venue"""
    google_place_id: Optional[str] = None
    """Google Place ID of the venue"""
    google_place_type: Optional[str] = None
    """Google Place type of the venue"""

    def __post_init__(self):
        """Set the attachment type to location."""
        self.type = AttachmentType.LOCATION

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Location":
        """Create Location instance from API response dictionary."""
        return cls(
            type=AttachmentType.LOCATION,
            latitude=data.get("latitude", 0.0),
            longitude=data.get("longitude", 0.0),
            title=data.get("title"),
            address=data.get("address"),
            provider=data.get("provider"),
            venue_id=data.get("venue_id"),
            foursquare_id=data.get("foursquare_id"),
            foursquare_type=data.get("foursquare_type"),
            google_place_id=data.get("google_place_id"),
            google_place_type=data.get("google_place_type"),
        )


@dataclass(slots=True)
class Share(InteractiveAttachment):
    """
    Share attachment
    """

    url: str
    """URL of the shared content"""
    title: Optional[str] = None
    """Title of the shared content"""
    description: Optional[str] = None
    """Description of the shared content"""
    image: Optional[str] = None
    """Token for the shared content's image"""
    site_name: Optional[str] = None
    """Name of the site"""
    content_type: Optional[str] = None
    """Content type of the shared content"""
    video_url: Optional[str] = None
    """URL of the video content"""
    video_width: Optional[int] = None
    """Width of the video"""
    video_height: Optional[int] = None
    """Height of the video"""
    video_duration: Optional[int] = None
    """Duration of the video in seconds"""

    def __post_init__(self):
        """Set the attachment type to share."""
        self.type = AttachmentType.SHARE

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Share":
        """Create Share instance from API response dictionary."""
        return cls(
            type=AttachmentType.SHARE,
            url=data.get("url", ""),
            title=data.get("title"),
            description=data.get("description"),
            image=data.get("image"),
            site_name=data.get("site_name"),
            content_type=data.get("content_type"),
            video_url=data.get("video_url"),
            video_width=data.get("video_width"),
            video_height=data.get("video_height"),
            video_duration=data.get("video_duration"),
        )


@dataclass(slots=True)
class Sticker(InteractiveAttachment):
    """
    Sticker attachment
    """

    token: str
    """Token for accessing the sticker"""
    width: Optional[int] = None
    """Width of the sticker in pixels"""
    height: Optional[int] = None
    """Height of the sticker in pixels"""
    emoji: Optional[str] = None
    """Emoji representation of the sticker"""
    pack_name: Optional[str] = None
    """Name of the sticker pack"""
    pack_id: Optional[str] = None
    """ID of the sticker pack"""
    is_animated: bool = False
    """Whether the sticker is animated"""
    is_video: bool = False
    """Whether the sticker is a video"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    def __post_init__(self):
        """Set the attachment type to sticker."""
        self.type = AttachmentType.STICKER

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Sticker":
        """Create Sticker instance from API response dictionary."""
        return cls(
            type=AttachmentType.STICKER,
            token=data.get("token", ""),
            width=data.get("width"),
            height=data.get("height"),
            emoji=data.get("emoji"),
            pack_name=data.get("pack_name"),
            pack_id=data.get("pack_id"),
            is_animated=data.get("is_animated", False),
            is_video=data.get("is_video", False),
        )


@dataclass(slots=True)
class ContactRequest:
    """
    Request for creating a contact attachment
    """

    first_name: str
    """First name of the contact"""
    last_name: Optional[str] = None
    """Last name of the contact"""
    phone: Optional[str] = None
    """Phone number of the contact"""
    email: Optional[str] = None
    """Email address of the contact"""
    company: Optional[str] = None
    """Company of the contact"""
    position: Optional[str] = None
    """Position of the contact"""
    about: Optional[str] = None
    """About information of the contact"""
    photo_token: Optional[str] = None
    """Token for the contact's photo"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactRequest":
        """Create ContactRequest instance from API response dictionary."""
        return cls(
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            phone=data.get("phone"),
            email=data.get("email"),
            company=data.get("company"),
            position=data.get("position"),
            about=data.get("about"),
            photo_token=data.get("photo_token"),
        )


@dataclass(slots=True)
class LocationRequest:
    """
    Request for creating a location attachment
    """

    latitude: float
    """Latitude of the location"""
    longitude: float
    """Longitude of the location"""
    title: Optional[str] = None
    """Title of the location"""
    address: Optional[str] = None
    """Address of the location"""
    provider: Optional[str] = None
    """Provider of the location data"""
    venue_id: Optional[str] = None
    """ID of the venue"""
    foursquare_id: Optional[str] = None
    """Foursquare ID of the venue"""
    foursquare_type: Optional[str] = None
    """Foursquare type of the venue"""
    google_place_id: Optional[str] = None
    """Google Place ID of the venue"""
    google_place_type: Optional[str] = None
    """Google Place type of the venue"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocationRequest":
        """Create LocationRequest instance from API response dictionary."""
        return cls(
            latitude=data.get("latitude", 0.0),
            longitude=data.get("longitude", 0.0),
            title=data.get("title"),
            address=data.get("address"),
            provider=data.get("provider"),
            venue_id=data.get("venue_id"),
            foursquare_id=data.get("foursquare_id"),
            foursquare_type=data.get("foursquare_type"),
            google_place_id=data.get("google_place_id"),
            google_place_type=data.get("google_place_type"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "latitude",
                    "longitude",
                    "title",
                    "address",
                    "provider",
                    "venue_id",
                    "foursquare_id",
                    "foursquare_type",
                    "google_place_id",
                    "google_place_type",
                }
            },
        )


@dataclass(slots=True)
class ShareRequest:
    """
    Request for creating a share attachment
    """

    url: str
    """URL of the shared content"""
    title: Optional[str] = None
    """Title of the shared content"""
    description: Optional[str] = None
    """Description of the shared content"""
    image_token: Optional[str] = None
    """Token for the shared content's image"""
    site_name: Optional[str] = None
    """Name of the site"""
    content_type: Optional[str] = None
    """Content type of the shared content"""
    video_url: Optional[str] = None
    """URL of the video content"""
    video_width: Optional[int] = None
    """Width of the video"""
    video_height: Optional[int] = None
    """Height of the video"""
    video_duration: Optional[int] = None
    """Duration of the video in seconds"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShareRequest":
        """Create ShareRequest instance from API response dictionary."""
        return cls(
            url=data.get("url", ""),
            title=data.get("title"),
            description=data.get("description"),
            image_token=data.get("image_token"),
            site_name=data.get("site_name"),
            content_type=data.get("content_type"),
            video_url=data.get("video_url"),
            video_width=data.get("video_width"),
            video_height=data.get("video_height"),
            video_duration=data.get("video_duration"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "url",
                    "title",
                    "description",
                    "image_token",
                    "site_name",
                    "content_type",
                    "video_url",
                    "video_width",
                    "video_height",
                    "video_duration",
                }
            },
        )


@dataclass(slots=True)
class StickerRequest:
    """
    Request for creating a sticker attachment
    """

    token: str
    """Token for accessing the sticker"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StickerRequest":
        """Create StickerRequest instance from API response dictionary."""
        return cls(token=data.get("token", ""), api_kwargs={k: v for k, v in data.items() if k not in {"token"}})
