"""File storage package.

Single-source implementation of the storage abstraction that backs
attachments. The default backend is a simple folder on disk — in
production that folder is an NFS mount point, in development it's a
local folder under the repo root. Either way the code path is the
same: plain Python file operations.

Public API:
    storage = get_storage()              # singleton bound to settings
    storage.save(key, file_obj)          # write bytes
    storage.open(key) -> file-like       # streaming read
    storage.delete(key)                  # remove file
    storage.exists(key) -> bool          # existence check
    storage.is_healthy() -> bool         # readiness probe
    storage.generate_storage_key(name)   # produce unique relative path
"""
from .file_storage import (
    FileStorage,
    StorageError,
    StorageUnavailableError,
    get_storage,
)

__all__ = [
    "FileStorage",
    "StorageError",
    "StorageUnavailableError",
    "get_storage",
]
