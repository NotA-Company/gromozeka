"""
Golden Data Provider for YandexSearchClient testing.

This module provides a GoldenDataProvider class that can patch the YandexSearchClient
to use golden data instead of making real API calls during testing.
"""

from .provider import GoldenDataProvider

# Export types
from .types import (
    YandexSearchCallInfo,
    YandexSearchGoldenDataEntry,
    YandexSearchGoldenDataFile,
    YandexSearchRequestInfo,
    YandexSearchResponseInfo,
)

__all__ = [
    "GoldenDataProvider",
    "YandexSearchCallInfo",
    "YandexSearchGoldenDataEntry",
    "YandexSearchGoldenDataFile",
    "YandexSearchRequestInfo",
    "YandexSearchResponseInfo",
]
