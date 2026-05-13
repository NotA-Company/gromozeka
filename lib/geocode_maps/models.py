"""Geocode Maps API Data Models.

This module defines TypedDict data models for the Geocode Maps API responses.
All models use TypedDict for runtime compatibility and comprehensive type hints.

The Geocode Maps API provides geocoding, reverse geocoding, and lookup services
for geographic locations. These models represent the structured data returned
by the API endpoints.

Example:
    >>> from lib.geocode_maps.models import SearchResult, Address
    >>> result: SearchResult = {
    ...     "place_id": 123456,
    ...     "lat": "52.517037",
    ...     "lon": "13.388860",
    ...     "display_name": "Berlin, Germany",
    ...     "address": {"city": "Berlin", "country": "Germany"}
    ... }
"""

import sys
from typing import List, NotRequired

if sys.version_info >= (3, 14):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class Address(TypedDict, total=False, closed=False):
    """Structured address components from geocoding response.

    This TypedDict represents the hierarchical address structure returned by
    the Geocode Maps API. All fields are optional as different locations have
    different address structures depending on the geographic region and
    administrative divisions.

    Attributes:
        road: Street name or thoroughfare.
        neighbourhood: Neighbourhood or district name within a city.
        suburb: Suburb name or residential area.
        city: City or town name.
        county: County or district name (second-level administrative division).
        state: State, province, or region name (first-level administrative division).
        postcode: Postal code or ZIP code.
        country: Country name.
        country_code: ISO 3166-1 alpha-2 country code (e.g., "ru", "us", "de").
        region: Region name (alternative to state in some regions).
        amenity: Amenity name if the location is a specific facility (e.g., "hospital").

    Example:
        >>> address: Address = {
        ...     "road": "Unter den Linden",
        ...     "city": "Berlin",
        ...     "state": "Berlin",
        ...     "country": "Germany",
        ...     "country_code": "de",
        ...     "postcode": "10117"
        ... }
    """

    road: str
    neighbourhood: str
    suburb: str
    city: str
    county: str
    state: str
    postcode: str
    country: str
    country_code: str
    region: str
    amenity: str


class NameDetails(TypedDict, total=False, closed=False):
    """Name translations in different languages.

    This TypedDict contains localized names for a geographic location.
    The API may return names in multiple languages depending on the
    location and available data.

    Attributes:
        name: Default or primary name of the location.
        int_name: International name (often English or Latin script).

    Note:
        Additional language-specific fields may be present in the format
        "name:XX" where XX is an ISO 639-1 language code (e.g., "name:en",
        "name:ru", "name:de"). These are not explicitly defined here due to
        the dynamic nature of language support.

    Example:
        >>> name_details: NameDetails = {
        ...     "name": "Берлин",
        ...     "int_name": "Berlin",
        ...     "name:en": "Berlin",
        ...     "name:ru": "Берлин"
        ... }
    """

    name: str
    int_name: str


class ExtraTags(TypedDict, total=False, closed=False):
    """Additional OSM tags and metadata.

    This TypedDict contains supplementary OpenStreetMap (OSM) tags and
    metadata that provide additional context about a geographic location.
    These tags are optional and vary based on the type of location and
    available OSM data.

    Attributes:
        website: Official website URL for the location.
        wikidata: Wikidata identifier (Q-number).
        wikipedia: Wikipedia article reference (format: "lang:Title").
        population: Population count as a string.
        start_date: Establishment or founding date.
        linked_place: Type of linked place (e.g., "city", "town").
        official_status: Official administrative status.
        area: Area indicator or measurement.
        surface: Surface type (e.g., "asphalt", "gravel").

    Note:
        Many additional OSM tags may be present depending on the location type.
        Common tags include opening hours, phone numbers, and various
        administrative classifications.

    Example:
        >>> extra_tags: ExtraTags = {
        ...     "wikidata": "Q64",
        ...     "wikipedia": "en:Berlin",
        ...     "population": "3644826",
        ...     "website": "https://www.berlin.de"
        ... }
    """

    website: str
    wikidata: str
    wikipedia: str
    population: str
    start_date: str
    linked_place: str
    official_status: str
    area: str
    surface: str
    # ... additional OSM tags as needed


