"""
S3 storage backend implementation

This module provides a storage backend for AWS S3 and S3-compatible storage services.
Uses boto3 library for S3 operations with proper error handling.
"""

from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..exceptions import StorageBackendError
from ..utils import sanitizeKey
from .abstract import AbstractStorageBackend


class S3StorageBackend(AbstractStorageBackend):
    """
    S3-based storage backend using boto3.

    Stores objects in AWS S3 or S3-compatible storage services (e.g., Yandex Object Storage).
    All keys are sanitized and optionally prefixed with a configured prefix.

    Features:
    - Support for custom S3 endpoints (for S3-compatible services)
    - Optional key prefix for namespace isolation
    - Content-Type set to application/octet-stream
    - Proper error handling with StorageBackendError wrapping
    - 404 errors return None/False instead of raising exceptions

    Args:
        endpoint: S3 endpoint URL (e.g., "https://s3.amazonaws.com")
        region: AWS region (e.g., "us-east-1", "ru-central1")
        keyId: AWS access key ID
        keySecret: AWS secret access key
        bucket: S3 bucket name
        prefix: Optional prefix for all keys (default: "")

    Raises:
        StorageBackendError: If S3 client initialization fails

    Example:
        >>> backend = S3StorageBackend(
        ...     endpoint="https://s3.amazonaws.com",
        ...     region="us-east-1",
        ...     keyId="AKIAIOSFODNN7EXAMPLE",
        ...     keySecret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        ...     bucket="my-bucket",
        ...     prefix="objects/"
        ... )
        >>> backend.store("test-key", b"data")
        >>> backend.get("test-key")
        b'data'
    """

    def __init__(
        self,
        endpoint: str,
        region: str,
        keyId: str,
        keySecret: str,
        bucket: str,
        prefix: str = "",
    ):
        """
        Initialize S3 storage backend.

        Args:
            endpoint: S3 endpoint URL
            region: AWS region
            keyId: AWS access key ID
            keySecret: AWS secret access key
            bucket: S3 bucket name
            prefix: Optional prefix for all keys

        Raises:
            StorageBackendError: If S3 client initialization fails
        """
        self.bucket = bucket
        self.prefix = prefix

        try:
            # Initialize boto3 S3 client
            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=keyId,
                aws_secret_access_key=keySecret,
            )
        except Exception as e:
            raise StorageBackendError(f"Failed to initialize S3 client: {e}", originalError=e)

    def _getS3Key(self, key: str) -> str:
        """
        Get the full S3 key with prefix and sanitization.

        Args:
            key: The storage key (will be sanitized)

        Returns:
            The full S3 key with prefix

        Raises:
            StorageKeyError: If the key is invalid
        """
        sanitizedKey = sanitizeKey(key)
        if self.prefix:
            return f"{self.prefix}{sanitizedKey}"
        return sanitizedKey

    def store(self, key: str, data: bytes) -> None:
        """
        Upload binary data to S3.

        Args:
            key: The storage key (will be sanitized and prefixed)
            data: The binary data to store

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the upload operation fails
        """
        s3Key = self._getS3Key(key)

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=s3Key,
                Body=data,
                ContentType="application/octet-stream",
            )
        except Exception as e:
            raise StorageBackendError(f"Failed to store object with key '{key}' to S3: {e}", originalError=e)

    def get(self, key: str) -> bytes | None:
        """
        Download binary data from S3.

        Args:
            key: The storage key (will be sanitized and prefixed)

        Returns:
            The binary data if the object exists, None if not found (404)

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the download operation fails (not for 404)
        """
        s3Key = self._getS3Key(key)

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=s3Key)
            return response["Body"].read()
        except ClientError as e:
            # Return None for 404 (object not found)
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise StorageBackendError(f"Failed to get object with key '{key}' from S3: {e}", originalError=e)
        except Exception as e:
            raise StorageBackendError(f"Failed to get object with key '{key}' from S3: {e}", originalError=e)

    def exists(self, key: str) -> bool:
        """
        Check if an object exists in S3.

        Args:
            key: The storage key (will be sanitized and prefixed)

        Returns:
            True if the object exists, False if not found

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the existence check fails
        """
        s3Key = self._getS3Key(key)

        try:
            self.client.head_object(Bucket=self.bucket, Key=s3Key)
            return True
        except ClientError as e:
            # Return False for 404 (object not found)
            if e.response["Error"]["Code"] == "404":
                return False
            raise StorageBackendError(f"Failed to check existence of key '{key}' in S3: {e}", originalError=e)
        except Exception as e:
            raise StorageBackendError(f"Failed to check existence of key '{key}' in S3: {e}", originalError=e)

    def delete(self, key: str) -> bool:
        """
        Delete an object from S3.

        Args:
            key: The storage key (will be sanitized and prefixed)

        Returns:
            True if the object was deleted, False if it didn't exist

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the deletion fails
        """
        s3Key = self._getS3Key(key)

        # Check if object exists first
        if not self.exists(key):
            return False

        try:
            self.client.delete_object(Bucket=self.bucket, Key=s3Key)
            return True
        except Exception as e:
            raise StorageBackendError(f"Failed to delete object with key '{key}' from S3: {e}", originalError=e)

    def list(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """
        List objects in S3 matching the prefix.

        Args:
            prefix: Optional prefix to filter keys (combined with backend prefix)
            limit: Optional maximum number of keys to return (default: None for no limit)

        Returns:
            List of keys matching the prefix, up to the specified limit.
            Keys are returned without the backend prefix.
            Returns empty list if no objects match.

        Raises:
            StorageBackendError: If the list operation fails
        """
        # Combine backend prefix with search prefix
        fullPrefix = f"{self.prefix}{prefix}" if self.prefix else prefix

        try:
            # Build list_objects_v2 parameters
            listParams: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": fullPrefix,
            }

            if limit is not None and limit > 0:
                listParams["MaxKeys"] = limit

            response = self.client.list_objects_v2(**listParams)

            # Extract keys from response
            if "Contents" not in response:
                return []

            keys = []
            prefixLen = len(self.prefix)

            for obj in response["Contents"]:
                s3Key = obj["Key"]
                # Remove backend prefix from returned keys
                if self.prefix and s3Key.startswith(self.prefix):
                    keys.append(s3Key[prefixLen:])
                else:
                    keys.append(s3Key)

            return keys

        except Exception as e:
            raise StorageBackendError(f"Failed to list objects with prefix '{prefix}' in S3: {e}", originalError=e)
