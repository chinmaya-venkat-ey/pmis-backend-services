"""Translation tables for the Activity Workflow integration.

EVERYTHING that depends on Java's specific vocabulary lives here so that
when the Java team confirms / changes a state name, an action verb, or a
role code, exactly one file changes.

Three concerns:
  1. Java state name  → FE-facing pill status (pending / approved /
     rejected) and the role(s) currently expected to act.
  2. PMIS role / division context → Java ``RequestInfo.roles`` codes.
  3. Local fallback state-machine: given the LAST transition's
     ``previousStatus + action``, what state are we in now? Used when
     Java's ``_search`` response does not carry an explicit
     ``currentStatus``.

Java vocabulary observed so far (per the Postman collections we have):
  Actions:  SUBMIT, APPROVE, REJECT, UPDATE
  States:   READYFORAPPROVAL, PENDINGATCONCERNEDDIVISION,
            PENDINGATOWNERDIVISION, APPROVED, REJECTED
            (terminal state name TBC — APPROVED vs COMPLETED)

If Java extends the vocabulary, edit the dicts below — no other file
needs to change.
"""
from __future__ import annotations

from typing import Dict, Tuple


# ── Java state names — keep these as named constants ──────────────────────
STATE_READY = "READYFORAPPROVAL"
STATE_PENDING_CONCERNED = "PENDINGATCONCERNEDDIVISION"
STATE_PENDING_OWNER = "PENDINGATOWNERDIVISION"
STATE_APPROVED = "APPROVED"
STATE_COMPLETED = "COMPLETED"  # alias some DIGIT installs use
# Terminal state the live Java service actually emits once the owner gives
# the final approval (verified in the Java source — its terminate state is
# ``ACTIVITYCOMPLETED``). Treated as a synonym of STATE_APPROVED everywhere
# the workflow is considered "done".
STATE_ACTIVITY_COMPLETED = "ACTIVITYCOMPLETED"
STATE_REJECTED = "REJECTED"


# Workflow states that mean "the approval is finished and the activity is
# approved" — i.e. the owner gave the final APPROVE. ``is_terminal_workflow_state``
# is the single gate the inbox service uses to decide when to mark the PMIS
# activity completed and roll the milestone up. Keep REJECTED OUT of this set:
# a rejection is terminal-for-this-round but must NOT complete the activity.
_TERMINAL_WORKFLOW_STATES: frozenset = frozenset({
    STATE_APPROVED, STATE_COMPLETED, STATE_ACTIVITY_COMPLETED,
})


def is_terminal_workflow_state(state: str) -> bool:
    """True when ``state`` is a workflow state that represents a fully
    approved (owner-approved) activity. This is the ONLY signal the inbox
    finalize path keys off — concerned-division approval lands at
    ``PENDINGATOWNERDIVISION`` (not in this set), so it never finalizes."""
    return (state or "").upper() in _TERMINAL_WORKFLOW_STATES


# ── Action verbs ───────────────────────────────────────────────────────────
ACTION_SUBMIT = "SUBMIT"
ACTION_APPROVE = "APPROVE"
ACTION_REJECT = "REJECT"
ACTION_UPDATE = "UPDATE"


# ── Pill-status mapping (Java → FE-facing) ─────────────────────────────────
# What the inbox row's "Status" column shows. Caller-relative
# adjustments (e.g. a concerned division sees ``approved`` once the
# state has moved past PENDINGATCONCERNEDDIVISION) live in the service
# layer using ``is_state_pending_for_role()`` below.
_STATE_TO_PILL: Dict[str, str] = {
    STATE_READY: "pending",
    STATE_PENDING_CONCERNED: "pending",
    STATE_PENDING_OWNER: "pending",
    STATE_APPROVED: "approved",
    STATE_COMPLETED: "approved",
    STATE_ACTIVITY_COMPLETED: "approved",
    STATE_REJECTED: "rejected",
}


def state_to_pill(state: str) -> str:
    """Map a Java state name to a FE-facing pill (``pending`` /
    ``approved`` / ``rejected``). Unknown states default to ``pending``."""
    return _STATE_TO_PILL.get(state or "", "pending")


# ── Role-context helpers ───────────────────────────────────────────────────

