"""Golden Data Testing System v2.

This package provides infrastructure for recording and replaying HTTP traffic
for testing purposes. It uses httpx transport layer patching to intercept
all HTTP recordings made by any httpx-based client.
"""

from .collector import collectGoldenData, sanitizeFilename
from .provider import GoldenDataProvider, findGoldenDataFiles, loadGoldenData
from .recorder import GoldenDataRecorder
from .replayer import GoldenDataReplayer
from .test_helpers import goldenClient, goldenDataProvider, useGoldenData
from .types import (
    CollectorInput,
    GoldenDataScenario,
    HttpCall,
    HttpRequest,
    HttpResponse,
)
