"""
TypedDicts for Yandex Search golden data structure.

This module defines TypedDicts that match the golden data structure
based on the actual data collected from Yandex Search API.
"""
from typing import Any, Dict, List, TypeAlias, TypedDict


class YandexSearchCallInfo(TypedDict):
    """Information about the API call made."""

    date: str
    method: str
    params: Dict[str, Any]


class YandexSearchRequestInfo(TypedDict):
    """Information about the HTTP request."""

    json: Dict[str, Any]


class YandexSearchResponseInfo(TypedDict):
    """Information about the HTTP response."""

    raw: str
    status_code: int


class YandexSearchGoldenDataEntry(TypedDict):
    """A single entry in the golden data file."""

    call: YandexSearchCallInfo
    request: YandexSearchRequestInfo
    response: YandexSearchResponseInfo


YandexSearchGoldenDataFile: TypeAlias = List[YandexSearchGoldenDataEntry]