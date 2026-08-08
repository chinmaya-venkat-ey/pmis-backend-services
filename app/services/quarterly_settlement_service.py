"""QuarterlySettlementService — Phase D quarter close.

The money layer: turns per-mapping aggregates (Phase B) + NPQP (Phase C)
into a single settlement row per (project, quarter) per RFP §5.28.1.d.h:

    LD_amount = min(Σ per-SLA LD%, contract_cap%) × NPQP  (§5.27.6 cap;
                                                          contract_cap%
                                                          from contract_ld_rules)
    AQP        = (PA − LD) + QGR                    (§5.28.1.d.h)

PA — payable for actual resource deployment for the quarter — is
sourced from the payment page (leave-mgmt already gives us F, which is
"planned"; PA is "actually paid based on attendance", but in the current
architecture the same cost/monthly endpoint is used for both). Phase E
wires the settlement's LD ₹ back into the payment page as a deduction
line item; that flow marks the settlement ``status='invoiced'``.

Auto-close trigger: run_daily calls ``close_projects_ready_to_close`` on
quarter_end + 1. Manual override via
``POST /sla-compliance/projects/{id}/settlement/{quarter}/override``.
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sla_definition import SlaDefinition

from app.core.errors import NotFoundError, ValidationError
from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_settlement_period import SlaSettlementPeriod
from app.repositories.sla_settlement_period_repository import (
    SlaSettlementPeriodRepository,
)
from app.services.npqp_service import NpqpService
from app.services.sla_compliance_service import SlaComplianceService
from app.utilities.logger import get_logger
from app.utilities.quarter import QuarterKey, quarter_of


logger = get_logger(__name__)


# Track B — SLA rules that participate in the quarterly-NPQP settlement.
# The SUM of these is capped per the contract's cap (from contract_ld_rules).
#   LADDER                     resource-based points ladder (SLA 004-011)
#   PER_UNIT_TIME_QUARTERLY    per-day × NPQP (SLA 003)
#   PER_OCCURRENCE             occurrence-count → severity (SLA 004 alt)
#   AVAILABILITY_UPTIME        MSIP §1.5.4 (evaluator TODO)
#   DAYS_WEIGHTED              BSP (evaluator TODO)
#
# Track A — SLA rules whose LD attaches to a specific deliverable's own
# invoice (RFP §5.28.2.b/c). NOT summed into the quarter cap:
#   PER_UNIT_TIME_DELIVERABLE  SLA 001/002, MSIP milestone
_TRACK_B_RULES = frozenset({
    "LADDER",
    "PER_UNIT_TIME_QUARTERLY",
    "PER_OCCURRENCE",
    "PER_UNIT_OVER_THRESHOLD",   # RFP §5.28.3.b (SLA 005)
    "AVAILABILITY_UPTIME",
    "DAYS_WEIGHTED",
})


def _resolve_cap_from_rules(rules: Dict[str, Decimal]) -> Optional[Decimal]:
    """Look up the quarterly cap from the contract's DSL rules.

    Returns None when the contract has no cap rule configured — caller
    must block the settlement in that case (never silently fall back to
    a hardcoded number, since each RFP's cap clause is contract-specific).
    """
    val = rules.get("quarterly_ld_cap_pct")
    return Decimal(str(val)) if val is not None else None


class QuarterlySettlementService:
    def __init__(
        self,
        db: Session,
        compliance_service: Optional[SlaComplianceService] = None,
        npqp_service: Optional[NpqpService] = None,
    ):
        self.db = db
        self.compliance = compliance_service or SlaComplianceService(db)
        self.npqp = npqp_service or NpqpService(db)
        self.repo = SlaSettlementPeriodRepository(db)

    # ------------------------------------------------------------------ close

    def close(
        self,
        project_id: str,
        qk: QuarterKey,
        *,
        mode: str = "auto",
        closed_by: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> SlaSettlementPeriod:
        """Compute + persist the quarter-close settlement row.

        Idempotent — re-invoking updates the row unless status='invoiced'
        (Phase E locks that transition). ``mode`` labels the status
        ('auto' → 'auto_closed', 'manual' → 'auto_closed' with a
        distinct ``closed_by``); genuine finance overrides go through
        ``override`` below.
        """
        existing = self.repo.get(project_id=project_id, qk=qk)
        if existing is not None and existing.status == "invoiced":
            # Immutable. Caller must issue a credit note instead.
            return existing

        # 1. Refresh Phase B aggregates for this project × quarter before
        #    reading them — a late observation lands in the aggregate
        #    within the same call so the settlement reflects it.
        self.compliance.rollup_project_for_quarter(project_id, qk)
        all_aggregates = self.compliance.qtr_agg_repo.list_for_project_quarter(
            project_id=project_id, qk=qk,
        )

        # 2. Track A/B split — RFP §5.28.2 vs §5.28.3.
        #    Only Track B (NPQP-based) rules participate in the quarter
        #    settlement's LD sum + cap. Track A (per-deliverable rules)
        #    have their own LD calc and are billed on the deliverable's
        #    OWN invoice line — surfaced via a separate endpoint that
        #    project-mgmt's payment page consumes per cost item.
        rule_by_sla_id = self._load_rule_by_sla_id(
            {a.sla_id for a in all_aggregates}
        )
        # Only rules explicitly classified as Track B participate in the
        # settlement. Unclassified SLAs (ld_formula_rule IS NULL) are
        # EXCLUDED — safer than assuming a default, since we can't know
        # whether an unclassified SLA is per-deliverable (Track A) or
        # NPQP-based (Track B). Ops sees them in the audit endpoint but
        # they don't contribute to the money math.
        unclassified = [a for a in all_aggregates if rule_by_sla_id.get(a.sla_id) is None]
        if unclassified:
            logger.info(
                "Settlement close for %s %s: %d aggregate rows have "
                "unclassified ld_formula_rule and are excluded from the "
                "quarter cap math (sla_ids=%s). Classify via "
                "sla_definitions.ld_formula_rule to include.",
                project_id, qk.label(), len(unclassified),
                sorted({a.sla_id for a in unclassified})[:5],
            )
        aggregates = [
            a for a in all_aggregates
            if (rule_by_sla_id.get(a.sla_id) or "") in _TRACK_B_RULES
        ]

        # 3. Sum per-SLA LD % (uncapped) → cap at the RFP quarter cap.
        sum_ld = sum(
            (Decimal(str(a.ld_percent)) for a in aggregates if a.ld_percent is not None),
            Decimal("0"),
        )
        # Cap is DATA-DRIVEN — sourced from contract_ld_rules keyed on the
        # project's contract type. Every contract's RFP has its own cap
        # clause (PMU §5.27.6, MSAP Annexure-3E, MSIP §1.5.5, BSP §22 —
        # all coincide at 10% today but stay independently configurable).
        # ``_resolve_contract_type`` uses ALL aggregates (Track A included)
        # so a project with only Track A SLAs still resolves its type;
        # falls back to a cross-schema query for empty quarters.
        contract_type = self._resolve_contract_type(all_aggregates, project_id=project_id)
        rules = self.compliance.evaluator._load_contract_ld_rules(contract_type)
        cap_pct = _resolve_cap_from_rules(rules)

        # No cap configured for this contract → block the settlement rather
        # than pick a magic number. The cap is a contract-specific RFP
        # clause; a missing rule is a data-config bug, not a runtime
        # fallback situation. Ops sees the block reason and fixes the seed.
        if cap_pct is None:
            logger.warning(
                "Settlement close for %s %s blocked — no "
                "quarterly_ld_cap_pct rule for contract_type=%r. "
                "Seed contract.contract_ld_rules for this contract.",
                project_id, qk.label(), contract_type,
            )
            return self.repo.upsert(
                project_id=project_id,
                contract_type=contract_type,
                qk=qk,
                sum_ld_percent=sum_ld,
                capped_ld_percent=None,
                f_amount=None, qgr_amount=None, npqp=None,
                ld_amount=None, pa_amount=None, aqp_amount=None,
                status="blocked_missing_cap",
                closed_by=closed_by,
                override_reason=None,
                source_aggregate_ids=[a.id for a in aggregates],
                consequence_flags={
                    "missing_rule": "quarterly_ld_cap_pct",
                    "contract_type": contract_type,
                },
            )

        capped_ld = min(sum_ld, cap_pct)

        # 3. NPQP for the quarter (Phase C). Bearer forwarded so leave-mgmt
        #    validates against the CALLER, not a service account.
        npqp_resp = self.npqp.compute(project_id, qk, bearer_token=bearer_token)

        # 4. LD ₹ = capped% × NPQP. Block when NPQP couldn't be computed.
        if npqp_resp.status != "ok":
            logger.warning(
                "Settlement close for %s %s blocked — NPQP status=%s",
                project_id, qk.label(), npqp_resp.status,
            )
            return self.repo.upsert(
                project_id=project_id,
                contract_type=contract_type,
                qk=qk,
                sum_ld_percent=sum_ld,
                capped_ld_percent=capped_ld,
                f_amount=npqp_resp.f_amount,
                qgr_amount=npqp_resp.qgr_amount,
                npqp=npqp_resp.npqp,
                ld_amount=None,      # unknown — NPQP unavailable
                pa_amount=None,
                aqp_amount=None,
                status="blocked_missing_npqp",
                closed_by=closed_by,
                override_reason=None,
                source_aggregate_ids=[a.id for a in aggregates],
                consequence_flags={"npqp_status": npqp_resp.status},
            )

        npqp = npqp_resp.npqp
        ld_amount = (capped_ld / Decimal("100")) * npqp
        # PA — actual attendance-adjusted payment (RFP §5.28.1.d.g). Distinct
        # from F: F is what the resource-deployment plan says the consultant
        # would be paid at full attendance; PA is what leave-mgmt's per-month
        # cost actually resolves to after leaves / absences. LD is calculated
        # on NPQP (F+QGR) per §5.28.1.d.f but deducted from PA per §5.28.1.d.h,
        # so a shortfall on attendance reduces the AQP linearly.
        pa = npqp_resp.pa_amount
        aqp = (pa - ld_amount) + npqp_resp.qgr_amount

        row = self.repo.upsert(
            project_id=project_id,
            contract_type=contract_type,
            qk=qk,
            sum_ld_percent=sum_ld,
            capped_ld_percent=capped_ld,
            f_amount=npqp_resp.f_amount,
            qgr_amount=npqp_resp.qgr_amount,
            npqp=npqp,
            ld_amount=ld_amount,
            pa_amount=pa,
            aqp_amount=aqp,
            status="auto_closed",
            closed_by=closed_by,
            override_reason=None,
            source_aggregate_ids=[a.id for a in aggregates],
        )
        return row

    # ------------------------------------------------------------------ helpers

    def _load_rule_by_sla_id(self, sla_ids) -> Dict[str, Optional[str]]:
        """Batch-load ``ld_formula_rule`` for a set of SLAs.

        Returns ``{sla_id: rule_or_None}``. Empty input → empty dict.
        Used by ``close`` to split aggregates into Track A / Track B.
        """
        if not sla_ids:
            return {}
        rows = self.db.execute(
            select(SlaDefinition.id, SlaDefinition.ld_formula_rule)
            .where(SlaDefinition.id.in_(list(sla_ids)))
        ).all()
        return {r.id: r.ld_formula_rule for r in rows}

    def _resolve_contract_type(
        self, aggregates, project_id: Optional[str] = None,
    ) -> Optional[str]:
        """Derive the project's contract_type.

        Prefers reading from an aggregate's SLA (cheap — one row already
        in memory). Falls back to a cross-schema query against ACTIVE
        mappings on the project when no aggregates exist — a project can
        legitimately have SLAs configured but zero breaches this quarter.
        Returns None only when the project has no SLAs at all.
        """
        # Fast path — read from any aggregate's SLA.
        if aggregates:
            sla_id = aggregates[0].sla_id
            row = self.db.execute(
                select(SlaDefinition.contract_type).where(SlaDefinition.id == sla_id)
            ).scalar()
            if row:
                return row

        # Fallback — no aggregates yet (empty quarter). Query the project's
        # own active SLAs to still get a contract_type populated so the
        # settlement row + cap lookup can proceed correctly.
        if project_id:
            from sqlalchemy import text as _text
            row = self.db.execute(
                _text("""
                    SELECT DISTINCT s.contract_type
                      FROM contract.sla_activity_mappings m
                      JOIN contract.sla_definitions s ON s.id = m.sla_id
                      JOIN project.activities a ON a.id = m.activity_id
                     WHERE m.status = 'ACTIVE'
                       AND s.contract_type IS NOT NULL
                       AND a.project_id = :pid
                     LIMIT 1
                """),
                {"pid": project_id},
            ).scalar()
            return row
        return None

    # ------------------------------------------------------------------ override

    def override(
        self,
        project_id: str,
        qk: QuarterKey,
        *,
        new_sum_ld_percent: Decimal,
        override_reason: str,
        closed_by: str,
    ) -> SlaSettlementPeriod:
        """Finance-role override — replace sum_ld_percent + recompute
        capped_ld/LD_amount/AQP with the same NPQP as the auto-close."""
        existing = self.repo.get(project_id=project_id, qk=qk)
        if existing is None:
            raise NotFoundError(
                f"No settlement row for {project_id} {qk.label()} — "
                "run auto-close first.",
                code="settlement_not_found",
            )
        if existing.status == "invoiced":
            raise ValidationError(
                "Cannot override an invoiced settlement — issue a credit note.",
                code="settlement_immutable",
            )

        # Cap is data-driven — read from the existing row's contract_type
        # (set at auto-close time) so an override honours the same
        # contract-specific cap that applied at close. Missing config →
        # refuse the override rather than default to a magic number.
        rules = self.compliance.evaluator._load_contract_ld_rules(existing.contract_type)
        cap_pct = _resolve_cap_from_rules(rules)
        if cap_pct is None:
            raise ValidationError(
                f"No quarterly_ld_cap_pct rule configured for "
                f"contract_type={existing.contract_type!r} — "
                f"seed contract.contract_ld_rules before overriding.",
                code="cap_rule_missing",
            )
        capped_ld = min(new_sum_ld_percent, cap_pct)
        # Reuse the existing NPQP — override changes only the LD %, not
        # the payment base.
        npqp = existing.npqp or Decimal("0")
        pa = existing.pa_amount or Decimal("0")
        qgr = existing.qgr_amount or Decimal("0")
        ld_amount = (capped_ld / Decimal("100")) * npqp
        aqp = (pa - ld_amount) + qgr

        return self.repo.upsert(
            project_id=project_id,
            contract_type=existing.contract_type,
            qk=qk,
            sum_ld_percent=new_sum_ld_percent,
            capped_ld_percent=capped_ld,
            f_amount=existing.f_amount,
            qgr_amount=qgr,
            npqp=npqp,
            ld_amount=ld_amount,
            pa_amount=pa,
            aqp_amount=aqp,
            status="overridden",
            closed_by=closed_by,
            override_reason=override_reason,
            source_aggregate_ids=existing.source_aggregate_ids,
            consequence_flags=existing.consequence_flags or {},
        )

    # ------------------------------------------------------------------ invoice lock

    def mark_invoiced(
        self,
        project_id: str,
        qk: QuarterKey,
        *,
        invoiced_by: str,
        invoice_ref: Optional[str] = None,
    ) -> SlaSettlementPeriod:
        """Lock the settlement row after invoice raise (Phase E).

        Once ``status='invoiced'`` the override endpoint refuses further
        changes (immutable audit — a mistake here means issue a credit
        note, not mutate the row). Called by project-mgmt's invoice-raise
        flow via HTTP; safe to invoke twice (idempotent).
        """
        existing = self.repo.get(project_id=project_id, qk=qk)
        if existing is None:
            raise NotFoundError(
                f"No settlement row for {project_id} {qk.label()} — "
                "run auto-close first.",
                code="settlement_not_found",
            )
        if existing.status == "invoiced":
            return existing   # idempotent

        return self.repo.upsert(
            project_id=project_id,
            contract_type=existing.contract_type,
            qk=qk,
            sum_ld_percent=existing.sum_ld_percent,
            capped_ld_percent=existing.capped_ld_percent,
            f_amount=existing.f_amount,
            qgr_amount=existing.qgr_amount,
            npqp=existing.npqp,
            ld_amount=existing.ld_amount,
            pa_amount=existing.pa_amount,
            aqp_amount=existing.aqp_amount,
            status="invoiced",
            closed_by=invoiced_by,
            override_reason=(
                f"invoiced (ref={invoice_ref})" if invoice_ref
                else "invoiced"
            ),
            source_aggregate_ids=existing.source_aggregate_ids,
            consequence_flags=existing.consequence_flags or {},
        )

    # ------------------------------------------------------------------ auto-close sweep

    def close_projects_ready_to_close(
        self, on_date: Optional[_date] = None,
    ) -> List[str]:
        """Cron hook — call on quarter_end+1 for every project that has
        active mappings but no settlement row for the just-ended quarter.

        Returns the list of project_ids closed on this run (for logging).
        """
        on_date = on_date or _date.today()
        prev_day = on_date - timedelta(days=1)

        # Find every project that has ANY active mapping (via the
        # cross-schema resolver — mapping doesn't carry project_id).
        mappings = self.db.execute(
            select(SlaActivityMapping).where(SlaActivityMapping.status == "ACTIVE")
        ).scalars().all()
        project_ids: set = set()
        for m in mappings:
            act = self.compliance.resolver.get_activity(m.activity_id) or {}
            pid = act.get("projectId") or act.get("project_id")
            if pid:
                project_ids.add(pid)

        # Quarters are PROJECT-anchored, so each project's quarter ends on its
        # OWN boundary (project_start + 3k months − 1 day). Close a project
        # only on the day AFTER *its* just-ended quarter — computed per project
        # from that project's start-date anchor.
        closed: List[str] = []
        for pid in project_ids:
            prev_qk = quarter_of(prev_day, self.compliance._project_anchor(pid))
            if on_date != prev_qk.quarter_end + timedelta(days=1):
                continue
            try:
                self.close(pid, prev_qk, mode="auto")
                closed.append(pid)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "auto-close failed for %s %s: %s", pid, prev_qk.label(), exc,
                )
        return closed
