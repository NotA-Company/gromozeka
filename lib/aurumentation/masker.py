"""Secret masking functionality for HTTP traffic.

This module implements secret masking for HTTP requests and responses
to ensure sensitive data is not stored in golden data files.
"""

import copy
import re
from typing import Any, Dict, List, Optional

from .types import HttpCallDict


class SecretMasker:
    """Masks secrets in HTTP requests and responses.

    Handles automatic secret masking in captured data including:
    - URL parameters (e.g., ?api_key=secret)
    - Headers (e.g., Authorization: Bearer token)
    - Request/response bodies (JSON and text)
    - Recursive dict/list structures
    """

    DEFAULT_PATTERNS = [r"api[_-]?key", r"api[key]", r"token", r"auth", r"password", r"secret", r"key"]

    MASKED_PLACEHOLDER = "***MASKED***"

    def __init__(self, secrets: List[str], patterns: Optional[List[str]] = None):
        """Initialize the secret masker.

        Args:
            secrets: List of specific secret strings to mask
            patterns: List of regex patterns for secret keys. If None, uses DEFAULT_PATTERNS.
        """
        if patterns is None:
            patterns = self.DEFAULT_PATTERNS

        self.secrets = [v for v in secrets if v]
        self.patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    def maskText(self, text: str) -> str:
        """Replace all secrets in text with masked placeholder.

        Args:
            text: Text to mask secrets in

        Returns:
            Text with secrets replaced by masked placeholder
        """
        if not text:
            return text

        result = text

        # Mask exact secret matches
        for secret in self.secrets:
            result = result.replace(secret, self.MASKED_PLACEHOLDER)

        return result

    def maskDict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively mask secrets in dictionary values.

        Args:
            data: Dictionary to mask secrets in

        Returns:
            Dictionary with secrets masked
        """
        if not isinstance(data, dict):
            return data

        masked = {}
        for key, value in data.items():
            # Check if key indicates it contains a secret
            if self._isSecretKey(key):
                masked[key] = self.MASKED_PLACEHOLDER
            elif isinstance(value, str):
                masked[key] = self.maskText(value)
            elif isinstance(value, dict):
                masked[key] = self.maskDict(value)
            elif isinstance(value, list):
                masked[key] = [
                    (
                        self.maskDict(item)
                        if isinstance(item, dict)
                        else self.maskText(item) if isinstance(item, str) else item
                    )
                    for item in value
                ]
            else:
                masked[key] = value
        return masked

    def maskHttpCall(self, call: HttpCallDict) -> HttpCallDict:
        """Mask secrets in an HTTP call (request and response).

        Args:
            call: HttpCallDict to mask secrets in

        Returns:
            HttpCallDict with secrets masked
        """
        # Mask request
        masked_request = copy.deepcopy(call["request"])
        masked_request["url"] = self.maskText(call["request"]["url"])
        masked_request["headers"] = self.maskDict(call["request"]["headers"])
        if "params" in call["request"]:
            masked_request["params"] = self.maskDict(call["request"]["params"])
        if "body" in call["request"] and call["request"]["body"] is not None:
            masked_request["body"] = self.maskText(call["request"]["body"])

        # Mask response
        masked_response = copy.deepcopy(call["response"])
        masked_response["headers"] = self.maskDict(call["response"]["headers"])
        masked_response["content"] = self.maskText(call["response"]["content"])

        # Create new HttpCall with masked data
        masked_call: HttpCallDict = {
            "request": masked_request,
            "response": masked_response,
            "timestamp": call["timestamp"],
        }
        return masked_call

    def _isSecretKey(self, key: str) -> bool:
        """Check if a key name indicates it contains a secret.

        Args:
            key: Key name to check

        Returns:
            True if key indicates it contains a secret, False otherwise
        """
        keyLower = key.lower()
        for pattern in self.patterns:
            if pattern.search(keyLower):
                return True
        return False
