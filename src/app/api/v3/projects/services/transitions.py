"""
Project status lifecycle + editable-field whitelist.

Single source of truth for:
  - the allowed status vocabulary
  - which fields are editable in each project state
  - which (from, to) status transitions are legal, and by whom
  - owner-value validation (division code OR user login)
"""
from typing import Optional, Set, Tuple
from sqlalchemy.orm import Session

from .....core.errors import ValidationError
from .....domain.projects.project import Project
from .....domain.resource_types.resource_type import DIVISION_CHOICES
from .....infrastructure.db.repositories.project_repository import ProjectRepository


# ---------------------------------------------------------------------------
# Owner value resolution
# ---------------------------------------------------------------------------
#
# The HTML edit-project form renders the project Owner field with the same
# `buildDivisionField` widget that drives the activity-resource division
# picker. So the project owner is a DIVISION value, not a user reference.
# Allowed wire values:
#
#     'tmd1' | 'tmd2' | 'others'
#
# Stored lowercase regardless of caller casing (`TMD1` is normalised to
# `tmd1`). The 'others' free-text label captured by the FE goes into a
# separate `categoryOther`-style follow-up if/when product needs that —
# today the bare division code is enough.
#
# project_owners catalog (the per-user whitelist introduced in doc 15)
# was a user-based gate from before owner became a division field. It
# stopped being consulted in doc 18, and the table + endpoints were
# removed entirely in doc 20. Owner is strictly a division code now.

OWNER_DIVISION_CODES: Set[str] = {c.lower() for c in DIVISION_CHOICES}


def normalize_owner_value(owner: Optional[str]) -> Optional[str]:
    """Lowercase + strip an owner value, or return None.

    Empty / whitespace-only strings are treated as None so the caller
    can keep "owner is unset" semantics on PATCH.
    """
    if owner is None:
        return None
    s = owner.strip()
    if not s:
        return None
    return s.lower()


def assert_owner_is_division(owner: Optional[str]) -> None:
    """Raise ValidationError unless ``owner`` is a recognised division code.

    Caller is expected to call ``normalize_owner_value`` first; this
    function applies the strict membership check only.
    """
    if owner is None:
        return
    if owner not in OWNER_DIVISION_CODES:
        raise ValidationError(
            f"Owner must be one of: {', '.join(sorted(OWNER_DIVISION_CODES))}.",
        )


# `owner == 'others'` means the FE picker is on the free-text branch.
# Same idiom as ``category == 'others'`` requiring ``categoryOther``.
OWNER_OTHERS = "others"


