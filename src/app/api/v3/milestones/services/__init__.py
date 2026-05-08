"""Milestone services."""
from .create import create_milestone
from .get import get_milestone
from .list import list_milestones
from .update import update_milestone
from .delete import delete_milestone
from .restore import restore_milestone
from .cascade import cascade_soft_delete_project

__all__ = [
    "create_milestone", "get_milestone", "list_milestones",
    "update_milestone", "delete_milestone", "restore_milestone",
    "cascade_soft_delete_project",
]
