# Storage Service

A unified interface for storing and retrieving binary objects across multiple backend implementations (Null, Filesystem, S3).

## Overview

The Storage Service provides scoped singleton services that manage object storage operations through pluggable backend implementations: one instance per `StorageScope` member (`DEFAULT`, `VISION`), held in the per-scope `_instances` registry. The `DEFAULT` scope reads the top-level `[storage]` table (the long-standing attachments store); every other scope reads its own `[storage.storages.{scope}]` table. The service follows the same patterns as other services in the project (CacheService, LLMService) and integrates seamlessly with the ConfigManager.

**Key Features:**
- 🔌 **Pluggable Backends**: Support for Null, Filesystem, and S3 storage
- 🔒 **Security**: Automatic key sanitization to prevent path traversal attacks
- 🎯 **Simple API**: Consistent interface across all backends
- 🧵 **Thread-Safe**: Scoped singletons (one per `StorageScope`) with RLock for thread safety
- ⚙️ **Configuration-Driven**: Easy backend switching via configuration files
- 📝 **Comprehensive Logging**: Detailed logging for debugging and monitoring

## Quick Start

### Basic Usage

```python
from internal.services.storage import StorageService, StorageScope
from internal.config.manager import ConfigManager

# Initialize the service (default scope — the attachments store)
configManager = ConfigManager()
storage = StorageService.getInstance()
storage.injectConfig(configManager)

# Scoped access (e.g. the native-vision store; see Named Storages below)
visionStorage = StorageService.getInstance(StorageScope.VISION)
visionStorage.injectConfig(configManager, scope=StorageScope.VISION)

# Store binary data
storage.store("my-document.pdf", pdfData)

# Retrieve data
data = storage.get("my-document.pdf")
if data:
    print(f"Retrieved {len(data)} bytes, dood!")

# Check if object exists
if storage.exists("my-document.pdf"):
    print("Document exists, dood!")

# List objects with prefix
keys = storage.list(prefix="doc-", limit=10)
print(f"Found {len(keys)} documents, dood!")

# Delete object
if storage.delete("my-document.pdf"):
    print("Document deleted, dood!")
```

## Configuration

### Filesystem Backend (Development)

Store objects as files in a local directory:

```toml
[storage]
type = "fs"

[storage.fs]
base-dir = "./storage/objects"
```

**Features:**
- Automatic directory creation
- Atomic file operations
- File permissions: 0o644
- Flat storage structure (no subdirectories)

### Null Backend (Testing)

No-op backend for testing without actual storage:

```toml
[storage]
type = "null"
```

**Features:**
- All operations validate keys but perform no I/O
- store() does nothing
- get() always returns None
- exists() always returns False
- delete() always returns False
- list() always returns empty list

### S3 Backend (Production)

Store objects in AWS S3 or S3-compatible storage:

```toml
[storage]
type = "s3"

[storage.s3]
endpoint = "https://s3.amazonaws.com"
region = "us-east-1"
key-id = "${AWS_ACCESS_KEY_ID}"
key-secret = "${AWS_SECRET_ACCESS_KEY}"
bucket = "gromozeka-production"
prefix = "objects/"
```

**S3-Compatible Services:**

**Yandex Object Storage:**
```toml
[storage.s3]
endpoint = "https://storage.yandexcloud.net"
region = "ru-central1"
key-id = "${YC_ACCESS_KEY_ID}"
key-secret = "${YC_SECRET_ACCESS_KEY}"
bucket = "gromozeka-storage"
prefix = "prod/"
```

**MinIO:**
```toml
[storage.s3]
endpoint = "http://localhost:9000"
region = "us-east-1"
key-id = "${MINIO_ACCESS_KEY}"
key-secret = "${MINIO_SECRET_KEY}"
bucket = "gromozeka"
prefix = ""
```

### Named Storages (Scoped Instances)