# What role is *currently* expected to act, per Java state.
_STATE_TO_ACTOR_ROLE: Dict[str, str] = {
    STATE_PENDING_CONCERNED: "concerned_division",
    STATE_PENDING_OWNER: "activity_owner",
}


def is_state_pending_for_role(state: str, role: str) -> bool:
    """Is the given Java state the one where ``role`` is supposed to
    act? Used to set ``my_view.can_approve`` / ``can_reject`` and to
    derive caller-relative row status."""
    return _STATE_TO_ACTOR_ROLE.get(state or "") == role


def states_pending_for_role(role: str) -> Tuple[str, ...]:
    """Return the Java state names the inbox should filter on for the
    given caller-role. Concerned-Division view = activities pending at
    PENDINGATCONCERNEDDIVISION. Owner view = pending at
    PENDINGATOWNERDIVISION."""
    if role == "concerned_division":
        return (STATE_PENDING_CONCERNED,)
    if role == "activity_owner":
        return (STATE_PENDING_OWNER,)
    return tuple(_STATE_TO_ACTOR_ROLE.keys())


# ── Local fallback state machine ───────────────────────────────────────────

# (previousStatus, action) → newStatus. Used to compute the CURRENT
# state from Java's ``_search`` response when no explicit ``currentStatus``
# field is present (the response we have today carries only
# ``previousStatus`` on each row, so we take the latest entry and apply
# this lookup).
#
# Confidence: SUBMIT and APPROVE are verified by the happy-path Postman
# collection. REJECT / UPDATE are inferred from the reject collection.
# Replace with Java's authoritative table once they provide one.
_TRANSITION_MAP: Dict[Tuple[str, str], str] = {
    (STATE_READY, ACTION_SUBMIT): STATE_PENDING_CONCERNED,
    (STATE_PENDING_CONCERNED, ACTION_APPROVE): STATE_PENDING_OWNER,
    (STATE_PENDING_CONCERNED, ACTION_REJECT): STATE_REJECTED,
    (STATE_PENDING_OWNER, ACTION_APPROVE): STATE_APPROVED,
    (STATE_PENDING_OWNER, ACTION_REJECT): STATE_REJECTED,
    (STATE_REJECTED, ACTION_UPDATE): STATE_READY,
    # After UPDATE the vendor SUBMITs again → back into the division stage.
}


def next_state(previous_status: str, action: str) -> str:
    """Apply ``(previousStatus, action) → newStatus``. Falls back to
    ``previous_status`` when the pair isn't mapped, so partial vocabulary
    drifts degrade gracefully."""
    return _TRANSITION_MAP.get(
        ((previous_status or "").upper(), (action or "").upper()),
        previous_status or "",
    )


# ── PMIS role → Java RequestInfo.roles mapping ─────────────────────────────
#
# The contextual flags ``is_concerned_division`` / ``is_owner_division``
# are computed by the caller (it requires knowing the activity), so this
# function takes them as parameters rather than the activity object.

_PMIS_ROLE_TO_JAVA_ROLE: Dict[str, str] = {
    "super_admin": "SUPER_ADMIN",
    "admin": "ADMIN",
    "pmis_admin": "PMIS_ADMIN",
    "project_admin": "PROJECT_ADMIN",
}


def build_java_roles(
    *,
    pmis_role_codes,
    is_concerned_division: bool = False,
    is_owner_division: bool = False,
) -> list[dict]:
    """Build the ``RequestInfo.roles`` list Java expects.

    Maps PMIS admin-tier roles 1:1 to Java equivalents. Adds the
    contextual ``CONCERNED_DIVISION`` / ``OWNER_DIVISION`` codes only
    when the caller's division matches the activity being acted on, so
    Java's permission gates see an honest picture.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for code in (pmis_role_codes or []):
        java = _PMIS_ROLE_TO_JAVA_ROLE.get((code or "").lower())
        if java and java not in seen:
            seen.add(java)
            out.append({"code": java, "name": java.replace("_", " ").title()})
    if is_concerned_division and "CONCERNED_DIVISION" not in seen:
        seen.add("CONCERNED_DIVISION")
        out.append({"code": "CONCERNED_DIVISION", "name": "Concerned Division"})
    if is_owner_division and "OWNER_DIVISION" not in seen:
        seen.add("OWNER_DIVISION")
        out.append({"code": "OWNER_DIVISION", "name": "Owner Division"})
    return out
