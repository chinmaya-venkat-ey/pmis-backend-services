"""Project audit log domain entity. Ported verbatim from the monolith."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

@dataclass
class ProjectAuditLog:
    id: int
    project_id: str
    actor_id: Optional[int]
    action: str
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]
    created_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "actor_id": self.actor_id,
            "action": self.action,
            "before": self.before,
            "after": self.after,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            }
