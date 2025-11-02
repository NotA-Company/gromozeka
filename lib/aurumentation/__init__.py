"""Golden Data Testing System v2.

This package provides infrastructure for recording and replaying HTTP traffic
for testing purposes. It uses httpx transport layer patching to intercept
all HTTP recordings made by any httpx-based client.
"""

from .collector import collectGoldenData, sanitizeFilename
from .provider import GoldenDataProvider, findGoldenDataFiles, loadGoldenData
from .recorder import GoldenDataRecorder
from .replayer import GoldenDataReplayer
from .test_helpers import baseGoldenDataProvider, baseGoldenClient
from .types import (
    CollectorInputDict,
    GoldenDataScenarioDict,
    HttpCallDict,
    HttpRequestDict,
    HttpResponseDict,
    ScenarioDict,
    ScenarioInitKwargs,
)

__all__ = [
    # Collector functions
    "collectGoldenData",
    "sanitizeFilename",
    # Provider classes and functions
    "GoldenDataProvider",
    "findGoldenDataFiles",
    "loadGoldenData",
    # Recorder and replayer classes
    "GoldenDataRecorder",
    "GoldenDataReplayer",
    # Test helpers
    "baseGoldenClient",
    "baseGoldenDataProvider",
    # Data models
    "CollectorInputDict",
    "GoldenDataScenarioDict",
    "HttpCallDict",
    "HttpRequestDict",
    "HttpResponseDict",
    "ScenarioDict",
    "ScenarioInitKwargs",
]
