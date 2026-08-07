"""Unit tests for lib.stt.providers.yandex_object_storage — mocked-boto3.

Covers:
- ``upload``: key generation (``{prefix}{uuid4}``), ``put_object`` call
  shape, returned URI contains bucket + key.
- ``delete``: key recovery from URI, ``delete_object`` call, no-op on
  missing object (``NoSuchKey`` / 404).
- Guarded import: module imports cleanly when boto3 is unavailable and
  ``_BOTO3_AVAILABLE`` flag is set to ``False``.
"""

import importlib
import sys
import threading
import uuid
from types import ModuleType
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from lib.stt.providers.yandex_object_storage import YandexObjectStorage


class _ImportErrorStub:
    """Module stub that raises ImportError on any attribute access.

    Used to simulate an absent package in ``sys.modules`` for guarded-import
    tests.  Only ``__getattr__`` is defined; ``__name__`` is set so the stub
    looks like a module to the import system.
    """

    def __init__(self, name: str) -> None:
        """Args:
        name: The module name this stub impersonates.
        """
        self.__name__ = name

    def __getattr__(self, item: str) -> object:
        """Raise ImportError for any attribute access.

        Args:
            item: The attribute name being accessed.

        Raises:
            ImportError: Always.
        """
        raise ImportError(f"simulated absent module: {self.__name__}.{item}")


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mockS3Client() -> MagicMock:
    """Create a mock boto3 S3 client with put_object / delete_object.

    Args:
        None.

    Returns:
        A MagicMock mimicking a boto3 S3 client.
    """
    client = MagicMock()
    client.put_object = MagicMock(return_value={})
    client.delete_object = MagicMock(return_value={})
    client.close = MagicMock()
    return client


@pytest.fixture
def storage(mockS3Client: MagicMock) -> YandexObjectStorage:
    """Build a YandexObjectStorage with a mocked boto3 client.

    Args:
        mockS3Client: The mocked S3 client from the fixture.

    Returns:
        A YandexObjectStorage instance whose boto3 client is the mock.
    """
    with patch(
        "lib.stt.providers.yandex_object_storage.boto3.client",
        return_value=mockS3Client,
    ):
        os = YandexObjectStorage(
            bucket="test-bucket",
            prefix="stt/",
            keyId="test-key-id",
            keySecret="test-key-secret",
        )
        # Ensure the mock is used (boto3.client was patched at import time,
        # but the constructor re-assigns self._client from the patched call).
        os._client = mockS3Client
        return os


# ============================================================================
# upload tests
# ============================================================================


