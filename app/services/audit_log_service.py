"""AuditLogService — paginated read of ``project.project_audit_logs`` for
a single project.

Powers ``GET /project/projects/{uuid}/audit-logs``. Returns the project
header alongside the paginated audit rows so the FE can render context
without a separate project read.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError
from app.models._cross_schema import Division, Role, User, UserRoleAssignment, Vendor
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository


def _serialize_entry(row, actor_map: dict, actor_role_map: dict) -> Dict[str, Any]:
    """Convert a ProjectAuditLog ORM row to a JSON-safe dict.

    Transformations applied for FE compatibility (Bug #10):
    - ``changes`` is flattened: per-field {before, after} deltas are
      aggregated into top-level ``before`` and ``after`` dicts.
    - Actor identity (login, user_code, role) is injected from the actor maps.
    """
    changes: dict = row.changes or {}

    # Aggregate per-field deltas produced by update audits.
    # create audits store {field: value} — treat as "after" only.
    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}
    for key, val in changes.items():
        if isinstance(val, dict) and "before" in val and "after" in val:
            before[key] = val["before"]
            after[key] = val["after"]
        else:
            after[key] = val

    actor_login = "—"
    actor_code = "—"
    actor_role = "—"
    if row.actor_user_id:
        u = actor_map.get(row.actor_user_id)
        if u:
            actor_login = u[0] or "—"
            actor_code = u[1] or row.actor_user_id
        else:
            actor_code = row.actor_user_id
        actor_role = actor_role_map.get(row.actor_user_id) or "—"

    entry: Dict[str, Any] = {
        "id": row.id,
        "project_id": row.project_id,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "action": row.action,
        "actor_user_id": row.actor_user_id,
        "actor_login": actor_login,
        "actor_code": actor_code,
        "actor_role": actor_role,
        "before": before,
        "after": after,
        "changes": changes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    # Drop ``note`` from the response when null — emit only when actually
    # populated (e.g. close action with a reason, reopen carrying the
    # prior reason, auto_complete carrying the marker message). Avoids
    # the blank ``"note": null`` field on every create/update row.
    if row.note is not None:
        entry["note"] = row.note
    return entry


class AuditLogService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def _load_actor_map(self, actor_ids: List[str]) -> Dict[str, tuple]:
        """Batch-load (login, user_code) for a set of user IDs."""
        if not actor_ids:
            return {}
        rows = self.db.execute(
            select(User.id, User.login, User.user_code).where(User.id.in_(actor_ids))
        ).all()
        return {uid: (login, code) for uid, login, code in rows}

    def _load_actor_roles(self, actor_ids: List[str]) -> Dict[str, str]:
        """Batch-resolve each actor's display ROLE for the audit-log Role column
        (Bug: roles not coming in audit logs). Joins the mirrored
        ``users.user_role_assignments`` → ``users.roles``. Prefers the actor's
        GLOBAL-scoped role(s) (org+project NULL — their tier, e.g. super_admin /
        admin); otherwise any role they hold. Distinct names are comma-joined.
        Returns ``{user_id: role_label}`` (absent when the actor holds no role)."""
        if not actor_ids:
            return {}
        rows = self.db.execute(
            select(
                UserRoleAssignment.user_id,
                Role.name,
                UserRoleAssignment.organization_id,
                UserRoleAssignment.project_id,
            )
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id.in_(actor_ids))
        ).all()
        global_roles: Dict[str, set] = {}
        scoped_roles: Dict[str, set] = {}
        for uid, name, org_id, project_id in rows:
            bucket = global_roles if (org_id is None and project_id is None) else scoped_roles
            bucket.setdefault(uid, set()).add(name)
        out: Dict[str, str] = {}
        for uid in set(global_roles) | set(scoped_roles):
            names = global_roles.get(uid) or scoped_roles.get(uid)
            if names:
                out[uid] = ", ".join(sorted(names))
        return out

    def _resolve_dep_codes(self, target_kind: str, project_id: str, uuids) -> List[str]:
        """Resolve a list of dependency-target UUIDs to their WBS display
        codes (M1 / A1.2 / T1.2.3 / S1.2.3.4…) for the given entity kind.
        Reuses the same resolvers the entity controllers use. Unresolved
        ids (e.g. a since-deleted target) are dropped — best-effort."""
        ids = [u for u in (uuids or []) if u]
        if not ids:
            return []
        if target_kind == "milestone":
            from app.controllers.milestone_controller import MilestoneController
            return MilestoneController(self.db)._resolve_milestone_display_codes(project_id, ids)
        if target_kind == "activity":
            from app.controllers.activity_controller import ActivityController
            return ActivityController(self.db)._resolve_activity_display_codes(project_id, ids)
        if target_kind == "task":
            from app.controllers.task_controller import TaskController
            return TaskController(self.db)._resolve_task_display_codes(project_id, ids)
        if target_kind == "subtask":
            from app.services.subtask_service import SubtaskService
            code_by_id = SubtaskService(self.db)._batch_resolve_display_codes(ids)
            return [code_by_id[u] for u in ids if u in code_by_id]
        return list(ids)

    def _enrich_dependency_display(self, entry: Dict[str, Any], row) -> None:
        """Make dependency changes render as WBS codes instead of opaque
        UUIDs. The FE diffs ``before``/``after`` (and the HAL layer camelCases
        the inner keys to ``dependsOn``, so the FE's snake-keyed override never
        fires) — so we replace the UUID list IN PLACE with display codes, and
        also surface ``dependsOnDisplay`` / ``dependsOnDisplayBefore`` at the
        top level for the FE's explicit path. ``changes`` is left raw (UUIDs)
        for fidelity."""
        before = entry.get("before") or {}
        after = entry.get("after") or {}
        if "depends_on" not in before and "depends_on" not in after:
            return
        kind = row.target_kind
        pid = row.project_id
        before_codes = self._resolve_dep_codes(kind, pid, before.get("depends_on"))
        after_codes = self._resolve_dep_codes(kind, pid, after.get("depends_on"))
        if "depends_on" in before:
            before["depends_on"] = before_codes
        if "depends_on" in after:
            after["depends_on"] = after_codes
        entry["depends_on_display"] = after_codes
        entry["depends_on_display_before"] = before_codes

    def _resolve_vendor_names(self, vendor_ids) -> List[str]:
        """Resolve vendor/organization UUIDs to their names via the
        masters.vendors mirror. Unknown ids fall back to the raw value."""
        ids = [v for v in (vendor_ids or []) if v]
        if not ids:
            return []
        rows = self.db.execute(
            select(Vendor.id, Vendor.name).where(Vendor.id.in_(ids))
        ).all()
        name_by_id = {vid: name for vid, name in rows}
        return [name_by_id.get(v, v) for v in ids]

    def _enrich_vendor_display(self, entry: Dict[str, Any], row) -> None:
        """Make organization (vendor) changes render as NAMES instead of
        UUIDs. Handles both wire shapes:
          * ``vendor_ids`` (list)  — project / milestone org membership
          * ``vendor_id``  (single)— activity organization
        Substituted in place in ``before``/``after`` (the FE renders those);
        ``changes`` stays raw for fidelity."""
        for side in (entry.get("before") or {}, entry.get("after") or {}):
            if isinstance(side.get("vendor_ids"), list):
                side["vendor_ids"] = self._resolve_vendor_names(side["vendor_ids"])
            if side.get("vendor_id"):
                names = self._resolve_vendor_names([side["vendor_id"]])
                side["vendor_id"] = names[0] if names else side["vendor_id"]

    def _resolve_owner_label(self, owner_code: str) -> str:
        """Look up the division label for a project owner code. Falls back
        to the raw code when the label cannot be resolved (null/"others"/
        unknown code) — Bug #149: audit-log Owner column must display the
        Division Label, not the Division Code."""
        if not owner_code or owner_code.lower() == "others":
            return owner_code
        label = self.db.execute(
            select(Division.label).where(Division.code == owner_code)
        ).scalar_one_or_none()
        return label or owner_code

    def list_for_project(
        self, project_id: str, *, offset: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        project = self.projects.get_by_id(project_id, include_deleted=True)
        if project is None:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        rows, total = self.audit.list_for_project(
            project_id, offset=offset, page_size=page_size,
        )

        actor_ids = list({r.actor_user_id for r in rows if r.actor_user_id})
        actor_map = self._load_actor_map(actor_ids)
        actor_role_map = self._load_actor_roles(actor_ids)

        elements = []
        for r in rows:
            entry = _serialize_entry(r, actor_map, actor_role_map)
            self._enrich_dependency_display(entry, r)
            self._enrich_vendor_display(entry, r)
            elements.append(entry)

        # Monolith parity: top-level Collection envelope with self-link,
        # count, and ``_embedded.elements`` (the wrap layer skips its
        # auto-wrap when ``_bare: True``).
        return {
            "_bare": True,
            "_type": "Collection",
            "_links": {
                "self": {
                    "href": (
                        f"/project/projects/{project_id}/audit-logs"
                        f"?offset={offset}&pageSize={page_size}"
                    ),
                },
            },
            "project": {
                "project_id": project.id,
                "project_code": project.project_code,
                "project_name": project.name,
                "project_status": project.status,
                # Bug #149: display the Division Label, not the Division Code.
                "owner": self._resolve_owner_label(project.owner),
                "owner_code": project.owner,
            },
            "total": total,
            "count": len(elements),
            "offset": offset,
            "page_size": page_size,
            "_embedded": {"elements": elements},
        }
