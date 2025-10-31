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

from typing import Dict, List, Optional, TypedDict

# Request Models


class SearchQuery(TypedDict):
    """
    Search query parameters for the Yandex Search API.

    This TypedDict defines the structure for search query parameters,
    including the search text, domain, and various search options.

    Fields:
        searchType (str): Search domain identifier. Required field.
            Valid values:
            - SEARCH_TYPE_RU: Russian search (yandex.ru)
            - SEARCH_TYPE_TR: Turkish search (yandex.com.tr)
            - SEARCH_TYPE_COM: International search (yandex.com)
            - SEARCH_TYPE_KK: Kazakh search (yandex.kz)
            - SEARCH_TYPE_BE: Belarusian search (yandex.by)
            - SEARCH_TYPE_UZ: Uzbek search (yandex.uz)

        queryText (str): The actual search query text. Required field.
            Can contain any characters supported by the search engine.

        familyMode (Optional[str]): Family filter mode for content filtering.
            Valid values:
            - FAMILY_MODE_MODERATE: Moderate content filtering
            - FAMILY_MODE_STRICT: Strict content filtering
            - FAMILY_MODE_OFF: No content filtering

        page (Optional[str]): Page number for pagination (0-based).
            Used to navigate through search results. Default is "0".

        fixTypoMode (Optional[str]): Typo correction mode.
            Valid values:
            - FIX_TYPO_MODE_ON: Enable automatic typo correction
            - FIX_TYPO_MODE_OFF: Disable typo correction

    Example:
        ```python
        query: SearchQuery = {
            "searchType": "SEARCH_TYPE_RU",
            "queryText": "python programming tutorials",
            "familyMode": "FAMILY_MODE_MODERATE",
            "fixTypoMode": "FIX_TYPO_MODE_ON"
        }
        ```
    """

    searchType: str
    queryText: str
    familyMode: Optional[str]
    page: Optional[str]
    fixTypoMode: Optional[str]


class SortSpec(TypedDict):
    """
    Sorting parameters for search results.

    This TypedDict defines how search results should be sorted and ordered.
    All fields are optional - if not provided, the API defaults will be used.

    Fields:
        sortMode (Optional[str]): Sort mode for results.
            Valid values:
            - SORT_MODE_BY_RELEVANCE: Sort by relevance score (default)
            - SORT_MODE_BY_TIME: Sort by publication date
            - SORT_MODE_BY_PRIORITY: Sort by priority ranking

        sortOrder (Optional[str]): Sort order direction.
            Valid values:
            - SORT_ORDER_DESC: Descending order (highest first, default)
            - SORT_ORDER_ASC: Ascending order (lowest first)

    Example:
        ```python
        sort: SortSpec = {
            "sortMode": "SORT_MODE_BY_RELEVANCE",
            "sortOrder": "SORT_ORDER_DESC"
        }
        ```
    """

    sortMode: Optional[str]
    sortOrder: Optional[str]


