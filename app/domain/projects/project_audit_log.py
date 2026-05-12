"""
Project audit log domain entity.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any, Dict
from ...shared.datetime import iso_ist


@dataclass
class ProjectAuditLog:
    id: int
    project_id: str
    # Doc 26: actor_id is a UUID string (was int pre-doc-26).
    actor_id: Optional[str]
    action: str
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]
    created_at: datetime
    # Doc 33: which role bucket the actor occupied at change time.
    actor_role: Optional[str] = None
    # Doc 47 (audit enrichment): denormalized fields captured at write
    # time. Optional on the dataclass so older test fixtures keep
    # compiling; the persistence layer guarantees them NOT NULL.
    actor_login: Optional[str] = None
    actor_code: Optional[str] = None
    project_name: Optional[str] = None
    project_status: Optional[str] = None
    owner: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_status": self.project_status,
            "owner": self.owner,
            "actor_id": self.actor_id,
            "actor_login": self.actor_login,
            "actor_code": self.actor_code,
            "actor_role": self.actor_role,
            "action": self.action,
            "before": self.before,
            "after": self.after,
            "created_at": iso_ist(self.created_at),
        }
