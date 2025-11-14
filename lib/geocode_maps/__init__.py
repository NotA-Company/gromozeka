"""
Geocode Maps API Client Library

This module provides a Python async client library for the Geocode Maps API (geocode.maps.co)
with type-safe responses, caching, and rate limiting support.

Example usage:
    from lib.geocode_maps import GeocodeMapsClient
    from lib.cache import DictCache

    client = GeocodeMapsClient(
        apiKey="your_api_key",
        searchCache=DictCache(),
        reverseCache=DictCache(),
        lookupCache=DictCache()
    )

    # Forward geocoding
    results = await client.search("Angarsk, Russia")

    # Reverse geocoding
    location = await client.reverse(52.5443, 103.8882)

    # OSM lookup
    places = await client.lookup(["R2623018"])
"""

from lib.geocode_maps.client import GeocodeMapsClient
from lib.geocode_maps.models import (
    Address,
    Coordinates,
    ExtraTags,
    LookupResponse,
    LookupResult,
    NameDetails,
    ReverseResponse,
    ReverseResult,
    SearchResponse,
    SearchResult,
)

__all__ = [
    "GeocodeMapsClient",
    "Address",
    "NameDetails",
    "ExtraTags",
    "SearchResult",
    "ReverseResult",
    "LookupResult",
    "SearchResponse",
    "ReverseResponse",
    "LookupResponse",
    "Coordinates",
]
