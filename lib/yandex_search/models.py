"""Comprehensive data models for Yandex Search API client integration.

This module defines TypedDict classes and enumerations that strictly conform to the
Yandex Search API v2 specification, providing type safety, comprehensive documentation,
and runtime compatibility for all data structures used throughout the client library.

Model Organization:
    - Request Models: Structures for API request parameters and configuration
    - Response Models: Structures for parsed API responses and results
    - Enumerations: Type-safe enums for API constants and options
    - Type Aliases: Convenient type aliases for complex structures

Design Philosophy:
    All models utilize TypedDict for runtime compatibility while maintaining
    static type checking support. This approach ensures that the code works
    correctly at runtime while providing excellent IDE support and type safety
    during development.

Example:
    Complete search request construction::

        request: SearchRequest = {
            "query": {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "python programming",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE
            },
            "sortSpec": {
                "sortMode": SortMode.SORT_MODE_BY_RELEVANCE,
                "sortOrder": SortOrder.SORT_ORDER_DESC
            },
            "groupSpec": {
                "groupMode": GroupMode.GROUP_MODE_DEEP,
                "groupsOnPage": "10",
                "docsInGroup": "2"
            },
            "maxPassages": "2",
            "region": "225",
            "l10n": Localization.LOCALIZATION_RU,
            "folderId": "your_folder_id",
            "responseFormat": ResponseFormat.FORMAT_XML
        }
"""

from enum import StrEnum
from typing import Dict, List, NotRequired, Optional, TypeAlias, TypedDict

# Request Models


class SearchType(StrEnum):
    """Enumeration of search domains for regional search targeting.

    This enum determines which Yandex search domain will be used for executing
    search queries, enabling region-specific search results and localization.

    Values:
        SEARCH_TYPE_RU: Russian search domain (yandex.ru)
            Targets Russian-language content and Russian regional results
        SEARCH_TYPE_TR: Turkish search domain (yandex.com.tr)
            Targets Turkish-language content and Turkish regional results
        SEARCH_TYPE_COM: International search domain (yandex.com)
            Targets global English-language content and international results
        SEARCH_TYPE_KK: Kazakh search domain (yandex.kz)
            Targets Kazakh-language content and Kazakhstan regional results
        SEARCH_TYPE_BE: Belarusian search domain (yandex.by)
            Targets Belarusian-language content and Belarus regional results
        SEARCH_TYPE_UZ: Uzbek search domain (yandex.uz)
            Targets Uzbek-language content and Uzbekistan regional results
    """

    SEARCH_TYPE_RU = "SEARCH_TYPE_RU"
    SEARCH_TYPE_TR = "SEARCH_TYPE_TR"
    SEARCH_TYPE_COM = "SEARCH_TYPE_COM"
    SEARCH_TYPE_KK = "SEARCH_TYPE_KK"
    SEARCH_TYPE_BE = "SEARCH_TYPE_BE"
    SEARCH_TYPE_UZ = "SEARCH_TYPE_UZ"


class FamilyMode(StrEnum):
    """Content filtering levels for family-safe search results.

    This enum controls the level of content filtering applied to search results,
    determining what types of content should be excluded based on family safety
    requirements.

    Values:
        FAMILY_MODE_UNSPECIFIED: Use API default filtering behavior
            Delegates content filtering decisions to the API's default settings
        FAMILY_MODE_MODERATE: Moderate content filtering
            Filters explicit content while allowing most general content
        FAMILY_MODE_STRICT: Strict content filtering
            Applies comprehensive filtering for maximum family safety
        FAMILY_MODE_OFF: No content filtering
            Disables all content filtering, showing all available results
    """

    FAMILY_MODE_UNSPECIFIED = "FAMILY_MODE_UNSPECIFIED"
    FAMILY_MODE_MODERATE = "FAMILY_MODE_MODERATE"
    FAMILY_MODE_STRICT = "FAMILY_MODE_STRICT"
    FAMILY_MODE_OFF = "FAMILY_MODE_OFF"