Optional per-feature storages under `[storage.storages.NAME]`, each shaped **exactly like the default `[storage]` table** — a `type` key plus the optional `.fs`/`.s3` sub-tables with the same keys, and nothing else (there is no app-layer prefix key; separation from the default store comes from backend placement only — a different fs `base-dir` or a different bucket, with the backend-level s3 `prefix` as the only remaining prefix).

```toml
# [storage.storages.vision] — the native-vision store
# (today the only sanctioned named storage; see the StorageScope StrEnum)
[storage.storages.vision]
type = "fs"

[storage.storages.vision.fs]
base-dir = "storage/vision"

# S3 instead of fs:
# [storage.storages.vision.s3]
# endpoint = "https://s3.amazonaws.com"
# region = "us-east-1"
# key-id = "${AWS_ACCESS_KEY_ID}"
# key-secret = "${AWS_SECRET_ACCESS_KEY}"
# bucket = "your-bucket"
# prefix = "vision/"    # backend-level s3 prefix — the ONLY prefix that exists here
```

**Semantics:**

- An **absent** named table resolves to a silent `NullStorageBackend` — the feature stores nothing (feature off, not an error).
- A **present-but-malformed** table raises `StorageConfigError` at `injectConfig()` time and aborts startup, exactly like a bad default `[storage]` table.
- A named storage is selected via `StorageService.getInstance(StorageScope.NAME)` + `injectConfig(configManager, scope=StorageScope.NAME)`; arg-less `getInstance()` / `injectConfig(configManager)` calls still address the default attachments store.
- `StorageScope` is the closed set of sanctioned scopes: adding a storage later means one enum member plus its config table.

## API Reference

### StorageService

The scoped singleton service class: one instance per `StorageScope`, from the class-level `_instances` registry. Both `StorageService` and `StorageScope` are re-exported from the package root:

```python
from internal.services.storage import StorageService, StorageScope
```

#### getInstance(scope: StorageScope = StorageScope.DEFAULT) -> StorageService

Get the singleton instance for the given scope. Arg-less calls return the DEFAULT-scope instance (the attachments store) — every pre-existing call site is unchanged.

```python
storage = StorageService.getInstance()                           # default scope
visionStorage = StorageService.getInstance(StorageScope.VISION)  # vision scope
```

#### injectConfig(configManager: ConfigManager, scope: StorageScope = StorageScope.DEFAULT) -> None

Initialize this scope's instance with configuration. Must be called once per scope before using that instance. The DEFAULT scope reads the top-level `[storage]` table; any other scope reads its `[storage.storages.{scope.value}]` table — an absent table silently resolves to a null backend (feature off), while a present table is validated exactly like the default one (bad config raises, never falls back).

```python
storage.injectConfig(configManager)                                  # default scope
visionStorage.injectConfig(configManager, scope=StorageScope.VISION)  # vision scope
```

**Raises:**
- StorageConfigError: If configuration is invalid or backend creation fails (an absent NAMED table does not raise — it resolves to the null backend)

#### store(key: str, data: bytes) -> None

Store binary data under the specified key. Overwrites existing data if key already exists.

```python
storage.store("report.pdf", pdfBytes)
```

**Args:**
- key: Storage key (will be sanitized)
- data: Binary data to store

**Raises:**
- StorageKeyError: If key is invalid
- StorageBackendError: If storage operation fails

#### get(key: str) -> bytes | None

Retrieve binary data for the specified key.

```python
data = storage.get("report.pdf")
if data is None:
    print("Object not found, dood!")
```

**Args:**
- key: Storage key to retrieve

**Returns:**
- Binary data if key exists, None if not found

**Raises:**
- StorageKeyError: If key is invalid
- StorageBackendError: If retrieval fails

#### exists(key: str) -> bool

Check if an object exists for the specified key.

```python
if storage.exists("report.pdf"):
    print("Report exists, dood!")
```

**Args:**
- key: Storage key to check

**Returns:**
- True if key exists, False otherwise

**Raises:**
- StorageKeyError: If key is invalid
- StorageBackendError: If check fails

#### delete(key: str) -> bool

