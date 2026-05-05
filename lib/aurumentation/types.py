"""Data models for Golden Data Testing System v2.

This module defines the core data structures used for capturing,
storing, and replaying HTTP traffic in the golden data testing system.

The module provides TypedDict definitions for:
- Collector input formats
- Scenario definitions and initialization parameters
- HTTP request/response recording structures
- Golden data file formats for test scenarios
"""

from typing import Any, Dict, List, NotRequired, Optional, Union

from typing_extensions import TypedDict


class CollectorInputDict(TypedDict):
    """TypedDict for collector input format.

    Attributes:
        description: A human-readable description of the collector input.
        kwargs: Dictionary of keyword arguments to be passed to the collector.
    """

    description: str
    kwargs: Dict[str, Any]


class ScenarioInitKwargs(TypedDict, total=False):
    """TypedDict for scenario initialization keyword arguments.

    Attributes:
        apiKey: API key for authentication with external services.
        cache: Optional cache instance for storing intermediate results.
        geocodingTTL: Time-to-live for geocoding cache entries in seconds.
        weatherTTL: Time-to-live for weather data cache entries in seconds.
    """

    apiKey: str
    cache: Optional[Any]
    geocodingTTL: int
    weatherTTL: int


ScenarioDict = TypedDict(
    "ScenarioDict",
    {
        "name": str,
        "description": str,
        "module": str,
        "class": str,  # Can't be declared via class syntax
        "method": str,
        "init_kwargs": NotRequired[Dict[str, Any]],
        "kwargs": Dict[str, Any],
    },
)
"""TypedDict for a complete scenario definition.

Attributes:
    name: Unique identifier for the scenario.
    description: Human-readable description of what the scenario tests.
    module: Python module path containing the scenario class.
    class: Name of the scenario class to instantiate.
    method: Name of the method to execute for the scenario.
    init_kwargs: Optional keyword arguments for class initialization.
    kwargs: Keyword arguments to pass to the scenario method.
"""


MetadataDict = TypedDict(
    "MetadataDict",
    {
        "name": str,
        "description": str,
        "module": str,
        "class": str,  # Can't be declared via class syntax
        "method": str,
        "init_kwargs": Dict[str, Any],
        "kwargs": Dict[str, Any],
        "createdAt": NotRequired[str],
        "result_type": NotRequired[str],
    },
)
"""TypedDict for metadata structure.

Attributes:
    name: Unique identifier for the test scenario.
    description: Human-readable description of the test scenario.
    module: Python module path containing the test class.
    class: Name of the test class.
    method: Name of the test method.
    init_kwargs: Keyword arguments used for class initialization.
    kwargs: Keyword arguments passed to the test method.
    createdAt: Optional ISO 8601 timestamp of when the test was created.
    result_type: Optional type identifier for the test result.
"""


class GoldenDataFormat(TypedDict):
    """TypedDict for the golden data file format.

    Attributes:
        metadata: Metadata describing the test scenario and configuration.
        recordings: List of recorded HTTP interactions as dictionaries.
    """

    metadata: MetadataDict
    recordings: List[Dict[str, Any]]


class HttpRequestDict(TypedDict):
    """TypedDict for HTTP request details captured during recording.

    Attributes:
        method: HTTP method (e.g., GET, POST, PUT, DELETE).
        url: Full URL of the HTTP request.
        headers: Dictionary of HTTP request headers.
        params: Optional query parameters as a dictionary mapping parameter names
            to either string values or lists of strings for multi-value parameters.
        body: Optional request body as a string, or None if no body.
    """

    method: str
    url: str
    headers: Dict[str, str]
    params: NotRequired[Dict[str, Union[str, List[str]]]]
    body: NotRequired[Optional[str]]


class HttpResponseDict(TypedDict):
    """TypedDict for HTTP response details captured during recording.

    Attributes:
        status_code: HTTP status code (e.g., 200, 404, 500).
        headers: Dictionary of HTTP response headers.
        content: Response body content as a string.
    """

    status_code: int
    headers: Dict[str, str]
    content: str


class HttpCallDict(TypedDict):
    """TypedDict for complete HTTP call with request, response, and timestamp.

    Attributes:
        request: HTTP request details including method, URL, headers, and body.
        response: HTTP response details including status code, headers, and content.
        timestamp: ISO 8601 timestamp of when the HTTP call was made.
    """

    request: HttpRequestDict
    response: HttpResponseDict
    timestamp: str


class GoldenDataFileFormat(TypedDict):
    """TypedDict for the complete golden data file format.

    Attributes:
        metadata: Metadata describing the test scenario and configuration.
        recordings: List of complete HTTP call recordings with request, response,
            and timestamp information.
    """

    metadata: MetadataDict
    recordings: List[HttpCallDict]


class GoldenDataScenarioDict(TypedDict):
    """TypedDict for complete test scenario with metadata.

    Attributes:
        name: Unique identifier for the test scenario.
        description: Human-readable description of the test scenario.
        functionName: Name of the function being tested.
        metadata: Detailed metadata about the test scenario configuration.
        recordings: List of HTTP call recordings captured during test execution.
        createdAt: ISO 8601 timestamp of when the test scenario was created.
    """

    name: str
    description: str
    functionName: str
    metadata: MetadataDict
    recordings: List[HttpCallDict]
    createdAt: str