class FixTypoMode(StrEnum):
    """Automatic typo correction modes for search queries.

    This enum controls whether the search engine should automatically detect and
    correct typographical errors in search queries to improve result relevance.

    Values:
        FIX_TYPO_MODE_UNSPECIFIED: Use API default typo correction behavior
            Delegates typo correction decisions to the API's default settings
        FIX_TYPO_MODE_ON: Enable automatic typo correction
            Automatically detects and corrects common typos in search queries
        FIX_TYPO_MODE_OFF: Disable automatic typo correction
            Searches exactly as typed without any automatic corrections
    """

    FIX_TYPO_MODE_UNSPECIFIED = "FIX_TYPO_MODE_UNSPECIFIED"
    FIX_TYPO_MODE_ON = "FIX_TYPO_MODE_ON"
    FIX_TYPO_MODE_OFF = "FIX_TYPO_MODE_OFF"


class SearchQuery(TypedDict):
    """Core search query parameters for Yandex Search API requests.

    This TypedDict defines the essential structure for search query parameters,
    encompassing the search text, domain selection, and fundamental search options
    that control how the query is processed and filtered.

    Attributes:
        searchType (SearchType): Search domain identifier determining which
            Yandex search domain to use. This is a required field.
        queryText (str): The actual search query text to be processed.
            Can contain any characters supported by the search engine.
            This is a required field.
        familyMode (Optional[FamilyMode]): Content filtering level for
            family-safe search results. Controls content filtering behavior.
        page (Optional[str]): Page number for pagination (0-based indexing).
            Used to navigate through multi-page search results.
            Default is "0" for the first page.
        fixTypoMode (Optional[FixTypoMode]): Automatic typo correction mode.
            Determines whether the search engine should correct typos.

    Example:
        Basic search query configuration::

            query: SearchQuery = {
                "searchType": SearchType.SEARCH_TYPE_RU,
                "queryText": "python programming tutorials",
                "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON
            }
    """

    searchType: SearchType
    queryText: str
    familyMode: Optional[FamilyMode]
    page: Optional[str]
    fixTypoMode: Optional[FixTypoMode]


class SortMode(StrEnum):
    """Sorting criteria for search result ordering.

    This enum determines the primary sorting method used to order search results,
    affecting how results are ranked and presented to the user.

    Values:
        SORT_MODE_UNSPECIFIED: Use API default sorting behavior
            Delegates sorting decisions to the API's default relevance algorithm
        SORT_MODE_BY_RELEVANCE: Sort by relevance score
            Orders results based on relevance to the search query (default)
        SORT_MODE_BY_TIME: Sort by document update time
            Orders results by when documents were last modified or published
    """

    SORT_MODE_UNSPECIFIED = "SORT_MODE_UNSPECIFIED"
    SORT_MODE_BY_RELEVANCE = "SORT_MODE_BY_RELEVANCE"
    SORT_MODE_BY_TIME = "SORT_MODE_BY_TIME"


class SortOrder(StrEnum):
    """Sort direction for ordered search results.

    This enum controls the direction of sorting when combined with SortMode,
    determining whether results are presented in ascending or descending order.

    Values:
        SORT_ORDER_UNSPECIFIED: Use API default sort direction
            Delegates sort direction to the API's default behavior
        SORT_ORDER_ASC: Ascending order (oldest to newest)
            Presents results from oldest to most recent
        SORT_ORDER_DESC: Descending order (newest to oldest)
            Presents results from most recent to oldest (default)
    """

    SORT_ORDER_UNSPECIFIED = "SORT_ORDER_UNSPECIFIED"
    SORT_ORDER_ASC = "SORT_ORDER_ASC"
    SORT_ORDER_DESC = "SORT_ORDER_DESC"


