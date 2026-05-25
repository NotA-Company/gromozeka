"""Metadata storage for sandbox sessions, runs, and runtimes.

This package provides data structures and protocols for persisting sandbox
metadata across storage backends. It separates the persistence interface
from concrete implementations, enabling pluggable storage mechanisms like
filesystem or database.

Key exports:
    SessionInfo: Dataclass representing persisted session metadata.
    MetadataStore: Protocol that all persistence backends must implement.
    FilesystemMetadataStore: Implementation backed by JSON files.

See also:
    base.py: Protocol definitions and core dataclasses.
    filesystem.py: Filesystem-backed metadata store implementation.
"""

from .base import MetadataStore
from .filesystem import FilesystemMetadataStore

__all__ = [
    "MetadataStore",
    "FilesystemMetadataStore",
]
