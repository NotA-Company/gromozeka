"""
Comprehensive tests for S3StorageBackend with mocks, dood!

This module tests the S3StorageBackend using mocked boto3 calls
to ensure proper S3 integration without making real API calls.
"""

from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from internal.services.storage.backends.s3 import S3StorageBackend
from internal.services.storage.exceptions import StorageBackendError, StorageKeyError


@pytest.fixture
def mockS3Client():
    """Create a mock boto3 S3 client, dood!"""
    client = Mock()
    client.put_object = Mock(return_value={})
    client.get_object = Mock()
    client.head_object = Mock(return_value={})
    client.delete_object = Mock(return_value={})
    client.list_objects_v2 = Mock(return_value={})
    return client


@pytest.fixture
def s3Backend(mockS3Client):
    """Create S3StorageBackend with mocked boto3 client, dood!"""
    with patch("internal.services.storage.backends.s3.boto3.client", return_value=mockS3Client):
        backend = S3StorageBackend(
            endpoint="https://s3.amazonaws.com",
            region="us-east-1",
            keyId="test-key-id",
            keySecret="test-key-secret",
            bucket="test-bucket",
            prefix="test-prefix/",
        )
        backend.client = mockS3Client  # Ensure mock is used
        return backend


@pytest.fixture
def s3BackendNoPrefix(mockS3Client):
    """Create S3StorageBackend without prefix, dood!"""
    with patch("internal.services.storage.backends.s3.boto3.client", return_value=mockS3Client):
        backend = S3StorageBackend(
            endpoint="https://s3.amazonaws.com",
            region="us-east-1",
            keyId="test-key-id",
            keySecret="test-key-secret",
            bucket="test-bucket",
            prefix="",
        )
        backend.client = mockS3Client
        return backend


class TestS3BackendInitialization:
    """Test S3StorageBackend initialization, dood!"""

    def testBackendCreation(self):
        """Test that backend can be created with required parameters"""
        with patch("internal.services.storage.backends.s3.boto3.client") as mockBoto3:
            mockClient = Mock()
            mockBoto3.return_value = mockClient

            backend = S3StorageBackend(
                endpoint="https://s3.amazonaws.com",
                region="us-east-1",
                keyId="test-key-id",
                keySecret="test-key-secret",
                bucket="test-bucket",
            )

            assert backend is not None
            assert backend.bucket == "test-bucket"
            assert backend.prefix == ""

            # Verify boto3 client was created with correct parameters
            mockBoto3.assert_called_once_with(
                "s3",
                endpoint_url="https://s3.amazonaws.com",
                region_name="us-east-1",
                aws_access_key_id="test-key-id",
                aws_secret_access_key="test-key-secret",
            )

    def testBackendCreationWithPrefix(self):
        """Test backend creation with prefix"""
        with patch("internal.services.storage.backends.s3.boto3.client"):
            backend = S3StorageBackend(
                endpoint="https://s3.amazonaws.com",
                region="us-east-1",
                keyId="test-key-id",
                keySecret="test-key-secret",
                bucket="test-bucket",
                prefix="objects/",
            )

            assert backend.prefix == "objects/"

    def testBackendCreationWithYandexCloud(self):
        """Test backend creation with Yandex Cloud endpoint"""
        with patch("internal.services.storage.backends.s3.boto3.client") as mockBoto3:
            S3StorageBackend(
                endpoint="https://storage.yandexcloud.net",
                region="ru-central1",
                keyId="yc-key-id",
                keySecret="yc-key-secret",
                bucket="yc-bucket",
            )

            mockBoto3.assert_called_once_with(
                "s3",
                endpoint_url="https://storage.yandexcloud.net",
                region_name="ru-central1",
                aws_access_key_id="yc-key-id",
                aws_secret_access_key="yc-key-secret",
            )

    def testBackendCreationFailureRaisesError(self):
        """Test that boto3 client creation failure raises StorageBackendError"""
        with patch("internal.services.storage.backends.s3.boto3.client", side_effect=Exception("Connection failed")):
            with pytest.raises(StorageBackendError, match="Failed to initialize S3 client"):
                S3StorageBackend(
                    endpoint="https://s3.amazonaws.com",
                    region="us-east-1",
                    keyId="test-key-id",
                    keySecret="test-key-secret",
                    bucket="test-bucket",
                )


