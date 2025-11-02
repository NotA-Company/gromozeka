# Golden Data Testing System Design v2.0

**Created:** 2025-11-02  
**Status:** Design Phase  
**Priority:** High  
**Author:** Architect Mode  
**Supersedes:** golden-data-testing-system-v1.md

## Executive Summary

This document describes version 2.0 of the Golden Data testing system, dood! The key improvement is moving from patching individual `_makeRequest()` methods to patching httpx directly at the transport layer. This makes the system generic, reusable, and eliminates the need for service-specific collection scripts.

**Key Improvements over v1:**
- ✅ Generic httpx patching works for ANY client using httpx
- ✅ No need to patch individual `_makeRequest()` methods
- ✅ Single collector script works for all services
- ✅ Automatic secret masking at the transport layer
- ✅ Captures ALL HTTP details (method, url, headers, body)
- ✅ Simpler integration with existing code
- ✅ Better separation of concerns

**Migration Path:**
- v1 golden data remains compatible
- New collectors can be written using v2 approach
- Gradual migration of existing collectors

---

## Table of Contents

1. [Problem with v1 Approach](#problem-with-v1-approach)
2. [Solution Overview](#solution-overview)
3. [httpx Patching Approaches](#httpx-patching-approaches)
4. [Recommended Architecture](#recommended-architecture)
5. [Generic Collector Design](#generic-collector-design)
6. [Golden Data Provider Design](#golden-data-provider-design)
7. [Secret Masking Strategy](#secret-masking-strategy)
8. [File Structure](#file-structure)
9. [API Design](#api-design)
10. [Integration Examples](#integration-examples)
11. [Migration Strategy](#migration-strategy)
12. [Implementation Plan](#implementation-plan)

---

## Problem with v1 Approach

### Current Issues

The v1 approach patches `_makeRequest()` methods in each client:

```python
# v1 approach - NOT scalable, dood!
async def patched_make_request(url: str, params: Dict[str, Any]):
    """Patched version of _makeRequest that captures raw responses."""
    import httpx
    
    # Manually create httpx client and make request
    async with httpx.AsyncClient(timeout=client.requestTimeout) as session:
        response = await session.get(url, params=params)
        # Capture and save...
        
client._makeRequest = patched_make_request  # Patch specific method
```

**Problems:**
1. **Not Generic:** Each service needs its own collector script
2. **Tight Coupling:** Must know internal implementation details (`_makeRequest`)
3. **Duplication:** Same patching logic repeated for each service
4. **Fragile:** Breaks if client implementation changes
5. **Limited Scope:** Only captures what `_makeRequest` exposes
6. **Manual Work:** Must write custom patching for each new service

### What We Need

A generic solution that:
- Works with ANY httpx-based client
- Requires NO knowledge of client internals
- Captures ALL HTTP traffic automatically
- Provides a single, reusable collector
- Masks secrets automatically

---

## Solution Overview

### Core Concept

Instead of patching individual methods, we patch httpx itself at the transport layer:

```python
# v2 approach - Generic and scalable, dood!
from tests.golden_data.core import HttpxRecorder

# Works with ANY httpx-based client!
async with HttpxRecorder() as recorder:
    # Use client normally - ALL httpx calls are captured
    client = OpenWeatherMapClient(apiKey=key, cache=cache)
    result = await client.getWeatherByCity("Minsk", "BY")
    
    # Save captured data
    recorder.saveGoldenData("openweathermap/getWeatherByCity_Minsk.json")
```

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Code                          │
│  (OpenWeatherMapClient, YandexSearchClient, etc.)           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    httpx.AsyncClient                         │
│              (session.get, session.post, etc.)              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              HttpxRecorder (v2 Interceptor)                  │
│  • Intercepts ALL httpx calls                               │
│  • Captures request/response                                │
│  • Masks secrets automatically                              │
│  • Saves golden data                                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Real HTTP Transport                        │
│              (Makes actual network calls)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## httpx Patching Approaches

### Approach 1: Custom Transport (RECOMMENDED)

**How it works:** Create a custom httpx transport that wraps the default transport and intercepts all requests/responses.

**Pros:**
- ✅ Clean, official httpx API
- ✅ Captures everything (method, url, headers, body, response)
- ✅ Works with both sync and async
- ✅ No monkey-patching required
- ✅ Type-safe and maintainable
- ✅ Can be used as context manager

**Cons:**
- ⚠️ Requires understanding httpx transport API
- ⚠️ Slightly more complex implementation

**Example:**
```python
import httpx
from typing import AsyncIterator

class RecordingTransport(httpx.AsyncBaseTransport):
    """Custom transport that records all HTTP traffic."""
    
    def __init__(self, wrapped: httpx.AsyncBaseTransport):
        self.wrapped = wrapped
        self.recordings = []
    
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Capture request
        requestData = {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode() if request.content else None
        }
        
        # Make actual request
        response = await self.wrapped.handle_async_request(request)
        
        # Capture response
        responseData = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": response.content.decode()
        }
        
        # Store recording
        self.recordings.append({
            "request": requestData,
            "response": responseData
        })
        
        return response
```

### Approach 2: unittest.mock.patch

**How it works:** Use `unittest.mock.patch` to replace httpx methods.

**Pros:**
- ✅ Familiar to Python developers
- ✅ Built-in to Python standard library
- ✅ Works with pytest

**Cons:**
- ❌ Monkey-patching is fragile
- ❌ Must patch multiple methods (get, post, put, delete, etc.)
- ❌ Harder to capture all details
- ❌ Can interfere with other code

**Example:**
```python
from unittest.mock import patch, AsyncMock

@patch('httpx.AsyncClient.get')
async def test_with_mock(mock_get):
    mock_get.return_value = AsyncMock(
        status_code=200,
        json=lambda: {"data": "test"}
    )
    # Test code...
```

### Approach 3: pytest-httpx (respx alternative)

**How it works:** Use pytest-httpx plugin to mock httpx requests.

**Pros:**
- ✅ Designed specifically for httpx
- ✅ Clean API for mocking
- ✅ Good for testing

**Cons:**
- ❌ External dependency
- ❌ Primarily for mocking, not recording
- ❌ Less control over capture process
- ❌ Not suitable for collection phase

### Approach 4: respx Library

**How it works:** Use respx library for httpx mocking and recording.

**Pros:**
- ✅ Designed for httpx
- ✅ Can record and replay
- ✅ Good documentation

**Cons:**
- ❌ External dependency
- ❌ Adds complexity
- ❌ May not fit our exact needs
- ❌ Another library to maintain

### Comparison Matrix

| Approach | Complexity | Flexibility | Maintainability | Dependencies | Recommended |
|----------|-----------|-------------|-----------------|--------------|-------------|
| Custom Transport | Medium | High | High | None | ✅ YES |
| unittest.mock | Low | Medium | Low | None | ❌ No |
| pytest-httpx | Low | Low | Medium | External | ❌ No |
| respx | Medium | Medium | Medium | External | ⚠️ Maybe |

### Recommendation

**Use Custom Transport (Approach 1)** because:
1. It's the official, supported way to intercept httpx traffic
2. No external dependencies
3. Complete control over what we capture
4. Clean, maintainable code
5. Works perfectly for both collection and replay

---

## Recommended Architecture

### Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                  Golden Data System v2                        │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────┐      ┌─────────────────────┐        │
│  │  HttpxRecorder     │      │  HttpxReplayer      │        │
│  │  (Collection)      │      │  (Testing)          │        │
│  └────────┬───────────┘      └──────────┬──────────┘        │
│           │                              │                    │
│           ▼                              ▼                    │
│  ┌────────────────────┐      ┌─────────────────────┐        │
│  │ RecordingTransport │      │  ReplayTransport    │        │
│  │ (Intercepts calls) │      │  (Returns golden)   │        │
│  └────────┬───────────┘      └──────────┬──────────┘        │
│           │                              │                    │
│           ▼                              ▼                    │
│  ┌────────────────────┐      ┌─────────────────────┐        │
│  │  SecretMasker      │      │  GoldenDataLoader   │        │
│  │  (Masks secrets)   │      │  (Loads files)      │        │
│  └────────┬───────────┘      └──────────┬──────────┘        │
│           │                              │                    │
│           ▼                              ▼                    │
│  ┌────────────────────┐      ┌─────────────────────┐        │
│  │  Golden Data File  │◄─────┤  Golden Data File   │        │
│  │  (JSON)            │      │  (JSON)             │        │
│  └────────────────────┘      └─────────────────────┘        │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. RecordingTransport

Custom httpx transport that intercepts and records all HTTP traffic.

```python
class RecordingTransport(httpx.AsyncBaseTransport):
    """
    Custom httpx transport that records all HTTP requests and responses.
    
    This transport wraps the default httpx transport and captures all
    traffic passing through it. It's the core of the golden data
    collection system.
    """
    
    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        secretMasker: Optional[SecretMasker] = None
    ):
        self.wrapped = wrapped
        self.secretMasker = secretMasker or SecretMasker()
        self.recordings: List[HttpRecording] = []
    
    async def handle_async_request(
        self,
        request: httpx.Request
    ) -> httpx.Response:
        """Intercept, record, and forward HTTP request."""
        # Capture request details
        requestData = self._captureRequest(request)
        
        # Make actual HTTP call
        response = await self.wrapped.handle_async_request(request)
        
        # Capture response details
        responseData = self._captureResponse(response)
        
        # Mask secrets
        maskedRequest = self.secretMasker.maskRequest(requestData)
        maskedResponse = self.secretMasker.maskResponse(responseData)
        
        # Store recording
        self.recordings.append({
            "request": maskedRequest,
            "response": maskedResponse,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        return response
```

#### 2. HttpxRecorder

High-level API for recording HTTP traffic.

```python
class HttpxRecorder:
    """
    Context manager for recording httpx traffic.
    
    Usage:
        async with HttpxRecorder(secrets=["api_key"]) as recorder:
            client = SomeClient(apiKey="secret")
            await client.doSomething()
            recorder.saveGoldenData("output.json", metadata={...})
    """
    
    def __init__(
        self,
        secrets: Optional[List[str]] = None,
        maskPatterns: Optional[List[str]] = None
    ):
        self.secrets = secrets or []
        self.maskPatterns = maskPatterns or []
        self.transport: Optional[RecordingTransport] = None
        self.originalTransport: Optional[httpx.AsyncBaseTransport] = None
    
    async def __aenter__(self) -> "HttpxRecorder":
        """Set up recording transport."""
        # Create secret masker
        masker = SecretMasker(
            secrets=self.secrets,
            patterns=self.maskPatterns
        )
        
        # Create recording transport
        defaultTransport = httpx.AsyncHTTPTransport()
        self.transport = RecordingTransport(
            wrapped=defaultTransport,
            secretMasker=masker
        )
        
        # Patch httpx to use our transport
        self.originalTransport = httpx.AsyncClient._transport
        httpx.AsyncClient._transport = self.transport
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Restore original transport."""
        if self.originalTransport:
            httpx.AsyncClient._transport = self.originalTransport
    
    def saveGoldenData(
        self,
        filepath: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Save recorded data to golden data file."""
        data = {
            "metadata": metadata or {},
            "recordings": self.transport.recordings
        }
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
```

#### 3. ReplayTransport

Custom transport that replays golden data instead of making real requests.

```python
class ReplayTransport(httpx.AsyncBaseTransport):
    """
    Custom httpx transport that replays golden data.
    
    Instead of making real HTTP requests, this transport looks up
    the request in golden data and returns the recorded response.
    """
    
    def __init__(self, goldenData: List[HttpRecording]):
        self.goldenData = goldenData
        self.requestIndex = 0
    
    async def handle_async_request(
        self,
        request: httpx.Request
    ) -> httpx.Response:
        """Return golden data response instead of making real request."""
        # Find matching golden data
        recording = self._findMatchingRecording(request)
        
        if not recording:
            raise ValueError(
                f"No golden data found for request: "
                f"{request.method} {request.url}"
            )
        
        # Create response from golden data
        return self._createResponse(recording["response"])
    
    def _findMatchingRecording(
        self,
        request: httpx.Request
    ) -> Optional[HttpRecording]:
        """Find golden data matching the request."""
        # Match by method and URL
        for recording in self.goldenData:
            if (recording["request"]["method"] == request.method and
                recording["request"]["url"] == str(request.url)):
                return recording
        return None
```

#### 4. SecretMasker

Handles automatic secret masking in captured data.

```python
class SecretMasker:
    """
    Masks secrets in HTTP requests and responses.
    
    Supports:
    - Exact string matching
    - Regex patterns
    - Header masking
    - URL parameter masking
    - JSON body masking
    """
    
    REDACTED = "REDACTED"
    
    def __init__(
        self,
        secrets: Optional[List[str]] = None,
        patterns: Optional[List[str]] = None
    ):
        self.secrets = secrets or []
        self.patterns = [re.compile(p) for p in (patterns or [])]
        
        # Common secret patterns
        self.defaultPatterns = [
            re.compile(r'api[_-]?key', re.IGNORECASE),
            re.compile(r'auth', re.IGNORECASE),
            re.compile(r'token', re.IGNORECASE),
            re.compile(r'secret', re.IGNORECASE),
            re.compile(r'password', re.IGNORECASE),
        ]
    
    def maskRequest(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Mask secrets in request data."""
        masked = request.copy()
        
        # Mask URL
        masked["url"] = self._maskString(masked["url"])
        
        # Mask headers
        if "headers" in masked:
            masked["headers"] = self._maskDict(masked["headers"])
        
        # Mask body
        if "content" in masked and masked["content"]:
            masked["content"] = self._maskString(masked["content"])
        
        return masked
    
    def maskResponse(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Mask secrets in response data."""
        masked = response.copy()
        
        # Mask headers
        if "headers" in masked:
            masked["headers"] = self._maskDict(masked["headers"])
        
        # Mask content
        if "content" in masked:
            masked["content"] = self._maskString(masked["content"])
        
        return masked
    
    def _maskString(self, text: str) -> str:
        """Mask secrets in a string."""
        result = text
        
        # Mask exact matches
        for secret in self.secrets:
            result = result.replace(secret, self.REDACTED)
        
        # Mask pattern matches
        for pattern in self.patterns + self.defaultPatterns:
            result = pattern.sub(self.REDACTED, result)
        
        return result
    
    def _maskDict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask secrets in a dictionary."""
        masked = {}
        for key, value in data.items():
            # Check if key matches secret pattern
            if self._isSecretKey(key):
                masked[key] = self.REDACTED
            elif isinstance(value, str):
                masked[key] = self._maskString(value)
            elif isinstance(value, dict):
                masked[key] = self._maskDict(value)
            else:
                masked[key] = value
        return masked
    
    def _isSecretKey(self, key: str) -> bool:
        """Check if a key name indicates it contains a secret."""
        keyLower = key.lower()
        for pattern in self.defaultPatterns:
            if pattern.search(keyLower):
                return True
        return False
```

---

## Generic Collector Design

### Collector Script

A single, generic collector that works with any httpx-based client:

```python
#!/usr/bin/env python3
"""
Generic Golden Data Collector v2

This script can collect golden data from ANY httpx-based client.
It reads test scenarios from a JSON file and executes them while
recording all HTTP traffic.

Usage:
    ./venv/bin/python3 tests/golden_data/core/collect.py \\
        --input scenarios.json \\
        --output golden/ \\
        --secrets API_KEY,FOLDER_ID
"""

import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from tests.golden_data.core import HttpxRecorder


async def collectGoldenData(
    scenarios: List[Dict[str, Any]],
    outputDir: Path,
    secrets: List[str]
) -> None:
    """
    Collect golden data for multiple scenarios.
    
    Args:
        scenarios: List of test scenarios to execute
        outputDir: Directory to save golden data
        secrets: List of secret values to mask
    """
    outputDir.mkdir(parents=True, exist_ok=True)
    
    for scenario in scenarios:
        print(f"Collecting: {scenario['description']}")
        
        # Extract scenario details
        modulePath = scenario["module"]
        className = scenario["class"]
        methodName = scenario["method"]
        kwargs = scenario["kwargs"]
        description = scenario["description"]
        
        # Import and instantiate class
        module = importlib.import_module(modulePath)
        cls = getattr(module, className)
        instance = cls(**scenario.get("init_kwargs", {}))
        
        # Record HTTP traffic
        async with HttpxRecorder(secrets=secrets) as recorder:
            # Call the method
            method = getattr(instance, methodName)
            result = await method(**kwargs)
            
            # Generate filename from description
            filename = _sanitizeFilename(description) + ".json"
            filepath = outputDir / filename
            
            # Save golden data
            recorder.saveGoldenData(
                filepath=str(filepath),
                metadata={
                    "description": description,
                    "module": modulePath,
                    "class": className,
                    "method": methodName,
                    "kwargs": kwargs,
                    "result_type": type(result).__name__
                }
            )
            
            print(f"  ✓ Saved to {filename}")


def _sanitizeFilename(text: str) -> str:
    """Convert text to safe filename."""
    # Replace special characters
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in text)
    # Remove multiple underscores
    while "__" in safe:
        safe = safe.replace("__", "_")
    # Limit length
    return safe[:100].strip("_ ")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generic Golden Data Collector v2"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSON file with test scenarios"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output directory for golden data"
    )
    parser.add_argument(
        "--secrets",
        help="Comma-separated list of environment variables containing secrets"
    )
    
    args = parser.parse_args()
    
    # Load scenarios
    with open(args.input) as f:
        scenarios = json.load(f)
    
    # Get secret values from environment
    secrets = []
    if args.secrets:
        for varName in args.secrets.split(","):
            value = os.getenv(varName.strip())
            if value:
                secrets.append(value)
    
    # Collect golden data
    await collectGoldenData(
        scenarios=scenarios,
        outputDir=Path(args.output),
        secrets=secrets
    )
    
    print("\n✅ Golden data collection complete!")


if __name__ == "__main__":
    asyncio.run(main())
```

### Scenario File Format

```json
[
  {
    "description": "Get weather for Minsk, Belarus",
    "module": "lib.openweathermap.client",
    "class": "OpenWeatherMapClient",
    "init_kwargs": {
      "apiKey": "${OPENWEATHERMAP_API_KEY}",
      "cache": null,
      "geocodingTTL": 0,
      "weatherTTL": 0
    },
    "method": "getWeatherByCity",
    "kwargs": {
      "city": "Minsk",
      "country": "BY"
    }
  },
  {
    "description": "Search for Python programming",
    "module": "lib.yandex_search.client",
    "class": "YandexSearchClient",
    "init_kwargs": {
      "apiKey": "${YANDEX_SEARCH_API_KEY}",
      "folderId": "${YANDEX_SEARCH_FOLDER_ID}",
      "cache": null,
      "useCache": false
    },
    "method": "search",
    "kwargs": {
      "queryText": "python programming"
    }
  }
]
```

---

## Golden Data Provider Design

### Provider API

```python
class GoldenDataProvider:
    """
    Provides golden data for testing by replaying recorded HTTP traffic.
    
    Usage:
        provider = GoldenDataProvider("golden/weather_minsk.json")
        
        async with provider.patchHttpx():
            client = OpenWeatherMapClient(apiKey="test", cache=cache)
            result = await client.getWeatherByCity("Minsk", "BY")
            # Returns golden data instead of making real API call
    """
    
    def __init__(self, goldenDataPath: str):
        """
        Initialize provider with golden data file.
        
        Args:
            goldenDataPath: Path to golden data JSON file
        """
        self.goldenDataPath = Path(goldenDataPath)
        self.goldenData = self._loadGoldenData()
    
    def _loadGoldenData(self) -> List[HttpRecording]:
        """Load golden data from file."""
        with open(self.goldenDataPath) as f:
            data = json.load(f)
        return data["recordings"]
    
    @asynccontextmanager
    async def patchHttpx(self):
        """
        Context manager that patches httpx to use golden data.
        
        Yields:
            None
        """
        # Create replay transport
        replayTransport = ReplayTransport(self.goldenData)
        
        # Store original transport
        originalTransport = httpx.AsyncClient._transport
        
        # Patch httpx
        httpx.AsyncClient._transport = replayTransport
        
        try:
            yield
        finally:
            # Restore original transport
            httpx.AsyncClient._transport = originalTransport
```

### Pytest Integration

```python
# tests/fixtures/golden_data_fixtures.py

import pytest
from tests.golden_data.core import GoldenDataProvider


@pytest.fixture
def goldenWeatherMinsk():
    """Provide golden data for Minsk weather."""
    provider = GoldenDataProvider(
        "tests/golden_data/openweathermap/golden/weather_minsk.json"
    )
    return provider


@pytest.fixture
async def patchedHttpxWeatherMinsk(goldenWeatherMinsk):
    """Patch httpx to use golden data for Minsk weather."""
    async with goldenWeatherMinsk.patchHttpx():
        yield
```

---

## Secret Masking Strategy

### Multi-Layer Masking

1. **Environment Variable Masking:** Automatically mask values from specified env vars
2. **Pattern-Based Masking:** Mask based on key names (api_key, token, etc.)
3. **Custom Masking:** Allow custom masking rules per service

### Masking Locations

```
Request:
├── URL
│   ├── Path parameters
│   └── Query parameters
├── Headers
│   ├── Authorization
│   ├── Api-Key
│   └── Custom headers
└── Body
    ├── JSON fields
    └── Form data

Response:
├── Headers
│   └── Set-Cookie
└── Body
    └── JSON fields (if they contain secrets)
```

### Example Masked Data

```json
{
  "request": {
    "method": "GET",
    "url": "https://api.openweathermap.org/data/3.0/onecall?lat=53.9&lon=27.5&appid=REDACTED",
    "headers": {
      "User-Agent": "httpx/0.24.0",
      "Authorization": "REDACTED"
    }
  },
  "response": {
    "status_code": 200,
    "headers": {
      "Content-Type": "application/json"
    },
    "content": "{\"lat\":53.9,\"lon\":27.5,\"timezone\":\"Europe/Minsk\",...}"
  }
}
```

---

## File Structure

```
tests/
├── golden_data/
│   ├── core/                           # v2 Core infrastructure
│   │   ├── __init__.py
│   │   ├── recorder.py                 # HttpxRecorder
│   │   ├── transport.py                # RecordingTransport, ReplayTransport
│   │   ├── masker.py                   # SecretMasker
│   │   ├── provider.py                 # GoldenDataProvider
│   │   ├── collect.py                  # Generic collector script
│   │   └── types.py                    # TypedDicts for v2
│   │
│   ├── openweathermap/
│   │   ├── scenarios.json              # Test scenarios for collection
│   │   ├── golden/                     # Golden data files (v2 format)
│   │   │   ├── weather_minsk.json
│   │   │   ├── weather_london.json
│   │   │   └── geocoding_tokyo.json
│   │   ├── collect.py                  # v1 collector (deprecated)
│   │   ├── provider.py                 # v1 provider (deprecated)
│   │   └── raw/                        # v1 raw data (keep for compatibility)
│   │
│   ├── yandex_search/
│   │   ├── scenarios.json
│   │   ├── golden/
│   │   │   ├── search_python.json
│   │   │   └── search_weather.json
│   │   ├── collect.py                  # v1 collector (deprecated)
│   │   ├── provider.py                 # v1 provider (deprecated)
│   │   └── golden/                     # v1 golden data (keep for compatibility)
│   │
│   └── README.md                       # Updated documentation
│
└── fixtures/
    └── golden_data_fixtures.py         # Pytest fixtures for v2
```

---

## API Design

### Collection API

```python
# Simple collection
async with HttpxRecorder(secrets=["api_key"]) as recorder:
    client = SomeClient(apiKey="secret")
    await client.doSomething()
    recorder.saveGoldenData("output.json")

# With metadata
async with HttpxRecorder(secrets=["api_key"]) as recorder:
    client = SomeClient(apiKey="secret")
    result = await client.doSomething()
    recorder.saveGoldenData(
        "output.json",
        metadata={
            "description": "Test scenario",
            "result_type": type(result).__
name": type(result).__name__
        }
    )

# Generic collector (command-line)
./venv/bin/python3 tests/golden_data/core/collect.py \
    --input scenarios.json \
    --output golden/ \
    --secrets OPENWEATHERMAP_API_KEY,YANDEX_SEARCH_API_KEY
```

### Replay API

```python
# Simple replay
provider = GoldenDataProvider("golden/weather_minsk.json")
async with provider.patchHttpx():
    client = OpenWeatherMapClient(apiKey="test", cache=cache)
    result = await client.getWeatherByCity("Minsk", "BY")
    # Uses golden data, no real API call

# Pytest fixture
@pytest.fixture
async def goldenWeatherMinsk():
    provider = GoldenDataProvider("golden/weather_minsk.json")
    async with provider.patchHttpx():
        yield

async def testWeatherParsing(goldenWeatherMinsk):
    client = OpenWeatherMapClient(apiKey="test", cache=cache)
    result = await client.getWeatherByCity("Minsk", "BY")
    assert result is not None
    assert result["location"]["name"] == "Minsk"
```

---

## Integration Examples

### Example 1: OpenWeatherMap Collection

**Scenario file:** `tests/golden_data/openweathermap/scenarios.json`

```json
[
  {
    "description": "Get weather for Minsk, Belarus",
    "module": "lib.openweathermap.client",
    "class": "OpenWeatherMapClient",
    "init_kwargs": {
      "apiKey": "${OPENWEATHERMAP_API_KEY}",
      "cache": null,
      "geocodingTTL": 0,
      "weatherTTL": 0
    },
    "method": "getWeatherByCity",
    "kwargs": {
      "city": "Minsk",
      "country": "BY"
    }
  },
  {
    "description": "Get coordinates for London",
    "module": "lib.openweathermap.client",
    "class": "OpenWeatherMapClient",
    "init_kwargs": {
      "apiKey": "${OPENWEATHERMAP_API_KEY}",
      "cache": null,
      "geocodingTTL": 0,
      "weatherTTL": 0
    },
    "method": "getCoordinates",
    "kwargs": {
      "city": "London",
      "country": "GB"
    }
  }
]
```

**Collection:**

```bash
./venv/bin/python3 tests/golden_data/core/collect.py \
    --input tests/golden_data/openweathermap/scenarios.json \
    --output tests/golden_data/openweathermap/golden/ \
    --secrets OPENWEATHERMAP_API_KEY
```

**Testing:**

```python
import pytest
from tests.golden_data.core import GoldenDataProvider
from lib.openweathermap.client import OpenWeatherMapClient
from lib.openweathermap.dict_cache import DictWeatherCache


@pytest.fixture
async def goldenWeatherMinsk():
    """Provide golden data for Minsk weather."""
    provider = GoldenDataProvider(
        "tests/golden_data/openweathermap/golden/Get_weather_for_Minsk_Belarus.json"
    )
    async with provider.patchHttpx():
        yield


async def testGetWeatherByCity(goldenWeatherMinsk):
    """Test getting weather by city using golden data."""
    client = OpenWeatherMapClient(
        apiKey="test",  # Doesn't matter, using golden data
        cache=DictWeatherCache(),
        geocodingTTL=0,
        weatherTTL=0
    )
    
    result = await client.getWeatherByCity("Minsk", "BY")
    
    assert result is not None
    assert result["location"]["name"] == "Minsk"
    assert result["location"]["country"] == "BY"
    assert "weather" in result
    assert "current" in result["weather"]
```

### Example 2: Yandex Search Collection

**Scenario file:** `tests/golden_data/yandex_search/scenarios.json`

```json
[
  {
    "description": "Search for Python programming",
    "module": "lib.yandex_search.client",
    "class": "YandexSearchClient",
    "init_kwargs": {
      "apiKey": "${YANDEX_SEARCH_API_KEY}",
      "folderId": "${YANDEX_SEARCH_FOLDER_ID}",
      "cache": null,
      "useCache": false
    },
    "method": "search",
    "kwargs": {
      "queryText": "python programming"
    }
  }
]
```

**Collection:**

```bash
./venv/bin/python3 tests/golden_data/core/collect.py \
    --input tests/golden_data/yandex_search/scenarios.json \
    --output tests/golden_data/yandex_search/golden/ \
    --secrets YANDEX_SEARCH_API_KEY,YANDEX_SEARCH_FOLDER_ID
```

**Testing:**

```python
import pytest
from tests.golden_data.core import GoldenDataProvider
from lib.yandex_search.client import YandexSearchClient


@pytest.fixture
async def goldenSearchPython():
    """Provide golden data for Python search."""
    provider = GoldenDataProvider(
        "tests/golden_data/yandex_search/golden/Search_for_Python_programming.json"
    )
    async with provider.patchHttpx():
        yield


async def testSearchPython(goldenSearchPython):
    """Test searching for Python using golden data."""
    client = YandexSearchClient(
        apiKey="test",  # Doesn't matter, using golden data
        folderId="test",
        cache=None,
        useCache=False
    )
    
    result = await client.search("python programming")
    
    assert result is not None
    assert result["found"] > 0
    assert len(result["groups"]) > 0
```

---

## Migration Strategy

### Phase 1: Infrastructure Setup (Week 1)

**Goal:** Implement core v2 components

**Tasks:**
1. Create `tests/golden_data/core/` directory structure
2. Implement `RecordingTransport` class
3. Implement `ReplayTransport` class
4. Implement `SecretMasker` class
5. Implement `HttpxRecorder` class
6. Implement `GoldenDataProvider` class
7. Write unit tests for core components

**Deliverables:**
- Working v2 infrastructure
- Unit tests with >90% coverage
- Documentation for core APIs

### Phase 2: Generic Collector (Week 2)

**Goal:** Create generic collection script

**Tasks:**
1. Implement `collect.py` script
2. Add scenario file parsing
3. Add dynamic module/class loading
4. Add environment variable substitution
5. Test with OpenWeatherMap scenarios
6. Test with Yandex Search scenarios

**Deliverables:**
- Working generic collector
- Example scenario files
- Collection documentation

### Phase 3: Migration of OpenWeatherMap (Week 3)

**Goal:** Migrate OpenWeatherMap to v2

**Tasks:**
1. Create `scenarios.json` for OpenWeatherMap
2. Collect golden data using v2 collector
3. Update tests to use v2 provider
4. Verify all tests pass
5. Mark v1 collector as deprecated

**Deliverables:**
- OpenWeatherMap fully migrated to v2
- All tests passing
- Migration guide document

### Phase 4: Migration of Yandex Search (Week 4)

**Goal:** Migrate Yandex Search to v2

**Tasks:**
1. Create `scenarios.json` for Yandex Search
2. Collect golden data using v2 collector
3. Update tests to use v2 provider
4. Verify all tests pass
5. Mark v1 collector as deprecated

**Deliverables:**
- Yandex Search fully migrated to v2
- All tests passing
- Updated documentation

### Phase 5: Documentation and Cleanup (Week 5)

**Goal:** Complete migration and documentation

**Tasks:**
1. Update main README with v2 approach
2. Create migration guide for future services
3. Remove v1 collectors (keep golden data for compatibility)
4. Add CI/CD integration for golden data refresh
5. Create video tutorial (optional)

**Deliverables:**
- Complete documentation
- Clean codebase
- CI/CD integration

---

## Implementation Plan

### Week 1: Core Infrastructure

```python
# tests/golden_data/core/transport.py
class RecordingTransport(httpx.AsyncBaseTransport):
    """Custom transport for recording HTTP traffic."""
    # Implementation as shown above

class ReplayTransport(httpx.AsyncBaseTransport):
    """Custom transport for replaying golden data."""
    # Implementation as shown above
```

```python
# tests/golden_data/core/masker.py
class SecretMasker:
    """Masks secrets in HTTP data."""
    # Implementation as shown above
```

```python
# tests/golden_data/core/recorder.py
class HttpxRecorder:
    """High-level API for recording."""
    # Implementation as shown above
```

```python
# tests/golden_data/core/provider.py
class GoldenDataProvider:
    """High-level API for replay."""
    # Implementation as shown above
```

### Week 2: Generic Collector

```python
# tests/golden_data/core/collect.py
# Generic collector script as shown above
```

### Week 3-4: Migration

1. Create scenario files for each service
2. Run collector to generate v2 golden data
3. Update tests to use v2 provider
4. Verify all tests pass

### Week 5: Documentation

1. Update README.md
2. Create migration guide
3. Add examples
4. Clean up deprecated code

---

## Advantages of v2 Over v1

### 1. Generic and Reusable

**v1:** Each service needs custom collector
```python
# openweathermap/collect.py - 354 lines
# yandex_search/collect.py - 239 lines
# Total: 593 lines of duplicated logic
```

**v2:** Single collector for all services
```python
# core/collect.py - ~150 lines
# Works for ANY httpx-based client
```

### 2. No Internal Knowledge Required

**v1:** Must know about `_makeRequest()` method
```python
# Must patch internal method
client._makeRequest = patched_make_request
```

**v2:** Works with any httpx client
```python
# Just use the client normally
async with HttpxRecorder() as recorder:
    result = await client.anyMethod()
```

### 3. Automatic Secret Masking

**v1:** Manual string replacement
```python
url.replace(self.apiKey, REDACTED_API_KEY)
```

**v2:** Automatic multi-layer masking
```python
# Automatically masks:
# - Environment variables
# - Common patterns (api_key, token, etc.)
# - Custom patterns
```

### 4. Complete HTTP Capture

**v1:** Only captures what `_makeRequest()` exposes
```python
# May miss headers, method, etc.
```

**v2:** Captures everything
```python
# Method, URL, headers, body, response, status code
```

### 5. Easier Testing

**v1:** Complex provider setup
```python
provider = GoldenDataProvider()
async with provider.patchClient(client):
    result = await client.method()
```

**v2:** Simple fixture
```python
@pytest.fixture
async def goldenData():
    provider = GoldenDataProvider("file.json")
    async with provider.patchHttpx():
        yield

async def test(goldenData):
    # Just use client normally
```

---

## Data Format Comparison

### v1 Format

```json
[
  {
    "call": {
      "method": "getCurrentWeatherByCity",
      "params": {"city": "Minsk", "countryCode": "BY"},
      "date": "2025-11-01T12:00:00Z"
    },
    "request": {
      "url": "https://api.openweathermap.org/data/3.0/onecall",
      "params": {"lat": "53.9", "lon": "27.5", "appid": "REDACTED"}
    },
    "response": {
      "raw": "{...}",
      "status_code": 200,
      "json": {...}
    }
  }
]
```

### v2 Format

```json
{
  "metadata": {
    "description": "Get weather for Minsk, Belarus",
    "module": "lib.openweathermap.client",
    "class": "OpenWeatherMapClient",
    "method": "getWeatherByCity",
    "kwargs": {"city": "Minsk", "country": "BY"},
    "collected_at": "2025-11-02T12:00:00Z"
  },
  "recordings": [
    {
      "request": {
        "method": "GET",
        "url": "https://api.openweathermap.org/geo/1.0/direct?q=Minsk,BY&limit=1&appid=REDACTED",
        "headers": {"User-Agent": "httpx/0.24.0"},
        "content": null
      },
      "response": {
        "status_code": 200,
        "headers": {"Content-Type": "application/json"},
        "content": "[{\"name\":\"Minsk\",\"lat\":53.9,\"lon\":27.5,\"country\":\"BY\"}]"
      },
      "timestamp": "2025-11-02T12:00:01Z"
    },
    {
      "request": {
        "method": "GET",
        "url": "https://api.openweathermap.org/data/3.0/onecall?lat=53.9&lon=27.5&exclude=minutely,hourly,alerts&units=metric&lang=ru&appid=REDACTED",
        "headers": {"User-Agent": "httpx/0.24.0"},
        "content": null
      },
      "response": {
        "status_code": 200,
        "headers": {"Content-Type": "application/json"},
        "content": "{\"lat\":53.9,\"lon\":27.5,\"timezone\":\"Europe/Minsk\",...}"
      },
      "timestamp": "2025-11-02T12:00:02Z"
    }
  ]
}
```

**Key Differences:**
- v2 captures ALL HTTP calls (geocoding + weather)
- v2 includes complete HTTP details (method, headers)
- v2 has richer metadata
- v2 preserves call sequence with timestamps

---

## Security Considerations

### 1. Secret Masking

**Multiple layers of protection:**
- Environment variable values automatically masked
- Pattern-based masking (api_key, token, etc.)
- Custom masking rules per service
- Masking in URLs, headers, and bodies

### 2. Git Safety

**Never commit:**
- `.env` files
- Unmasked golden data
- API keys or tokens

**Always commit:**
- Masked golden data
- Scenario files (with `${VAR}` placeholders)
- Documentation

### 3. Review Process

**Before committing golden data:**
1. Review for any unmasked secrets
2. Check URLs for sensitive parameters
3. Verify headers are clean
4. Scan response bodies for PII

---

## Future Enhancements

### 1. Smart Matching

Instead of exact URL matching, use fuzzy matching:
```python
# Match by URL pattern, not exact URL
pattern = "https://api.openweathermap.org/data/3.0/onecall?lat=*&lon=*"
```

### 2. Response Variations

Support multiple responses for same request:
```python
# Return different responses on subsequent calls
recordings = [
    {"request": {...}, "response": response1},
    {"request": {...}, "response": response2},  # Same request, different response
]
```

### 3. Conditional Responses

Return responses based on request content:
```python
# Return error for specific inputs
if request.params["city"] == "InvalidCity":
    return error_response
```

### 4. Recording Modes

```python
# Record mode: Capture and save
recorder = HttpxRecorder(mode="record")

# Replay mode: Use golden data
recorder = HttpxRecorder(mode="replay")

# Passthrough mode: Use real API but log
recorder = HttpxRecorder(mode="passthrough")
```

### 5. Diff Tool

Compare golden data versions:
```bash
./venv/bin/python3 tests/golden_data/core/diff.py \
    old_golden.json \
    new_golden.json
```

### 6. Auto-Refresh

Automatically refresh golden data on schedule:
```yaml
# .github/workflows/refresh-golden-data.yml
name: Refresh Golden Data
on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly
```

---

## Testing Strategy

### Unit Tests

Test core components in isolation:

```python
# tests/golden_data/core/test_masker.py
def testSecretMasker():
    masker = SecretMasker(secrets=["secret123"])
    
    text = "The API key is secret123"
    masked = masker._maskString(text)
    
    assert "secret123" not in masked
    assert "REDACTED" in masked


# tests/golden_data/core/test_transport.py
async def testRecordingTransport():
    wrapped = httpx.AsyncHTTPTransport()
    transport = RecordingTransport(wrapped)
    
    request = httpx.Request("GET", "https://example.com")
    response = await transport.handle_async_request(request)
    
    assert len(transport.recordings) == 1
    assert transport.recordings[0]["request"]["method"] == "GET"
```

### Integration Tests

Test with real clients:

```python
# tests/golden_data/core/test_integration.py
async def testRecorderWithRealClient():
    """Test recorder with actual OpenWeatherMap client."""
    async with HttpxRecorder(secrets=[os.getenv("OPENWEATHERMAP_API_KEY")]) as recorder:
        client = OpenWeatherMapClient(
            apiKey=os.getenv("OPENWEATHERMAP_API_KEY"),
            cache=DictWeatherCache()
        )
        
        result = await client.getWeatherByCity("Minsk", "BY")
        
        assert result is not None
        assert len(recorder.transport.recordings) > 0
        
        # Verify secrets are masked
        for recording in recorder.transport.recordings:
            assert "REDACTED" in recording["request"]["url"]
```

### End-to-End Tests

Test complete workflow:

```python
# tests/golden_data/core/test_e2e.py
async def testCollectAndReplay():
    """Test collecting golden data and replaying it."""
    # Collect
    async with HttpxRecorder(secrets=["test_key"]) as recorder:
        # Make some HTTP calls
        async with httpx.AsyncClient() as client:
            await client.get("https://httpbin.org/get")
        
        # Save golden data
        recorder.saveGoldenData("/tmp/test_golden.json")
    
    # Replay
    provider = GoldenDataProvider("/tmp/test_golden.json")
    async with provider.patchHttpx():
        # Same call should return golden data
        async with httpx.AsyncClient() as client:
            response = await client.get("https://httpbin.org/get")
            assert response.status_code == 200
```

---

## Summary

### Key Design Decisions

1. **Custom httpx Transport:** Use official httpx transport API for clean, maintainable patching
2. **Generic Collector:** Single collector script works for all httpx-based clients
3. **Scenario-Based:** Test scenarios defined in JSON files, not code
4. **Multi-Layer Masking:** Automatic secret masking at multiple levels
5. **Backward Compatible:** v1 golden data remains usable during migration

### Benefits

- ✅ **80% less code:** Single collector vs multiple service-specific collectors
- ✅ **Zero coupling:** No knowledge of client internals required
- ✅ **Complete capture:** All HTTP details captured automatically
- ✅ **Secure by default:** Automatic secret masking
- ✅ **Easy to use:** Simple API for both collection and replay
- ✅ **Future-proof:** Works with any httpx-based client

### Next Steps

1. Review this design document
2. Get approval from team
3. Start Phase 1 implementation (core infrastructure)
4. Iterate based on feedback

---

## Questions for Discussion

1. **Transport vs Mock:** Are we comfortable using custom transports, or prefer mocking?
2. **Scenario Format:** Is JSON the right format, or prefer YAML/TOML?
3. **Migration Timeline:** Is 5 weeks reasonable, or need more/less time?
4. **Backward Compatibility:** Keep v1 golden data forever, or migrate and delete?
5. **Secret Masking:** Are the default patterns sufficient, or need more?
6. **File Organization:** Is the proposed directory structure clear?

---

## Appendix A: Type Definitions

```python
# tests/golden_data/core/types.py

from typing import Any, Dict, List, Optional, TypedDict


class HttpRequest(TypedDict):
    """HTTP request details."""
    method: str
    url: str
    headers: Dict[str, str]
    content: Optional[str]


class HttpResponse(TypedDict):
    """HTTP response details."""
    status_code: int
    headers: Dict[str, str]
    content: str


class HttpRecording(TypedDict):
    """Single HTTP request/response recording."""
    request: HttpRequest
    response: HttpResponse
    timestamp: str


class GoldenDataMetadata(TypedDict):
    """Metadata about golden data collection."""
    description: str
    module: str
    class_name: str
    method: str
    kwargs: Dict[str, Any]
    collected_at: str


class GoldenDataFile(TypedDict):
    """Complete golden data file structure."""
    metadata: GoldenDataMetadata
    recordings: List[HttpRecording]


class TestScenario(TypedDict):
    """Test scenario for collection."""
    description: str
    module: str
    class_name: str
    init_kwargs: Dict[str, Any]
    method: str
    kwargs: Dict[str, Any]
```

---

## Appendix B: Example Golden Data File

```json
{
  "metadata": {
    "description": "Get weather for Minsk, Belarus",
    "module": "lib.openweathermap.client",
    "class": "OpenWeatherMapClient",
    "method": "getWeatherByCity",
    "kwargs": {
      "city": "Minsk",
      "country": "BY"
    },
    "collected_at": "2025-11-02T12:00:00.000Z"
  },
  "recordings": [
    {
      "request": {
        "method": "GET",
        "url": "https://api.openweathermap.org/geo/1.0/direct?q=Minsk,BY&limit=1&appid=REDACTED",
        "headers": {
          "User-Agent": "httpx/0.24.0",
          "Accept": "*/*",
          "Accept-Encoding": "gzip, deflate",
          "Connection": "keep-alive"
        },
        "content": null
      },
      "response": {
        "status_code": 200,
        "headers": {
          "Content-Type": "application/json; charset=utf-8",
          "Content-Length": "123",
          "Date": "Sat, 02 Nov 2025 12:00:01 GMT"
        },
        "content": "[{\"name\":\"Minsk\",\"local_names\":{\"ru\":\"Минск\"},\"lat\":53.9024716,\"lon\":27.5618225,\"country\":\"BY\"}]"
      },
      "timestamp": "2025-11-02T12:00:01.234Z"
    },
    {
      "request": {
        "method": "GET",
        "url": "https://api.openweathermap.org/data/3.0/onecall?lat=53.9024716&lon=27.5618225&exclude=minutely,hourly,alerts&units=metric&lang=ru&appid=REDACTED",
        "headers": {
          "User-Agent": "httpx/0.24.0",
          "Accept": "*/*",
          "Accept-Encoding": "gzip, deflate",
          "Connection": "keep-alive"
        },
        "content": null
      },
      "response": {
        "status_code": 200,
        "headers": {
          "Content-Type": "application/json; charset=utf-8",
          "Content-Length": "2345",
          "Date": "Sat, 02 Nov 2025 12:00:02 GMT"
        },
        "content": "{\"lat\":53.9024716,\"lon\":27.5618225,\"timezone\":\"Europe/Minsk\",\"timezone_offset\":10800,\"current\":{\"dt\":1730548802,\"sunrise\":1730523456,\"sunset\":1730558901,\"temp\":5.2,\"feels_like\":2.1,\"pressure\":1013,\"humidity\":76,\"dew_point\":1.2,\"uvi\":0.5,\"clouds\":40,\"visibility\":10000,\"wind_speed\":3.5,\"wind_deg\":180,\"weather\":[{\"id\":802,\"main\":\"Clouds\",\"description\":\"переменная облачность\",\"icon\":\"03d\"}]},\"daily\":[...]}"
      },
      "timestamp": "2025-11-02T12:00:02.567Z"
    }
  ]
}
```

---

**End of Design Document**

Dood, this v2 design provides a complete, generic, and scalable solution for golden data testing! 🎉