class GroupSpec(TypedDict):
    """
    Grouping parameters for search results.

    This TypedDict defines how search results should be grouped and organized.
    Grouping helps organize related documents together, such as pages from
    the same website or different sections of the same document.

    Fields:
        groupMode (Optional[str]): Result grouping mode.
            Valid values:
            - GROUP_MODE_DEEP: Deep grouping with hierarchical structure (default)
            - GROUP_MODE_FLAT: Flat results without grouping

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

    groupMode: Optional[str]
    groupsOnPage: Optional[str]
    docsInGroup: Optional[str]


class SearchMetadata(TypedDict):
    """
    Search metadata and configuration flags.

    This TypedDict contains metadata that controls various aspects of the search
    operation, including response format, localization, and API configuration.

    Fields:
        maxPassages (Optional[str]): Maximum number of text passages per document.
            Valid range: 1-5. Default is "2".
            Passages are text snippets with highlighted search terms.

        region (Optional[str]): Region code for localized results.
            Default is "225" for Russia.
            See Yandex Search API documentation for complete list of region codes.

        l10n (Optional[str]): Localization language for results.
            Valid values:
            - LOCALIZATION_RU: Russian (default)
            - LOCALIZATION_EN: English
            - LOCALIZATION_TR: Turkish
            - And others based on supported languages

        folderId (str): Yandex Cloud folder ID. Required field.
            This identifies your Yandex Cloud account and project.

        responseFormat (Optional[str]): Response format from the API.
            Valid values:
            - FORMAT_XML: XML response format (default)
            - FORMAT_HTML: HTML response format

    Example:
        ```python
        metadata: SearchMetadata = {
            "folderId": "your_folder_id",
            "responseFormat": "FORMAT_XML",
            "maxPassages": "2",
            "region": "225",
            "l10n": "LOCALIZATION_RU"
        }
        ```
    """

    maxPassages: Optional[str]
    region: Optional[str]
    l10n: Optional[str]
    folderId: str
    responseFormat: Optional[str]


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
            See Yandex Search API documentation for complete list of region codes.

        l10n (str): Localization language for results.
            Valid values:
            - LOCALIZATION_RU: Russian (default)
            - LOCALIZATION_EN: English
            - LOCALIZATION_TR: Turkish
            - And others based on supported languages

        folderId (str): Yandex Cloud folder ID. Required field.
            This identifies your Yandex Cloud account and project.

        responseFormat (str): Response format from the API.
            Valid values:
            - FORMAT_XML: XML response format (default)
            - FORMAT_HTML: HTML response format

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
    sortSpec: Optional[SortSpec]
    groupSpec: Optional[GroupSpec]
    maxPassages: str
    region: str
    l10n: str
    folderId: str
    responseFormat: str


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
    passages: List[str]
    modtime: Optional[str]
    size: Optional[str]
    charset: Optional[str]
    mimetypes: Optional[List[str]]
    hlwords: Optional[List[str]]


class SearchGroup(TypedDict):
    """
    Group of related search results.

    This TypedDict represents a group of related documents, typically from
    the same website or about the same topic. Groups help organize search
    results and show multiple relevant pages from the same source together.

    Fields:
        group (List[SearchResult]): List of search results in this group.
                                  The number of results is controlled by the
                                  docsInGroup parameter in the search request.
                                  Required field, but may be empty list.

    Example:
        ```python
        group: SearchGroup = {
            "group": [
                {
                    "url": "https://example.com/page1",
                    "domain": "example.com",
                    "title": "Main Page",
                    "passages": ["Welcome to our *website*"],
                    "hlwords": ["website"]
                },
                {
                    "url": "https://example.com/page2",
                    "domain": "example.com",
                    "title": "About Us",
                    "passages": ["Learn more about our *company*"],
                    "hlwords": ["company"]
                }
            ]
        }
        ```
    """

    group: List[SearchResult]


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
    error: Optional[Dict]


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
    details: Optional[str]


# Authentication Models


class AuthConfig(TypedDict):
    """
    Authentication configuration for the Yandex Search API.

    This TypedDict contains the authentication credentials and configuration
    needed to access the Yandex Search API. Either an IAM token or API key
    must be provided, along with a folder ID.

    Fields:
        iamToken (Optional[str]): IAM token for authentication.
                                IAM tokens are temporary credentials that
                                can be automatically refreshed. Recommended
                                for production applications.
                                Obtain from Yandex Cloud IAM service.

        apiKey (Optional[str]): Static API key for authentication.
                              API keys are long-lived credentials suitable
                              for simple applications or testing.
                              Create in Yandex Cloud console.

        folderId (str): Yandex Cloud folder ID. Required field.
                       Identifies your Yandex Cloud account and project.
                       Find in Yandex Cloud console.

    Note:
        Either iamToken or apiKey must be provided, but not both.
        IAM tokens are preferred for production use as they provide
        better security and can be automatically rotated.

    Example:
        ```python
        # Using IAM token
        auth: AuthConfig = {
            "iamToken": "t1.9euel9q...",
            "folderId": "b1g8v1h2..."
        }

        # Using API key
        auth: AuthConfig = {
            "apiKey": "AQVN1...",
            "folderId": "b1g8v1h2..."
        }
        ```
    """

    iamToken: Optional[str]
    apiKey: Optional[str]
    folderId: str
