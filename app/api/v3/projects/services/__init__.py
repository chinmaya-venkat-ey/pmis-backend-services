"""
Project services module.
"""
from .create import create_project
from .get import get_project_by_id
from .list import list_projects
from .update import update_project
from .delete import delete_project
from .upsert import upsert_project
from .publish import publish_project
from .close import close_project
from .save import save_project_setup
from .transitions import (
    transition_to_draft_if_new,
    editable_fields_for,
    PROJECT_STATUS_CHOICES,
    PROJECT_CATEGORY_CHOICES,
)

__all__ = [
    "create_project",
    "get_project_by_id",
    "list_projects",
    "update_project",
    "delete_project",
    "upsert_project",
    "publish_project",
    "close_project",
    "save_project_setup",
    "transition_to_draft_if_new",
    "editable_fields_for",
    "PROJECT_STATUS_CHOICES",
    "PROJECT_CATEGORY_CHOICES",
]