class SearchResult(TypedDict):
    """Single result from /search endpoint.

    This TypedDict represents a single geographic location result returned
    by the Geocode Maps API's search endpoint. The search endpoint accepts
    a query string and returns matching locations with their coordinates
    and metadata.

    Attributes:
        place_id: Unique place identifier in the Geocode Maps database.
        licence: Data licence information (typically ODbL).
        osm_type: OSM object type: "node", "way", or "relation".
        osm_id: OSM object ID (unique identifier in OpenStreetMap).
        lat: Latitude as a string (decimal degrees).
        lon: Longitude as a string (decimal degrees).
        category: Place category (e.g., "place", "highway", "building").
        type: Place type (e.g., "city", "street", "house").
        place_rank: Place importance rank (higher = more important).
        importance: Importance score between 0 and 1 (higher = more important).
        addresstype: Primary address type (e.g., "city", "road").
        name: Place name.
        display_name: Full human-readable display name.
        address: Structured address components.
        boundingbox: Bounding box as [min_lat, max_lat, min_lon, max_lon].
        extratags: Optional extra OSM tags and metadata.
        namedetails: Optional name translations in different languages.
        geotext: Optional geometry as WKT (Well-Known Text) polygon.

    Example:
        >>> result: SearchResult = {
        ...     "place_id": 123456,
        ...     "licence": "Data © OpenStreetMap contributors",
        ...     "osm_type": "relation",
        ...     "osm_id": 62422,
        ...     "lat": "52.517037",
        ...     "lon": "13.388860",
        ...     "category": "place",
        ...     "type": "city",
        ...     "place_rank": 16,
        ...     "importance": 0.8,
        ...     "addresstype": "city",
        ...     "name": "Berlin",
        ...     "display_name": "Berlin, Germany",
        ...     "address": {"city": "Berlin", "country": "Germany"},
        ...     "boundingbox": ["52.33824", "52.67551", "13.08835", "13.76116"]
        ... }
    """

    place_id: int
    licence: str
    osm_type: str
    osm_id: int
    lat: str
    lon: str
    category: str
    type: str
    place_rank: int
    importance: float
    addresstype: str
    name: str
    display_name: str
    address: Address
    boundingbox: List[str]
    extratags: NotRequired[ExtraTags]
    namedetails: NotRequired[NameDetails]
    geotext: NotRequired[str]


class ReverseResult(TypedDict):
    """Result from /reverse endpoint.

    This TypedDict represents the result returned by the Geocode Maps API's
    reverse geocoding endpoint. The reverse endpoint accepts latitude and
    longitude coordinates and returns the nearest address or place.

    Attributes:
        place_id: Unique place identifier in the Geocode Maps database.
        licence: Data licence information (typically ODbL).
        osm_type: OSM object type: "node", "way", or "relation".
        osm_id: OSM object ID (unique identifier in OpenStreetMap).
        lat: Latitude as a string (decimal degrees).
        lon: Longitude as a string (decimal degrees).
        category: Place category (e.g., "place", "highway", "building").
        type: Place type (e.g., "city", "street", "house").
        place_rank: Place importance rank (higher = more important).
        importance: Importance score between 0 and 1 (higher = more important).
        addresstype: Primary address type (e.g., "city", "road").
        name: Place name.
        display_name: Full human-readable display name.
        address: Structured address components.
        boundingbox: Bounding box as [min_lat, max_lat, min_lon, max_lon].
        extratags: Optional extra OSM tags and metadata.
        namedetails: Optional name translations in different languages.

    Example:
        >>> result: ReverseResult = {
        ...     "place_id": 123456,
        ...     "licence": "Data © OpenStreetMap contributors",
        ...     "osm_type": "way",
        ...     "osm_id": 12345678,
        ...     "lat": "52.517037",
        ...     "lon": "13.388860",
        ...     "category": "highway",
        ...     "type": "primary",
        ...     "place_rank": 26,
        ...     "importance": 0.1,
        ...     "addresstype": "road",
        ...     "name": "Unter den Linden",
        ...     "display_name": "Unter den Linden, Mitte, Berlin, Germany",
        ...     "address": {
        ...         "road": "Unter den Linden",
        ...         "suburb": "Mitte",
        ...         "city": "Berlin",
        ...         "country": "Germany"
        ...     },
        ...     "boundingbox": ["52.516", "52.518", "13.388", "13.390"]
        ... }
    """

    place_id: int
    licence: str
    osm_type: str
    osm_id: int
    lat: str
    lon: str
    category: str
    type: str
    place_rank: int
    importance: float
    addresstype: str
    name: str
    display_name: str
    address: Address
    boundingbox: List[str]
    extratags: NotRequired[ExtraTags]
    namedetails: NotRequired[NameDetails]


