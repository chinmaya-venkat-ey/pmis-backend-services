"""Comments + attachments domain — Phases 11 + 12.

Polymorphic over the M/A/T/S nodes — single ``comments`` and
``attachments`` tables both serve milestones / activities / tasks /
subtasks via ``target_kind`` + ``target_id``.
"""
from .attachment import Attachment
from .comment import Comment

__all__ = ["Attachment", "Comment"]

# Allowed target kinds for comments and attachments.
TARGET_KINDS = ("milestone", "activity", "task", "subtask")
