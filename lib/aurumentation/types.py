"""Data models for Golden Data Testing System v2.

This module defines the core data structures used for capturing,
storing, and replaying HTTP traffic in the golden data testing system.
"""

from typing import Any, Dict, List, NotRequired, Optional, Union

from typing_extensions import TypedDict


class CollectorInputDict(TypedDict):
    """TypedDict for collector input format."""

    description: str
    kwargs: Dict[str, Any]


class ScenarioInitKwargs(TypedDict, total=False):
    """TypedDict for scenario initialization keyword arguments."""

    apiKey: str
    cache: Optional[Any]
    geocodingTTL: int
    weatherTTL: int


ScenarioDict = TypedDict(
    "ScenarioDict",
    {
        "description": str,
        "module": str,
        "class": str,
        "method": str,
        "init_kwargs": NotRequired[Dict[str, Any]],
        "kwargs": Dict[str, Any],
    },
)
"""TypedDict for a complete scenario definition."""


MetadataDict = TypedDict(
    "MetadataDict",
    {
        "description": str,
        "module": str,
        "class": str,
        "method": str,
        "init_kwargs": Dict[str, Any],
        "kwargs": Dict[str, Any],
        "createdAt": str,
        "result_type": NotRequired[str],
    },
    total=False,
)
"""TypedDict for metadata structure."""


class GoldenDataFormat(TypedDict):
    """TypedDict for the golden data file format."""

    metadata: MetadataDict
    recordings: List[Dict[str, Any]]


class HttpRequestDict(TypedDict):
    """TypedDict for HTTP request details captured during recording."""

    method: str
    url: str
    headers: Dict[str, str]
    params: NotRequired[Dict[str, Union[str, List[str]]]]
    body: NotRequired[Optional[str]]


class HttpResponseDict(TypedDict):
    """TypedDict for HTTP response details captured during recording."""

    status_code: int
    headers: Dict[str, str]
    content: str


class HttpCallDict(TypedDict):
    """TypedDict for complete HTTP call with request, response, and timestamp."""

    request: HttpRequestDict
    response: HttpResponseDict
    timestamp: str


class GoldenDataFileFormat(TypedDict):
    """TypedDict for the complete golden data file format."""

    metadata: MetadataDict
    recordings: List[HttpCallDict]


class GoldenDataScenarioDict(TypedDict):
    """TypedDict for complete test scenario with metadata."""

    description: str
    functionName: str
    metadata: MetadataDict
    recordings: List[HttpCallDict]
    createdAt: str