class TestUpload:
    """Tests for YandexObjectStorage.upload."""

    async def testUploadGeneratesPrefixedUuidKey(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """upload generates a key of the shape ``{prefix}{uuid4}``.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        await storage.upload(b"audio-data")

        mockS3Client.put_object.assert_called_once()
        callKwargs = mockS3Client.put_object.call_args
        key: str = callKwargs.kwargs["Key"]
        assert key.startswith("stt/")
        # After prefix, the remainder should be a valid UUID4 string.
        uuidPart = key[len("stt/") :]
        # uuid.UUID will raise ValueError if not a valid UUID.
        uuid.UUID(uuidPart)

    async def testUploadCallsPutObjectWithCorrectArgs(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock  # noqa: F821
    ) -> None:
        """upload calls put_object with the expected Bucket, Key, and Body.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        data = b"\x00\x01\x02"
        await storage.upload(data)

        mockS3Client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key=mockS3Client.put_object.call_args.kwargs["Key"],
            Body=data,
        )

    async def testUploadReturnsUriContainingBucketAndKey(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock  # noqa: F821
    ) -> None:
        """upload returns an HTTPS URI containing the bucket and the generated key.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        uri = await storage.upload(b"data")
        key = mockS3Client.put_object.call_args.kwargs["Key"]
        assert "test-bucket" in uri
        assert key in uri
        assert uri.startswith("https://storage.yandexcloud.net/")


# ============================================================================
# delete tests
# ============================================================================


class TestDelete:
    """Tests for YandexObjectStorage.delete."""

    async def testDeleteRecoversKeyAndCallsDeleteObject(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock  # noqa: F821
    ) -> None:
        """delete recovers the key from the URI and calls delete_object.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        uri = "https://storage.yandexcloud.net/test-bucket/stt/some-uuid"
        await storage.delete(uri)

        mockS3Client.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="stt/some-uuid",
        )

    async def testDeleteIsNoOpOnMissingObject(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """delete returns without raising when the object does not exist.

        Mocks delete_object to raise a ClientError with NoSuchKey code.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        notFoundError = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            "DeleteObject",
        )
        mockS3Client.delete_object.side_effect = notFoundError

        # Should not raise.
        await storage.delete("https://storage.yandexcloud.net/test-bucket/stt/gone")

        mockS3Client.delete_object.assert_called_once()

    async def testDeleteIsNoOpOn404(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """delete returns without raising when delete_object returns a 404 code.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        notFoundError = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "DeleteObject",
        )
        mockS3Client.delete_object.side_effect = notFoundError

        await storage.delete("https://storage.yandexcloud.net/test-bucket/stt/gone")
        mockS3Client.delete_object.assert_called_once()

    async def testDeleteRaisesOnNonMissingError(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """delete re-raises ClientError codes that are not NoSuchKey/404.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        accessDenied = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "DeleteObject",
        )
        mockS3Client.delete_object.side_effect = accessDenied

        with pytest.raises(ClientError):
            await storage.delete("https://storage.yandexcloud.net/test-bucket/stt/forbidden")

    async def testDeleteRaisesValueErrorOnMalformedUri(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """delete raises ValueError when the URI lacks the expected bucket segment.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        with pytest.raises(ValueError, match="Not an upload URI"):
            await storage.delete("https://example.com/no-bucket-here/key")

        # delete_object must not have been called.
        mockS3Client.delete_object.assert_not_called()


# ============================================================================
# aclose test
# ============================================================================


class TestAclose:
    """Tests for YandexObjectStorage.aclose."""

    async def testAcloseClosesBoto3Client(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """aclose delegates to the underlying boto3 client close.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        await storage.aclose()
        mockS3Client.close.assert_called_once()


# ============================================================================
# Offload regression tests (asyncio.to_thread)
# ============================================================================


class TestOffload:
    """Regression tests ensuring blocking boto3 calls are offloaded to worker threads.

    If ``asyncio.to_thread`` is accidentally removed, the mock captures the
    event-loop thread instead of a worker thread and these tests fail.
    """

    async def testUploadOffloadsBoto3ToWorkerThread(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """upload runs put_object on a worker thread, not the event-loop thread.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        mainThread = threading.current_thread()
        capturedThreads: list[threading.Thread] = []

        def fakePutObject(**kwargs: object) -> dict:
            capturedThreads.append(threading.current_thread())
            return {}

        mockS3Client.put_object.side_effect = fakePutObject
        await storage.upload(b"data")
        assert capturedThreads, "put_object was never called"
        assert capturedThreads[0] is not mainThread, "put_object ran on the event-loop thread (not offloaded)"

    async def testDeleteOffloadsBoto3ToWorkerThread(
        self, storage: "YandexObjectStorage", mockS3Client: MagicMock
    ) -> None:  # noqa: F821
        """delete runs delete_object on a worker thread, not the event-loop thread.

        Args:
            storage: The fixture-built YandexObjectStorage.
            mockS3Client: The mocked S3 client.
        """
        mainThread = threading.current_thread()
        capturedThreads: list[threading.Thread] = []

        def fakeDeleteObject(**kwargs: object) -> dict:
            capturedThreads.append(threading.current_thread())
            return {}

        mockS3Client.delete_object.side_effect = fakeDeleteObject
        await storage.delete("https://storage.yandexcloud.net/test-bucket/stt/some-key")
        assert capturedThreads, "delete_object was never called"
        assert capturedThreads[0] is not mainThread, "delete_object ran on the event-loop thread (not offloaded)"


# ============================================================================
# Guarded import test
# ============================================================================


class TestGuardedImport:
    """Tests for the _BOTO3_AVAILABLE guarded import flag."""

    def testModuleImportsCleanlyWhenBoto3Unavailable(self) -> None:
        """The module imports without error even when boto3 is absent.

        We simulate an absent boto3 by temporarily injecting a module stub
        into ``sys.modules`` that raises ``ImportError`` on attribute access,
        then reloading the module.  After the test the original module state
        is restored.

        Args:
            None.
        """
        # Save original state.
        savedModules: Dict[str, ModuleType | None] = {}
        boto3Related = [k for k in sys.modules if k.startswith("boto3") or k.startswith("botocore")]
        for mod in boto3Related:
            savedModules[mod] = sys.modules.pop(mod, None)

        # Also remove our module so it gets re-imported.
        ourMod = "lib.stt.providers.yandex_object_storage"
        savedOurMod: ModuleType | None = sys.modules.pop(ourMod, None)

        # Remove parent package modules so the re-import doesn't short-circuit.
        parentMods = ["lib.stt.providers", "lib.stt", "lib"]
        savedParentMods: Dict[str, ModuleType] = {}
        for mod in parentMods:
            if mod in sys.modules:
                savedParentMods[mod] = sys.modules.pop(mod)  # type: ignore[assignment]

        try:
            # Inject stubs that raise ImportError so the guarded import
            # takes the except branch.
            for pkg in ("boto3", "botocore", "botocore.config", "botocore.exceptions"):
                sys.modules[pkg] = _ImportErrorStub(pkg)  # type: ignore[assignment]

            # Restore parent packages so importlib can traverse them.
            for mod, obj in savedParentMods.items():
                sys.modules[mod] = obj

            # Re-import the module.
            imported = importlib.import_module(ourMod)
            assert hasattr(imported, "_BOTO3_AVAILABLE")
            assert imported._BOTO3_AVAILABLE is False
        finally:
            # Remove the stubs.
            for pkg in ("boto3", "botocore", "botocore.config", "botocore.exceptions"):
                sys.modules.pop(pkg, None)
            # Restore original state.
            for mod, obj in savedModules.items():
                if obj is not None:
                    sys.modules[mod] = obj
            if savedOurMod is not None:
                sys.modules[ourMod] = savedOurMod
