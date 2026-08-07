"""Yandex Object Storage helper for STT — co-located alongside the Yandex SpeechKit provider.

Uploads extracted audio to Yandex Object Storage (S3-compatible) and returns
a URI that SpeechKit can consume via the ``uri`` submit-body field.  The
helper is **Yandex-specific**: the endpoint and region are constants baked
into the module, not config knobs.  Only ``YandexSpeechKitProvider`` uses it.

**Hard ``boto3`` import.** ``boto3`` is an external dependency (pinned in
``requirements.direct.txt``) and is imported unconditionally at module
top-level — an absent boto3 fails at import time, so importing this module
(and the provider that imports it) requires boto3 installed even when Object
Storage is not configured.

**URI scheme — smoke pending.** The exact URI scheme SpeechKit consumes
(``s3://bucket/key`` vs HTTPS) is a smoke-test verification item
(design §11 item 1).  The current default is an HTTPS URL; ``delete()``
recovers the key from whatever ``upload()`` returns, so changing the scheme
later requires updating only these two methods.

**No ``internal.*`` imports.** This module lives in ``lib/stt`` and respects
the dependency firewall — boto3 is external and allowed.
"""

import asyncio
import logging
import uuid

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import ClientError

_STT_S3_CONFIG = BotocoreConfig(
    connect_timeout=5,
    read_timeout=30,
    retries={"max_attempts": 3, "mode": "standard"},
)

logger = logging.getLogger(__name__)

# Yandex Object Storage constants (not config knobs).
_YANDEX_OS_ENDPOINT = "https://storage.yandexcloud.net"
_YANDEX_OS_REGION = "ru-central1"


class YandexObjectStorage:
    """Co-located Yandex Object Storage helper for the STT pipeline.

    Wraps boto3 S3 calls with Yandex-specific defaults (endpoint, region)
    and bounded transport timeouts.  Used directly by
    ``YandexSpeechKitProvider`` — not a service-layer client, not reusable
    by attachment storage.

    Attributes:
        _bucket: The S3 bucket name.
        _prefix: Key prefix for all objects uploaded by this instance.
        _client: The boto3 S3 client (built once with bounded config).
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "stt/",
        keyId: str,
        keySecret: str,
    ) -> None:
        """Build a Yandex Object Storage helper with a boto3 S3 client.

        Args:
            bucket: The S3 bucket name for STT audio objects.
            prefix: Key prefix for uploaded objects (default ``"stt/"``).
                A trailing ``/`` is conventional but not enforced.
            keyId: Yandex static access-key ID (SigV4 credential).
            keySecret: Yandex static access-key secret (SigV4 credential).
        """
        self._bucket = bucket
        self._prefix = prefix
        self._client = boto3.client(
            "s3",
            endpoint_url=_YANDEX_OS_ENDPOINT,
            region_name=_YANDEX_OS_REGION,
            aws_access_key_id=keyId,
            aws_secret_access_key=keySecret,
            config=_STT_S3_CONFIG,
        )

    async def upload(self, data: bytes) -> str:
        """Upload audio bytes to Object Storage and return a SpeechKit-consumable URI.

        Generates a unique key (``{prefix}{uuid4}``), calls ``put_object``,
        and returns an HTTPS URI.  The URI scheme is smoke-pending
        (design §11 item 1); ``delete()`` recovers the key from whatever
        this method returns.

        Args:
            data: The raw audio bytes to upload.

        Returns:
            An HTTPS URI (``https://storage.yandexcloud.net/{bucket}/{key}``)
            that SpeechKit can consume via the ``uri`` field.

        Raises:
            ClientError: On infrastructure failure (auth, network, 5xx).
                The provider wraps this in a best-effort try/except
                (Phase 3).
        """
        key = f"{self._prefix}{uuid.uuid4()}"
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
        )
        return f"https://storage.yandexcloud.net/{self._bucket}/{key}"

    async def delete(self, uri: str) -> None:
        """Delete an object from Object Storage, no-op if already missing.

        Recovers the key from the URI produced by ``upload()`` and calls
        ``delete_object``.  A missing object (``NoSuchKey`` / 404) is a
        no-op — the method returns without raising, matching the
        idempotent-delete contract the attachment ``S3StorageBackend`` has.

        Args:
            uri: The URI previously returned by ``upload()``.

        Returns:
            None.

        Raises:
            ValueError: If *uri* does not contain the expected bucket
                segment (i.e. was not produced by ``upload()``).
            ClientError: On infrastructure failures other than a missing
                object (e.g. permission denied, network).  A missing-object
                error is caught and silently ignored.
        """
        parts = uri.split(f"/{self._bucket}/", 1)
        if len(parts) != 2:
            raise ValueError(f"Not an upload URI: {uri!r}")
        key = parts[1]
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except ClientError as exc:
            errorCode = exc.response.get("Error", {}).get("Code", "")
            if errorCode in ("NoSuchKey", "404"):
                return
            raise

    async def aclose(self) -> None:
        """Close the underlying boto3 S3 client.

        Called by the provider's ``aclose()`` (Phase 2) during shutdown.
        The blocking ``boto3.client.close()`` is offloaded to a worker
        thread via ``asyncio.to_thread`` for convention consistency with
        the other async methods.

        Returns:
            None.
        """
        await asyncio.to_thread(self._client.close)
