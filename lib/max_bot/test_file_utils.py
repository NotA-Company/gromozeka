"""
Tests for file utilities in Max Messenger Bot API.

This module contains comprehensive tests for file operations including
MIME type detection, file validation, and other helper functions.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import aiofiles
import pytest

from .constants import MAX_FILE_SIZE
from .file_utils import (
    FileTooLargeError,
    FileValidationError,
    ProgressCallback,
    UnsupportedFileTypeError,
    copyWithProgress,
    detectMimeType,
    getAllowedTypesForUpload,
    getFileExtension,
    readFileAsync,
    sanitizeFilename,
    validateFileForUpload,
    validateFileSize,
    validateFileType,
    writeFileAsync,
)


class TestDetectMimeType:
    """Test MIME type detection functionality."""

    @patch("lib.max_bot.file_utils.magic")
    def testDetectMimeTypeWithMagic(self, mockMagic):
        """Test MIME type detection using python-magic."""
        # Setup mock
        mock_mime_instance = Mock()
        mock_mime_instance.from_file.return_value = "image/jpeg"
        mockMagic.Magic.return_value = mock_mime_instance

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tempFile:
            tempPath = tempFile.name

            # Test detection
            result = detectMimeType(tempPath)

            # Verify
            assert result == "image/jpeg"
            mockMagic.Magic.assert_called_once_with(mime=True)
            mock_mime_instance.from_file.assert_called_once_with(tempPath)

    @patch("lib.max_bot.file_utils.magic")
    @patch("lib.max_bot.file_utils.mimetypes")
    def testDetectMimeTypeFallbackToMimetypes(self, mockMimetypes, mockMagic):
        """Test MIME type detection fallback to mimetypes module."""
        # Setup magic to fail
        mockMagic.Magic.side_effect = ImportError("magic not available")

        # Setup mimetypes
        mockMimetypes.guess_type.return_value = ("image/png", None)

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".png") as tempFile:
            tempPath = tempFile.name

            # Test detection
            result = detectMimeType(tempPath)

            # Verify
            assert result == "image/png"
            mockMimetypes.guess_type.assert_called_once_with(tempPath)

    @patch("lib.max_bot.file_utils.magic")
    @patch("lib.max_bot.file_utils.mimetypes")
    def testDetectMimeTypeDefaultFallback(self, mockMimetypes, mockMagic):
        """Test MIME type detection default fallback."""
        # Setup both to fail
        mockMagic.Magic.side_effect = ImportError("magic not available")
        mockMimetypes.guess_type.return_value = (None, None)

        # Create a temporary file
        with tempfile.NamedTemporaryFile() as tempFile:
            tempPath = tempFile.name

            # Test detection
            result = detectMimeType(tempPath)

            # Verify
            assert result == "application/octet-stream"

    @patch("lib.max_bot.file_utils.magic")
    @patch("lib.max_bot.file_utils.mimetypes")
    def testDetectMimeTypeWithOSError(self, mockMimetypes, mockMagic):
        """Test MIME type detection with OSError."""
        # Setup mock to raise OSError
        mockMagic.Magic.side_effect = OSError("File not found")
        # Setup mimetypes to also return None
        mockMimetypes.guess_type.return_value = (None, None)

        # Test with non-existent file - should fallback to default
        result = detectMimeType("/non/existent/file.jpg")
        # Should return default fallback when both magic and mimetypes fail
        assert result == "application/octet-stream"


class TestValidateFileSize:
    """Test file size validation functionality."""

    def testValidateFileSizeValid(self):
        """Test validation of file within size limit."""
        # Create a temporary file with known size
        with tempfile.NamedTemporaryFile() as tempFile:
            tempPath = tempFile.name
            # Write some data
            tempFile.write(b"x" * 1000)
            tempFile.flush()

            # Test validation with larger limit
            result = validateFileSize(tempPath, maxSize=2000)
            assert result is True

    def testValidateFileSizeTooLarge(self):
        """Test validation of file exceeding size limit."""
        # Create a temporary file with known size
        with tempfile.NamedTemporaryFile() as tempFile:
            tempPath = tempFile.name
            # Write some data
            tempFile.write(b"x" * 1000)
            tempFile.flush()

            # Test validation with smaller limit
            with pytest.raises(FileTooLargeError, match="exceeds maximum allowed size"):
                validateFileSize(tempPath, maxSize=500)

    def testValidateFileSizeNonExistent(self):
        """Test validation of non-existent file."""
        with pytest.raises(FileValidationError, match="Cannot access file"):
            validateFileSize("/non/existent/file.jpg")

    def testValidateFileSizeDefaultLimit(self):
        """Test validation with default size limit."""
        # Create a small temporary file
        with tempfile.NamedTemporaryFile() as tempFile:
            tempPath = tempFile.name
            tempFile.write(b"x" * 100)
            tempFile.flush()

            # Test with default limit (should pass)
            result = validateFileSize(tempPath)
            assert result is True


class TestValidateFileType:
    """Test file type validation functionality."""

    @patch("lib.max_bot.file_utils.detectMimeType")
    def testValidateFileTypeValid(self, mockDetect):
        """Test validation of valid file type."""
        # Setup mock
        mockDetect.return_value = "image/jpeg"

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tempFile:
            tempPath = tempFile.name

            # Test validation
            result = validateFileType(tempPath, ["image/jpeg", "image/png"])
            assert result is True

    @patch("lib.max_bot.file_utils.detectMimeType")
    def testValidateFileTypeUnsupported(self, mockDetect):
        """Test validation of unsupported file type."""
        # Setup mock
        mockDetect.return_value = "application/pdf"

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tempFile:
            tempPath = tempFile.name

            # Test validation
            with pytest.raises(UnsupportedFileTypeError, match="is not supported"):
                validateFileType(tempPath, ["image/jpeg", "image/png"])

    @patch("lib.max_bot.file_utils.detectMimeType")
    @patch("lib.max_bot.file_utils.getFileExtension")
    def testValidateFileTypeExtensionMismatch(self, mockGetExt, mockDetect):
        """Test validation with extension mismatch."""
        # Setup mocks
        mockDetect.return_value = "image/jpeg"
        mockGetExt.return_value = ".pdf"

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tempFile:
            tempPath = tempFile.name

            # Test validation
            with pytest.raises(UnsupportedFileTypeError, match="suggests type"):
                validateFileType(tempPath, ["image/jpeg", "image/png"])

    @patch("lib.max_bot.file_utils.detectMimeType")
    @patch("lib.max_bot.file_utils.getFileExtension")
    def testValidateFileTypeNoExtension(self, mockGetExt, mockDetect):
        """Test validation with no file extension."""
        # Setup mocks
        mockDetect.return_value = "image/jpeg"
        mockGetExt.return_value = ""

        # Create a temporary file
        with tempfile.NamedTemporaryFile() as tempFile:
            tempPath = tempFile.name

            # Test validation
            with pytest.raises(UnsupportedFileTypeError, match="no extension"):
                validateFileType(tempPath, ["image/jpeg", "image/png"])

    @patch("lib.max_bot.file_utils.detectMimeType")
    def testValidateFileTypeNoExtensionCheck(self, mockDetect):
        """Test validation without extension check."""
        # Setup mock
        mockDetect.return_value = "image/jpeg"

        # Create a temporary file
        with tempfile.NamedTemporaryFile() as tempFile:
            tempPath = tempFile.name

            # Test validation without extension check
            result = validateFileType(tempPath, ["image/jpeg", "image/png"], checkExtension=False)
            assert result is True


class TestGetFileExtension:
    """Test file extension extraction functionality."""

    def testGetFileExtensionWithExtension(self):
        """Test getting extension from file with extension."""
        result = getFileExtension("/path/to/file.jpg")
        assert result == ".jpg"

    def testGetFileExtensionMultipleDots(self):
        """Test getting extension from file with multiple dots."""
        result = getFileExtension("/path/to/file.name.with.dots.jpg")
        assert result == ".jpg"

    def testGetFileExtensionNoExtension(self):
        """Test getting extension from file without extension."""
        result = getFileExtension("/path/to/file")
        assert result == ""

    def testGetFileExtensionUppercase(self):
        """Test getting extension with uppercase."""
        result = getFileExtension("/path/to/file.JPG")
        assert result == ".jpg"

    def testGetFileExtensionWithPathObject(self):
        """Test getting extension with Path object."""
        result = getFileExtension(Path("/path/to/file.png"))
        assert result == ".png"


class TestSanitizeFilename:
    """Test filename sanitization functionality."""

    def testSanitizeFilenameNormal(self):
        """Test sanitization of normal filename."""
        result = sanitizeFilename("normal_file.jpg")
        assert result == "normal_file.jpg"

    def testSanitizeFilenameWithSpaces(self):
        """Test sanitization of filename with spaces."""
        result = sanitizeFilename("file with spaces.jpg")
        assert result == "file with spaces.jpg"

    def testSanitizeFilenameWithDangerousChars(self):
        """Test sanitization of filename with dangerous characters."""
        result = sanitizeFilename('file<>:"/\\|?*.jpg')
        assert result == "file_________.jpg"

    def testSanitizeFilenameWithControlChars(self):
        """Test sanitization of filename with control characters."""
        result = sanitizeFilename("file\x00\x1f.jpg")
        assert result == "file.jpg"

    def testSanitizeFilenameWithLeadingTrailingDots(self):
        """Test sanitization of filename with leading/trailing dots."""
        result = sanitizeFilename("...file.jpg...")
        assert result == "file.jpg"

    def testSanitizeFilenameEmpty(self):
        """Test sanitization of empty filename."""
        result = sanitizeFilename("")
        assert result == "unnamed_file"

    def testSanitizeFilenameTooLong(self):
        """Test sanitization of very long filename."""
        long_name = "a" * 300 + ".jpg"
        result = sanitizeFilename(long_name)
        assert len(result) <= 255
        assert result.endswith(".jpg")

    def testSanitizeFilenameOnlyDangerousChars(self):
        """Test sanitization of filename with only dangerous characters."""
        result = sanitizeFilename('<>:"/\\|?*')
        assert result == "_________"


class TestReadFileAsync:
    """Test asynchronous file reading functionality."""

    @pytest.mark.asyncio
    async def testReadFileAsyncSuccess(self):
        """Test successful async file reading."""
        # Create a temporary file with content
        content = b"Test content for async reading"
        with tempfile.NamedTemporaryFile(delete=False) as tempFile:
            tempPath = tempFile.name
            tempFile.write(content)
            tempFile.flush()

        try:
            # Test reading
            result = await readFileAsync(tempPath)
            assert result == content
        finally:
            os.unlink(tempPath)

    @pytest.mark.asyncio
    async def testReadFileAsyncWithChunks(self):
        """Test async file reading with custom chunk size."""
        # Create a temporary file with content
        content = b"x" * 100  # Small content for testing
        with tempfile.NamedTemporaryFile(delete=False) as tempFile:
            tempPath = tempFile.name
            tempFile.write(content)
            tempFile.flush()

        try:
            # Test reading with small chunk size
            result = await readFileAsync(tempPath, chunkSize=10)
            assert result == content
        finally:
            os.unlink(tempPath)

    @pytest.mark.asyncio
    async def testReadFileAsyncNonExistent(self):
        """Test async file reading of non-existent file."""
        with pytest.raises(FileValidationError, match="Cannot read file"):
            await readFileAsync("/non/existent/file.jpg")


class TestWriteFileAsync:
    """Test asynchronous file writing functionality."""

    @pytest.mark.asyncio
    async def testWriteFileAsyncSuccess(self):
        """Test successful async file writing."""
        content = b"Test content for async writing"

        with tempfile.TemporaryDirectory() as tempDir:
            tempPath = os.path.join(tempDir, "test_file.txt")

            # Test writing
            await writeFileAsync(tempPath, content)

            # Verify content
            with open(tempPath, "rb") as f:
                assert f.read() == content

    @pytest.mark.asyncio
    async def testWriteFileAsyncCreateDirectory(self):
        """Test async file writing with directory creation."""
        content = b"Test content for nested directory"

        with tempfile.TemporaryDirectory() as tempDir:
            tempPath = os.path.join(tempDir, "nested", "dir", "test_file.txt")

            # Test writing (should create directories)
            await writeFileAsync(tempPath, content)

            # Verify content
            with open(tempPath, "rb") as f:
                assert f.read() == content

    @pytest.mark.asyncio
    async def testWriteFileAsyncPermissionError(self):
        """Test async file writing with permission error."""
        content = b"Test content"

        # Try to write to a location that should cause permission error
        # Using a non-existent directory in root
        tempPath = "/root/nonexistent/test_file.txt"

        with pytest.raises(FileValidationError, match="Cannot write file"):
            await writeFileAsync(tempPath, content)


class TestGetAllowedTypesForUpload:
    """Test getting allowed MIME types for upload."""

    def testGetAllowedTypesImage(self):
        """Test getting allowed types for images."""
        result = getAllowedTypesForUpload("image")
        assert "image/jpeg" in result
        assert "image/png" in result
        assert "image/gif" in result
        assert "video/mp4" not in result

    def testGetAllowedTypesVideo(self):
        """Test getting allowed types for videos."""
        result = getAllowedTypesForUpload("video")
        assert "video/mp4" in result
        assert "video/avi" in result
        assert "image/jpeg" not in result

    def testGetAllowedTypesAudio(self):
        """Test getting allowed types for audio."""
        result = getAllowedTypesForUpload("audio")
        assert "audio/mpeg" in result
        assert "audio/wav" in result
        assert "image/jpeg" not in result

    def testGetAllowedTypesFile(self):
        """Test getting allowed types for documents."""
        result = getAllowedTypesForUpload("file")
        assert "application/pdf" in result
        assert "text/plain" in result
        assert "application/zip" in result

    def testGetAllowedTypesUnknown(self):
        """Test getting allowed types for unknown upload type."""
        result = getAllowedTypesForUpload("unknown")
        assert result == []


class TestValidateFileForUpload:
    """Test comprehensive file validation for upload."""

    @patch("lib.max_bot.file_utils.validateFileType")
    @patch("lib.max_bot.file_utils.validateFileSize")
    @patch("lib.max_bot.file_utils.detectMimeType")
    @patch("lib.max_bot.file_utils.getFileExtension")
    @patch("lib.max_bot.file_utils.sanitizeFilename")
    def testValidateFileForUploadSuccess(
        self, mockSanitize, mockGetExt, mockDetect, mockValidateSize, mockValidateType
    ):
        """Test successful file validation for upload."""
        # Setup mocks
        mockSanitize.return_value = "sanitized_file.jpg"
        mockGetExt.return_value = ".jpg"
        mockDetect.return_value = "image/jpeg"
        mockValidateSize.return_value = True
        mockValidateType.return_value = True

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tempFile:
            tempPath = tempFile.name
            tempFile.write(b"x" * 1000)
            tempFile.flush()

            # Test validation
            result = validateFileForUpload(tempPath, "image", maxSize=2000)

            # Verify result structure
            assert "file_path" in result
            assert "original_name" in result
            assert "sanitized_name" in result
            assert "size" in result
            assert "mime_type" in result
            assert "extension" in result
            assert "upload_type" in result
            assert "allowed_types" in result
            assert "max_size" in result

            # Verify values
            assert result["upload_type"] == "image"
            assert result["max_size"] == 2000
            assert result["sanitized_name"] == "sanitized_file.jpg"

    def testValidateFileForUploadNonExistent(self):
        """Test validation of non-existent file."""
        with pytest.raises(FileValidationError, match="File does not exist"):
            validateFileForUpload("/non/existent/file.jpg", "image")

    @patch("lib.max_bot.file_utils.validateFileType")
    @patch("lib.max_bot.file_utils.validateFileSize")
    @patch("lib.max_bot.file_utils.detectMimeType")
    @patch("lib.max_bot.file_utils.getFileExtension")
    @patch("lib.max_bot.file_utils.sanitizeFilename")
    def testValidateFileForUploadDefaultSize(
        self, mockSanitize, mockGetExt, mockDetect, mockValidateSize, mockValidateType
    ):
        """Test validation with default size limit."""
        # Setup mocks
        mockSanitize.return_value = "sanitized_file.jpg"
        mockGetExt.return_value = ".jpg"
        mockDetect.return_value = "image/jpeg"
        mockValidateSize.return_value = True
        mockValidateType.return_value = True

        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tempFile:
            tempPath = tempFile.name
            tempFile.write(b"x" * 1000)
            tempFile.flush()

            # Test validation without size parameter
            result = validateFileForUpload(tempPath, "image")

            # Verify default size is used
            assert result["max_size"] == MAX_FILE_SIZE


class TestProgressCallback:
    """Test progress callback functionality."""

    def testProgressCallbackInitialization(self):
        """Test progress callback initialization."""
        callback = Mock()
        progress = ProgressCallback(callback, totalSize=1000)

        assert progress.callback == callback
        assert progress.totalSize == 1000
        assert progress.transferred == 0
        assert progress.lastReportTime == 0
        assert progress.reportInterval == 1.0

    def testProgressCallbackUpdate(self):
        """Test progress callback update."""
        callback = Mock()
        progress = ProgressCallback(callback, totalSize=1000)

        # First update
        progress.update(100)
        assert progress.transferred == 100

        # Second update
        progress.update(200)
        assert progress.transferred == 300

        # Finish to ensure callback is called
        progress.finish()

        # The callback should be called at least once
        assert callback.call_count >= 1

        # Check callback arguments for the last call
        assert callback.call_args[0] == (300, 1000)

    def testProgressCallbackThrottled(self):
        """Test progress callback throttling."""
        callback = Mock()
        progress = ProgressCallback(callback, totalSize=1000)

        # Multiple rapid updates
        progress.update(100)
        progress.update(100)
        progress.update(100)

        # Finish to ensure callback is called
        progress.finish()

        # The callback should be called at least once
        assert callback.call_count >= 1

    def testProgressCallbackFinish(self):
        """Test progress callback finish."""
        callback = Mock()
        progress = ProgressCallback(callback, totalSize=1000)

        progress.transferred = 800
        progress.finish()

        callback.assert_called_with(800, 1000)

    def testProgressCallbackNoCallback(self):
        """Test progress callback without callback function."""
        progress = ProgressCallback(totalSize=1000)

        # Should not raise any errors
        progress.update(100)
        progress.finish()


class TestCopyWithProgress:
    """Test copy with progress functionality."""

    @pytest.mark.asyncio
    async def testCopyWithProgressPaths(self):
        """Test copying with progress using paths."""
        # Create source file
        content = b"x" * 100
        with tempfile.NamedTemporaryFile(delete=False) as sourceFile:
            sourcePath = sourceFile.name
            sourceFile.write(content)
            sourceFile.flush()

        # Create destination path
        with tempfile.TemporaryDirectory() as tempDir:
            destPath = os.path.join(tempDir, "dest_file.txt")

            try:
                # Setup progress callback
                callback = Mock()
                progress = ProgressCallback(callback, totalSize=len(content))

                # Test copy
                await copyWithProgress(sourcePath, destPath, progress)

                # Verify content
                with open(destPath, "rb") as f:
                    assert f.read() == content

                # Verify progress was tracked
                assert progress.transferred == len(content)
                callback.assert_called()

            finally:
                os.unlink(sourcePath)

    @pytest.mark.asyncio
    async def testCopyWithProgressFileObjects(self):
        """Test copying with progress using file objects."""
        # Create source file
        content = b"x" * 100
        with tempfile.NamedTemporaryFile(delete=False) as sourceFile:
            sourcePath = sourceFile.name
            sourceFile.write(content)
            sourceFile.flush()

        # Create destination path
        with tempfile.TemporaryDirectory() as tempDir:
            destPath = os.path.join(tempDir, "dest_file.txt")

            try:
                # Open file objects
                async with aiofiles.open(sourcePath, "rb") as sourceObj:
                    async with aiofiles.open(destPath, "wb") as destObj:
                        # Setup progress callback
                        callback = Mock()
                        progress = ProgressCallback(callback, totalSize=len(content))

                        # Test copy
                        await copyWithProgress(sourceObj, destObj, progress)

                # Verify content
                with open(destPath, "rb") as f:
                    assert f.read() == content

                # Verify progress was tracked
                assert progress.transferred == len(content)

            finally:
                os.unlink(sourcePath)

    @pytest.mark.asyncio
    async def testCopyWithProgressNoCallback(self):
        """Test copying without progress callback."""
        # Create source file
        content = b"x" * 100
        with tempfile.NamedTemporaryFile(delete=False) as sourceFile:
            sourcePath = sourceFile.name
            sourceFile.write(content)
            sourceFile.flush()

        # Create destination path
        with tempfile.TemporaryDirectory() as tempDir:
            destPath = os.path.join(tempDir, "dest_file.txt")

            try:
                # Test copy without callback
                await copyWithProgress(sourcePath, destPath)

                # Verify content
                with open(destPath, "rb") as f:
                    assert f.read() == content

            finally:
                os.unlink(sourcePath)

    @pytest.mark.asyncio
    async def testCopyWithProgressCustomChunkSize(self):
        """Test copying with custom chunk size."""
        # Create source file
        content = b"x" * 100
        with tempfile.NamedTemporaryFile(delete=False) as sourceFile:
            sourcePath = sourceFile.name
            sourceFile.write(content)
            sourceFile.flush()

        # Create destination path
        with tempfile.TemporaryDirectory() as tempDir:
            destPath = os.path.join(tempDir, "dest_file.txt")

            try:
                # Test copy with small chunk size
                await copyWithProgress(sourcePath, destPath, chunkSize=10)

                # Verify content
                with open(destPath, "rb") as f:
                    assert f.read() == content

            finally:
                os.unlink(sourcePath)