class SortSpec(TypedDict):
    """Sorting configuration for search result ordering.

    This TypedDict defines the sorting parameters that control how search results
    are ordered and presented. All fields are optional - if not provided, the API
    will apply its default sorting behavior (typically relevance-based descending).

    Attributes:
        sortMode (NotRequired[SortMode]): Primary sorting criteria for results.
            Determines what aspect of the documents to sort by (relevance, time, etc.).
        sortOrder (NotRequired[SortOrder]): Sort direction for the results.
            Controls whether results are ordered ascending or descending.

    Example:
        Relevance-based descending sort::

            sort: SortSpec = {
                "sortMode": SortMode.SORT_MODE_BY_RELEVANCE,
                "sortOrder": SortOrder.SORT_ORDER_DESC
            }

        Time-based ascending sort::

            sort: SortSpec = {
                "sortMode": SortMode.SORT_MODE_BY_TIME,
                "sortOrder": SortOrder.SORT_ORDER_ASC
            }
    """

    sortMode: NotRequired[SortMode]
    sortOrder: NotRequired[SortOrder]


class GroupMode(StrEnum):
    """Grouping method."""

    GROUP_MODE_UNSPECIFIED = "GROUP_MODE_UNSPECIFIED"
    GROUP_MODE_FLAT = "GROUP_MODE_FLAT"  # Flat grouping. Each group contains a single document.
    GROUP_MODE_DEEP = "GROUP_MODE_DEEP"  # Grouping by domain. Each group contains documents from one domain.


class GroupSpec(TypedDict):
    """Grouping configuration for organizing search results.

    This TypedDict defines parameters that control how search results are grouped
    and organized, helping to cluster related documents together for better
    user experience and result presentation.

    Attributes:
        groupMode (NotRequired[GroupMode]): Primary grouping strategy for results.
            Determines how documents should be clustered together.
        groupsOnPage (NotRequired[str]): Number of result groups per page.
            Valid range: 1-100. Default is "10".
            Each group may contain multiple documents depending on the grouping mode.
        docsInGroup (NotRequired[str]): Maximum documents per group.
            Valid range: 1-10. Default is "2".
            Controls how many related documents are shown together in each group.

    Example:
        Deep grouping with custom limits::

            group: GroupSpec = {
                "groupMode": GroupMode.GROUP_MODE_DEEP,
                "groupsOnPage": "10",
                "docsInGroup": "2"
            }

        Flat grouping with single documents::

            group: GroupSpec = {
                "groupMode": GroupMode.GROUP_MODE_FLAT,
                "groupsOnPage": "20"
            }
    """

    groupMode: NotRequired[GroupMode]
    groupsOnPage: NotRequired[str]
    docsInGroup: NotRequired[str]


class Localization(StrEnum):
    """Interface language settings for search response localization.

    This enum determines the language used for interface elements, notifications,
    and response formatting in the search results, affecting how metadata and
    system messages are presented to the user.

    Values:
        LOCALIZATION_UNSPECIFIED: Use API default language
            Delegates language selection to the API's default behavior
        LOCALIZATION_RU: Russian language interface
            Russian language for all interface elements and messages (default)
        LOCALIZATION_UK: Ukrainian language interface
            Ukrainian language for interface elements and messages
        LOCALIZATION_BE: Belarusian language interface
            Belarusian language for interface elements and messages
        LOCALIZATION_KK: Kazakh language interface
            Kazakh language for interface elements and messages
        LOCALIZATION_TR: Turkish language interface
            Turkish language for interface elements and messages
        LOCALIZATION_EN: English language interface
            English language for interface elements and messages
    """

    LOCALIZATION_UNSPECIFIED = "LOCALIZATION_UNSPECIFIED"
    LOCALIZATION_RU = "LOCALIZATION_RU"
    LOCALIZATION_UK = "LOCALIZATION_UK"
    LOCALIZATION_BE = "LOCALIZATION_BE"
    LOCALIZATION_KK = "LOCALIZATION_KK"
    LOCALIZATION_TR = "LOCALIZATION_TR"
    LOCALIZATION_EN = "LOCALIZATION_EN"


class ResponseFormat(StrEnum):
    """Output format options for search response data.

    This enum specifies the format in which the search API should return response
    data, affecting how results are structured and parsed by the client.

    Values:
        FORMAT_UNSPECIFIED: Use API default response format
            Delegates format selection to the API's default behavior
        FORMAT_XML: XML response format
            Structured XML format that can be parsed into TypedDict models (default)
        FORMAT_HTML: HTML response format
            HTML format intended for direct display (not supported by this client)
    """

    FORMAT_UNSPECIFIED = "FORMAT_UNSPECIFIED"
    FORMAT_XML = "FORMAT_XML"
    FORMAT_HTML = "FORMAT_HTML"