class TestS3BackendStore:
    """Test S3StorageBackend store operation, dood!"""

    def testStoreSimpleData(self, s3Backend, mockS3Client):
        """Test storing simple data"""
        key = "test-key"
        data = b"test data"

        s3Backend.store(key, data)

        # Verify put_object was called with correct parameters
        mockS3Client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="test-prefix/test-key",
            Body=data,
            ContentType="application/octet-stream",
        )

    def testStoreWithoutPrefix(self, s3BackendNoPrefix, mockS3Client):
        """Test storing without prefix"""
        key = "test-key"
        data = b"test data"

        s3BackendNoPrefix.store(key, data)

        mockS3Client.put_object.assert_called_once_with(
            Bucket="test-bucket", Key="test-key", Body=data, ContentType="application/octet-stream"
        )

    def testStoreWithSanitizedKey(self, s3Backend, mockS3Client):
        """Test storing with key that needs sanitization"""
        key = "path/to/file"
        data = b"test data"

        s3Backend.store(key, data)

        # Key should be sanitized to path_to_file
        mockS3Client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="test-prefix/path_to_file",
            Body=data,
            ContentType="application/octet-stream",
        )

    def testStoreWithInvalidKeyRaisesError(self, s3Backend):
        """Test that store with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            s3Backend.store("", b"data")

    def testStoreFailureRaisesError(self, s3Backend, mockS3Client):
        """Test that S3 put_object failure raises StorageBackendError"""
        mockS3Client.put_object.side_effect = Exception("Network error")

        with pytest.raises(StorageBackendError, match="Failed to store object"):
            s3Backend.store("test-key", b"data")

    def testStoreLargeData(self, s3Backend, mockS3Client):
        """Test storing large data"""
        key = "large-key"
        data = b"x" * 1000000  # 1MB

        s3Backend.store(key, data)

        mockS3Client.put_object.assert_called_once()
        call_args = mockS3Client.put_object.call_args
        assert call_args[1]["Body"] == data


class TestS3BackendGet:
    """Test S3StorageBackend get operation, dood!"""

    def testGetExistingObject(self, s3Backend, mockS3Client):
        """Test getting existing object"""
        key = "test-key"
        data = b"test data"

        # Mock response
        mockResponse = {"Body": Mock()}
        mockResponse["Body"].read = Mock(return_value=data)
        mockS3Client.get_object.return_value = mockResponse

        result = s3Backend.get(key)

        assert result == data
        mockS3Client.get_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/test-key")

    def testGetNonExistentObject(self, s3Backend, mockS3Client):
        """Test getting non-existent object returns None"""
        key = "non-existent"

        # Mock 404 error
        error = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        mockS3Client.get_object.side_effect = error

        result = s3Backend.get(key)

        assert result is None

    def testGetWithoutPrefix(self, s3BackendNoPrefix, mockS3Client):
        """Test getting without prefix"""
        key = "test-key"
        data = b"test data"

        mockResponse = {"Body": Mock()}
        mockResponse["Body"].read = Mock(return_value=data)
        mockS3Client.get_object.return_value = mockResponse

        result = s3BackendNoPrefix.get(key)

        assert result == data
        mockS3Client.get_object.assert_called_once_with(Bucket="test-bucket", Key="test-key")

    def testGetWithInvalidKeyRaisesError(self, s3Backend):
        """Test that get with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            s3Backend.get("")

    def testGetNetworkErrorRaisesError(self, s3Backend, mockS3Client):
        """Test that network error raises StorageBackendError"""
        mockS3Client.get_object.side_effect = Exception("Network error")

        with pytest.raises(StorageBackendError, match="Failed to get object"):
            s3Backend.get("test-key")

    def testGetOtherClientErrorRaisesError(self, s3Backend, mockS3Client):
        """Test that non-404 ClientError raises StorageBackendError"""
        error = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        mockS3Client.get_object.side_effect = error

        with pytest.raises(StorageBackendError, match="Failed to get object"):
            s3Backend.get("test-key")


