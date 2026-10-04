"""
Storage service package

This package provides a unified interface for storing and retrieving binary objects
across multiple backend implementations (Null, Filesystem, S3).
"""

from .service import StorageScope, StorageService

__all__ = ["StorageScope", "StorageService"]
