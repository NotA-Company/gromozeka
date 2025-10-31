"""
Data models for Yandex Search API client

This module defines TypedDict classes for API requests and responses that
conform to the Yandex Search API v2 specification. These models provide
type safety and documentation for the data structures used throughout
the client library.

All models use TypedDict for runtime compatibility while providing
static type checking support. The models are organized into:
- Request models: Structures for API request parameters
- Response models: Structures for parsed API responses
- Authentication models: Structures for authentication configuration

Example:
    ```python
    # Creating a search request
    request: SearchRequest = {
        "query": {
            "searchType": "SEARCH_TYPE_RU",
            "queryText": "python programming",
            "familyMode": "FAMILY_MODE_MODERATE"
        },
        "sortSpec": {
            "sortMode": "SORT_MODE_BY_RELEVANCE",
            "sortOrder": "SORT_ORDER_DESC"
        },
        "groupSpec": {
            "groupMode": "GROUP_MODE_DEEP",
            "groupsOnPage": "10",
            "docsInGroup": "2"
        },
        "metadata": {
            "folderId": "your_folder_id",
            "responseFormat": "FORMAT_XML",
            "maxPassages": "2"
        }
    }
    ```
"""

from enum import StrEnum
from typing import Dict, List, NotRequired, Optional, TypeAlias, TypedDict

# Request Models


class SearchType(StrEnum):
    """Search type that determines the domain name that will be used for the search queries."""

    SEARCH_TYPE_RU = "SEARCH_TYPE_RU"  # Russian search (yandex.ru)
    SEARCH_TYPE_TR = "SEARCH_TYPE_TR"  # Turkish search (yandex.com.tr)
    SEARCH_TYPE_COM = "SEARCH_TYPE_COM"  # International search (yandex.com)
    SEARCH_TYPE_KK = "SEARCH_TYPE_KK"  # Kazakh search (yandex.kz)
    SEARCH_TYPE_BE = "SEARCH_TYPE_BE"  # Belarusian search (yandex.by)
    SEARCH_TYPE_UZ = "SEARCH_TYPE_UZ"  # Uzbek search (yandex.uz)


class FamilyMode(StrEnum):
    """Rule for filtering search results and determines whether any documents should be excluded."""

    FAMILY_MODE_UNSPECIFIED = "FAMILY_MODE_UNSPECIFIED"
    FAMILY_MODE_MODERATE = "FAMILY_MODE_MODERATE"  # Moderate content filtering
    FAMILY_MODE_STRICT = "FAMILY_MODE_STRICT"  # Strict content filtering
    FAMILY_MODE_OFF = "FAMILY_MODE_OFF"  # No content filtering


class FixTypoMode(StrEnum):
    """Typos autocorrections mode"""

    FIX_TYPO_MODE_UNSPECIFIED = "FIX_TYPO_MODE_UNSPECIFIED"
    FIX_TYPO_MODE_ON = "FIX_TYPO_MODE_ON"  # Automatically correct typos (default value).
    FIX_TYPO_MODE_OFF = "FIX_TYPO_MODE_OFF"  # Autocorrection is off.


class SearchQuery(TypedDict):
    """
    Search query parameters for the Yandex Search API.

    This TypedDict defines the structure for search query parameters,
    including the search text, domain, and various search options.

    Fields:
        searchType (SearchType): Search domain identifier. Required field.

        queryText (str): The actual search query text. Required field.
            Can contain any characters supported by the search engine.

        familyMode (Optional[FamilyMode]): Family filter mode for content filtering.

        page (Optional[str]): Page number for pagination (0-based).
            Used to navigate through search results. Default is "0".

        fixTypoMode (Optional[FixTypoMode]): Typo correction mode.

    Example:
        ```python
        query: SearchQuery = {
            "searchType": SearchType.SEARCH_TYPE_RU,
            "queryText": "python programming tutorials",
            "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
            "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON
        }
        ```
    """

    searchType: SearchType
    queryText: str
    familyMode: Optional[FamilyMode]
    page: Optional[str]
    fixTypoMode: Optional[FixTypoMode]


class SortMode(StrEnum):
    """Documents sorting mode."""

    SORT_MODE_UNSPECIFIED = "SORT_MODE_UNSPECIFIED"
    SORT_MODE_BY_RELEVANCE = "SORT_MODE_BY_RELEVANCE"  # Sort documents by relevance (default value).
    SORT_MODE_BY_TIME = "SORT_MODE_BY_TIME"  # Sort documents by update time.


class SortOrder(StrEnum):
    """Documents sorting order."""

    SORT_ORDER_UNSPECIFIED = "SORT_ORDER_UNSPECIFIED"
    SORT_ORDER_ASC = "SORT_ORDER_ASC"  # Reverse order from oldest to most recent.
    SORT_ORDER_DESC = "SORT_ORDER_DESC"  # Direct order from most recent to oldest (default).


