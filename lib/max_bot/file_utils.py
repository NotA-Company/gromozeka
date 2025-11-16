"""
File utilities for Max Messenger Bot API.

This module provides utility functions for file operations including MIME type detection,
file validation, and other helper functions for file uploads and downloads.
"""

import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import aiofiles
import magic

from .constants import MAX_FILE_SIZE
from .exceptions import MaxBotError


class FileValidationError(MaxBotError):
    """Exception raised when file validation fails."""

    pass


class FileTooLargeError(FileValidationError):
    """Exception raised when file exceeds size limit."""

    pass


class UnsupportedFileTypeError(FileValidationError):
    """Exception raised when file type is not supported."""

    pass


def detectMimeType(filePath: Union[str, Path]) -> str:
    """Detect MIME type from file path or content.

    Uses python-magic library for accurate MIME type detection based on file content.
    Falls back to mimetypes module if magic is not available.

    Args:
        filePath: Path to the file to analyze

    Returns:
        MIME type string (e.g., "image/jpeg", "video/mp4")

    Raises:
        FileValidationError: If file cannot be read or MIME type cannot be detected

    Example:
        >>> mime_type = detectMimeType("/path/to/file.jpg")
        >>> print(mime_type)  # "image/jpeg"
    """
    try:
        # Try to detect from file content using python-magic
        mime = magic.Magic(mime=True)
        detected_type = mime.from_file(str(filePath))

        if detected_type:
            return detected_type

    except (ImportError, OSError, FileNotFoundError):
        # Fallback to mimetypes module
        mime_type, _ = mimetypes.guess_type(str(filePath))
        if mime_type:
            return mime_type

    # Default fallback
    return "application/octet-stream"


def validateFileSize(filePath: Union[str, Path], maxSize: int = MAX_FILE_SIZE) -> bool:
    """Validate file size against maximum allowed size.

    Args:
        filePath: Path to the file to validate
        maxSize: Maximum allowed file size in bytes (default: 4GB)

    Returns:
        True if file size is valid

    Raises:
        FileTooLargeError: If file exceeds maximum size
        FileValidationError: If file cannot be accessed

    Example:
        >>> validateFileSize("/path/to/file.jpg", maxSize=10*1024*1024)  # 10MB
        >>> True
    """
    try:
        file_size = os.path.getsize(str(filePath))

        if file_size > maxSize:
            raise FileTooLargeError(f"File size {file_size} bytes exceeds maximum allowed size {maxSize} bytes")

        return True

    except OSError as e:
        raise FileValidationError(f"Cannot access file: {e}")


def validateFileType(filePath: Union[str, Path], allowedTypes: List[str], checkExtension: bool = True) -> bool:
    """Validate file type against allowed types.

    Args:
        filePath: Path to the file to validate
        allowedTypes: List of allowed MIME types (e.g., ["image/jpeg", "image/png"])
        checkExtension: Whether to also check file extension (default: True)

    Returns:
        True if file type is valid

    Raises:
        UnsupportedFileTypeError: If file type is not supported
        FileValidationError: If file cannot be read

    Example:
        >>> validateFileType(
        ...     "/path/to/file.jpg",
        ...     ["image/jpeg", "image/png"]
        ... )
        >>> True
    """
    # Detect MIME type from content
    mime_type = detectMimeType(filePath)

    # Check if MIME type is allowed
    if mime_type not in allowedTypes:
        raise UnsupportedFileTypeError(
            f"File type '{mime_type}' is not supported. " f"Allowed types: {', '.join(allowedTypes)}"
        )

    # Optionally check file extension
    if checkExtension:
        extension = getFileExtension(filePath)
        if not extension:
            raise UnsupportedFileTypeError("File has no extension")

        # Basic extension validation for common types
        extension_mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".wmv": "video/x-ms-wmv",
            ".flv": "video/x-flv",
            ".webm": "video/webm",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain",
            ".zip": "application/zip",
            ".rar": "application/x-rar-compressed",
        }

        expected_mime = extension_mime_map.get(extension.lower())
        if expected_mime and expected_mime not in allowedTypes:
            raise UnsupportedFileTypeError(
                f"File extension '{extension}' suggests type '{expected_mime}' " f"which is not in allowed types"
            )

    return True