class SearchRequest(TypedDict):
    """Comprehensive search request structure for Yandex Search API integration.

    This TypedDict consolidates all components of a search request into a unified
    structure that can be serialized and transmitted to the API. It encompasses
    query parameters, sorting options, grouping settings, and essential metadata
    fields as required by the API specification.

    Attributes:
        query (SearchQuery): Core search query parameters including search text,
            domain selection, and fundamental query options. This is a required field.
        sortSpec (NotRequired[SortSpec]): Sorting configuration for results.
            If omitted, API defaults will be applied (relevance-based sorting).
        groupSpec (NotRequired[GroupSpec]): Grouping configuration for results.
            If omitted, API defaults will be used (deep grouping with 10 groups).
        maxPassages (NotRequired[str]): Maximum text passages per document.
            Valid range: 1-5. Default is "2".
            Passages are text snippets with highlighted search terms for context.
        region (NotRequired[str]): Region code for localized search results.
            Default is "225" for Russia.
            Reference: https://yandex.cloud/ru/docs/search-api/reference/regions
        l10n (NotRequired[Localization]): Interface language for response localization.
            Controls language of system messages and metadata.
        folderId (str): Yandex Cloud folder identifier. Required field.
            Uniquely identifies your Yandex Cloud account and project.
        responseFormat (NotRequired[ResponseFormat]): Desired response format.
            Only ResponseFormat.FORMAT_XML is supported by this client.
        metadata (NotRequired[Dict[str, str]]): Search flags as key:value pairs.
            Maximum 64 pairs. Values: max 63 chars, must match [-_0-9a-z]*.
            Keys: 1-63 chars, must match [a-z][-_0-9a-z]*.

    Example:
        Complete search request with all parameters::

            request: SearchRequest = {
                "query": {
                    "searchType": SearchType.SEARCH_TYPE_RU,
                    "queryText": "python programming",
                    "familyMode": FamilyMode.FAMILY_MODE_MODERATE,
                    "page": "0",
                    "fixTypoMode": FixTypoMode.FIX_TYPO_MODE_ON
                },
                "sortSpec": {
                    "sortMode": SortMode.SORT_MODE_BY_RELEVANCE,
                    "sortOrder": SortOrder.SORT_ORDER_DESC
                },
                "groupSpec": {
                    "groupMode": GroupMode.GROUP_MODE_DEEP,
                    "groupsOnPage": "10",
                    "docsInGroup": "2"
                },
                "maxPassages": "2",
                "region": "225",
                "l10n": Localization.LOCALIZATION_RU,
                "folderId": "your_folder_id",
                "responseFormat": ResponseFormat.FORMAT_XML
            }
    """

    query: SearchQuery
    sortSpec: NotRequired[SortSpec]
    groupSpec: NotRequired[GroupSpec]
    maxPassages: NotRequired[str]
    region: NotRequired[str]
    l10n: NotRequired[Localization]
    folderId: str
    responseFormat: ResponseFormat
    metadata: NotRequired[Dict[str, str]]


# Response Models


