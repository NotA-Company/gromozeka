# Storage Service Design v1

**Author:** Roo (Architect Mode)  
**Date:** 2025-12-03  
**Status:** Draft - Awaiting Approval

## Overview

This document describes the design for a generic storage service that provides a unified interface for storing and retrieving binary objects across multiple backend implementations: Null, Filesystem, and S3.

## Goals

1. Provide a singleton service with a consistent API for object storage operations
2. Support multiple storage backends with runtime configuration
3. Follow existing project patterns established in the codebase
4. Ensure security through key sanitization to prevent path traversal attacks
5. Maintain simplicity with clear error handling semantics

## Non-Goals

The following are explicitly out of scope for version 1:
- Object versioning
- Object metadata tracking
- Streaming uploads or downloads
- Access control or permissions
- Encryption at rest

## Architecture

### Component Structure

Main Service Files:
- internal/services/storage/__init__.py
- internal/services/storage/service.py
- internal/services/storage/exceptions.py
- internal/services/storage/utils.py

Backend Files:
- internal/services/storage/backends/__init__.py
- internal/services/storage/backends/abstract.py
- internal/services/storage/backends/null.py
- internal/services/storage/backends/filesystem.py
- internal/services/storage/backends/s3.py

## Interface Design

### StorageService Class

The main service class following the singleton pattern used in CacheService and LLMService.

Methods:
- getInstance() - Get singleton instance
- injectConfig(configManager) - Initialize with configuration
- store(key, data) - Store binary data
- get(key) - Retrieve binary data, None when not found
- exists(key) - Check if object exists
- delete(key) - Delete object
- list(prefix, limit) - List objects with optional filtering

Attributes:
- _instance - Singleton instance
- _lock - Thread safety lock (RLock)
- backend - Active storage backend instance
- initialized - Initialization flag

### AbstractStorageBackend Interface

Base class that all backends must implement.

Required Methods:
- store(key, data) - Store binary data
- get(key) - Retrieve binary data or None when not found
- exists(key) - Check if object exists, returns boolean
- delete(key) - Delete object, returns boolean
- list(prefix, limit) - List objects with optional filtering

## Backend Implementations

### 1. NullStorageBackend

A no-op implementation for testing purposes.

Behavior:
- store: Does nothing, returns immediately
- get: Always returns None
- exists: Always returns False
- delete: Always returns False
- list: Always returns empty list

Use Cases:
- Unit testing without actual storage
- Disabling storage functionality
- Performance testing without I/O

### 2. FSStorageBackend

Stores objects as files in a local directory.

Configuration Parameter:
- base_dir: Base directory path for storage (required)

Implementation Details:
- Objects stored directly in base_dir with sanitized filenames
- Flat storage structure, no subdirectories
- Automatically creates base_dir if needed
- Uses atomic file operations where possible
- File permissions: 0o644

### 3. S3StorageBackend

Stores objects in AWS S3 or S3-compatible storage.

Configuration Parameters:
- endpoint: S3 endpoint URL
- region: AWS region (required)
- key_id: Access key ID (required)
- key_secret: Secret access key (required)
- bucket: S3 bucket name (required)
- prefix: Optional prefix for all keys

Implementation Details:
- Uses boto3 library
- Keys prefixed with configured prefix if provided
- Sanitized keys stored as object keys in S3
- Content-Type set to application/octet-stream

## Configuration Format

### Example: Development with Filesystem

[storage]
type = "fs"

[storage.fs]
base-dir = "./storage/objects"

### Example: Testing with Null Backend

[storage]
type = "null"

### Example: Production with S3

[storage]
type = "s3"

[storage.s3]
endpoint = "https://s3.amazonaws.com"
region = "us-east-1"
key-id = "${AWS_ACCESS_KEY_ID}"
key-secret = "${AWS_SECRET_ACCESS_KEY}"
bucket = "gromozeka-production"
prefix = "objects/"

### Example: Yandex Object Storage

[storage]
type = "s3"

[storage.s3]
endpoint = "https://storage.yandexcloud.net"
region = "ru-central1"
key-id = "${YC_ACCESS_KEY_ID}"
key-secret = "${YC_SECRET_ACCESS_KEY}"
bucket = "gromozeka-storage"
prefix = "prod/"

## Key Sanitization

### Security Considerations

To prevent path traversal attacks and ensure safe filenames:

1. Remove path separators like forward slash, backslash, and double-dot
2. Remove dangerous characters like null bytes and control characters
3. Trim whitespace from leading and trailing edges
4. Validate length is between 1 and 255 characters
5. Character whitelist: allow only alphanumeric, underscore, hyphen, dot

