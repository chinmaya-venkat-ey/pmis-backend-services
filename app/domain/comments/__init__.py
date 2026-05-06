"""Comments domain entities (doc 35: unified send-event model).

The legacy ``Attachment`` standalone domain entity is gone — file
metadata now travels embedded on the comment row as ``AttachmentInfo``.
"""
from .comment import AttachmentInfo, Comment

__all__ = ["AttachmentInfo", "Comment"]


# Allowed target kinds for comments + attachment-only sends.
# Mirrors the design (panel sits on every M/A/T/S node).
TARGET_KINDS = ("milestone", "activity", "task", "subtask")