def validate_owner_pair(
    owner: Optional[str],
    owner_other: Optional[str],
    *,
    require_owner: bool,
    db: Optional[Session] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Normalise + validate the ``(owner, owner_other)`` pair.

    Returns ``(normalised_owner, normalised_owner_other, error)``. ``error``
    is None on success; on failure it's a user-facing string the caller
    should return as a 422 ``validation_error``. The two normalised
    values are what the caller should pass downstream.

    Rules:
      * If ``owner`` is None or normalises to None and ``require_owner``
        is True → "Owner is required" error.
      * If ``db`` is supplied: ``owner`` must be the ``code`` of an
        active row in the ``divisions`` table (built-in OR user-added).
        If ``db`` is None: fall back to the in-code OWNER_DIVISION_CODES
        set (covers tests that don't run init_db).
      * When normalised owner == 'others': ``owner_other`` MUST be a
        non-empty string ≤ 255 chars; trimmed.
      * When normalised owner != 'others': ``owner_other`` MUST be None
        or an empty string; supplying a non-empty value is a 422.
    """
    n_owner = normalize_owner_value(owner)
    if n_owner is None:
        if require_owner:
            return (None, None, (
                f"Owner is required. Must be one of: "
                f"{', '.join(sorted(OWNER_DIVISION_CODES))}."
            ))
        # Field omitted on PATCH and not required → no-op.
        return (None, None, None)

    # Built-in codes (tmd1 / tmd2 / others) are ALWAYS accepted, even
    # when the divisions catalog hasn't been seeded (e.g. fresh in-memory
    # test DBs). User-added codes from the table EXTEND the accepted set.
    accepted_codes = set(OWNER_DIVISION_CODES)
    if db is not None:
        from .....infrastructure.db.repositories.division_repository import (
            DivisionRepository,
        )
        for row in DivisionRepository(db).list_active():
            accepted_codes.add(row.code)

    if n_owner not in accepted_codes:
        return (None, None, (
            f"Owner '{n_owner}' is not a known division. Pick one from "
            f"GET /divisions or use 'others' with a custom ownerOther "
            f"label."
        ))

    other_clean = (owner_other or "").strip()
    if n_owner == OWNER_OTHERS:
        if not other_clean:
            return (None, None, (
                "ownerOther is required (non-empty) when owner is 'others'."
            ))
        if len(other_clean) > 255:
            return (None, None, (
                "ownerOther must be 1-255 characters."
            ))
        return (n_owner, other_clean, None)

    # Not 'others' — owner_other MUST be empty.
    if other_clean:
        return (None, None, (
            "ownerOther may only be provided when owner is 'others'."
        ))
    return (n_owner, None, None)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

STATUS_NEW = "new"
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_CLOSED = "closed"

PROJECT_STATUS_CHOICES: Tuple[str, ...] = (
    STATUS_NEW,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUS_CLOSED,
)

CATEGORY_MSAP = "MSAP"
CATEGORY_MSIP = "MSIP"
CATEGORY_BSP = "BSP"
# Free-text category. When used, ``category_other`` on the project row MUST
# be a non-empty string (max 255 chars) — the create/upsert services enforce.
CATEGORY_OTHERS = "others"
PROJECT_CATEGORY_CHOICES: Tuple[str, ...] = (
    CATEGORY_MSAP,
    CATEGORY_MSIP,
    CATEGORY_BSP,
    CATEGORY_OTHERS,
)

# ---------------------------------------------------------------------------
# Editable field whitelist
# ---------------------------------------------------------------------------

# Snake_case names matching ProjectModel columns / ProjectUpdateRequest fields.
EDITABLE_FIELDS_PROJECT: Set[str] = {
    "name",
    "description",
    "owner",
    "owner_other",
    "start_date",
    "end_date",
    "actual_start_date",
    "actual_end_date",
    "active",
    "status_explanation",
    # Doc 38: ``public`` / ``category`` / ``category_other`` /
    # ``category_other_reason`` were removed from the editable surface.
    # DB columns kept (Option B deprecation); read-side keeps returning
    # them for legacy rows but PATCH and upsert no longer accept them.
}

# Doc 33: published projects keep the same editable surface — publish is now
# a sign-off marker (not a freeze). Closed projects reject every PATCH at
# the service layer separately.

# Status changes never flow through PATCH — they go through
# /publish, /close, /save which apply the transition state machine.
# PATCHing `status` returns 422 invalid_field with a hint pointing at the
# dedicated endpoints.


def editable_fields_for(project: Project) -> Set[str]:
    """Return the set of field names a PATCH may modify for this project.

    Every live (non-closed) project has the same editable surface.
    """
    return EDITABLE_FIELDS_PROJECT


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
#
# Legal (from_status, to_status) edges. Admin-only edges are tagged in
# ``ADMIN_ONLY_TRANSITIONS``.

_LEGAL_TRANSITIONS: Set[Tuple[str, str]] = {
    (STATUS_NEW, STATUS_DRAFT),
    (STATUS_DRAFT, STATUS_NEW),          # revert if milestones removed (allowed)
    (STATUS_NEW, STATUS_PUBLISHED),      # admin
    (STATUS_DRAFT, STATUS_PUBLISHED),    # admin
    (STATUS_NEW, STATUS_CLOSED),         # admin
    (STATUS_DRAFT, STATUS_CLOSED),       # admin
    (STATUS_PUBLISHED, STATUS_CLOSED),   # admin
    # Doc 33: published is a checkpoint, not a freeze. A published
    # project can be reverted to draft for further editing if needed.
    (STATUS_PUBLISHED, STATUS_DRAFT),
}

ADMIN_ONLY_TRANSITIONS: Set[Tuple[str, str]] = {
    (STATUS_NEW, STATUS_PUBLISHED),
    (STATUS_DRAFT, STATUS_PUBLISHED),
    (STATUS_NEW, STATUS_CLOSED),
    (STATUS_DRAFT, STATUS_CLOSED),
    (STATUS_PUBLISHED, STATUS_CLOSED),
    (STATUS_PUBLISHED, STATUS_DRAFT),
}


def assert_transition_allowed(
    *,
    from_status: str,
    to_status: str,
    actor_is_admin: bool,
    db: Optional[Session] = None,
) -> None:
    """Raise ValidationError if the requested status transition is illegal.

    Consults the ``project_status_transitions`` catalog table when ``db`` is
    supplied — that table is the runtime source of truth for legal edges,
    admin-gating, and version-gating, and ops can edit it without a code
    change. Falls back to the in-code constants when ``db`` is missing or the
    catalog has no rows for the edge (covers tests on a fresh in-memory DB
    before init_db has seeded the catalog).
    """
    from_status = (from_status or "").lower()
    to_status = (to_status or "").lower()

    if from_status == to_status:
        # No-op transitions are silently accepted by callers that pre-check;
        # if this helper is reached, treat as invalid to surface the mistake.
        raise ValidationError(
            "Status is already set to that value",
            details={
                "errorIdentifier": "invalid_transition",
                "from": from_status,
                "to": to_status,
            },
        )

    edge = (from_status, to_status)

    # Catalog-driven path. Find the active row for this edge; if present, it
    # wins over the in-code constants.
    catalog_row = None
    if db is not None:
        from .....infrastructure.db.repositories.project_status_transition_repository import (
            ProjectStatusTransitionRepository,
        )
        catalog_row = ProjectStatusTransitionRepository(db).find_edge(
            from_status, to_status,
        )

    if catalog_row is not None:
        requires_admin = bool(catalog_row.requires_admin)
    else:
        # Fallback: in-code constants. Used when the table hasn't been
        # seeded (e.g. fresh test DB) or no `db` was passed.
        if edge not in _LEGAL_TRANSITIONS:
            raise ValidationError(
                f"Illegal status transition: {from_status} -> {to_status}",
                details={
                    "errorIdentifier": "invalid_transition",
                    "from": from_status,
                    "to": to_status,
                },
            )
        requires_admin = edge in ADMIN_ONLY_TRANSITIONS

    if requires_admin and not actor_is_admin:
        raise ValidationError(
            f"Transition {from_status} -> {to_status} requires admin privileges",
            details={
                "errorIdentifier": "invalid_transition",
                "from": from_status,
                "to": to_status,
                "reason": "admin_required",
            },
        )


# ---------------------------------------------------------------------------
# Cross-module helper: new -> draft on first-milestone save
# ---------------------------------------------------------------------------

def transition_to_draft_if_new(
    db: Session,
    project_id: str,
    actor_id: Optional[str],
) -> Optional[Project]:
    """
    Flip status from 'new' to 'draft' when the M/A/T/S contributor's save
    finalizes (i.e., at least one milestone has been added and the user
    clicks Save Project). No-op if project is not in 'new'.

    Does NOT commit — caller (the M/A/T/S save endpoint) owns the transaction.
    Returns the updated Project when a transition happened, else None.
    """
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return None
    if (project.status or "").lower() != STATUS_NEW:
        return None

    updated = repo.update(
        project_id=project_id,
        status=STATUS_DRAFT,
        updated_by=actor_id,
    )
    # Audit is recorded by the caller (they know the triggering action).
    return updated
