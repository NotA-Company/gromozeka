"""
Geocode Maps API Async Client

This module provides the main GeocodeMapsClient class for interacting with
the Geocode Maps API (geocode.maps.co) with caching and rate limiting support.
"""

import json
import logging
from typing import Any, Dict, List, Optional, cast

import httpx

from lib.cache import CacheInterface, NullCache
from lib.rate_limiter import RateLimiterManager

from .models import (
    LookupResponse,
    ReverseResponse,
    SearchResponse,
)

logger = logging.getLogger(__name__)


class GeocodeMapsClient:
    """Async client for Geocode Maps API with caching and rate limiting, dood!

    Provides type-safe access to geocoding services with automatic caching
    and rate limiting. Creates new HTTP session for each request to support
    proper concurrent operations.

    Example:
        >>> from lib.geocode_maps import GeocodeMapsClient
        >>> from lib.cache import DictCache
        >>>
        >>> client = GeocodeMapsClient(
        ...     apiKey="your_api_key",
        ...     searchCache=DictCache(),
        ...     reverseCache=DictCache(),
        ...     lookupCache=DictCache(),
        ...     searchTTL=2592000,      # 30 days
        ...     reverseTTL=2592000,     # 30 days
        ...     lookupTTL=2592000,      # 30 days
        ...     acceptLanguage="en"
        ... )
        >>>
        >>> # Forward geocoding
        >>> results = await client.search("Angarsk, Russia")
        >>>
        >>> # Reverse geocoding
        >>> location = await client.reverse(52.5443, 103.8882)
        >>>
        >>> # OSM lookup
        >>> places = await client.lookup(["R2623018"])
    """

    API_BASE_URL = "https://geocode.maps.co"

    def __init__(
        self,
        apiKey: str,
        searchCache: Optional[CacheInterface[Dict[str, Any], SearchResponse]] = None,
        reverseCache: Optional[CacheInterface[Dict[str, Any], ReverseResponse]] = None,
        lookupCache: Optional[CacheInterface[Dict[str, Any], LookupResponse]] = None,
        searchTTL: Optional[int] = 2592000,  # 30 days (geocoding rarely changes)
        reverseTTL: Optional[int] = 2592000,  # 30 days
        lookupTTL: Optional[int] = 2592000,  # 30 days
        requestTimeout: int = 10,
        acceptLanguage: Optional[str] = None,
        rateLimiterQueue: str = "geocode-maps",
    ):
        """Initialize Geocode Maps client, dood!

        Args:
            apiKey: Geocode Maps API key (required)
            searchCache: Cache for search results (default: NullCache)
            reverseCache: Cache for reverse geocoding results (default: NullCache)
            lookupCache: Cache for lookup results (default: NullCache)
            searchTTL: Cache TTL for search results in seconds (default: 30 days)
            reverseTTL: Cache TTL for reverse results in seconds (default: 30 days)
            lookupTTL: Cache TTL for lookup results in seconds (default: 30 days)
            requestTimeout: HTTP request timeout in seconds (default: 10)
            acceptLanguage: Optional language for results (e.g., "en", "ru", "fr") (default: None)
            rateLimiterQueue: Rate limiter queue name (default: "geocode-maps")
        """
        self.apiKey = apiKey
        self.searchCache: CacheInterface[Dict[str, Any], SearchResponse] = (
            searchCache if searchCache is not None else NullCache()
        )
        self.reverseCache: CacheInterface[Dict[str, Any], ReverseResponse] = (
            reverseCache if reverseCache is not None else NullCache()
        )
        self.lookupCache: CacheInterface[Dict[str, Any], LookupResponse] = (
            lookupCache if lookupCache is not None else NullCache()
        )
        self.searchTTL = searchTTL
        self.reverseTTL = reverseTTL
        self.lookupTTL = lookupTTL
        self.requestTimeout = requestTimeout
        self.acceptLanguage = acceptLanguage
        self.rateLimiterQueue = rateLimiterQueue
        self._rateLimiter = RateLimiterManager.getInstance()

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        countrycodes: Optional[str] = None,
        viewbox: Optional[str] = None,
        bounded: bool = False,
        addressdetails: bool = True,
        extratags: bool = True,
        namedetails: bool = True,
        dedupe: bool = True,
        acceptLanguage: Optional[str] = None,
    ) -> Optional[SearchResponse]:
        """Forward geocoding: convert address to coordinates, dood!

        Searches for locations matching the query string and returns
        geographic coordinates and structured address information.

        Args:
            query: Free-form search query (e.g., "Angarsk, Russia")
            limit: Maximum number of results (0-40, default: 10)
            countrycodes: Comma-separated country codes to restrict search (e.g., "ru,us")
            viewbox: Bounding box to bias search (format: "min_lon,min_lat,max_lon,max_lat")
            bounded: Restrict results to viewbox (default: False)
            addressdetails: Include structured address (default: True)
            extratags: Include extra OSM tags (default: True)
            namedetails: Include name translations (default: True)
            dedupe: Remove duplicate results (default: True)
            acceptLanguage: Optional language for results (e.g., "en", "ru", "fr") (default: None)

        Returns:
            List of search results or None if error occurs

        Cache key format: "search:{query}:{limit}:{countrycodes}:{viewbox}:{bounded}"

        Example:
            >>> results = await client.search("Angarsk, Russia", limit=5)
            >>> if results:
            ...     first = results[0]
            ...     print(f"Found: {first['display_name']}")
            ...     print(f"Coordinates: {first['lat']}, {first['lon']}")
        """
        query = query.strip()
        # Build cache key
        # locals() NOTE: Whether or not updates to this dictionary will affect name lookups in
        #  the local scope and vice-versa is implementation dependent and not
        #  covered by any backwards compatibility guarantees.
        # so we'll copy it before deleteing self from it
        cacheKey = locals().copy()
        logger.debug(cacheKey)
        cacheKey.pop("self", None)

        # Check cache first
        try:
            cachedData = await self.searchCache.get(cacheKey, self.searchTTL)
            if cachedData:
                logger.debug(f"Cache hit for search: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for search {cacheKey}: {e}")

        # Build params dict
        params = {
            "q": query,
            "limit": limit,
            "addressdetails": 1 if addressdetails else 0,
            "extratags": 1 if extratags else 0,
            "namedetails": 1 if namedetails else 0,
            "dedupe": 1 if dedupe else 0,
        }

        # Add optional parameters
        if countrycodes:
            params["countrycodes"] = countrycodes
        if viewbox:
            params["viewbox"] = viewbox
        if bounded:
            params["bounded"] = 1
        if acceptLanguage:
            params["accept-language"] = acceptLanguage

        # Make API request
        result = await self._makeRequest("search", params)
        if result is None:
            return None

        # Cast to SearchResponse (List[SearchResult])
        searchResult = cast(SearchResponse, result)

        # Store in cache
        try:
            await self.searchCache.set(cacheKey, searchResult)
        except Exception as e:
            logger.warning(f"Cache set error for search {cacheKey}: {e}")

        return searchResult

    async def reverse(
        self,
        lat: float,
        lon: float,
        *,
        zoom: Optional[int] = None,
        addressdetails: bool = True,
        extratags: bool = True,
        namedetails: bool = True,
        acceptLanguage: Optional[str] = None,
    ) -> Optional[ReverseResponse]:
        """Reverse geocoding: convert coordinates to address, dood!

        Finds the nearest OSM object to the given coordinates and returns
        its address and metadata.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)
            zoom: Detail level (3-18, higher = more detailed)
            addressdetails: Include structured address (default: True)
            extratags: Include extra OSM tags (default: True)
            namedetails: Include name translations (default: True)
            acceptLanguage: Optional language for results (e.g., "en", "ru", "fr") (default: None)

        Returns:
            Reverse geocoding result or None if error occurs

        Cache key format: "reverse:{lat_rounded}:{lon_rounded}:{zoom}"
        Coordinates are rounded to 4 decimal places (~11m precision)

        Example:
            >>> location = await client.reverse(52.5443, 103.8882)
            >>> if location:
            ...     print(f"Address: {location['display_name']}")
            ...     print(f"City: {location['address'].get('city', 'N/A')}")
        """

        # Build cache key
        cacheKey = locals().copy()
        cacheKey.pop("self", None)

        # Check cache first
        try:
            cachedData = await self.reverseCache.get(cacheKey, self.reverseTTL)
            if cachedData:
                logger.debug(f"Cache hit for reverse: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for reverse {cacheKey}: {e}")

        # Build params dict
        params = {
            "lat": lat,  # Use original coordinates for API call
            "lon": lon,  # Use original coordinates for API call
            "addressdetails": 1 if addressdetails else 0,
            "extratags": 1 if extratags else 0,
            "namedetails": 1 if namedetails else 0,
        }

        # Add optional zoom parameter
        if zoom is not None:
            params["zoom"] = zoom
        if acceptLanguage:
            params["accept-language"] = acceptLanguage

        # Make API request
        result = await self._makeRequest("reverse", params)
        if result is None:
            return None

        # Cast result to proper type for cache storage
        reverseResult = cast(ReverseResponse, result)

        # Store in cache
        try:
            await self.reverseCache.set(cacheKey, reverseResult)
        except Exception as e:
            logger.warning(f"Cache set error for reverse {cacheKey}: {e}")

        # Return result as ReverseResponse
        return reverseResult

    async def lookup(
        self,
        osmIds: List[str],
        *,
        addressdetails: bool = True,
        extratags: bool = True,
        namedetails: bool = True,
        polygonGeojson: bool = False,
        polygonKml: bool = False,
        polygonSvg: bool = False,
        polygonText: bool = False,
        acceptLanguage: Optional[str] = None,
    ) -> Optional[LookupResponse]:
        """Lookup OSM objects by ID, dood!

        Retrieves details for one or more OSM objects using their IDs.
        IDs must include type prefix: N (node), W (way), or R (relation).

        Args:
            osmIds: List of OSM IDs with type prefix (e.g., ["R2623018", "N107775"])
            addressdetails: Include structured address (default: True)
            extratags: Include extra OSM tags (default: True)
            namedetails: Include name translations (default: True)
            polygonGeojson: Include GeoJSON polygon (default: False)
            polygonKml: Include KML polygon (default: False)
            polygonSvg: Include SVG polygon (default: False)
            polygonText: Include WKT polygon (default: False)
            acceptLanguage: Optional language for results (e.g., "en", "ru", "fr") (default: None)

        Returns:
            List of lookup results or None if error occurs

        Cache key format: "lookup:{sorted_osm_ids}:{polygon_flags}"

        Example:
            >>> places = await client.lookup(["R2623018"])
            >>> if places:
            ...     place = places[0]
            ...     print(f"Place: {place['name']}")
            ...     print(f"Type: {place['type']}")
        """
        # Sort OSM IDs alphabetically for consistent cache keys
        osmIds = sorted(osmIds)

        # Build cache key
        cacheKey = locals().copy()
        cacheKey.pop("self", None)

        # Check cache first
        try:
            cachedData = await self.lookupCache.get(cacheKey, self.lookupTTL)
            if cachedData:
                logger.debug(f"Cache hit for lookup: {cacheKey}")
                return cachedData
        except Exception as e:
            logger.warning(f"Cache error for lookup {cacheKey}: {e}")

        # Build params dict
        params = {
            "osm_ids": ",".join(osmIds),
            "addressdetails": 1 if addressdetails else 0,
            "extratags": 1 if extratags else 0,
            "namedetails": 1 if namedetails else 0,
            "polygon_geojson": 1 if polygonGeojson else 0,
            "polygon_kml": 1 if polygonKml else 0,
            "polygon_svg": 1 if polygonSvg else 0,
            "polygon_text": 1 if polygonText else 0,
        }
        if acceptLanguage:
            params["accept-language"] = acceptLanguage

        # Make API request
        result = await self._makeRequest("lookup", params)
        if result is None:
            return None

        # Cast result to proper type for cache storage
        lookupResult = cast(LookupResponse, result)

        # Store in cache
        try:
            await self.lookupCache.set(cacheKey, lookupResult)
        except Exception as e:
            logger.warning(f"Cache set error for lookup {cacheKey}: {e}")

        # Return result as LookupResponse
        return lookupResult

    async def _makeRequest(
        self,
        endpoint: str,
        params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Make HTTP request to Geocode Maps API, dood!

        Single point for all HTTP requests with error handling, rate limiting,
        and authentication. Creates new session per request for thread safety.

        Args:
            endpoint: API endpoint path (e.g., "search", "reverse", "lookup")
            params: Query parameters (api_key and format added automatically)

        Returns:
            Parsed JSON response or None on error

        Error Handling:
            - 401: Invalid API key (logs error, returns None)
            - 404: Location not found (logs warning, returns None)
            - 429: Rate limit exceeded (logs error, returns None)
            - 5xx: Server error (logs error, returns None)
            - Timeout: Request timeout (logs error, returns None)
            - Network: Connection error (logs error, returns None)
        """
        try:
            # Build full URL
            url = f"{self.API_BASE_URL}/{endpoint}"

            # Add required parameters
            # TODO: do not add api_key to params
            params["api_key"] = self.apiKey
            params["format"] = "jsonv2"
            if self.acceptLanguage and "accept-language" not in params:
                params["accept-language"] = self.acceptLanguage

            # Build headers
            headers = {"Authorization": f"Bearer {self.apiKey}"}

            logger.debug(f"Making request to {url} with params: {params}")

            # Apply rate limiting
            await self._rateLimiter.applyLimit(self.rateLimiterQueue)

            # Create new session for each request
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
                response = await session.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"API request successful: {response.status_code}")
                    return data

                elif response.status_code == 401:
                    logger.error("Invalid API key")
                    return None

                elif response.status_code == 404:
                    logger.warning("Location not found")
                    return None

                elif response.status_code == 429:
                    logger.error("Rate limit exceeded")
                    return None

                elif response.status_code >= 500:
                    logger.error(f"Server error: {response.status_code}")
                    return None

                else:
                    logger.error(f"API request failed: {response.status_code}")
                    logger.error(f"Response text: {response.text}")
                    return None

        except httpx.TimeoutException:
            logger.error("Request timeout")
            return None

        except httpx.RequestError as e:
            logger.error(f"Network error: {e}")
            return None

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error during API request: {e}")
            return None
