"""
TypedDicts for OpenWeatherMap golden data structure.

This module defines TypedDicts that match the golden data structure
based on the actual data collected from OpenWeatherMap API.
"""

from typing import Any, Dict, List, TypeAlias, TypedDict

from typing_extensions import NotRequired


class CallInfo(TypedDict):
    """Information about the API call made."""

    date: str
    method: str
    params: Dict[str, Any]


class RequestInfo(TypedDict):
    """Information about the HTTP request."""

    params: Dict[str, str]
    url: str


class ResponseInfo(TypedDict):
    """Information about the HTTP response."""

    json: NotRequired[Any]
    raw: str
    status_code: int


class GoldenDataEntry(TypedDict):
    """A single entry in the golden data file."""

    call: CallInfo
    request: RequestInfo
    response: ResponseInfo


GoldenDataFile: TypeAlias = List[GoldenDataEntry]