### Sanitization Algorithm

The sanitizeKey() function performs these steps in order:
1. Remove null bytes and control characters
2. Replace path separators with underscores
3. Remove double-dot sequences
4. Strip dangerous leading and trailing characters
5. Apply regex to allow only safe characters
6. Validate length is between 1-255 characters
7. Raise StorageKeyError if key is invalid

## Error Handling

### Exception Hierarchy

StorageError - Base exception for storage service

StorageKeyError - Raised when key is invalid, extends StorageError

StorageConfigError - Raised when configuration is invalid, extends StorageError

StorageBackendError - Raised when backend operation fails, extends StorageError

### Error Handling Rules

1. Missing Objects: get() returns None, exists() returns False, delete() returns False
2. Invalid Keys: Raise StorageKeyError immediately
3. Configuration Errors: Raise StorageConfigError during initialization
4. Backend Errors: Wrap backend-specific errors in StorageBackendError
5. Network Errors: Wrap in StorageBackendError with original exception details

### Logging

All operations will be logged appropriately:
- Info level for normal operations like initialization and successful stores
- Warning level for recoverable issues like missing objects
- Error level for failures like network errors and backend failures

## Integration

### ConfigManager Integration

Add a new method to ConfigManager class in internal/config/manager.py

Method name: getStorageConfig
Purpose: Get storage configuration from config files

### Service Initialization

In main application initialization, similar to CacheService:
1. Create singleton instance using StorageService.getInstance()
2. Inject configuration using injectConfig(configManager)

## Testing Strategy

### Unit Tests

Key Sanitization Tests:
- Valid keys pass through unchanged
- Path traversal attempts are properly sanitized
- Invalid characters are removed or replaced
- Edge cases: empty strings, very long strings, special characters

NullBackend Tests:
- All operations return expected no-op values
- No side effects or actual storage occurs

FSBackend Tests:
- Store and retrieve files correctly
- Directory creation works as expected
- File permissions are set correctly
- List operation works with and without prefix
- Delete operation works correctly
- Missing files handled properly

S3Backend Tests with mocks:
- boto3 client called with correct parameters
- Error handling works properly
- Prefix handling works correctly
- Credential configuration is properly used

### Integration Tests

Filesystem Integration:
- End-to-end store and retrieve cycle
- Persistence across service restarts
- Concurrent access handling

S3 Integration:
- Real S3 operations if available
- Network error handling
- Large file handling

### Test Structure

tests/services/storage/test_service.py - StorageService tests
tests/services/storage/test_sanitization.py - Key sanitization tests
tests/services/storage/test_null_backend.py - NullBackend tests
tests/services/storage/test_fs_backend.py - FSBackend tests
tests/services/storage/test_s3_backend.py - S3Backend tests with mocks
tests/services/storage/test_integration.py - Integration tests

## Implementation Plan

### Phase 1: Core Infrastructure
1. Create directory structure
2. Implement exception classes
3. Implement key sanitization utilities
4. Implement AbstractStorageBackend
5. Write sanitization tests

### Phase 2: Backend Implementations
1. Implement NullStorageBackend with tests
2. Implement FSStorageBackend with tests
3. Implement S3StorageBackend with mocked tests

### Phase 3: Service Layer
1. Implement StorageService singleton
2. Add configuration loading
3. Add backend factory and initialization
4. Write service tests

### Phase 4: Integration
1. Add getStorageConfig() to ConfigManager
2. Create default configuration files
3. Add service initialization to main app
4. Write integration tests
5. Update documentation

### Phase 5: Production Readiness
1. Add comprehensive logging
2. Performance testing
3. Documentation review
4. Code review
5. Deploy to staging environment

## Future Enhancements

Potential features for future versions:

1. Streaming Support for large files
2. Metadata Tracking for size, type, modified time
3. Compression with automatic compression/decompression
4. Encryption with at-rest encryption support
5. Caching with LRU cache layer for frequently accessed objects
6. Async Operations with full async/await support
7. Object Versioning to keep multiple versions
8. Batch Operations for bulk store/delete
9. Progress Callbacks for large file operations
10. Azure Blob Storage backend
11. Google Cloud Storage backend

## Open Questions

None at this time. All requirements have been clarified with the user.

## References

- CacheService Implementation: internal/services/cache/service.py
- LLMService Implementation: internal/services/llm/service.py
- ConfigManager Implementation: internal/config/manager.py
- boto3 Documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/index.html

---

**Review Status:** Awaiting user approval before implementation, dood!