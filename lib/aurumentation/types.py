"""Data models for Golden Data Testing System v2.

This module defines the core data structures used for capturing,
storing, and replaying HTTP traffic in the golden data testing system.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class HttpRequest(BaseModel):
    """HTTP request details captured during recording.

    Captures all relevant information about an HTTP request including
    method, URL, headers, query parameters, and body content.
    """

    method: str
    url: str
    headers: Dict[str, str]
    params: Optional[Dict[str, Union[str, List[str]]]] = None
    body: Optional[str] = None


class HttpResponse(BaseModel):
    """HTTP response details captured during recording.

    Captures all relevant information about an HTTP response including
    status code, headers, and body content.
    """

    status_code: int
    headers: Dict[str, str]
    content: str


class HttpCall(BaseModel):
    """Complete HTTP call with request, response, and timestamp.

    Represents a single HTTP transaction with both request and response
    details along with when it occurred.
    """

    request: HttpRequest
    response: HttpResponse
    timestamp: datetime


class GoldenDataScenario(BaseModel):
    """Complete test scenario with metadata.

    A complete golden data scenario that includes metadata about
    the test case and all HTTP recordings made during its execution.
    """

    description: str
    functionName: str
    kwargs: Dict[str, Any]
    recordings: List[HttpCall]
    createdAt: datetime


class CollectorInput(BaseModel):
    """Input format for the collector.

    Defines the structure for collector input which includes
    a description and keyword arguments for the function being tested.
    """

    description: str
    kwargs: Dict[str, Any]