class SearchResult(TypedDict):
    """Individual search result document from Yandex Search API.

    This TypedDict represents a single document within the search results,
    containing comprehensive metadata about the document and relevant text
    passages that highlight the search terms.

    Attributes:
        url (str): Complete URL of the document. Required field.
        domain (str): Domain name of the document source (e.g., "example.com").
            Required field.
        title (str): Document title as displayed in search results.
            Required field.
        passages (List[str]): Text passages containing search terms with highlighting.
            Highlighted words are marked with asterisks. Required field, may be empty.
        charset (NotRequired[str]): Character encoding of the document.
            Examples: "utf-8", "windows-1251", "iso-8859-1".
        lang (NotRequired[str]): Language code of the document content.
            Examples: "ru", "en", "tr".
        mimeType (NotRequired[str]): MIME type of the document.
            Examples: "text/html", "application/pdf", "image/jpeg".
        savedCopyUrl (NotRequired[str]): URL to saved copy or cached version.
            Provides access to archived or cached document versions.
        modtime (NotRequired[float]): Last modification timestamp.
            Unix timestamp format (seconds since epoch).
        size (NotRequired[int]): Document size in bytes.
            Integer value representing total file size.
        extendedText (NotRequired[str]): Additional extended text or description.
            May contain summaries or additional document metadata.
        hlwords (NotRequired[List[str]]): Highlighted words from search query.
            List of terms that matched and were highlighted in the document.

    Example:
        Complete search result with all available fields::

            result: SearchResult = {
                "url": "https://example.com/python-tutorial",
                "domain": "example.com",
                "title": "Python Programming Tutorial",
                "passages": [
                    "Learn *Python* programming with our comprehensive tutorial",
                    "This *Python* guide covers all the basics"
                ],
                "modtime": 1684147200.0,
                "size": 25984,
                "charset": "utf-8",
                "lang": "en",
                "mimeType": "text/html",
                "hlwords": ["Python", "programming"]
            }
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
    """Error response structure for Yandex Search API failures.

    This TypedDict represents standardized error responses from the API,
    providing structured information about what went wrong during search
    request processing and helping with debugging and error handling.

    Attributes:
        code (str): Machine-readable error code for programmatic handling.
            Common error codes include:
            - "ERR_INVALID_REQUEST": Invalid request parameters or structure
            - "ERR_AUTH_FAILED": Authentication or authorization failure
            - "ERR_RATE_LIMITED": Rate limit exceeded or throttled
            - "ERR_INTERNAL_ERROR": Internal server error or service issue
        message (str): Human-readable error description.
            Suitable for display to end users or logging purposes.
            Provides clear explanation of what went wrong.

    Example:
        Authentication error response::

            error: ErrorResponse = {
                "code": "ERR_AUTH_FAILED",
                "message": "Invalid authentication credentials"
            }

        Parameter validation error::

            error: ErrorResponse = {
                "code": "ERR_INVALID_REQUEST",
                "message": "Invalid search query parameters"
            }
    """

    code: str
    message: str


class SearchResponse(TypedDict):
    """Complete parsed response structure from Yandex Search API.

    This TypedDict represents the full response structure from a search request,
    encompassing search metadata, result statistics, and the actual search results.
    The response is parsed from the Base64-encoded XML data returned by the API.

    Attributes:
        requestId (str): Unique identifier for this specific search request.
            Essential for debugging, tracking, and support inquiries.
        found (int): Total number of results found for the query.
            May significantly exceed the number of results actually returned.
        foundHuman (str): Human-readable formatted result count.
            Localized string examples: "About 1,234 results", "Найдено 567 результатов".
        page (int): Current page number in paginated results (0-based indexing).
            Corresponds to the page parameter used in the search request.
        groups (List[SearchGroup]): List of search result groups.
            Number of groups controlled by groupsOnPage parameter.
            Required field, but may be empty list if no results found.
        error (NotRequired[ErrorResponse]): Error information for failed searches.
            Contains structured error data if search failed, None if successful.

    Example:
        Successful search response with results::

            response: SearchResponse = {
                "requestId": "req-12345678-abcde",
                "found": 12345,
                "foundHuman": "Найдено 12 345 результатов",
                "page": 0,
                "groups": [
                    [
                        {
                            "url": "https://example.com/result1",
                            "domain": "example.com",
                            "title": "Search Result 1",
                            "passages": ["This is a *search* result"],
                            "hlwords": ["search"]
                        }
                    ]
                ]
            }

        Error response::

            response: SearchResponse = {
                "requestId": "req-87654321-fedcba",
                "found": 0,
                "foundHuman": "No results found",
                "page": 0,
                "groups": [],
                "error": {
                    "code": "ERR_INVALID_REQUEST",
                    "message": "Invalid search query"
                }
            }
    """

    requestId: str
    found: int
    foundHuman: str
    page: int
    groups: List[SearchGroup]
    error: NotRequired[ErrorResponse]