class LookupResult(TypedDict):
    """Result from /lookup endpoint.

    This TypedDict represents the result returned by the Geocode Maps API's
    lookup endpoint. The lookup endpoint accepts OSM object identifiers
    (osm_type and osm_id) and returns detailed information about that
    specific geographic object.

    Attributes:
        place_id: Unique place identifier in the Geocode Maps database.
        licence: Data licence information (typically ODbL).
        osm_type: OSM object type: "node", "way", or "relation".
        osm_id: OSM object ID (unique identifier in OpenStreetMap).
        lat: Latitude as a string (decimal degrees).
        lon: Longitude as a string (decimal degrees).
        category: Place category (e.g., "place", "highway", "building").
        type: Place type (e.g., "city", "street", "house").
        place_rank: Place importance rank (higher = more important).
        importance: Importance score between 0 and 1 (higher = more important).
        addresstype: Primary address type (e.g., "city", "road").
        name: Place name.
        display_name: Full human-readable display name.
        address: Structured address components.
        boundingbox: Bounding box as [min_lat, max_lat, min_lon, max_lon].
        extratags: Optional extra OSM tags and metadata.
        namedetails: Optional name translations in different languages.
        geotext: Optional geometry as WKT (Well-Known Text) polygon.

    Example:
        >>> result: LookupResult = {
        ...     "place_id": 123456,
        ...     "licence": "Data © OpenStreetMap contributors",
        ...     "osm_type": "relation",
        ...     "osm_id": 62422,
        ...     "lat": "52.517037",
        ...     "lon": "13.388860",
        ...     "category": "place",
        ...     "type": "city",
        ...     "place_rank": 16,
        ...     "importance": 0.8,
        ...     "addresstype": "city",
        ...     "name": "Berlin",
        ...     "display_name": "Berlin, Germany",
        ...     "address": {"city": "Berlin", "country": "Germany"},
        ...     "boundingbox": ["52.33824", "52.67551", "13.08835", "13.76116"],
        ...     "geotext": "POLYGON((13.08835 52.33824,13.76116 52.33824,...))"
        ... }
    """

    place_id: int
    licence: str
    osm_type: str
    osm_id: int
    lat: str
    lon: str
    category: str
    type: str
    place_rank: int
    importance: float
    addresstype: str
    name: str
    display_name: str
    address: Address
    boundingbox: List[str]
    extratags: NotRequired[ExtraTags]
    namedetails: NotRequired[NameDetails]
    geotext: NotRequired[str]


# Response types for each endpoint
SearchResponse = List[SearchResult]
"""Type alias for /search endpoint response.

The search endpoint returns an array of SearchResult objects, ordered by
relevance/importance. The array may be empty if no results are found.

Example:
    >>> response: SearchResponse = [
    ...     {
    ...         "place_id": 123456,
    ...         "lat": "52.517037",
    ...         "lon": "13.388860",
    ...         "display_name": "Berlin, Germany",
    ...         "address": {"city": "Berlin", "country": "Germany"},
    ...         # ... other required fields
    ...     }
    ... ]
"""

ReverseResponse = ReverseResult
"""Type alias for /reverse endpoint response.

The reverse endpoint returns a single ReverseResult object representing
the nearest address or place to the provided coordinates.

Example:
    >>> response: ReverseResponse = {
    ...     "place_id": 123456,
    ...     "lat": "52.517037",
    ...     "lon": "13.388860",
    ...     "display_name": "Unter den Linden, Berlin, Germany",
    ...     "address": {"road": "Unter den Linden", "city": "Berlin"},
    ...     # ... other required fields
    ... }
"""

LookupResponse = List[LookupResult]
"""Type alias for /lookup endpoint response.

The lookup endpoint returns an array of LookupResult objects. Typically
contains a single result, but may return multiple if the OSM ID matches
multiple objects.

Example:
    >>> response: LookupResponse = [
    ...     {
    ...         "place_id": 123456,
    ...         "osm_type": "relation",
    ...         "osm_id": 62422,
    ...         "lat": "52.517037",
    ...         "lon": "13.388860",
    ...         "display_name": "Berlin, Germany",
    ...         # ... other required fields
    ...     }
    ... ]
"""


class Coordinates(TypedDict):
    """Latitude/longitude pair.

    This TypedDict represents a geographic coordinate pair with latitude
    and longitude values as floats. This is used internally for coordinate
    calculations and conversions.

    Attributes:
        lat: Latitude in decimal degrees (range: -90 to 90).
        lon: Longitude in decimal degrees (range: -180 to 180).

    Example:
        >>> coords: Coordinates = {"lat": 52.517037, "lon": 13.388860}
    """

    lat: float
    lon: float
