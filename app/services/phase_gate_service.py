"""Phase-gate validator — RFP §5.28.2.a enforcement.

Blocks attaching an SLA whose ``sla.phase`` classifier disagrees with
the ``contract_phase_config`` entry for the activity's deliverable.
Example: a PMU resource-management SLA (phase=NONE, applies to all
phases) can attach to any activity; but SLA 001/002 (phase=PHASE_1)
must attach only to a Phase 1 deliverable (D1-D8 on PMU).

Deliverable code is extracted from the activity's own name or its
milestone's name via a simple ``\\bD\\d+`` regex — the naming
convention used consistently on the VM ("D6 - Enhanced functional…",
"D11 - Governance Tool"). When neither name matches, the gate SOFTS
(allows the attach) rather than blocking — better to over-allow than
break every attach for un-conventionally-named activities.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.utilities.logger import get_logger


logger = get_logger(__name__)


_DELIVERABLE_CODE_RE = re.compile(r"\bD(\d{1,2})\b", re.IGNORECASE)


def _extract_deliverable_code(name: Optional[str]) -> Optional[str]:
    """Return 'D<n>' from a name like 'D6 - Enhanced ...' or None."""
    if not name:
        return None
    m = _DELIVERABLE_CODE_RE.search(name)
    if not m:
        return None
    return f"D{int(m.group(1))}"


class PhaseGateService:
    """Validate SLA-to-activity attaches per RFP §5.28.2.a.

    Cross-schema reads into project.activities + project.milestones. No
    caching — mapping attach is rare (per-project setup) so a single
    SELECT is fine.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _lookup_deliverable_code(self, activity_id: str) -> Optional[str]:
        row = self.db.execute(
            text("""
                SELECT a.name AS activity_name, m.name AS milestone_name
                  FROM project.activities a
                  LEFT JOIN project.milestones m ON m.id = a.milestone_id
                 WHERE a.id = :aid
            """),
            {"aid": activity_id},
        ).first()
        if row is None:
            return None
        return (
            _extract_deliverable_code(row.activity_name)
            or _extract_deliverable_code(row.milestone_name)
        )

    def _lookup_config_phase(
        self, contract_type: str, deliverable_code: str,
    ) -> Optional[str]:
        return self.db.execute(
            text("""
                SELECT phase FROM contract.contract_phase_config
                 WHERE contract_type = :ct AND deliverable_code = :dc
            """),
            {"ct": contract_type, "dc": deliverable_code},
        ).scalar()

    def assert_phase_matches(
        self,
        *,
        contract_type: Optional[str],
        sla_phase: Optional[str],
        sla_ref: str,
        activity_id: str,
    ) -> None:
        """Raise ValidationError(422) if the SLA's phase doesn't match
        the activity's deliverable's configured phase.

        Fail-open on:
          * NULL / 'NONE' sla_phase (SLA is contract-wide)
          * contract_type is None (legacy SLAs without classifier)
          * activity not found (project-mgmt schema drift — don't block)
          * deliverable code un-extractable from activity/milestone name
          * no contract_phase_config row for the (contract_type, code)

        These fail-opens are logged so ops can spot mis-classifications
        without blocking any attach.
        """
        if not sla_phase or sla_phase.upper() == "NONE":
            return
        if not contract_type:
            logger.info(
                "phase-gate skipped for SLA '%s' — no contract_type set",
                sla_ref,
            )
            return
        dcode = self._lookup_deliverable_code(activity_id)
        if dcode is None:
            logger.info(
                "phase-gate: cannot extract deliverable code for activity=%s — "
                "attach allowed (SLA=%s phase=%s)",
                activity_id, sla_ref, sla_phase,
            )
            return
        config_phase = self._lookup_config_phase(contract_type, dcode)
        if config_phase is None:
            logger.info(
                "phase-gate: no contract_phase_config for (%s, %s) — attach allowed",
                contract_type, dcode,
            )
            return
        if config_phase != sla_phase:
            raise ValidationError(
                f"SLA '{sla_ref}' (phase={sla_phase}) cannot be attached to "
                f"deliverable {dcode} (phase={config_phase}) — RFP §5.28.2.a "
                f"forbids the mismatch.",
                code="phase_mismatch",
            )