class SortSpec(TypedDict):
    """
    Sorting parameters for search results.

    This TypedDict defines how search results should be sorted and ordered.
    All fields are optional - if not provided, the API defaults will be used.

    Fields:
        sortMode (Optional[SortMode]): Sort mode for results.

        sortOrder (Optional[SortOrder]): Sort order direction.


    Example:
        ```python
        sort: SortSpec = {
            "sortMode": "SORT_MODE_BY_RELEVANCE",
            "sortOrder": "SORT_ORDER_DESC"
        }
        ```
    """

    sortMode: NotRequired[SortMode]
    sortOrder: NotRequired[SortOrder]


class GroupMode(StrEnum):
    """Grouping method."""

    GROUP_MODE_UNSPECIFIED = "GROUP_MODE_UNSPECIFIED"
    GROUP_MODE_FLAT = "GROUP_MODE_FLAT"  # Flat grouping. Each group contains a single document.
    GROUP_MODE_DEEP = "GROUP_MODE_DEEP"  # Grouping by domain. Each group contains documents from one domain.


class GroupSpec(TypedDict):
    """
    Grouping parameters for search results.

    This TypedDict defines how search results should be grouped and organized.
    Grouping helps organize related documents together, such as pages from
    the same website or different sections of the same document.

    Fields:
        groupMode (Optional[GroupMode]): Result grouping mode.

        groupsOnPage (Optional[str]): Number of result groups per page.
            Valid range: 1-100. Default is "10".
            Each group may contain multiple documents.

        docsInGroup (Optional[str]): Number of documents in each group.
            Valid range: 1-10. Default is "2".
            Controls how many related documents are shown together.

    Example:
        ```python
        group: GroupSpec = {
            "groupMode": "GROUP_MODE_DEEP",
            "groupsOnPage": "10",
            "docsInGroup": "2"
        }
        ```
    """

    groupMode: NotRequired[GroupMode]
    groupsOnPage: NotRequired[str]
    docsInGroup: NotRequired[str]


class Localization(StrEnum):
    """The notification language for a search response."""

    LOCALIZATION_UNSPECIFIED = "LOCALIZATION_UNSPECIFIED"
    LOCALIZATION_RU = "LOCALIZATION_RU"  # Russian (default value)
    LOCALIZATION_UK = "LOCALIZATION_UK"  # Ukrainian
    LOCALIZATION_BE = "LOCALIZATION_BE"  # Belarusian
    LOCALIZATION_KK = "LOCALIZATION_KK"  # Kazakh
    LOCALIZATION_TR = "LOCALIZATION_TR"  # Turkish
    LOCALIZATION_EN = "LOCALIZATION_EN"  # English


class ResponseFormat(StrEnum):
    """Search results format."""

    FORMAT_UNSPECIFIED = "FORMAT_UNSPECIFIED"
    FORMAT_XML = "FORMAT_XML"  # XML format (default value)
    FORMAT_HTML = "FORMAT_HTML"  # HTML format (Unsupported by this client)


class SearchRequest(TypedDict):
    """
    Complete search request structure for the Yandex Search API.

    This TypedDict combines all components of a search request into a single
    structure that can be serialized and sent to the API. It includes the query
    parameters, sorting options, grouping settings, and metadata fields directly
    at the top level as required by the API specification.

    Fields:
        query (SearchQuery): The search query parameters including the search text,
                           domain, and query options. Required field.

        sortSpec (Optional[SortSpec]): Sorting parameters for results.
            If None, API defaults will be used (relevance-based sorting).

        groupSpec (Optional[GroupSpec]): Grouping parameters for results.
            If None, API defaults will be used (deep grouping with 10 groups).

        maxPassages (str): Maximum number of text passages per document.
            Valid range: 1-5. Default is "2".
            Passages are text snippets with highlighted search terms.

        region (str): Region code for localized results.
            Default is "225" for Russia.
            See Yandex Search API documentation for complete list of region codes:
            https://yandex.cloud/ru/docs/search-api/reference/regions

        l10n (Localization): Localization language for results.

        folderId (str): Yandex Cloud folder ID. Required field.
            This identifies your Yandex Cloud account and project.

        responseFormat (ResponseFormat): Response format from the API.
            Valid value: ResponseFormat.FORMAT_XML

    Example:
        ```python
        request: SearchRequest = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": "python programming",
                "familyMode": "FAMILY_MODE_MODERATE",
                "page": "0",
                "fixTypoMode": "FIX_TYPO_MODE_ON"
            },
            "sortSpec": {
                "sortMode": "SORT_MODE_BY_RELEVANCE",
                "sortOrder": "SORT_ORDER_DESC"
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_DEEP",
                "groupsOnPage": "10",
                "docsInGroup": "2"
            },
            "maxPassages": "2",
            "region": "225",
            "l10n": "LOCALIZATION_RU",
            "folderId": "your_folder_id",
            "responseFormat": "FORMAT_XML"
        }
        ```
    """

    query: SearchQuery
    sortSpec: NotRequired[SortSpec]
    groupSpec: NotRequired[GroupSpec]
    maxPassages: NotRequired[str]
    region: NotRequired[str]
    l10n: NotRequired[Localization]
    folderId: str
    responseFormat: ResponseFormat