def getFileExtension(filePath: Union[str, Path]) -> str:
    """Get file extension from file path.

    Args:
        filePath: Path to the file

    Returns:
        File extension including the dot (e.g., ".jpg", ".mp4")
        Returns empty string if no extension found

    Example:
        >>> extension = getFileExtension("/path/to/file.jpg")
        >>> print(extension)  # ".jpg"
    """
    return Path(filePath).suffix.lower()


def sanitizeFilename(filename: str) -> str:
    """Sanitize filename for safety and compatibility.

    Removes or replaces characters that could cause issues in file systems
    or API requests. Preserves Unicode characters while removing dangerous ones.

    Args:
        filename: Original filename to sanitize

    Returns:
        Sanitized filename safe for use in file operations

    Example:
        >>> safe_name = sanitizeFilename("my file?.jpg")
        >>> print(safe_name)  # "my_file_.jpg"
    """
    # Remove null bytes and control characters
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)

    # Replace dangerous characters with underscores
    dangerous_chars = r'[<>:"/\\|?*\x00-\x1f]'
    filename = re.sub(dangerous_chars, "_", filename)

    # Remove leading/trailing spaces and dots
    filename = filename.strip(" .")

    # Ensure filename is not empty
    if not filename:
        filename = "unnamed_file"

    # Limit filename length (255 characters is common limit)
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        max_name_len = 255 - len(ext)
        filename = name[:max_name_len] + ext

    return filename


async def readFileAsync(filePath: Union[str, Path], chunkSize: int = 8192) -> bytes:
    """Read file asynchronously in chunks.

    Args:
        filePath: Path to the file to read
        chunkSize: Size of chunks to read (default: 8KB)

    Returns:
        File content as bytes

    Raises:
        FileValidationError: If file cannot be read

    Example:
        >>> content = await readFileAsync("/path/to/file.jpg")
        >>> print(len(content))  # File size in bytes
    """
    try:
        async with aiofiles.open(str(filePath), "rb") as file:
            chunks = []
            while True:
                chunk = await file.read(chunkSize)
                if not chunk:
                    break
                chunks.append(chunk)

            return b"".join(chunks)

    except OSError as e:
        raise FileValidationError(f"Cannot read file: {e}")


async def writeFileAsync(filePath: Union[str, Path], content: bytes) -> None:
    """Write file asynchronously.

    Args:
        filePath: Path where to write the file
        content: File content as bytes

    Raises:
        FileValidationError: If file cannot be written

    Example:
        >>> await writeFileAsync("/path/to/output.jpg", file_content)
    """
    try:
        # Create directory if it doesn't exist
        Path(filePath).parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(str(filePath), "wb") as file:
            await file.write(content)

    except OSError as e:
        raise FileValidationError(f"Cannot write file: {e}")


def getAllowedTypesForUpload(uploadType: str) -> List[str]:
    """Get allowed MIME types for a specific upload type.

    Args:
        uploadType: Type of upload ("image", "video", "audio", "file")

    Returns:
        List of allowed MIME types for the upload type

    Example:
        >>> types = getAllowedTypesForUpload("image")
        >>> print(types)  # ["image/jpeg", "image/png", ...]
    """
    type_mapping = {
        "image": [
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/bmp",
            "image/tiff",
        ],
        "video": [
            "video/mp4",
            "video/avi",
            "video/quicktime",
            "video/x-msvideo",
            "video/x-ms-wmv",
            "video/x-flv",
            "video/webm",
            "video/matroska",
        ],
        "audio": [
            "audio/mpeg",
            "audio/wav",
            "audio/flac",
            "audio/aac",
            "audio/ogg",
            "audio/x-wav",
            "audio/mp4",
        ],
        "file": [
            # Documents
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/plain",
            "text/csv",
            "application/rtf",
            # Archives
            "application/zip",
            "application/x-rar-compressed",
            "application/x-7z-compressed",
            "application/gzip",
            "application/x-tar",
            # Other common types
            "application/octet-stream",
        ],
    }

    return type_mapping.get(uploadType, [])