Delete the object for the specified key.

```python
if storage.delete("report.pdf"):
    print("Report deleted, dood!")
else:
    print("Report not found, dood!")
```

**Args:**
- key: Storage key to delete

**Returns:**
- True if object was deleted, False if it did not exist

**Raises:**
- StorageKeyError: If key is invalid
- StorageBackendError: If deletion fails

#### list(prefix: str = "", limit: int | None = None) -> list[str]

List all keys with optional prefix filter and limit.

```python
# List all keys
allKeys = storage.list()

# List with prefix
reports = storage.list(prefix="report-")

# List with limit
recent = storage.list(prefix="log-", limit=100)
```

**Args:**
- prefix: Optional prefix to filter keys (default: "" for all keys)
- limit: Optional maximum number of keys to return (default: None for no limit)

**Returns:**
- List of keys matching the prefix, up to the specified limit

**Raises:**
- StorageBackendError: If list operation fails

## Backend Comparison

| Feature | Null | Filesystem | S3 |
|---------|------|------------|-----|
| **Use Case** | Testing | Development, Small deployments | Production, Scalable deployments |
| **Performance** | Instant | Fast (local I/O) | Network-dependent |
| **Persistence** | None | Local disk | Cloud storage |
| **Scalability** | N/A | Limited by disk | Highly scalable |
| **Cost** | Free | Disk space | Pay per usage |
| **Setup** | None | Directory path | AWS/S3 credentials |
| **Concurrency** | N/A | File system limits | High |
| **Durability** | None | Single disk | 99.999999999% (S3) |

## Security Considerations

### Key Sanitization

All storage keys are automatically sanitized to prevent security vulnerabilities:

1. **Path Traversal Prevention**: Removes ../, /, \ sequences
2. **Control Character Removal**: Strips null bytes and ASCII control characters
3. **Character Whitelist**: Only allows alphanumeric, underscore, hyphen, and dot
4. **Length Validation**: Keys must be 1-255 characters after sanitization
5. **Dangerous Character Stripping**: Removes leading/trailing whitespace, dots, underscores

**Examples:**

```python
# Safe keys pass through unchanged
sanitizeKey("valid-key.txt")  # → "valid-key.txt"
sanitizeKey("report_2024.pdf")  # → "report_2024.pdf"

# Dangerous keys are sanitized
sanitizeKey("../../../etc/passwd")  # → "etc_passwd"
sanitizeKey("file/with/slashes")  # → "file_with_slashes"
sanitizeKey("  .hidden  ")  # → "hidden"

# Invalid keys raise StorageKeyError
sanitizeKey("")  # → StorageKeyError
sanitizeKey("   ")  # → StorageKeyError
sanitizeKey("a" * 300)  # → StorageKeyError (too long)
```

### Best Practices

1. **Use Environment Variables**: Store credentials in environment variables, not config files
2. **Principle of Least Privilege**: Use IAM roles/policies with minimal required permissions
3. **Enable Encryption**: Use S3 bucket encryption for sensitive data
4. **Validate Input**: Validate data before storing (size limits, content type, etc.)
5. **Monitor Access**: Enable logging and monitoring for production backends
6. **Backup Strategy**: Implement regular backups for filesystem backend

## Error Handling

### Exception Hierarchy

All storage exceptions inherit from StorageError:

```
StorageError (base)
├── StorageKeyError (invalid keys)
├── StorageConfigError (configuration errors)
└── StorageBackendError (backend operation failures)
```

### Error Handling Patterns

**Basic Error Handling:**

```python
from internal.services.storage import StorageService
from internal.services.storage.exceptions import (
    StorageError,
    StorageKeyError,
    StorageBackendError
)

try:
    storage.store("my-key", data)
except StorageKeyError as e:
    print(f"Invalid key: {e}")
except StorageBackendError as e:
    print(f"Storage failed: {e}")
    if e.originalError:
        print(f"Original error: {e.originalError}")
except StorageError as e:
    print(f"Storage error: {e}")
```

