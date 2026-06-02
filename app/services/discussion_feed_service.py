"""DiscussionFeedService — unified paginated feed of every comment row
attached to the project or any of its M/A/T/S descendants.

Used by the project Activity tab on the FE so a single round-trip
returns both written discussion AND uploaded files across the entire
project subtree.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError
from app.models.activity import Activity
from app.models.milestone import Milestone
from app.models.subtask import Subtask
from app.models.task import Task
from app.repositories.comment_repository import CommentRepository
from app.repositories.project_repository import ProjectRepository


class DiscussionFeedService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)

    def list_for_project(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")

        db = self.db
        milestone_id_to_name = dict(db.execute(
            select(Milestone.id, Milestone.name)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
        ).all())
        activity_id_to_name = dict(db.execute(
            select(Activity.id, Activity.name)
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
        ).all())
        task_id_to_name = dict(db.execute(
            select(Task.id, Task.name)
            .where(Task.project_id == project_id)
            .where(Task.deleted_at.is_(None))
        ).all())
        subtask_id_to_name = dict(db.execute(
            select(Subtask.id, Subtask.name)
            .where(Subtask.project_id == project_id)
            .where(Subtask.deleted_at.is_(None))
        ).all())

        rows, total = self.comments.list_for_project_tree(
            project_id,
            milestone_ids=list(milestone_id_to_name.keys()),
            activity_ids=list(activity_id_to_name.keys()),
            task_ids=list(task_id_to_name.keys()),
            subtask_ids=list(subtask_id_to_name.keys()),
            offset=offset,
            page_size=page_size,
        )

        name_resolvers = {
            "project": {project_id: project.name},
            "milestone": milestone_id_to_name,
            "activity": activity_id_to_name,
            "task": task_id_to_name,
            "subtask": subtask_id_to_name,
        }

        elements: List[Dict[str, Any]] = []
        for c in rows:
            elements.append({
                "id": c.id,
                "target_kind": c.target_kind,
                "target_id": c.target_id,
                "target_name": name_resolvers.get(c.target_kind, {}).get(c.target_id),
                "body": c.body,
                "attachments": c.attachments or [],
                "created_at": c.created_at,
                "created_by": c.author_user_id,
            })

        # Monolith parity: Collection envelope with self-link, count, and
        # ``_embedded.elements``.
        return {
            "_bare": True,
            "_type": "Collection",
            "_links": {
                "self": {
                    "href": (
                        f"/project/projects/{project_id}/discussion-feed"
                        f"?offset={offset}&pageSize={page_size}"
                    ),
                },
            },
            "project": {"id": project.id, "name": project.name},
            "total": total,
            "count": len(elements),
            "offset": offset,
            "page_size": page_size,
            "_embedded": {"elements": elements},
        }