class TestS3BackendExists:
    """Test S3StorageBackend exists operation, dood!"""

    def testExistsForExistingObject(self, s3Backend, mockS3Client):
        """Test exists returns True for existing object"""
        key = "test-key"

        mockS3Client.head_object.return_value = {}

        result = s3Backend.exists(key)

        assert result is True
        mockS3Client.head_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/test-key")

    def testExistsForNonExistentObject(self, s3Backend, mockS3Client):
        """Test exists returns False for non-existent object"""
        key = "non-existent"

        error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        mockS3Client.head_object.side_effect = error

        result = s3Backend.exists(key)

        assert result is False

    def testExistsWithoutPrefix(self, s3BackendNoPrefix, mockS3Client):
        """Test exists without prefix"""
        key = "test-key"

        mockS3Client.head_object.return_value = {}

        result = s3BackendNoPrefix.exists(key)

        assert result is True
        mockS3Client.head_object.assert_called_once_with(Bucket="test-bucket", Key="test-key")

    def testExistsWithInvalidKeyRaisesError(self, s3Backend):
        """Test that exists with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            s3Backend.exists("")

    def testExistsNetworkErrorRaisesError(self, s3Backend, mockS3Client):
        """Test that network error raises StorageBackendError"""
        mockS3Client.head_object.side_effect = Exception("Network error")

        with pytest.raises(StorageBackendError, match="Failed to check existence"):
            s3Backend.exists("test-key")


class TestS3BackendDelete:
    """Test S3StorageBackend delete operation, dood!"""

    def testDeleteExistingObject(self, s3Backend, mockS3Client):
        """Test deleting existing object"""
        key = "test-key"

        # Mock exists check
        mockS3Client.head_object.return_value = {}
        mockS3Client.delete_object.return_value = {}

        result = s3Backend.delete(key)

        assert result is True
        mockS3Client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/test-key")

    def testDeleteNonExistentObject(self, s3Backend, mockS3Client):
        """Test deleting non-existent object returns False"""
        key = "non-existent"

        # Mock exists check returning False
        error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        mockS3Client.head_object.side_effect = error

        result = s3Backend.delete(key)

        assert result is False
        mockS3Client.delete_object.assert_not_called()

    def testDeleteWithoutPrefix(self, s3BackendNoPrefix, mockS3Client):
        """Test deleting without prefix"""
        key = "test-key"

        mockS3Client.head_object.return_value = {}
        mockS3Client.delete_object.return_value = {}

        result = s3BackendNoPrefix.delete(key)

        assert result is True
        mockS3Client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="test-key")

    def testDeleteWithInvalidKeyRaisesError(self, s3Backend):
        """Test that delete with invalid key raises StorageKeyError"""
        with pytest.raises(StorageKeyError):
            s3Backend.delete("")

    def testDeleteNetworkErrorRaisesError(self, s3Backend, mockS3Client):
        """Test that network error raises StorageBackendError"""
        mockS3Client.head_object.return_value = {}
        mockS3Client.delete_object.side_effect = Exception("Network error")

        with pytest.raises(StorageBackendError, match="Failed to delete object"):
            s3Backend.delete("test-key")


class TestS3BackendList:
    """Test S3StorageBackend list operation, dood!"""

    def testListEmptyBucket(self, s3Backend, mockS3Client):
        """Test listing empty bucket"""
        mockS3Client.list_objects_v2.return_value = {}

        result = s3Backend.list()

        assert result == []
        mockS3Client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="test-prefix/")

    def testListWithObjects(self, s3Backend, mockS3Client):
        """Test listing bucket with objects"""
        mockS3Client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "test-prefix/file1.txt"},
                {"Key": "test-prefix/file2.txt"},
                {"Key": "test-prefix/file3.txt"},
            ]
        }

        result = s3Backend.list()

        assert result == ["file1.txt", "file2.txt", "file3.txt"]

    def testListWithPrefix(self, s3Backend, mockS3Client):
        """Test listing with additional prefix"""
        mockS3Client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "test-prefix/docs/file1.txt"},
                {"Key": "test-prefix/docs/file2.txt"},
            ]
        }

        result = s3Backend.list(prefix="docs/")

        assert result == ["docs/file1.txt", "docs/file2.txt"]
        mockS3Client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="test-prefix/docs/")

    def testListWithLimit(self, s3Backend, mockS3Client):
        """Test listing with limit"""
        mockS3Client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "test-prefix/file1.txt"},
                {"Key": "test-prefix/file2.txt"},
            ]
        }

        result = s3Backend.list(limit=5)

        assert len(result) == 2
        mockS3Client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="test-prefix/", MaxKeys=5)

    def testListWithoutPrefix(self, s3BackendNoPrefix, mockS3Client):
        """Test listing without backend prefix"""
        mockS3Client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "file1.txt"},
                {"Key": "file2.txt"},
            ]
        }

        result = s3BackendNoPrefix.list()

        assert result == ["file1.txt", "file2.txt"]
        mockS3Client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="")

    def testListNetworkErrorRaisesError(self, s3Backend, mockS3Client):
        """Test that network error raises StorageBackendError"""
        mockS3Client.list_objects_v2.side_effect = Exception("Network error")

        with pytest.raises(StorageBackendError, match="Failed to list objects"):
            s3Backend.list()


class TestS3BackendKeyHandling:
    """Test S3 key handling with prefix, dood!"""

    def testGetS3KeyWithPrefix(self, s3Backend):
        """Test _getS3Key with prefix"""
        key = "test-key"
        s3Key = s3Backend._getS3Key(key)
        assert s3Key == "test-prefix/test-key"

    def testGetS3KeyWithoutPrefix(self, s3BackendNoPrefix):
        """Test _getS3Key without prefix"""
        key = "test-key"
        s3Key = s3BackendNoPrefix._getS3Key(key)
        assert s3Key == "test-key"

    def testGetS3KeyWithSanitization(self, s3Backend):
        """Test _getS3Key with key sanitization"""
        key = "path/to/file"
        s3Key = s3Backend._getS3Key(key)
        assert s3Key == "test-prefix/path_to_file"

    def testGetS3KeyInvalidRaisesError(self, s3Backend):
        """Test _getS3Key with invalid key raises error"""
        with pytest.raises(StorageKeyError):
            s3Backend._getS3Key("")


class TestS3BackendRealWorldScenarios:
    """Test real-world scenarios, dood!"""

    def testStoreAndRetrieveCycle(self, s3Backend, mockS3Client):
        """Test complete store and retrieve cycle"""
        key = "test-key"
        data = b"test data"

        # Store
        s3Backend.store(key, data)

        # Mock get response
        mockResponse = {"Body": Mock()}
        mockResponse["Body"].read = Mock(return_value=data)
        mockS3Client.get_object.return_value = mockResponse

        # Retrieve
        result = s3Backend.get(key)
        assert result == data

    def testMultipleObjects(self, s3Backend, mockS3Client):
        """Test storing multiple objects"""
        objects = {
            "file1.txt": b"data1",
            "file2.txt": b"data2",
            "file3.txt": b"data3",
        }

        for key, data in objects.items():
            s3Backend.store(key, data)

        # Verify all were stored
        assert mockS3Client.put_object.call_count == 3

    def testImageStorage(self, s3Backend, mockS3Client):
        """Test storing image-like data"""
        key = "avatar-123.jpg"
        data = b"\xff\xd8\xff\xe0" + b"x" * 1000

        s3Backend.store(key, data)

        call_args = mockS3Client.put_object.call_args
        assert call_args[1]["Body"] == data
        assert call_args[1]["ContentType"] == "application/octet-stream"