def validateFileForUpload(filePath: Union[str, Path], uploadType: str, maxSize: Optional[int] = None) -> Dict[str, Any]:
    """Comprehensive file validation for upload.

    Validates file size, type, and other constraints for a specific upload type.

    Args:
        filePath: Path to the file to validate
        uploadType: Type of upload ("image", "video", "audio", "file")
        maxSize: Maximum allowed file size (uses default if None)

    Returns:
        Dictionary with validation results and file metadata

    Raises:
        FileValidationError: If validation fails

    Example:
        >>> result = validateFileForUpload("/path/to/file.jpg", "image")
        >>> print(result["mime_type"])  # "image/jpeg"
        >>> print(result["size"])  # File size in bytes
    """
    if maxSize is None:
        maxSize = MAX_FILE_SIZE

    # Get file metadata
    file_path = Path(filePath)
    if not file_path.exists():
        raise FileValidationError(f"File does not exist: {filePath}")

    file_size = file_path.stat().st_size
    mime_type = detectMimeType(filePath)
    extension = getFileExtension(filePath)
    sanitized_name = sanitizeFilename(file_path.name)

    # Validate size
    validateFileSize(filePath, maxSize)

    # Validate type
    allowed_types = getAllowedTypesForUpload(uploadType)
    if allowed_types:
        validateFileType(filePath, allowed_types)

    return {
        "file_path": str(file_path),
        "original_name": file_path.name,
        "sanitized_name": sanitized_name,
        "size": file_size,
        "mime_type": mime_type,
        "extension": extension,
        "upload_type": uploadType,
        "allowed_types": allowed_types,
        "max_size": maxSize,
    }


# Progress tracking utilities
class ProgressCallback:
    """Callback for tracking file upload/download progress."""

    def __init__(self, callback: Optional[Callable[[int, int], None]] = None, totalSize: Optional[int] = None):
        """Initialize progress callback.

        Args:
            callback: Function to call with (bytes_transferred, total_bytes)
            totalSize: Total size of the file (if known)
        """
        self.callback = callback
        self.totalSize = totalSize
        self.transferred = 0
        self.lastReportTime = 0
        self.reportInterval = 1.0  # Report at most once per second

    def update(self, chunkSize: int) -> None:
        """Update progress with transferred chunk size.

        Args:
            chunkSize: Number of bytes transferred in this chunk
        """
        self.transferred += chunkSize

        if self.callback:
            import time

            current_time = time.time()

            # Throttle reports to avoid too frequent updates
            if current_time - self.lastReportTime >= self.reportInterval:
                self.callback(self.transferred, self.totalSize or 0)
                self.lastReportTime = current_time

    def finish(self) -> None:
        """Call the callback one final time with complete progress."""
        if self.callback:
            self.callback(self.transferred, self.totalSize or 0)


async def copyWithProgress(
    source: Any, destination: Any, progressCallback: Optional[ProgressCallback] = None, chunkSize: int = 8192
) -> None:
    """Copy data with progress tracking.

    Args:
        source: Source file-like object or path
        destination: Destination file-like object or path
        progressCallback: Progress callback to track transfer
        chunkSize: Size of chunks to copy

    Example:
        >>> callback = ProgressCallback(lambda current, total: print(f"{current}/{total}"))
        >>> await copyWithProgress("source.jpg", "dest.jpg", callback)
    """
    # Handle string paths
    if isinstance(source, (str, Path)):
        source_file = await aiofiles.open(str(source), "rb")
        should_close_source = True
    else:
        source_file = source
        should_close_source = False

    if isinstance(destination, (str, Path)):
        dest_file = await aiofiles.open(str(destination), "wb")
        should_close_dest = True
    else:
        dest_file = destination
        should_close_dest = False

    try:
        while True:
            chunk = await source_file.read(chunkSize)
            if not chunk:
                break

            await dest_file.write(chunk)

            if progressCallback:
                progressCallback.update(len(chunk))

    finally:
        if progressCallback:
            progressCallback.finish()

        if should_close_source:
            await source_file.close()
        if should_close_dest:
            await dest_file.close()
