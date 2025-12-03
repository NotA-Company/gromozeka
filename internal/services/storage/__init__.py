"""
Storage service package

This package provides a unified interface for storing and retrieving binary objects
across multiple backend implementations (Null, Filesystem, S3).
"""

from .service import StorageService

__all__ = ["StorageService"]
