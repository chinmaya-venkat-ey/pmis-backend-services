"""Permission code constants for pmis-masters-management (Option C — granular per-catalog).

Each of the 10 owned catalogs has TWO codes:
  - `<catalog>:read`   — gates GET endpoints (list + details)
  - `<catalog>:manage` — gates POST / PATCH / DELETE / restore

These string constants are used in route dependencies via
`Depends(require_permission(DIVISIONS_READ))` etc. The actual permission
records (rows in `users.permissions`) are SEEDED by the pmis-user-management
bootstrap data-migration; the `users.role_permissions` grants are also owned
by user-svc.

Default role-grant model (first-pass; finalized during user-svc port):
  - `<catalog>:read`   → every standard role
  - `<catalog>:manage` → super_admin + admin only

Row-level scoping beyond these auth gates (e.g. "org_admin only sees vendors
in their own organization") is applied as SERVICE-LAYER FILTERS, not as
additional permission codes. Each `<catalog>_service.py` inspects
`request.state.user_id` / `vendor_id` / `is_admin` and narrows results.
The exact filter rules are deferred to the user-svc port discussion.

WARNING: Each constant below MUST also exist in:
  - services/pmis-user-management/app/core/permissions.py
    (the canonical declaration; seeded into users.permissions)
  - The string code value MUST stay byte-identical across services.
Changes here without matching user-svc updates will fail the Q24
cross-schema drift CI test once user-svc is ported.

Legacy `MASTER_DATA_VIEW` / `MASTER_DATA_MANAGE` are NOT referenced by any
endpoint in this service. They remain in `users.permissions` for back-compat
during cutover; can be dropped post burn-in.
"""
from __future__ import annotations

from typing import Final


# =========================================================================
# Catalog: divisions
#   Used by FE: project-creation division picker, user-form division dropdown,
#   admin /masters/divisions CRUD page.
# =========================================================================
DIVISIONS_READ: Final[str] = "divisions:read"
DIVISIONS_MANAGE: Final[str] = "divisions:manage"


# =========================================================================
# Catalog: vendors  (a.k.a. "organizations" on the FE — wire keeps `vendor`)
#   Cross-schema FK target from users.users.vendor_id,
#   users.user_role_assignments.organization_id, project.project_vendors,
#   project.activities.vendor_id, project.milestone_vendors.
# =========================================================================
VENDORS_READ: Final[str] = "vendors:read"
VENDORS_MANAGE: Final[str] = "vendors:manage"


# =========================================================================
# Catalog: resource_types
#   FK target from project.activity_resources.type_of_resource_id.
# =========================================================================
RESOURCE_TYPES_READ: Final[str] = "resource_types:read"
RESOURCE_TYPES_MANAGE: Final[str] = "resource_types:manage"


# =========================================================================
# Catalog: priorities  (doc-41 — FE picker for milestones / tasks / subtasks)
# =========================================================================
PRIORITIES_READ: Final[str] = "priorities:read"
PRIORITIES_MANAGE: Final[str] = "priorities:manage"


# =========================================================================
# Catalog: project_categories  (doc-37 — FE picker for project create form)
# =========================================================================
PROJECT_CATEGORIES_READ: Final[str] = "project_categories:read"
PROJECT_CATEGORIES_MANAGE: Final[str] = "project_categories:manage"


# =========================================================================
# Catalog: activity_types  (doc-37)
# =========================================================================
ACTIVITY_TYPES_READ: Final[str] = "activity_types:read"
ACTIVITY_TYPES_MANAGE: Final[str] = "activity_types:manage"


# =========================================================================
# Catalog: activity_statuses  (doc-37)
# =========================================================================
ACTIVITY_STATUSES_READ: Final[str] = "activity_statuses:read"
ACTIVITY_STATUSES_MANAGE: Final[str] = "activity_statuses:manage"


# =========================================================================
# Catalog: milestone_statuses  (doc-37)
# =========================================================================
MILESTONE_STATUSES_READ: Final[str] = "milestone_statuses:read"
MILESTONE_STATUSES_MANAGE: Final[str] = "milestone_statuses:manage"


# =========================================================================
# Catalog: project_status_transitions  (doc — defines allowed state machine)
# =========================================================================
PROJECT_STATUS_TRANSITIONS_READ: Final[str] = "project_status_transitions:read"
PROJECT_STATUS_TRANSITIONS_MANAGE: Final[str] = "project_status_transitions:manage"


# =========================================================================
# Catalog: notification_templates  (moved here from notification-svc per Q3)
#   notification-svc reads cross-schema for dispatch + cron template render.
# =========================================================================
NOTIFICATION_TEMPLATES_READ: Final[str] = "notification_templates:read"
NOTIFICATION_TEMPLATES_MANAGE: Final[str] = "notification_templates:manage"


# =========================================================================
# Catalog: cost_types  (Project-Finance payment screen — Cost Type dropdown)
# =========================================================================
COST_TYPES_READ: Final[str] = "cost_types:read"
COST_TYPES_MANAGE: Final[str] = "cost_types:manage"


# =========================================================================
# Catalog: frequencies  (Project-Finance payment screen — Frequency dropdown)
# =========================================================================
FREQUENCIES_READ: Final[str] = "frequencies:read"
FREQUENCIES_MANAGE: Final[str] = "frequencies:manage"


# =========================================================================
# Catalog: payment_types  (milestone — Payment Type dropdown)
# =========================================================================
PAYMENT_TYPES_READ: Final[str] = "payment_types:read"
PAYMENT_TYPES_MANAGE: Final[str] = "payment_types:manage"


# =========================================================================
# Aggregate lists — used by the bootstrap migration and CI drift tests.
# =========================================================================
ALL_MASTERS_READ_PERMISSIONS: Final[tuple[str, ...]] = (
    DIVISIONS_READ,
    VENDORS_READ,
    RESOURCE_TYPES_READ,
    PRIORITIES_READ,
    PROJECT_CATEGORIES_READ,
    ACTIVITY_TYPES_READ,
    ACTIVITY_STATUSES_READ,
    MILESTONE_STATUSES_READ,
    PROJECT_STATUS_TRANSITIONS_READ,
    NOTIFICATION_TEMPLATES_READ,
    COST_TYPES_READ,
    FREQUENCIES_READ,
    PAYMENT_TYPES_READ,
)

ALL_MASTERS_MANAGE_PERMISSIONS: Final[tuple[str, ...]] = (
    DIVISIONS_MANAGE,
    VENDORS_MANAGE,
    RESOURCE_TYPES_MANAGE,
    PRIORITIES_MANAGE,
    PROJECT_CATEGORIES_MANAGE,
    ACTIVITY_TYPES_MANAGE,
    ACTIVITY_STATUSES_MANAGE,
    MILESTONE_STATUSES_MANAGE,
    PROJECT_STATUS_TRANSITIONS_MANAGE,
    NOTIFICATION_TEMPLATES_MANAGE,
    COST_TYPES_MANAGE,
    FREQUENCIES_MANAGE,
    PAYMENT_TYPES_MANAGE,
)

