"""Attachment services (doc 35: thin wrappers over comments services).

After doc 35 the standalone attachments table is gone. These wrappers
preserve the FE-facing endpoint paths (POST/GET/DELETE under
``/<entity>/{id}/attachments`` and ``/attachments/{id}``) while routing
into the unified comments services. The streaming download endpoint
has been removed — clients fetch bytes directly from the URL stored
on the comment row.
"""
from .upload import upload_standalone_attachment
from .delete import delete_attachment
from .list import list_standalone_attachments

__all__ = [
    "upload_standalone_attachment",
    "delete_attachment",
    "list_standalone_attachments",
]
