"""File storage package.

Public API has two layers:

  Low-level (still used internally for byte read/write):
      storage = get_storage()              # singleton bound to settings
      storage.save(key, file_obj)          # write bytes
      storage.open(key) -> file-like       # streaming read
      storage.delete(key)                  # remove file
      storage.exists(key) -> bool          # existence check
      storage.is_healthy() -> bool         # readiness probe
      storage.generate_storage_key(name)   # produce unique relative path

  High-level (doc 35: what services / controllers should call):
      client = get_file_client()
      info = client.upload(file_obj, original_filename, mime_type)
      # info.url is what gets persisted on the comment row.
      client.delete(storage_key)           # rollback on failure

The low-level layer is still exposed because the local-fallback
``GET /files/{key}`` route streams from it, and the cleanup cron
deletes by storage_key. Everything else should use ``get_file_client``.
"""
from .external_file_client import (
    FileClient,
    HttpExternalFileClient,
    LocalAndPublicUrlClient,
    StoredFile,
    get_file_client,
    reset_file_client_for_tests,
)
from .file_storage import (
    FileStorage,
    StorageError,
    StorageUnavailableError,
    get_storage,
)

__all__ = [
    "FileClient",
    "FileStorage",
    "HttpExternalFileClient",
    "LocalAndPublicUrlClient",
    "StorageError",
    "StorageUnavailableError",
    "StoredFile",
    "get_file_client",
    "get_storage",
    "reset_file_client_for_tests",
]
