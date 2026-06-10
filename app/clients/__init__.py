"""Cross-service HTTP / file clients.

``AnyFileClient`` is the Protocol-style union of the two upload backends
(``FileStoreClient`` for the S3 microservice and ``LocalFileClient`` for
NFS / dev). Anything that consumes a file client just types against the
union; the singleton resolver in ``dependencies.get_file_store_client``
returns whichever one .env says to use.
"""
from typing import Union

from app.clients.file_store_client import (
    FileStoreClient,
    FileStoreUnavailable,
    RefreshedUrl,
    StoredFile,
)
from app.clients.local_file_client import LocalFileClient
from app.clients.project_management_client import (
    ProjectManagementClient,
    ProjectManagementUnavailable,
)


# Both backends expose the same upload / refresh_url / delete surface;
# typing.Union is enough — no runtime protocol class needed.
AnyFileClient = Union[FileStoreClient, LocalFileClient]


__all__ = [
    "AnyFileClient",
    "FileStoreClient",
    "FileStoreUnavailable",
    "LocalFileClient",
    "ProjectManagementClient",
    "ProjectManagementUnavailable",
    "RefreshedUrl",
    "StoredFile",
]
