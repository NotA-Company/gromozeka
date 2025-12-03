# Storage Service Usage Examples

Practical examples demonstrating how to use the Storage Service in various scenarios.

## Table of Contents

1. [Basic Usage](#basic-usage)
2. [Filesystem Backend](#filesystem-backend)
3. [S3 Backend](#s3-backend)
4. [Error Handling](#error-handling)
5. [Integration Patterns](#integration-patterns)
6. [Common Use Cases](#common-use-cases)
7. [Best Practices](#best-practices)

## Basic Usage

### Initialization

```python
from internal.config.manager import ConfigManager
from internal.services.storage import StorageService

# Initialize configuration manager
configManager = ConfigManager()

# Get storage service instance and inject config
storage = StorageService.getInstance()
storage.injectConfig(configManager)
```

### Store and Retrieve

```python
# Store binary data
documentData = b"This is my document content"
storage.store("document-123.txt", documentData)

# Retrieve data
retrievedData = storage.get("document-123.txt")
if retrievedData:
    print(f"Retrieved {len(retrievedData)} bytes, dood!")
else:
    print("Document not found, dood!")

# Check existence
if storage.exists("document-123.txt"):
    print("Document exists, dood!")

# Delete document
if storage.delete("document-123.txt"):
    print("Document deleted successfully, dood!")
```

### List Objects

```python
# List all objects
allKeys = storage.list()
print(f"Total objects: {len(allKeys)}")

# List with prefix filter
reports = storage.list(prefix="report-")
print(f"Found {len(reports)} reports")

# List with limit
recentLogs = storage.list(prefix="log-", limit=100)
print(f"Retrieved {len(recentLogs)} recent logs")
```

## Filesystem Backend

### Configuration

Create or update your config file:

```toml
[storage]
type = "fs"

[storage.fs]
base-dir = "./storage/objects"
```

### Usage Example

```python
from pathlib import Path
from internal.services.storage import StorageService

storage = StorageService.getInstance()

# Store a file
with open("input.pdf", "rb") as f:
    pdfData = f.read()
storage.store("report-2024.pdf", pdfData)

# Retrieve and save to different location
data = storage.get("report-2024.pdf")
if data:
    with open("output.pdf", "wb") as f:
        f.write(data)
    print("File retrieved and saved, dood!")
```

### Working with Images

```python
from PIL import Image
import io

# Store an image
with open("photo.jpg", "rb") as f:
    imageData = f.read()
storage.store("user-avatar-123.jpg", imageData)

# Retrieve and process image
imageData = storage.get("user-avatar-123.jpg")
if imageData:
    image = Image.open(io.BytesIO(imageData))
    # Process image
    thumbnail = image.resize((128, 128))
    
    # Store thumbnail
    thumbBuffer = io.BytesIO()
    thumbnail.save(thumbBuffer, format="JPEG")
    storage.store("user-avatar-123-thumb.jpg", thumbBuffer.getvalue())
```

## S3 Backend

### Configuration for AWS S3

```toml
[storage]
type = "s3"

[storage.s3]
endpoint = "https://s3.amazonaws.com"
region = "us-east-1"
key-id = "${AWS_ACCESS_KEY_ID}"
key-secret = "${AWS_SECRET_ACCESS_KEY}"
bucket = "my-app-storage"
prefix = "production/"
```

### Configuration for Yandex Object Storage

```toml
[storage]
type = "s3"

[storage.s3]
endpoint = "https://storage.yandexcloud.net"
region = "ru-central1"
key-id = "${YC_ACCESS_KEY_ID}"
key-secret = "${YC_SECRET_ACCESS_KEY}"
bucket = "my-app-storage"
prefix = "prod/"
```

### Usage Example

```python
from internal.services.storage import StorageService

storage = StorageService.getInstance()

# Store large file
with open("large-video.mp4", "rb") as f:
    videoData = f.read()
storage.store("videos/tutorial-001.mp4", videoData)

# List all videos
videos = storage.list(prefix="videos/")
print(f"Found {len(videos)} videos in storage, dood!")

# Retrieve specific video
videoData = storage.get("videos/tutorial-001.mp4")
if videoData:
    with open("downloaded-video.mp4", "wb") as f:
        f.write(videoData)
```

## Error Handling

### Basic Error Handling

```python
from internal.services.storage import StorageService
from internal.services.storage.exceptions import (
    StorageError,
    StorageKeyError,
    StorageConfigError,
    StorageBackendError
)

storage = StorageService.getInstance()

try:
    storage.store("my-document.pdf", documentData)
    print("Document stored successfully, dood!")
    
except StorageKeyError as e:
    print(f"Invalid key: {e}")
    # Handle invalid key (e.g., log error, notify user)
    
except StorageBackendError as e:
    print(f"Storage operation failed: {e}")
    if e.originalError:
        print(f"Original error: {e.originalError}")
    # Handle backend error (e.g., retry, use fallback)
    
except StorageError as e:
    print(f"General storage error: {e}")
    # Handle any other storage error
```

### Retry Logic with Exponential Backoff

```python
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def storeWithRetry(
    storage: StorageService,
    key: str,
    data: bytes,
    maxRetries: int = 3,
    baseDelay: float = 1.0
) -> bool:
    """
    Store data with retry logic for transient errors.
    
    Args:
        storage: StorageService instance
        key: Storage key
        data: Binary data to store
        maxRetries: Maximum number of retry attempts
        baseDelay: Base delay in seconds for exponential backoff
        
    Returns:
        True if successful, False otherwise
    """
    for attempt in range(maxRetries):
        try:
            storage.store(key, data)
            logger.info(f"Successfully stored {key}, dood!")
            return True
            
        except StorageKeyError as e:
            # Don't retry for invalid keys
            logger.error(f"Invalid key {key}: {e}")
            return False
            
        except StorageBackendError as e:
            if attempt < maxRetries - 1:
                delay = baseDelay * (2 ** attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{maxRetries} failed for {key}: {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"Failed to store {key} after {maxRetries} attempts: {e}")
                return False
                
    return False
```

### Graceful Degradation

```python
from typing import Optional

def getWithFallback(
    storage: StorageService,
    key: str,
    fallbackData: Optional[bytes] = None
) -> Optional[bytes]:
    """
    Retrieve data with fallback to default value on error.
    
    Args:
        storage: StorageService instance
        key: Storage key
        fallbackData: Data to return if retrieval fails
        
    Returns:
        Retrieved data, fallback data, or None
    """
    try:
        data = storage.get(key)
        if data is not None:
            return data
        logger.warning(f"Key {key} not found, using fallback")
        return fallbackData
        
    except StorageBackendError as e:
        logger.error(f"Failed to retrieve {key}: {e}, using fallback")
        return fallbackData
```

## Integration Patterns

### Using with Bot Message Attachments

```python
from internal.services.storage import StorageService
from internal.services.storage.exceptions import StorageError
import logging

logger = logging.getLogger(__name__)

class AttachmentHandler:
    """Handle bot message attachments using storage service."""
    
    def __init__(self, storage: StorageService):
        self.storage = storage
    
    def storeAttachment(self, chatId: int, messageId: int, fileData: bytes, filename: str) -> Optional[str]:
        """
        Store message attachment.
        
        Args:
            chatId: Chat ID
            messageId: Message ID
            fileData: File binary data
            filename: Original filename
            
        Returns:
            Storage key if successful, None otherwise
        """
        # Generate unique key
        key = f"attachments/{chatId}/{messageId}/{filename}"
        
        try:
            self.storage.store(key, fileData)
            logger.info(f"Stored attachment {key}, dood!")
            return key
        except StorageError as e:
            logger.error(f"Failed to store attachment: {e}")
            return None
    
    def getAttachment(self, key: str) -> Optional[bytes]:
        """
        Retrieve attachment by key.
        
        Args:
            key: Storage key
            
        Returns:
            File data if found, None otherwise
        """
        try:
            return self.storage.get(key)
        except StorageError as e:
            logger.error(f"Failed to retrieve attachment {key}: {e}")
            return None
    
    def cleanupOldAttachments(self, chatId: int, daysOld: int = 30):
        """
        Clean up old attachments for a chat.
        
        Args:
            chatId: Chat ID
            daysOld: Delete attachments older than this many days
        """
        prefix = f"attachments/{chatId}/"
        try:
            keys = self.storage.list(prefix=prefix)
            logger.info(f"Found {len(keys)} attachments for chat {chatId}")
            
            # In real implementation, would check timestamps
            # For now, just demonstrate the pattern
            for key in keys:
                # Check if old enough (implementation specific)
                # if isOldEnough(key, daysOld):
                #     self.storage.delete(key)
                pass
                
        except StorageError as e:
            logger.error(f"Failed to cleanup attachments: {e}")
```

### Caching Layer Pattern

```python
from typing import Optional, Callable
import hashlib

class CachedStorage:
    """Storage service with in-memory caching layer."""
    
    def __init__(self, storage: StorageService, maxCacheSize: int = 100):
        self.storage = storage
        self.cache: dict[str, bytes] = {}
        self.maxCacheSize = maxCacheSize
    
    def get(self, key: str) -> Optional[bytes]:
        """Get data with caching."""
        # Check cache first
        if key in self.cache:
            logger.debug(f"Cache hit for {key}")
            return self.cache[key]
        
        # Fetch from storage
        data = self.storage.get(key)
        if data is not None:
            # Add to cache
            self._addToCache(key, data)
        
        return data
    
    def store(self, key: str, data: bytes) -> None:
        """Store data and update cache."""
        self.storage.store(key, data)
        self._addToCache(key, data)
    
    def _addToCache(self, key: str, data: bytes) -> None:
        """Add item to cache with size limit."""
        if len(self.cache) >= self.maxCacheSize:
            # Remove oldest item (simple FIFO)
            oldestKey = next(iter(self.cache))
            del self.cache[oldestKey]
        
        self.cache[key] = data
```

## Common Use Cases

### Storing User Uploads

```python
def handleUserUpload(userId: int, fileData: bytes, filename: str) -> Optional[str]:
    """
    Handle user file upload.
    
    Args:
        userId: User ID
        fileData: Uploaded file data
        filename: Original filename
        
    Returns:
        Storage key if successful, None otherwise
    """
    storage = StorageService.getInstance()
    
    # Generate safe key
    timestamp = int(time.time())
    key = f"uploads/user-{userId}/{timestamp}-{filename}"
    
    try:
        storage.store(key, fileData)
        logger.info(f"User {userId} uploaded file: {key}")
        return key
    except StorageError as e:
        logger.error(f"Failed to store upload: {e}")
        return None
```

### Temporary File Storage

```python
import uuid
from datetime import datetime, timedelta

class TempFileStorage:
    """Manage temporary file storage with automatic cleanup."""
    
    def __init__(self, storage: StorageService):
        self.storage = storage
        self.tempPrefix = "temp/"
    
    def storeTempFile(self, data: bytes, ttlHours: int = 24) -> str:
        """
        Store temporary file.
        
        Args:
            data: File data
            ttlHours: Time to live in hours
            
        Returns:
            Temporary file key
        """
        # Generate unique key
        fileId = str(uuid.uuid4())
        key = f"{self.tempPrefix}{fileId}"
        
        self.storage.store(key, data)
        logger.info(f"Stored temp file {key} (TTL: {ttlHours}h)")
        
        return key
    
    def getTempFile(self, key: str) -> Optional[bytes]:
        """Retrieve temporary file."""
        if not key.startswith(self.tempPrefix):
            logger.warning(f"Invalid temp file key: {key}")
            return None
        
        return self.storage.get(key)
    
    def cleanupExpired(self):
        """Clean up expired temporary files."""
        try:
            tempFiles = self.storage.list(prefix=self.tempPrefix)
            logger.info(f"Checking {len(tempFiles)} temp files for cleanup")
            
            for key in tempFiles:
                # In real implementation, check file age
                # For now, just demonstrate the pattern
                pass
                
        except StorageError as e:
            logger.error(f"Failed to cleanup temp files: {e}")
```

### Document Versioning

```python
from datetime import datetime

class VersionedDocumentStorage:
    """Store documents with version history."""
    
    def __init__(self, storage: StorageService):
        self.storage = storage
    
    def storeVersion(self, docId: str, data: bytes) -> str:
        """
        Store new version of document.
        
        Args:
            docId: Document identifier
            data: Document data
            
        Returns:
            Version key
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        versionKey = f"docs/{docId}/versions/{timestamp}"
        
        # Store version
        self.storage.store(versionKey, data)
        
        # Update current version pointer
        currentKey = f"docs/{docId}/current"
        self.storage.store(currentKey, data)
        
        logger.info(f"Stored version {versionKey} for document {docId}")
        return versionKey
    
    def getCurrent(self, docId: str) -> Optional[bytes]:
        """Get current version of document."""
        currentKey = f"docs/{docId}/current"
        return self.storage.get(currentKey)
    
    def listVersions(self, docId: str) -> list[str]:
        """List all versions of document."""
        prefix = f"docs/{docId}/versions/"
        return self.storage.list(prefix=prefix)
```

## Best Practices

### 1. Key Naming Conventions

```python
# Good: Use hierarchical structure
storage.store("users/123/avatar.jpg", data)
storage.store("reports/2024/Q1/sales.pdf", data)
storage.store("logs/2024-01-15/app.log", data)

# Good: Include identifiers
storage.store(f"attachments/{chatId}/{messageId}/file.pdf", data)

# Avoid: Flat structure without organization
storage.store("file1.pdf", data)
storage.store("file2.pdf", data)
```

### 2. Error Handling

```python
# Always handle specific exceptions
try:
    storage.store(key, data)
except StorageKeyError:
    # Handle invalid key
    pass
except StorageBackendError:
    # Handle backend failure
    pass

# Log errors with context
logger.error(f"Failed to store {key}: {e}", exc_info=True)
```

### 3. Resource Management

```python
# Clean up temporary files
def processWithCleanup(storage: StorageService, tempKey: str):
    try:
        data = storage.get(tempKey)
        # Process data
        return processData(data)
    finally:
        # Always cleanup
        storage.delete(tempKey)
```

### 4. Validation

```python
# Validate before storing
def storeWithValidation(storage: StorageService, key: str, data: bytes):
    # Check size
    maxSize = 10 * 1024 * 1024  # 10 MB
    if len(data) > maxSize:
        raise ValueError(f"File too large: {len(data)} bytes")
    
    # Check key format
    if not key.endswith(('.pdf', '.jpg', '.png')):
        raise ValueError(f"Invalid file type: {key}")
    
    storage.store(key, data)
```

### 5. Monitoring and Logging

```python
import time

def storeWithMetrics(storage: StorageService, key: str, data: bytes):
    """Store with performance metrics."""
    startTime = time.time()
    
    try:
        storage.store(key, data)
        duration = time.time() - startTime
        logger.info(
            f"Stored {key}: {len(data)} bytes in {duration:.2f}s, dood!"
        )
    except StorageError as e:
        duration = time.time() - startTime
        logger.error(
            f"Failed to store {key} after {duration:.2f}s: {e}"
        )
        raise
```

## Related Documentation

- [Storage Service README](../../internal/services/storage/README.md) - Complete API reference
- [Design Document](../design/storage-service-design-v1.md) - Architecture and design decisions

---

**Note:** All examples use "dood!" suffix in log messages to maintain consistency with the project's Prinny-inspired style, dood!
