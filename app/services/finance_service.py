"""FinanceService — contract finance fields + CCN consumption rollup.

Owns the GET/PATCH /projects/{uuid}/finance flow:

  - ``summary``  — builds the aggregated finance view (TPV in/excl tax,
                   CCN cap/used/headroom/%, effective value, CCN items).
  - ``update``   — applies the publish-lock and writes the three
                   contract fields with an audit-log entry.

The CCN cap check (used by milestone / activity services on
create/update of CCN rows) lives in ``app/utilities/ccn_calc.py`` so
the two callers share exactly one rule.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ProjectNotFoundError
from app.repositories.finance_repository import FinanceRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.finance import CCNItem, FinanceSummaryResponse, FinanceUpdateRequest
from app.utilities import ccn_calc


# Fields owned by this service. Any subset of these may be sent on PATCH.
_FINANCE_FIELDS = (
    "total_project_value_excl_tax",
    "tax_percent",
    "ccn_cap_percent",
)


class FinanceService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.finance = FinanceRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ----------------------------------------------------------------- read

    def summary(self, project_id: str) -> FinanceSummaryResponse:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(
                f"Project with ID {project_id} not found"
            )
        return self._build_summary(project)

    # ----------------------------------------------------------------- write

    def update(
        self,
        project_id: str,
        payload: FinanceUpdateRequest,
        *, caller_user_id: Optional[str],
    ) -> FinanceSummaryResponse:
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(
                f"Project with ID {project_id} not found"
            )

        updates = payload.model_dump(exclude_unset=True)
        # Filter out fields not owned by this service (extra="forbid" on
        # the schema already prevents unknown keys, but be defensive).
        updates = {k: v for k, v in updates.items() if k in _FINANCE_FIELDS}

        if not updates:
            # No-op PATCH — return the current summary so the client gets
            # consistent shape regardless.
            return self._build_summary(project)

        # Publish-lock (Q3.1 default — "Final onboarding"). Once the
        # project is published all three finance fields are frozen.
        if (project.status or "").lower() == "published":
            raise ConflictError(
                "Finance fields are locked once the project is published. "
                "Edits are not permitted after publish.",
                code="conflict",
                details={
                    "project_id": project.id,
                    "project_status": project.status,
                    "locked_fields": list(_FINANCE_FIELDS),
                },
            )

        # Coerce Decimal-or-None values cleanly (Pydantic already
        # validated bounds via ge=0 / le=100).
        before = {k: getattr(project, k) for k in updates.keys()}
        self.projects.update(project, updated_by=caller_user_id, **updates)

        # Audit log — one entry per finance update with a before/after
        # diff for every touched field. Reuses the existing per-project
        # audit table (no new table).
        self.audit.write(
            project_id=project.id,
            target_kind="project", target_id=project.id,
            action="update_finance", actor_user_id=caller_user_id,
            changes={
                k: {
                    "before": _decimal_to_str(before[k]),
                    "after": _decimal_to_str(updates[k]),
                }
                for k in updates
            },
        )
        self.db.commit()
        return self._build_summary(project)

    # ----------------------------------------------------------- helpers

    def _build_summary(self, project) -> FinanceSummaryResponse:
        tpv_excl = project.total_project_value_excl_tax
        tax_pct = project.tax_percent
        cap_pct = project.ccn_cap_percent

        tpv_incl = ccn_calc.total_project_value_incl_tax(tpv_excl, tax_pct)
        cap_amount = ccn_calc.ccn_cap_amount(tpv_excl, cap_pct)
        used = self.finance.sum_ccn_used(project.id)
        used_pct = ccn_calc.ccn_used_percent(used, cap_amount)
        headroom = ccn_calc.ccn_headroom(used, cap_amount)
        effective = ccn_calc.effective_value(tpv_excl, used)
        cap_active = ccn_calc.is_cap_active(tpv_excl)
        is_locked = (project.status or "").lower() == "published"

        ccn_items = self._build_ccn_items(project.id)

        return FinanceSummaryResponse(
            project_id=project.id,
            project_code=project.project_code,
            status=project.status,
            total_project_value_excl_tax=_to_2dp(tpv_excl),
            tax_percent=_to_2dp(tax_pct),
            total_project_value_incl_tax=tpv_incl,
            ccn_cap_percent=_to_2dp(cap_pct),
            ccn_cap_amount=cap_amount,
            ccn_used=_to_2dp(used),
            ccn_used_percent=used_pct,
            ccn_headroom=headroom,
            effective_value=effective,
            is_locked=is_locked,
            cap_active=cap_active,
            ccn_items=ccn_items,
        )

    def _build_ccn_items(self, project_id: str):
        items: list[CCNItem] = []
        for mid, mname, mpos, mccn, mcreated in self.finance.list_ccn_milestones(project_id):
            items.append(CCNItem(
                level="Milestone",
                id=mid,
                display_code=f"M{mpos}" if mpos else None,
                name=mname,
                ccn_value=_to_2dp(mccn),
                created_at=mcreated,
            ))
        for aid, aname, mpos, apos, accn, acreated in self.finance.list_ccn_activities(project_id):
            display = None
            if mpos and apos:
                display = f"A{mpos}.{apos}"
            items.append(CCNItem(
                level="Activity",
                id=aid,
                display_code=display,
                name=aname,
                ccn_value=_to_2dp(accn),
                created_at=acreated,
            ))
        return items


def _to_2dp(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _decimal_to_str(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(Decimal(str(value)))
