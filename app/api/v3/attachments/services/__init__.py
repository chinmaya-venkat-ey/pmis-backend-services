"""Attachment services."""
from .upload import upload_standalone_attachment
from .download import open_attachment_for_download
from .delete import delete_attachment
from .list import list_standalone_attachments

__all__ = [
    "upload_standalone_attachment",
    "open_attachment_for_download",
    "delete_attachment",
    "list_standalone_attachments",
]