# Response Models


class SearchResult(TypedDict):
    """
    Individual search result from the Yandex Search API.

    This TypedDict represents a single document in the search results,
    containing metadata about the document and relevant text passages.

    Fields:
        url (str): The full URL of the document. Required field.

        domain (str): The domain name of the document (e.g., "example.com").
                     Required field.

        title (str): The title of the document as displayed in search results.
                    Required field.

        passages (List[str]): List of text passages containing the search terms.
                            Passages include highlighted words marked with asterisks.
                            Required field, but may be empty list.

        modtime (Optional[str]): Last modification time of the document.
                                Format varies by source (Unix timestamp, ISO date, etc.).

        size (Optional[str]): Size of the document in human-readable format
                            (e.g., "15.2 KB", "1.5 MB").

        charset (Optional[str]): Character encoding of the document
                               (e.g., "utf-8", "windows-1251").

        mimetypes (Optional[List[str]]): List of MIME types for the document.
                                        Common values include "text/html", "application/pdf".

        hlwords (Optional[List[str]]): List of highlighted words from the search query.
                                      These are the terms that matched in the document.

    Example:
        ```python
        result: SearchResult = {
            "url": "https://example.com/python-tutorial",
            "domain": "example.com",
            "title": "Python Programming Tutorial",
            "passages": [
                "Learn *Python* programming with our comprehensive tutorial",
                "This *Python* guide covers all the basics"
            ],
            "modtime": "2023-05-15",
            "size": "25.3 KB",
            "charset": "utf-8",
            "mimetypes": ["text/html"],
            "hlwords": ["Python"]
        }
        ```
    """

    url: str
    domain: str
    title: str
    charset: NotRequired[str]
    lang: NotRequired[str]

    mimeType: NotRequired[str]
    savedCopyUrl: NotRequired[str]
    modtime: NotRequired[float]
    size: NotRequired[int]

    extendedText: NotRequired[str]

    passages: List[str]
    hlwords: NotRequired[List[str]]


SearchGroup: TypeAlias = List[SearchResult]


class ErrorResponse(TypedDict):
    """
    Error response structure from the Yandex Search API.

    This TypedDict represents an error response from the API, containing
    information about what went wrong during the search request.

    Fields:
        code (str): Machine-readable error code.
                  Common values include:
                  - "ERR_INVALID_REQUEST": Invalid request parameters
                  - "ERR_AUTH_FAILED": Authentication failed
                  - "ERR_RATE_LIMITED": Rate limit exceeded
                  - "ERR_INTERNAL_ERROR": Internal server error

        message (str): Human-readable error message describing the problem.
                      This message is suitable for display to end users.

        details (Optional[str]): Additional error details or context.
                               May include specific information about what
                               parameter caused the error or suggested fixes.

    Example:
        ```python
        error: ErrorResponse = {
            "code": "ERR_INVALID_REQUEST",
            "message": "Invalid search query",
            "details": "The query text is too short (minimum 3 characters)"
        }
        ```
    """

    code: str
    message: str


class SearchResponse(TypedDict):
    """
    Parsed XML response structure from the Yandex Search API.

    This TypedDict represents the complete response from a search request,
    including metadata about the search and the actual results. The response
    is parsed from the Base64-encoded XML returned by the API.

    Fields:
        requestId (str): Unique identifier for this search request.
                        Useful for debugging and tracking API calls.

        found (int): Total number of results found for the query.
                    This may be much larger than the number of results returned.

        foundHuman (str): Human-readable representation of the result count.
                         Examples: "About 1,234 results", "Найдено 567 результатов".

        page (int): Current page number (0-based) for paginated results.
                   Used with the page parameter in search requests.

        groups (List[SearchGroup]): List of search result groups.
                                  The number of groups is controlled by the
                                  groupsOnPage parameter in the search request.
                                  Required field, but may be empty list.

        error (Optional[Dict]): Error information if the search failed.
                               Contains error code, message, and details.
                               None if the search was successful.

    Example:
        ```python
        response: SearchResponse = {
            "requestId": "req-12345678-abcde",
            "found": 12345,
            "foundHuman": "Найдено 12 345 результатов",
            "page": 0,
            "groups": [
                {
                    "group": [
                        {
                            "url": "https://example.com/result1",
                            "domain": "example.com",
                            "title": "Search Result 1",
                            "passages": ["This is a *search* result"],
                            "hlwords": ["search"]
                        }
                    ]
                }
            ],
            "error": None
        }
        ```
    """

    requestId: str
    found: int
    foundHuman: str
    page: int
    groups: List[SearchGroup]
    error: NotRequired[ErrorResponse]