**Graceful Degradation:**

```python
def storeWithFallback(key: str, data: bytes) -> bool:
    """Store data with graceful error handling."""
    try:
        storage.store(key, data)
        return True
    except StorageKeyError:
        logger.error(f"Invalid storage key: {key}")
        return False
    except StorageBackendError as e:
        logger.error(f"Storage backend error: {e}")
        return False
```

**Retry Logic:**

```python
import time
from typing import Optional

def getWithRetry(key: str, maxRetries: int = 3) -> Optional[bytes]:
    """Retrieve data with retry logic for transient errors."""
    for attempt in range(maxRetries):
        try:
            return storage.get(key)
        except StorageBackendError as e:
            if attempt < maxRetries - 1:
                logger.warning(f"Retry {attempt + 1}/{maxRetries}: {e}")
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Failed after {maxRetries} attempts: {e}")
                raise
    return None
```

## Testing

### Running Tests

```bash
# Run all storage service tests
./venv/bin/python3 -m pytest tests/services/storage/ -v

# Run specific test file
./venv/bin/python3 -m pytest tests/services/storage/test_service.py -v

# Run with coverage
./venv/bin/python3 -m pytest tests/services/storage/ --cov=internal/services/storage --cov-report=html
```

### Test Structure

```
tests/services/storage/
├── test_service.py          # StorageService tests
├── test_sanitization.py     # Key sanitization tests
├── test_null_backend.py     # NullBackend tests
├── test_fs_backend.py       # FSBackend tests
├── test_s3_backend.py       # S3Backend tests (mocked)
└── test_integration.py      # Integration tests
```

### Writing Tests

**Resetting the scoped singletons:** `StorageService` keeps one instance per `StorageScope` in the class-level `_instances` registry — reset ALL scopes in fixtures with `StorageService._instances.clear()` (not `_instance = None`).

**Example Test:**

```python
import pytest
from internal.services.storage import StorageService
from internal.services.storage.exceptions import StorageKeyError

def test_store_and_retrieve(storage_service):
    """Test basic store and retrieve operations."""
    testData = b"Hello, dood!"
    
    storage_service.store("test-key", testData)
    retrieved = storage_service.get("test-key")
    assert retrieved == testData
    assert storage_service.exists("test-key")
    assert storage_service.delete("test-key")
    assert not storage_service.exists("test-key")

def test_invalid_key_raises_error(storage_service):
    """Test that invalid keys raise StorageKeyError."""
    with pytest.raises(StorageKeyError):
        storage_service.store("", b"data")
```

## Implementation Files

- service.py - StorageService scoped singletons + the `StorageScope` StrEnum
- exceptions.py - Exception classes
- utils.py - Key sanitization utilities
- backends/abstract.py - Abstract backend interface
- backends/null.py - Null backend implementation
- backends/filesystem.py - Filesystem backend implementation
- backends/s3.py - S3 backend implementation

## Future Enhancements

Potential features for future versions:

1. **Streaming Support**: Handle large files with streaming uploads/downloads
2. **Metadata Tracking**: Store and retrieve object metadata (size, type, modified time)
3. **Compression**: Automatic compression/decompression for stored objects
4. **Encryption**: At-rest encryption support for sensitive data
5. **Caching Layer**: LRU cache for frequently accessed objects
6. **Async Operations**: Full async/await support for better performance
7. **Object Versioning**: Keep multiple versions of objects
8. **Batch Operations**: Bulk store/delete operations
9. **Progress Callbacks**: Progress tracking for large file operations
10. **Additional Backends**: Azure Blob Storage, Google Cloud Storage

## Related Documentation

- Design Document: docs/archive/design/storage-service-design-v1.md
- Scoped-Storage Design: docs/design/scoped-storage-design-v1.md
- Usage Examples: docs/examples/storage-service-usage.md
- ConfigManager: internal/config/manager.py

## Support

For issues, questions, or contributions, please refer to the project's main documentation, dood!
