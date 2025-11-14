"""
Geocode Maps API Data Models

This module defines TypedDict data models for the Geocode Maps API responses.
All models use TypedDict for runtime compatibility and comprehensive type hints.
"""

import sys
from typing import List, NotRequired

if sys.version_info >= (3, 14):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class Address(TypedDict, total=False, closed=False):
    """Structured address components from geocoding response, dood!

    All fields are optional as different locations have different address structures.
    """

    road: str  # Street name
    neighbourhood: str  # Neighbourhood/district
    suburb: str  # Suburb name
    city: str  # City name
    county: str  # County/district name
    state: str  # State/region name
    postcode: str  # Postal code
    country: str  # Country name
    country_code: str  # ISO country code (e.g., "ru")
    region: str  # Region name
    amenity: str  # Amenity name (if applicable)
    # ISO 3166-2 level 4 code
    # ISO3166-2-lvl4: str  # ISO 3166-2 subdivision code.


class NameDetails(TypedDict, total=False, closed=False):
    """Name translations in different languages, dood!"""

    name: str  # Default name
    int_name: str  # International name
    # Language-specific names (examples)
    # name:en: str  # English name
    # name:ru: str  # Russian name
    # ... additional language codes as needed


class ExtraTags(TypedDict, total=False, closed=False):
    """Additional OSM tags and metadata, dood!"""

    website: str  # Official website URL
    wikidata: str  # Wikidata ID
    wikipedia: str  # Wikipedia article reference
    population: str  # Population count
    start_date: str  # Establishment date
    linked_place: str  # Linked place type
    official_status: str  # Official administrative status
    area: str  # Area indicator
    surface: str  # Surface type
    # ... additional OSM tags as needed


class SearchResult(TypedDict):
    """Single result from /search endpoint, dood!"""

    place_id: int  # Unique place identifier
    licence: str  # Data licence information
    osm_type: str  # OSM object type (node/way/relation)
    osm_id: int  # OSM object ID
    lat: str  # Latitude (string in API response)
    lon: str  # Longitude (string in API response)
    category: str  # Place category
    type: str  # Place type
    place_rank: int  # Place importance rank
    importance: float  # Importance score (0-1)
    addresstype: str  # Address type
    name: str  # Place name
    display_name: str  # Full display name
    address: Address  # Structured address components
    boundingbox: List[str]  # Bounding box [min_lat, max_lat, min_lon, max_lon]
    extratags: NotRequired[ExtraTags]  # Optional extra OSM tags
    namedetails: NotRequired[NameDetails]  # Optional name translations
    geotext: NotRequired[str]  # Optional geometry as WKT polygon


class ReverseResult(TypedDict):
    """Result from /reverse endpoint, dood!"""

    place_id: int  # Unique place identifier
    licence: str  # Data licence information
    osm_type: str  # OSM object type
    osm_id: int  # OSM object ID
    lat: str  # Latitude (string in API response)
    lon: str  # Longitude (string in API response)
    category: str  # Place category
    type: str  # Place type
    place_rank: int  # Place importance rank
    importance: float  # Importance score
    addresstype: str  # Address type
    name: str  # Place name
    display_name: str  # Full display name
    address: Address  # Structured address components
    boundingbox: List[str]  # Bounding box
    extratags: NotRequired[ExtraTags]  # Optional extra OSM tags
    namedetails: NotRequired[NameDetails]  # Optional name translations


class LookupResult(TypedDict):
    """Result from /lookup endpoint, dood!"""

    place_id: int  # Unique place identifier
    licence: str  # Data licence information
    osm_type: str  # OSM object type
    osm_id: int  # OSM object ID
    lat: str  # Latitude (string in API response)
    lon: str  # Longitude (string in API response)
    category: str  # Place category
    type: str  # Place type
    place_rank: int  # Place importance rank
    importance: float  # Importance score
    addresstype: str  # Address type
    name: str  # Place name
    display_name: str  # Full display name
    address: Address  # Structured address components
    boundingbox: List[str]  # Bounding box
    extratags: NotRequired[ExtraTags]  # Optional extra OSM tags
    namedetails: NotRequired[NameDetails]  # Optional name translations
    geotext: NotRequired[str]  # Optional geometry as WKT polygon


# Response types for each endpoint
SearchResponse = List[SearchResult]  # /search returns array
ReverseResponse = ReverseResult  # /reverse returns single object
LookupResponse = List[LookupResult]  # /lookup returns array


class Coordinates(TypedDict):
    """Latitude/longitude pair, dood!"""

    lat: float
    lon: float
