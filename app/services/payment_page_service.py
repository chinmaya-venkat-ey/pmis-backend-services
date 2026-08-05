"""PaymentPageService — carry-forward, CCN cap, per-activity split, and the
aggregated payment page.

Builds the read-only, reactive Project-Finance page (everything derived is
recomputed on every read), and owns the writes that don't belong to a single
row:
  - set_carry_forward          — per-phase "carry forward cost" (ex-QRG)
  - set_phase_frequency        — one frequency for the whole phase
  - set_phase_sequence         — override a phase's integer order
  - set_payment_term_activities— per-activity split of a partial milestone term
  - update_ccn_cap             — writes projects.ccn_cap_percent

Phases are ordered by their integer ``sequence`` (config row); carry-forward
flows to the immediate next phase and compounds down the chain.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.errors import ProjectNotFoundError, ValidationError
from app.repositories.activity_repository import ActivityRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_cost_item_repository import ProjectCostItemRepository
from app.repositories.project_payment_term_activity_repository import (
    ProjectPaymentTermActivityRepository,
)
from app.repositories.project_cf_pool_installment_repository import (
    ProjectCfPoolInstallmentRepository,
)
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_phase_cf_allocation_repository import (
    ProjectPhaseCfAllocationRepository,
)
from app.repositories.project_phase_qrg_repository import ProjectPhaseQrgRepository
from app.repositories.project_repository import ProjectRepository
from app.clients.contract_management_client import ContractManagementClient
from app.schemas.payment import (
    CarryForwardAllocationResponse,
    CarryForwardResponse,
    CfPoolInstallmentResponse,
    CcnBlock,
    CostItemResponse,
    CostItemSlaLdBlock,
    CostItemSlaLdDetail,
    PaymentPageResponse,
    PaymentTermActivityResponse,
    PaymentTermResponse,
    PaymentTotals,
    PhaseBlock,
    SlaLdDeductionBlock,
)
from app.utilities import catalogs, cf_pool, cycle_calc, payment_calc
from app.utilities.payment_lock import assert_payment_writable, is_payment_locked
from app.utilities.payment_masters import validate_frequency_code

_PARTIAL = "partial_payment"


def _safe_cycle_count(start, end, frequency, anchor=None) -> Optional[int]:
    """Resilient cycle count for a project / phase / milestone span — null (never
    raises) when a frequency isn't applied yet, isn't a cycle frequency
    (one_time/daily), the dates are missing, or the range is unusable. Keeps the
    read endpoints from ever 500ing. ``anchor`` (the project/contract start date)
    makes the buckets contract-relative (bug #325); omit it for calendar
    buckets."""
    if start is None or end is None or not frequency:
        return None
    try:
        return cycle_calc.count_cycles_from_datetimes(start, end, frequency, anchor=anchor)
    except ValidationError:
        return None


# Phase ordering lives in a shared util so this builder and the payment-term
# "last phase must total 100%" validation agree on order / which phase is last.
# Re-exported under the legacy underscore names (used by tests + _order_phases).
from app.utilities.phase_order import (  # noqa: E402
    name_key as _name_key,  # noqa: F401
    phase_order_key as _phase_order_key,
)


class PaymentPageService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.payment_terms = ProjectPaymentTermRepository(db)
        self.phase_qrg = ProjectPhaseQrgRepository(db)
        self.cf_allocations = ProjectPhaseCfAllocationRepository(db)
        self.cf_pool = ProjectCfPoolInstallmentRepository(db)
        self.milestones = MilestoneRepository(db)
        self.activities = ActivityRepository(db)
        self.term_activities = ProjectPaymentTermActivityRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------- phase order

    def _order_phases(self, phases, phase_dates) -> List[str]:
        """Chronological phase order (see ``_phase_order_key``) — earliest start
        first, shorter span breaks ties, undated last. Drives both the displayed
        order AND the carry-forward "subsequent phases/milestones" set."""
        return sorted(phases, key=lambda p: _phase_order_key(p, phase_dates))

    def _load_phase_state(self, project_id, *, cost_rows=None, term_rows=None, configs=None):
        """Resolve ordered phases + carry-forward distribution for a project.

        Returns ``(ordered_phases, config_by_phase, cf, cost_rows, term_rows)``
        where ``cf`` is ``payment_calc.carry_forward_distribution`` output."""
        if cost_rows is None:
            cost_rows = self.cost_items.list_all_live(project_id)
        if term_rows is None:
            term_rows = self.payment_terms.list_all_live(project_id)
        if configs is None:
            configs = self.phase_qrg.list_all_live(project_id)
        config_by_phase = {q.phase: q for q in configs}
        # A phase EXISTS iff it has live cost/term rows. Config rows
        # (project_phase_qrg) are NOT a source of phases — a phase whose cost
        # rows were deleted/renamed leaves a stale config behind, and counting
        # it here is what made a deleted/edited phase linger as a phantom.
        distinct = {c.phase for c in cost_rows if c.phase is not None}
        distinct |= {t.phase for t in term_rows if t.phase is not None}

        # Per-phase date span drives BOTH the chronological order and the
        # per-phase cycle counts (time methods). Ordering is date-derived — the
        # legacy ``sequence`` column is not consulted.
        project = self._require_project(project_id)
        project_freq = project.payment_frequency_code
        project_bounds = (project.start_date, project.end_date)
        phase_dates = self.cost_items.phase_milestone_date_bounds(project_id)
        ordered = self._order_phases(distinct, phase_dates)
        phase_cycle_counts = {}
        for p in ordered:
            s, e = phase_dates.get(p, (None, None))
            phase_cycle_counts[p] = _safe_cycle_count(s, e, project_freq, anchor=project.start_date) or 0
        ms_by_phase: dict = {}
        for t in term_rows:
            if t.phase is not None and t.milestone_id is not None:
                ms_by_phase.setdefault(t.phase, []).append(t.milestone_id)
        alloc_by_phase: dict = {}
        for a in self.cf_allocations.list_all_live(project_id):
            alloc_by_phase.setdefault(a.source_phase, {})[a.recipient_key] = a

        cf_config = {}
        for i, p in enumerate(ordered):
            cfg_row = config_by_phase.get(p)
            enabled = bool(getattr(cfg_row, "carry_forward_enabled", False))
            code = getattr(cfg_row, "carry_forward_method_code", None)
            frequency = None
            if enabled:
                method, variant, formula = self._resolve_cf_method(code)
                recipient_vars = self._build_cf_recipient_vars(
                    method, variant, i, ordered, ms_by_phase,
                    phase_cycle_counts, alloc_by_phase.get(p, {}),
                )
                # For the POOL family the variant IS the calendar frequency
                # (time_quarterly → quarterly) driving the installment schedule.
                if method == payment_calc.CF_TIME:
                    frequency = variant
            else:
                method = formula = None
                recipient_vars = {}
            cf_config[p] = {
                "enabled": enabled,
                "method": method,
                "formula": formula,
                "recipient_vars": recipient_vars,
                "frequency": frequency,
            }

        # One-time pool distribution: each non-last opted-in phase takes its
        # share (₹/%), the last phase absorbs the remainder. The allocation joins
        # each phase's billable base for carry-forward.
        one_time_config = {
            q.phase: {
                "enabled": bool(getattr(q, "one_time_enabled", False)),
                "mode": getattr(q, "one_time_mode", None),
                "value": getattr(q, "one_time_value", None),
            }
            for q in configs
        }
        one_time_alloc = payment_calc.one_time_distribution(cost_rows, ordered, one_time_config)
        cf = payment_calc.carry_forward_distribution(
            cost_rows, term_rows, ordered, cf_config, one_time_alloc=one_time_alloc,
            phase_dates=phase_dates, project_bounds=project_bounds)
        self._one_time_alloc = one_time_alloc  # exposed to build_page for the response
        return ordered, config_by_phase, cf, cost_rows, term_rows

    def _resolve_cf_method(self, code):
        """Resolve a carry-forward method code → (recipient unit, variant,
        formula) from the masters mirror, with a built-in fallback for the
        evenly methods so distribution still works if the mirror is momentarily
        unavailable."""
        if not code:
            return None, None, None
        row = catalogs.carry_forward_method_row(self.db, code)
        if row is not None:
            return row.method, row.variant, row.formula
        if code in ("phase_evenly", "milestone_evenly"):
            return code.split("_", 1)[0], "evenly", "leftover / numRecipients"
        return None, None, None

    def _build_cf_recipient_vars(
        self, method, variant, idx, ordered, ms_by_phase, phase_cycle_counts, alloc_map,
    ) -> dict:
        """Per-recipient formula variables for the carrying phase at ``idx``:

          * time methods   → ``recipientCycles`` (the recipient phase's own
                             cycle count at the project frequency) + ``totalCycles``
                             (Σ over the subsequent phases).
          * custom methods → ``recipientPercent`` (the stored share, covering
                             every current subsequent recipient — see the
                             re-normalisation note below).
          * evenly methods → ``{}`` (the formula needs no per-recipient var).
        """
        subsequent = ordered[idx + 1:]
        if method == payment_calc.CF_TIME:
            total = sum(phase_cycle_counts.get(r, 0) for r in subsequent)
            return {
                r: {"recipientCycles": Decimal(phase_cycle_counts.get(r, 0)),
                    "totalCycles": Decimal(total)}
                for r in subsequent
            }
        if variant == "custom":
            if method == payment_calc.CF_MILESTONE:
                recipients = [m for sp in subsequent for m in ms_by_phase.get(sp, [])]
            else:
                recipients = subsequent
            out = {}
            for r in recipients:
                a = alloc_map.get(r)
                pct = Decimal(str(a.percent)) if (a is not None and a.percent is not None) else Decimal("0")
                out[r] = {"recipientPercent": pct}
            # Use the SAVED shares as-is — do NOT silently rescale to 100%. A
            # custom allocation can go stale when a milestone-date edit reorders
            # phases so a recipient drops out of "subsequent"; the remaining
            # shares then sum to < 100. We deliberately carry only that
            # explicitly-allocated portion (the dropped share is NOT
            # redistributed onto the survivors) so the derived payout stays
            # faithful to what the user saved. Re-saving the allocation
            # re-normalises it across the current recipients (the write path,
            # _normalise_cf_allocations). In the normal case shares already sum
            # to 100 and this is unchanged.
            return out
        return {}

    def ensure_phase_configs(self, project_id: str) -> None:
        """Upsert a phase-config row (with a ``sequence``) for every distinct
        phase that has cost/term rows but no config yet. Write path only."""
        cost_rows = self.cost_items.list_all_live(project_id)
        term_rows = self.payment_terms.list_all_live(project_id)
        configs = self.phase_qrg.list_all_live(project_id)
        existing = {q.phase for q in configs}
        distinct = {c.phase for c in cost_rows if c.phase is not None}
        distinct |= {t.phase for t in term_rows if t.phase is not None}
        missing = [p for p in distinct if p not in existing]
        if not missing:
            return
        next_seq = self.phase_qrg.max_sequence(project_id)
        for p in sorted(missing, key=lambda x: int(x) if str(x).isdigit() else 10 ** 9):
            if str(p).isdigit():
                seq = int(p)
            else:
                next_seq += 1
                seq = next_seq
            self.phase_qrg.create(project_id=project_id, phase=p, sequence=seq)
        self.db.flush()

    # ------------------------------------------------------------------ read

    def build_page(
        self,
        project_id: str,
        *,
        bearer_token: Optional[str] = None,
    ) -> PaymentPageResponse:
        project = self._require_project(project_id)
        project_freq = project.payment_frequency_code  # ONE frequency per project

        cost_rows = self.cost_items.list_all_live(project_id)
        ms_map = self.cost_items.milestone_ids_by_cost_item([c.id for c in cost_rows])
        # Resource-based costing FIRST: override each resource_cost row's cost from
        # its milestones' activities' snapshots (rate × qty × duration), in-memory
        # (no DB write) — done BEFORE _load_phase_state so the carry-forward /
        # effective base uses the DERIVED cost too (not the typed one).
        resource_cost_by_activity, resource_ms_ids, res_acts_by_ms = \
            self._apply_resource_costs(cost_rows, ms_map)
        ordered, config_by_phase, cf, cost_rows, term_rows = self._load_phase_state(
            project_id, cost_rows=cost_rows)
        phase_dates = self.cost_items.phase_milestone_date_bounds(project_id)
        ms_dates = self.cost_items.milestone_date_map(project_id)
        # Resource (cost-driven) terms: value = Σ activities' resource cost, percent
        # = derived cost-share (see _resource_term_derived). Keyed by term id.
        resource_term_derived = self._resource_term_derived(
            term_rows, resource_ms_ids, res_acts_by_ms, resource_cost_by_activity)

        # Saved custom-split shares, grouped by carrying phase (for round-trip).
        alloc_resp_by_phase: dict = {}
        for a in self.cf_allocations.list_all_live(project_id):
            alloc_resp_by_phase.setdefault(a.source_phase, []).append(
                CarryForwardAllocationResponse(
                    recipient_key=a.recipient_key,
                    recipient_kind=a.recipient_kind,
                    alloc_mode=a.alloc_mode,
                    input_value=payment_calc.to_2dp(a.input_value),
                    percent=Decimal(str(a.percent)) if a.percent is not None else Decimal("0.0000"),
                )
            )

        # Partial-payment activity enrichment (bulk; no N+1).
        term_ms_ids = [t.milestone_id for t in term_rows if t.milestone_id]
        payment_type_map = self.milestones.payment_type_by_ids(term_ms_ids)
        partial_ms_ids = [m for m in term_ms_ids if payment_type_map.get(m) == _PARTIAL]
        activities_by_ms = self.activities.list_by_milestone_ids(partial_ms_ids)
        ms_pos = self.milestones.position_by_ids(partial_ms_ids)
        term_acts = self.term_activities.list_for_terms([t.id for t in term_rows])
        ms_received = cf["milestone_received"]

        # A row's own total = its line total: transaction rows are
        # perTxn × planned + tax (not the stored cost, which is 0 for them).
        row_total_by_ci = {
            c.id: payment_calc.line_total(c) for c in cost_rows
        }

        totals_d = payment_calc.contract_totals(cost_rows)
        totals = PaymentTotals(
            total_contract_cost=totals_d["total_contract_cost"],
            fixed_cost=totals_d["fixed_cost"],
            one_time_cost=totals_d["one_time_cost"],
            resource_cost=totals_d["resource_cost"],
            transaction_cost=totals_d["transaction_cost"],
            recurring_cost=totals_d["recurring_cost"],
        )

        # Recurring schedules honour each row's OWN frequency (falling back to
        # the project frequency). Built once here: per-row for the cost-item
        # response, and merged per-phase for the phase overlay below.
        rec_by_ci, rec_by_phase = _build_recurring_schedules(
            cost_rows, phase_dates, project_freq, project_start=project.start_date,
        )
        # Phases carrying ONLY recurring cost sit outside the billing sequence:
        # no payment-term %, no one-time share, no carry-forward in or out.
        # They still render with their dates + frequency schedule.
        recurring_phases = payment_calc.recurring_only_phases(cost_rows)
        # The terminal BILLING phase (ignoring any trailing recurring-only phase).
        last_billing_phase = next(
            (p for p in reversed(list(ordered)) if p not in recurring_phases), None
        )
        cost_items = [
            _cost_item_response(c, ms_map.get(c.id, []), rec_by_ci.get(c.id, []))
            for c in cost_rows
        ]

        # Last-phase strict full utilisation: null milestones split the
        # remaining (100 − Σ explicit) evenly so the phase always totals 100%
        # (its leftover can't carry forward).
        pct_overrides = _last_phase_percent_overrides(ordered, term_rows)
        # LD-basis allotment: every billing phase totals 100% (default even
        # split); this is the basis penalties / LD are computed on.
        ld_basis_overrides = _ld_basis_overrides(term_rows, recurring_phases)

        phase_blocks: List[PhaseBlock] = []
        for idx, phase in enumerate(ordered):
            cfg = config_by_phase.get(phase)
            phase_fixed = payment_calc.phase_fixed_total(cost_rows, phase)
            phase_base = payment_calc.phase_base_total(cost_rows, phase)
            effective_total = cf["effective_base"].get(phase, phase_base)
            # Resource + transaction subtotal on this phase (informational — their
            # value is already part of the base that milestone %s split).
            expense_total = payment_calc.phase_expense_total(cost_rows, phase)
            terms_in_phase = [t for t in term_rows if t.phase == phase]
            term_responses = []
            for t in terms_in_phase:
                override = pct_overrides.get(t.id)
                m_start, m_end = ms_dates.get(t.milestone_id, (None, None))
                resp = _payment_term_response(
                    t, effective_total, row_total_by_ci.get(t.cost_item_id, Decimal("0")),
                    cycle_count=_safe_cycle_count(m_start, m_end, project_freq, anchor=project.start_date),
                    start_date=m_start, end_date=m_end,
                    carry_received=ms_received.get(t.milestone_id, Decimal("0")),
                    percent_override=override,
                    ld_basis_override=ld_basis_overrides.get(t.id),
                )
                resp.payment_type = payment_type_map.get(t.milestone_id)
                if resp.payment_type == _PARTIAL:
                    ms_acts = activities_by_ms.get(t.milestone_id, [])
                    resp.activities = _build_term_activities(
                        effective_total,
                        ms_acts,
                        term_acts.get(t.id, []),
                        override if override is not None else t.percent_of_payment,
                        ms_pos.get(t.milestone_id),
                        cost_by_activity=resource_cost_by_activity,
                        is_resource=t.milestone_id in resource_ms_ids,
                    )
                # Resource (cost-driven) milestone: term value = Σ its activities'
                # resource cost, percent = derived cost-share (never even-split/null).
                if t.id in resource_term_derived:
                    resp.value, resp.percent_of_payment = resource_term_derived[t.id]
                term_responses.append(resp)

            start_date, end_date = phase_dates.get(phase, (None, None))
            # Recurring costs on this phase: each row's schedule is built from
            # its OWN frequency (see _build_recurring_schedules) and the rows are
            # merged into one calendar overlay here. Not billed via the
            # percentage terms, so it's a separate overlay on top of the base.
            recurring_total = payment_calc.phase_recurring_total(cost_rows, phase)
            recurring_sched = rec_by_phase.get(phase, [])
            recurring_pool = [
                CfPoolInstallmentResponse(
                    period_index=inst["period_index"],
                    period_start=inst["period_start"],
                    period_end=inst["period_end"],
                    amount=payment_calc.to_2dp(inst["amount"]),
                )
                for inst in recurring_sched
            ]
            # Milestone-wise inflow to THIS phase = Σ add-ons paid to its
            # milestones (proportional to its milestone count).
            received_ms = sum(
                (ms_received.get(t.milestone_id, Decimal("0")) for t in terms_in_phase),
                Decimal("0"),
            )
            # Terminal BILLING phase — a trailing recurring-only phase is out of
            # the sequence and must not claim this flag.
            is_last = phase == last_billing_phase
            pool_list = cf.get("pool", {}).get(phase, [])
            # A recurring-only phase is outside the billing sequence: carry
            # forward is not applicable to it (neither given nor received), so
            # report it as disabled regardless of any stale stored config.
            is_recurring_phase = phase in recurring_phases
            # An explicit one-time (OPE) share only counts for phases inside the
            # billing sequence that aren't the auto-absorbing last phase.
            _ope_config_honoured = not is_recurring_phase and not is_last
            cf_block = CarryForwardResponse(
                enabled=(False if is_recurring_phase
                         else bool(getattr(cfg, "carry_forward_enabled", False))),
                method_code=getattr(cfg, "carry_forward_method_code", None),
                # Last phase auto-utilised → nothing unallocated.
                leftover=(Decimal("0.00") if (is_last and pct_overrides)
                          else cf["leftover"].get(phase, Decimal("0.00"))),
                carried_out=cf["carried_out"].get(phase, Decimal("0.00")),
                received=cf["phase_received"].get(phase, Decimal("0.00")),
                received_milestone=payment_calc.to_2dp(received_ms),
                is_last_phase=is_last,
                allocations=alloc_resp_by_phase.get(phase, []),
                pool=[
                    CfPoolInstallmentResponse(
                        period_index=inst["period_index"],
                        period_start=inst["period_start"],
                        period_end=inst["period_end"],
                        amount=payment_calc.to_2dp(inst["amount"]),
                    )
                    for inst in pool_list
                ],
                pool_per_period=(payment_calc.to_2dp(pool_list[0]["amount"])
                                 if pool_list else Decimal("0.00")),
            )
            phase_blocks.append(PhaseBlock(
                phase=phase,
                # 1-based position in the chronological order — array order and
                # ``sequence`` always agree (no longer the stored counter).
                sequence=idx + 1,
                phase_fixed_total=phase_fixed,
                phase_base_total=phase_base,
                effective_phase_total=effective_total,
                one_time_allocated=getattr(self, "_one_time_alloc", {}).get(phase, Decimal("0.00")),
                # An explicit OPE share is honoured ONLY for phases that take
                # part in the one-time distribution: NOT recurring-only phases
                # (outside the billing sequence) and NOT the last billing phase
                # (it auto-absorbs the remainder). For those the stored config is
                # ignored, so report it fully CLEARED — reporting a stale
                # enabled/mode/value is what made an edit look like it "reset" on
                # reload (a phase set here, then turned recurring-only or shuffled
                # to last, kept a ghost value the FE showed then dropped).
                one_time_enabled=(bool(getattr(cfg, "one_time_enabled", False))
                                  if _ope_config_honoured else False),
                one_time_mode=(getattr(cfg, "one_time_mode", None)
                               if _ope_config_honoured else None),
                one_time_value=(getattr(cfg, "one_time_value", None)
                                if _ope_config_honoured else None),
                expense_total=expense_total,
                # Full value of the phase: the billable base (fixed + resource +
                # transaction + one-time allocated + carry-forward received) that
                # milestone %s pay out of, PLUS the phase's recurring total (which
                # pays via its own schedule below).
                phase_total=payment_calc.to_2dp(effective_total + recurring_total),
                recurring_total=recurring_total,
                recurring_per_period=(recurring_pool[0].amount
                                      if recurring_pool else Decimal("0.00")),
                recurring_schedule=recurring_pool,
                start_date=start_date,
                end_date=end_date,
                cycle_count=_safe_cycle_count(start_date, end_date, project_freq, anchor=project.start_date),
                pending_cycles=cf_pool.remaining_periods(
                    project.end_date, end_date, project_freq, anchor=project.start_date),
                payment_terms=term_responses,
                carry_forward=cf_block,
            ))

        # Project-level OPE allocation guide (pre-validate/publish): how much of
        # the one-time pool the user has ALLOCATED so far vs. what is still
        # PENDING. Explicit allocation only — the auto-absorbed remainder is the
        # pending amount that must reach 0 to publish. Rebuild the same
        # one_time_config shape _load_phase_state uses (phase → enabled/mode/value).
        one_time_config = {
            p: {
                "enabled": bool(getattr(cfg, "one_time_enabled", False)),
                "mode": getattr(cfg, "one_time_mode", None),
                "value": getattr(cfg, "one_time_value", None),
            }
            for p, cfg in config_by_phase.items()
        }
        ope = payment_calc.one_time_allocation_summary(cost_rows, ordered, one_time_config)
        totals.one_time_allocated = ope["allocated"]
        totals.one_time_pending = ope["pending"]
        if ope["pool"] > Decimal("0.00"):
            alloc_pct = payment_calc.to_2dp(ope["allocated"] / ope["pool"] * Decimal("100"))
            totals.one_time_allocated_percent = alloc_pct
            totals.one_time_pending_percent = payment_calc.to_2dp(
                Decimal("100") - alloc_pct)

        cap_pct = payment_calc.to_2dp(project.ccn_cap_percent)
        ccn = CcnBlock(
            cap_percent=cap_pct,
            value=payment_calc.ccn_value(totals.total_contract_cost, cap_pct),
        )

        # Phase E — SLA quarterly LD deductions from contract-mgmt (Track B).
        # Soft-fail: any HTTP / parse issue returns [] so the payment page
        # renders without the block rather than 5xxing.
        sla_ld_deductions = self._build_sla_ld_deductions(
            project_id, bearer_token,
        )

        # P1b — Track A (per-deliverable) LDs on cost items.
        # Bulk-fetch per-activity Track A LDs, then attach to each cost
        # item via its linked milestones → activities. Soft-fails to a
        # no-op when contract-mgmt is unreachable.
        self._inject_track_a_lds_into_cost_items(
            cost_items, project_id, bearer_token,
        )

        return PaymentPageResponse(
            project_id=project.id,
            project_code=project.project_code,
            status=project.status,
            is_locked=is_payment_locked(project.status),
            frequency_code=project_freq,
            start_date=project.start_date,
            end_date=project.end_date,
            cycle_count=_safe_cycle_count(
                project.start_date, project.end_date, project_freq,
                anchor=project.start_date,
            ),
            cost_items=cost_items,
            totals=totals,
            phases=phase_blocks,
            ccn=ccn,
            sla_ld_deductions=sla_ld_deductions,
        )

    # ------------------------------------------------------------------ Phase E

    def _inject_track_a_lds_into_cost_items(
        self,
        cost_items: List[CostItemResponse],
        project_id: str,
        bearer_token: Optional[str],
    ) -> None:
        """Mutate cost_items in place — attach ``sla_ld_deduction`` block
        to each cost item that has at least one activity with a Track A
        (per-deliverable) LD. Soft-fails to no-op on any error."""
        try:
            client = ContractManagementClient()
            by_activity = client.get_deliverable_lds_by_activity(
                project_id, bearer_token,
            )
        except Exception:  # noqa: BLE001
            return
        if not by_activity:
            return

        # Gather activities per cost item via its milestones.
        # cost_item → milestones (from cost_item.milestone_ids)
        # milestone → activities (via ActivityRepository)
        all_ms_ids = {ms for ci in cost_items for ms in (ci.milestone_ids or [])}
        if not all_ms_ids:
            return
        activities_by_ms = self.activities.list_by_milestone_ids(list(all_ms_ids))

        for ci in cost_items:
            if not ci.milestone_ids:
                continue
            details: List[CostItemSlaLdDetail] = []
            total = Decimal("0.00")
            for ms_id in ci.milestone_ids:
                for act in (activities_by_ms.get(ms_id) or []):
                    aid = act.id if hasattr(act, "id") else act.get("id")
                    entry = by_activity.get(aid)
                    if not entry:
                        continue
                    for item in entry.get("items", []):
                        try:
                            amt = Decimal(str(item.get("ldAmount") or "0"))
                        except (ValueError, ArithmeticError):
                            amt = Decimal("0")
                        try:
                            pct = Decimal(str(item.get("ldPercent"))) if item.get("ldPercent") else None
                        except (ValueError, ArithmeticError):
                            pct = None
                        try:
                            base = Decimal(str(item.get("ldBaseAmount"))) if item.get("ldBaseAmount") else None
                        except (ValueError, ArithmeticError):
                            base = None
                        details.append(CostItemSlaLdDetail(
                            activity_id=aid,
                            sla_ref=item.get("slaRef"),
                            ld_formula_rule=item.get("ldFormulaRule") or "",
                            ld_percent=pct,
                            # amt=0 is a valid value ("SLA compliant, no LD");
                            # preserve it as 0 rather than coercing to None.
                            ld_amount=amt,
                            ld_base_amount=base,
                            observed_value=(
                                Decimal(str(item["observedValue"]))
                                if item.get("observedValue") is not None else None
                            ),
                            evaluated_on=item.get("evaluatedOn"),
                            status=item.get("status"),
                        ))
                        total += amt
            if details:
                ci.sla_ld_deduction = CostItemSlaLdBlock(
                    total_amount=total, details=details,
                )

    def _build_sla_ld_deductions(
        self, project_id: str, bearer_token: Optional[str],
    ) -> List[SlaLdDeductionBlock]:
        """Fetch settlement rows from contract-mgmt + shape them for the
        payment page. Never raises — a failed fetch returns []."""
        try:
            client = ContractManagementClient()
            items = client.list_settlements(project_id, bearer_token)
        except Exception:  # noqa: BLE001 — never break the payment page
            return []

        out: List[SlaLdDeductionBlock] = []
        for it in items:
            try:
                out.append(SlaLdDeductionBlock(
                    settlement_id=it["id"],
                    fiscal_year=it["fiscalYear"],
                    quarter=it["quarter"],
                    quarter_start=it["quarterStart"],
                    quarter_end=it["quarterEnd"],
                    sum_ld_percent=it.get("sumLdPercent"),
                    capped_ld_percent=it.get("cappedLdPercent"),
                    f_amount=it.get("fAmount"),
                    qgr_amount=it.get("qgrAmount"),
                    npqp=it.get("npqp"),
                    ld_amount=it.get("ldAmount"),
                    pa_amount=it.get("paAmount"),
                    aqp_amount=it.get("aqpAmount"),
                    status=it.get("status") or "unknown",
                    override_reason=it.get("overrideReason"),
                ))
            except (KeyError, TypeError, ValueError):
                # Skip malformed row — better than losing the whole block.
                continue
        return out

    def validate_finance(self, project_id: str) -> dict:
        """Run the server-side finance-page validation checks (the checks behind
        the FE "Validate" button). Returns ``{"checks": [...], "all_pass": bool}``."""
        from sqlalchemy import select

        from app.models.milestone import Milestone
        from app.utilities.finance_validation import run_finance_validation

        self._require_project(project_id)
        page = self.build_page(project_id)
        active_ids = list(self.db.execute(
            select(Milestone.id)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.is_meeting.is_(False))
        ).scalars())
        return run_finance_validation(page, active_ids)

    def term_response(self, term_id: str) -> PaymentTermResponse:
        """Public: one payment-term response with the per-activity split."""
        return self._single_term_response(term_id)

    def list_term_responses(
        self, project_id: str, term_rows, *, bearer_token: Optional[str] = None,
    ) -> List[PaymentTermResponse]:
        """Build responses for a set of term rows under one carry-forward pass
        (used by the payment-term list endpoint). Enriches partial-payment
        milestones with their activity split (resource milestones: cost-driven)."""
        cost_rows = self.cost_items.list_all_live(project_id)
        ms_map = self.cost_items.milestone_ids_by_cost_item([c.id for c in cost_rows])
        # Override resource costs BEFORE the effective-base pass (see build_page).
        cost_by_activity, resource_ms_ids, res_acts_by_ms = \
            self._apply_resource_costs(cost_rows, ms_map)
        ordered, _, cf, cost_rows, all_terms = self._load_phase_state(
            project_id, cost_rows=cost_rows)
        _project = self._require_project(project_id)
        project_freq = _project.payment_frequency_code
        # A row's own total = its line total: transaction rows are
        # perTxn × planned + tax (not the stored cost, which is 0 for them).
        row_total_by_ci = {
            c.id: payment_calc.line_total(c) for c in cost_rows
        }
        ms_dates = self.cost_items.milestone_date_map(project_id)
        term_ms_ids = [t.milestone_id for t in term_rows if t.milestone_id]
        payment_type_map = self.milestones.payment_type_by_ids(term_ms_ids)
        partial_ms_ids = [m for m in term_ms_ids if payment_type_map.get(m) == _PARTIAL]
        activities_by_ms = self.activities.list_by_milestone_ids(partial_ms_ids)
        ms_pos = self.milestones.position_by_ids(partial_ms_ids)
        term_acts = self.term_activities.list_for_terms([t.id for t in term_rows])
        ms_received = cf["milestone_received"]
        pct_overrides = _last_phase_percent_overrides(ordered, all_terms)
        # Resource-term value + derived % computed over ALL terms (this endpoint is
        # paginated, so the phase resource total must span the whole phase).
        resource_term_derived = self._resource_term_derived(
            all_terms, resource_ms_ids, res_acts_by_ms, cost_by_activity)
        out: List[PaymentTermResponse] = []
        for t in term_rows:
            override = pct_overrides.get(t.id)
            eff = cf["effective_base"].get(t.phase, Decimal("0"))
            m_start, m_end = ms_dates.get(t.milestone_id, (None, None))
            resp = _payment_term_response(
                t, eff, row_total_by_ci.get(t.cost_item_id, Decimal("0")),
                cycle_count=_safe_cycle_count(m_start, m_end, project_freq, anchor=_project.start_date),
                start_date=m_start, end_date=m_end,
                carry_received=ms_received.get(t.milestone_id, Decimal("0")),
                percent_override=override,
            )
            resp.payment_type = payment_type_map.get(t.milestone_id)
            if resp.payment_type == _PARTIAL:
                ms_acts = activities_by_ms.get(t.milestone_id, [])
                resp.activities = _build_term_activities(
                    eff, ms_acts, term_acts.get(t.id, []),
                    override if override is not None else t.percent_of_payment,
                    ms_pos.get(t.milestone_id),
                    cost_by_activity=cost_by_activity,
                    is_resource=t.milestone_id in resource_ms_ids,
                )
            if t.id in resource_term_derived:
                resp.value, resp.percent_of_payment = resource_term_derived[t.id]
            out.append(resp)
        return out

    # ----------------------------------------------------------------- write

    def set_project_frequency(
        self, project_id: str, frequency_code: str, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Set the ONE billing frequency for the whole project — drives every
        cycle count + time-based carry-forward. Also syncs every live term's
        ``frequency_code`` (kept for the FE's per-term display)."""
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        code = validate_frequency_code(self.db, frequency_code)

        self.projects.update(project, updated_by=caller_user_id, payment_frequency_code=code)
        terms = self.payment_terms.list_all_live(project_id)
        for t in terms:
            self.payment_terms.update(t, frequency_code=code, updated_by=caller_user_id)
        self.audit.write(
            project_id=project_id, target_kind="project", target_id=project_id,
            action="set_project_frequency", actor_user_id=caller_user_id,
            changes={"frequency_code": code, "terms_synced": len(terms)},
        )
        self.db.commit()
        return self.build_page(project_id)

    def set_phase_frequency(
        self, project_id: str, phase: str, frequency_code: str, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Back-compat: frequency is now project-level, so the per-phase route
        sets the WHOLE project's frequency (``phase`` is ignored)."""
        return self.set_project_frequency(
            project_id, frequency_code,
            caller_user_id=caller_user_id, caller_is_admin=caller_is_admin,
        )

    def set_phase_sequence(
        self, project_id: str, phase: str, sequence: int, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Override the integer order of a phase (creates the config row if
        needed). Returns the recomputed page."""
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.ensure_phase_configs(project_id)
        row = self.phase_qrg.get_for_phase(project_id, phase)
        if row is None:
            row = self.phase_qrg.create(
                project_id=project_id, phase=phase, sequence=sequence,
                created_by=caller_user_id, updated_by=caller_user_id,
            )
        else:
            self.phase_qrg.update(row, sequence=sequence, updated_by=caller_user_id)
        self.audit.write(
            project_id=project_id, target_kind="phase_config", target_id=row.id,
            action="set_phase_sequence", actor_user_id=caller_user_id,
            changes={"phase": phase, "sequence": sequence},
        )
        self.db.commit()
        return self.build_page(project_id)

    def set_carry_forward(
        self, project_id: str, phase: str, *,
        enabled: bool, method_code: Optional[str], caller_user_id: Optional[str],
        allocation_mode: Optional[str] = None, allocations: Optional[List[dict]] = None,
        caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Configure carry-forward for a phase. A carrying phase always carries
        its ENTIRE leftover, distributed per the master ``method_code``:

          * ``*_evenly``  — split equally across the recipient unit (subsequent
                            phases for 'phase', subsequent milestones for
                            'milestone').
          * ``*_custom``  — split by an explicit per-recipient share. ``allocations``
                            (``[{recipientKey, value}]``) plus ``allocation_mode``
                            ('percent' | 'amount') are REQUIRED and must FULLY
                            allocate (normalised shares sum to 100%); some may be 0.
          * ``time_*``    — split across subsequent phases weighted by each phase's
                            payment-cycle count at the project frequency.

        Validations: the phase must exist; ``method_code`` must be a known method;
        there must be eligible recipients; time methods require a project
        frequency with > 0 total recipient cycles; custom methods must fully
        allocate to valid recipients.
        """
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.ensure_phase_configs(project_id)

        ordered, config_by_phase, cf, cost_rows, term_rows = self._load_phase_state(project_id)
        if phase not in ordered:
            raise ValidationError(
                f"Phase '{phase}' has no cost rows to carry forward from.",
                code="validation_error",
            )

        alloc_rows: List[dict] = []
        if enabled:
            if not method_code or not catalogs.is_known_carry_forward_method(self.db, method_code):
                raise ValidationError(
                    "methodCode must be a known carry-forward method.",
                    code="validation_error",
                )
            method, variant, _formula = self._resolve_cf_method(method_code)
            subsequent = ordered[ordered.index(phase) + 1:]
            sub_ms = [
                t.milestone_id for t in term_rows
                if t.phase in subsequent and t.milestone_id is not None
            ]
            # Recipient availability. APPLIED phase-wise needs a subsequent phase;
            # the FREQUENCY (pool) family needs future calendar periods, not phases.
            if method == payment_calc.CF_PHASE and not subsequent:
                raise ValidationError(
                    "Cannot carry forward phase-wise from the last phase — no subsequent phase.",
                    code="validation_error",
                )
            if method == payment_calc.CF_MILESTONE and not sub_ms:
                raise ValidationError(
                    "Cannot carry forward milestone-wise — no subsequent milestones.",
                    code="validation_error",
                )
            # Frequency (pool) methods build a dated schedule over the periods
            # AFTER this phase ends up to the project end — there must be at least
            # one such future period at the method's frequency.
            if method == payment_calc.CF_TIME:
                if not project.payment_frequency_code:
                    raise ValidationError(
                        "Time-based carry-forward needs a project frequency.",
                        code="validation_error",
                    )
                phase_dates = self.cost_items.phase_milestone_date_bounds(project_id)
                _, phase_end = phase_dates.get(phase, (None, None))
                if not (phase_end and project.start_date and project.end_date):
                    raise ValidationError(
                        "Time-based carry-forward needs a dated phase and project bounds.",
                        code="validation_error",
                    )
                if not cf_pool.remaining_periods(project.end_date, phase_end, variant, anchor=project.start_date):
                    raise ValidationError(
                        "Time-based carry-forward has no future billing periods after this phase.",
                        code="validation_error",
                    )
            # Custom methods need a fully-allocated share set over valid recipients.
            # The basis is the OTHER-cost leftover (what the custom method actually
            # distributes — OPE carries via its own phase-wise stream, bug #326).
            if variant == "custom":
                recipients = sub_ms if method == payment_calc.CF_MILESTONE else subsequent
                alloc_rows = self._normalise_cf_allocations(
                    method, allocation_mode, allocations, recipients,
                    leftover=cf["leftover"].get(phase, Decimal("0.00")),
                )

        fields = dict(
            carry_forward_enabled=enabled,
            carry_forward_method_code=method_code if enabled else None,
            updated_by=caller_user_id,
        )
        row = config_by_phase.get(phase) or self.phase_qrg.get_for_phase(project_id, phase)
        if row is None:
            seq = int(phase) if str(phase).isdigit() else self.phase_qrg.max_sequence(project_id) + 1
            row = self.phase_qrg.create(
                project_id=project_id, phase=phase, sequence=seq,
                created_by=caller_user_id, **fields,
            )
        else:
            self.phase_qrg.update(row, **fields)

        # Persist (or clear) the custom allocation set for this phase.
        if alloc_rows:
            self.cf_allocations.replace_for_phase(
                project_id, phase, alloc_rows, actor_user_id=caller_user_id)
        else:
            self.cf_allocations.soft_delete_for_phase(
                project_id, phase, actor_user_id=caller_user_id)

        # NOTE: the PENDING pool schedule is derived state (a pure function of the
        # phase's current leftover), so it is computed fresh on every payment-page
        # read and returned in CarryForwardResponse.pool — never persisted here.
        # Persisting it would go stale the moment any later edit changed the
        # leftover. The project_cf_pool_installment table is reserved for the
        # FROZEN (on_invoice) installments that the future invoicing flow writes
        # when it draws from the pool — those are immutable, so persisting them is
        # correct.

        self.audit.write(
            project_id=project_id, target_kind="phase_config", target_id=row.id,
            action="set_carry_forward", actor_user_id=caller_user_id,
            changes={"phase": phase, "enabled": enabled, "method_code": method_code,
                     "allocations": len(alloc_rows) or None},
        )
        self.db.commit()
        return self.build_page(project_id)

    @staticmethod
    def _one_time_share(mode, value, pool) -> Decimal:
        v = Decimal(str(value or 0))
        if v <= 0:
            return Decimal("0.00")
        if (mode or "").lower() == "percent":
            return payment_calc.to_2dp(pool * v / Decimal("100"))
        return payment_calc.to_2dp(v)

    def set_one_time_allocation(
        self, project_id: str, phase: str, *,
        enabled: bool, mode: Optional[str], value: Optional[Decimal],
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Opt a phase into a share of the project one-time pool (₹ or % of the
        one-time total). The chronologically LAST phase auto-absorbs the
        remainder and can't be set. Σ of the non-last explicit shares may not
        exceed the pool."""
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.ensure_phase_configs(project_id)

        ordered, config_by_phase, _cf, cost_rows, _terms = self._load_phase_state(project_id)
        if phase not in ordered:
            raise ValidationError(
                f"Phase '{phase}' has no cost rows.", code="validation_error")
        if enabled and ordered and ordered[-1] == phase:
            raise ValidationError(
                "The last phase auto-absorbs the one-time remainder; it cannot be "
                "given an explicit share.", code="validation_error")
        # A recurring-only phase sits outside the billing sequence and never
        # takes a one-time (OPE) share — build_page forces its oneTimeEnabled
        # back to false on read, so allowing the write here would silently
        # orphan the config (stored true, always read false → looks like it
        # "resets" on reload). Reject it up front instead.
        recurring_phases = payment_calc.recurring_only_phases(cost_rows)
        if enabled and phase in recurring_phases:
            raise ValidationError(
                "This phase is recurring-only; it does not take a one-time (OPE) "
                "share.", code="validation_error")
        if enabled:
            pool = payment_calc.one_time_total(cost_rows)
            if pool <= 0:
                raise ValidationError(
                    "There is no one-time cost to allocate.", code="validation_error")
            this_share = self._one_time_share(mode, value, pool)
            last = ordered[-1] if ordered else None
            others = Decimal("0.00")
            for q in config_by_phase.values():
                # Exclude recurring-only phases from the pool-consumption check —
                # they are excluded from the actual distribution and from the
                # totals, so a stale orphan config on one must NOT eat headroom
                # here (that would wrongly block a legitimate allocation).
                if (q.phase != phase and q.phase in ordered and q.phase != last
                        and q.phase not in recurring_phases
                        and getattr(q, "one_time_enabled", False)):
                    others += self._one_time_share(q.one_time_mode, q.one_time_value, pool)
            if others + this_share > pool + Decimal("0.01"):
                raise ValidationError(
                    f"One-time allocations would exceed the pool (₹{pool}). Already "
                    f"allocated ₹{others}, attempted ₹{this_share} "
                    f"(headroom ₹{pool - others}).", code="validation_error")

        fields = dict(
            one_time_enabled=enabled,
            one_time_mode=mode if enabled else None,
            one_time_value=value if enabled else None,
            updated_by=caller_user_id,
        )
        row = config_by_phase.get(phase) or self.phase_qrg.get_for_phase(project_id, phase)
        if row is None:
            seq = int(phase) if str(phase).isdigit() else self.phase_qrg.max_sequence(project_id) + 1
            row = self.phase_qrg.create(
                project_id=project_id, phase=phase, sequence=seq,
                created_by=caller_user_id, **fields)
        else:
            self.phase_qrg.update(row, **fields)

        self.audit.write(
            project_id=project_id, target_kind="phase_config", target_id=row.id,
            action="set_one_time_allocation", actor_user_id=caller_user_id,
            changes={"phase": phase, "enabled": enabled, "mode": mode,
                     "value": (str(value) if value is not None else None)},
        )
        self.db.commit()
        return self.build_page(project_id)

    def _normalise_cf_allocations(
        self, method, allocation_mode, allocations, recipients, *, leftover: Decimal,
    ) -> List[dict]:
        """Validate + normalise custom carry-forward allocations to percent rows.

        ``allocations`` is ``[{recipientKey|recipient_key, value}]``;
        ``allocation_mode`` is 'percent' or 'amount'. Every key must be a valid
        recipient (subsequent phase / milestone); recipients omitted default to
        0. Percent shares (or amount shares against ``leftover``) must sum to the
        full leftover ("must fully allocate"). Returns repository rows with the
        normalised ``percent`` (0..100)."""
        mode = (allocation_mode or "").lower()
        if mode not in ("percent", "amount"):
            raise ValidationError(
                "allocationMode must be 'percent' or 'amount' for a custom method.",
                code="validation_error",
            )
        if not allocations:
            raise ValidationError(
                "Custom carry-forward requires allocations.", code="validation_error",
            )
        valid = set(recipients)
        recipient_kind = "milestone" if method == payment_calc.CF_MILESTONE else "phase"
        rows: List[dict] = []
        seen: set = set()
        pct_sum = Decimal("0")
        for a in allocations:
            key = a.get("recipient_key") or a.get("recipientKey")
            if key not in valid:
                raise ValidationError(
                    f"Allocation recipient '{key}' is not a valid subsequent {recipient_kind}.",
                    code="validation_error",
                )
            if key in seen:
                raise ValidationError(
                    f"Duplicate allocation for recipient '{key}'.", code="validation_error",
                )
            seen.add(key)
            raw = a.get("value")
            value = Decimal(str(raw)) if raw is not None else Decimal("0")
            if value < 0:
                raise ValidationError("Allocation value cannot be negative.", code="validation_error")
            if mode == "percent":
                pct = value
            else:  # amount → percent of the leftover
                if leftover <= 0:
                    raise ValidationError(
                        "Cannot allocate by amount when the phase has no leftover.",
                        code="validation_error",
                    )
                pct = (value / leftover) * Decimal("100")
            pct_sum += pct
            rows.append({
                "recipient_kind": recipient_kind,
                "recipient_key": key,
                "alloc_mode": mode,
                "input_value": value,
                "percent": pct.quantize(Decimal("0.0001")),
            })
        # Must fully allocate — normalised shares sum to 100% (allow a small
        # rounding tolerance for amount-mode division).
        if abs(pct_sum - Decimal("100")) > Decimal("0.05"):
            unit = "amounts must sum to the leftover" if mode == "amount" else "percentages must sum to 100"
            raise ValidationError(
                f"Custom allocation must fully allocate the leftover ({unit}).",
                code="validation_error",
            )
        return rows

    def set_payment_term_activities(
        self, term_id: str, allocations: List[dict], *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentTermResponse:
        """Set the per-activity split of a partial-payment milestone's term.

        Each activity must belong to the term's milestone; the percents must sum
        EXACTLY to the term's ``percent_of_payment`` (unless the list is empty,
        which clears the split). Returns the recomputed payment-term response.
        """
        term = self.payment_terms.get_by_id(term_id)
        if term is None:
            raise ValidationError("Payment term not found.", code="not_found")
        project = self._require_project(term.project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        ptype = self.milestones.payment_type_by_ids([term.milestone_id]).get(term.milestone_id)
        if ptype != _PARTIAL:
            raise ValidationError(
                "Per-activity split is only allowed for a partial-payment milestone.",
                code="validation_error",
            )
        ms = self.milestones.get_by_id(term.milestone_id)
        if getattr(ms, "is_resource_based", False):
            raise ValidationError(
                "The activity split for a resource-based milestone is derived from "
                "its activities' planned resources and cannot be set manually.",
                code="validation_error",
            )

        ms_activities = self.activities.list_by_milestone_ids(
            [term.milestone_id]).get(term.milestone_id, [])
        valid_ids = {a.id for a in ms_activities}
        seen: set = set()
        total = Decimal("0")
        for a in allocations:
            aid = a["activity_id"]
            if aid not in valid_ids:
                raise ValidationError(
                    f"Activity {aid} does not belong to this term's milestone.",
                    code="validation_error",
                )
            if aid in seen:
                raise ValidationError(
                    f"Duplicate activity {aid} in the split.", code="validation_error",
                )
            seen.add(aid)
            total += Decimal(str(a["percent_of_payment"]))

        if allocations:
            term_pct = term.percent_of_payment or Decimal("0")
            if total != term_pct:
                raise ValidationError(
                    f"Per-activity percents must sum to the milestone's percent "
                    f"({term_pct}); got {total}.",
                    code="validation_error",
                    details={"expected": str(term_pct), "got": str(total)},
                )

        self.term_activities.replace_for_term(
            project_id=term.project_id, payment_term_id=term_id,
            allocations=allocations, caller_user_id=caller_user_id,
        )
        self.audit.write(
            project_id=term.project_id, target_kind="payment_term", target_id=term_id,
            action="set_term_activities", actor_user_id=caller_user_id,
            changes={"count": len(allocations), "sum_percent": _s(total)},
        )
        self.db.commit()
        return self._single_term_response(term_id)

    def update_ccn_cap(
        self, project_id: str, ccn_cap_percent: Optional[Decimal], *,
        additional_cost_type: Optional[str] = None,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        # Only the CCN kind is wired to backend logic. 'qgr'/'aqp' are accepted
        # (so the FE selector works) but carry no effect yet — return the page
        # unchanged. Unknown kinds are rejected at the schema layer.
        if additional_cost_type in (None, "ccn"):
            before = project.ccn_cap_percent
            self.projects.update(
                project, updated_by=caller_user_id, ccn_cap_percent=ccn_cap_percent)
            self.audit.write(
                project_id=project_id, target_kind="project", target_id=project_id,
                action="update_ccn_cap", actor_user_id=caller_user_id,
                changes={"ccn_cap_percent": {"before": _s(before), "after": _s(ccn_cap_percent)}},
            )
            self.db.commit()
        return self.build_page(project_id)

    # --------------------------------------------------------------- helpers

    def _single_term_response(
        self, term_id: str, *, bearer_token: Optional[str] = None,
    ) -> PaymentTermResponse:
        """Build one payment-term response (with the per-activity split) using
        the live carry-forward state for the term's phase."""
        term = self.payment_terms.get_by_id(term_id)
        if term is None:
            raise ValidationError("Payment term not found.", code="not_found")
        cost_rows = self.cost_items.list_all_live(term.project_id)
        ms_map = self.cost_items.milestone_ids_by_cost_item([c.id for c in cost_rows])
        cost_by_activity, resource_ms_ids, res_acts_by_ms = \
            self._apply_resource_costs(cost_rows, ms_map)
        ordered, _, cf, cost_rows, all_terms = self._load_phase_state(
            term.project_id, cost_rows=cost_rows)
        _project = self._require_project(term.project_id)
        project_freq = _project.payment_frequency_code
        effective_total = cf["effective_base"].get(term.phase, Decimal("0"))
        resource_term_derived = self._resource_term_derived(
            all_terms, resource_ms_ids, res_acts_by_ms, cost_by_activity)
        override = _last_phase_percent_overrides(ordered, all_terms).get(term.id)
        row_total = next(
            (payment_calc.row_total(c.cost, c.tax_amount)
             for c in cost_rows if c.id == term.cost_item_id), Decimal("0"),
        )
        ms_dates = self.cost_items.milestone_date_map(term.project_id)
        m_start, m_end = ms_dates.get(term.milestone_id, (None, None))
        resp = _payment_term_response(
            term, effective_total, row_total,
            cycle_count=_safe_cycle_count(m_start, m_end, project_freq, anchor=_project.start_date),
            start_date=m_start, end_date=m_end,
            carry_received=cf["milestone_received"].get(term.milestone_id, Decimal("0")),
            percent_override=override,
        )
        resp.payment_type = self.milestones.payment_type_by_ids(
            [term.milestone_id]).get(term.milestone_id)
        if resp.payment_type == _PARTIAL:
            ms_acts = self.activities.list_by_milestone_ids(
                [term.milestone_id]).get(term.milestone_id, [])
            ms_position = self.milestones.position_by_ids(
                [term.milestone_id]).get(term.milestone_id)
            resp.activities = _build_term_activities(
                effective_total, ms_acts, self.term_activities.list_for_term(term_id),
                override if override is not None else term.percent_of_payment, ms_position,
                cost_by_activity=cost_by_activity,
                is_resource=term.milestone_id in resource_ms_ids,
            )
        if term.id in resource_term_derived:
            resp.value, resp.percent_of_payment = resource_term_derived[term.id]
        return resp

    def _cost_by_activity(self, activities):
        """``{activity_id: resource_cost}`` for ``activities`` — Σ the SNAPSHOTTED
        ``computed_cost`` over each activity's planned-resource allocations (the
        rate + cost were resolved from the Java service and stored at write time;
        no live call here). Activities without allocations are omitted."""
        if not activities:
            return {}
        alloc_rows = self.activities.list_planned_resources_for_activities(
            [a.id for a in activities]
        )
        if not alloc_rows:
            return {}
        out: dict = {}
        for r in alloc_rows:
            out[r.activity_id] = out.get(r.activity_id, Decimal("0")) + (
                r.computed_cost or Decimal("0")
            )
        return {aid: payment_calc.to_2dp(v) for aid, v in out.items()}

    def _apply_resource_costs(self, cost_rows, ms_map):
        """Set each ``resource_cost`` cost item's ``cost`` from its milestones'
        activities' SNAPSHOTTED planned-resource costs, and return
        ``(cost_by_activity, resource_ms_ids, acts_by_ms)``.

        ``resource_ms_ids`` = milestones bound to a ``resource_cost`` line — these
        are the COST-DRIVEN milestones (even one with no resource activities and a
        ₹0 cost). Callers use this set rather than "does any activity have a cost",
        so a resource milestone never falls back to percent × base.

        The cost is set on the (detached) ORM rows in-memory so the payment math
        (line_total / phase_base_total / totals) consumes it unchanged — WITHOUT
        writing to the DB (the page is a read). MUST be applied BEFORE the
        carry-forward / effective-base pass so those use the derived cost too."""
        resource_ci = [
            c for c in cost_rows if c.cost_type_code == payment_calc.RESOURCE_COST
        ]
        resource_ms_ids = {m for c in resource_ci for m in ms_map.get(c.id, [])}
        if not resource_ci:
            return {}, resource_ms_ids, {}
        acts_by_ms = self.activities.list_by_milestone_ids(sorted(resource_ms_ids))
        all_acts = [a for acts in acts_by_ms.values() for a in acts]
        cost_by_activity = self._cost_by_activity(all_acts)
        for c in resource_ci:
            ci_total = sum(
                (cost_by_activity.get(a.id, Decimal("0"))
                 for m in ms_map.get(c.id, [])
                 for a in acts_by_ms.get(m, [])),
                Decimal("0"),
            )
            self.db.expunge(c)          # detach so the in-memory cost is not flushed
            c.cost = payment_calc.to_2dp(ci_total)
        return cost_by_activity, resource_ms_ids, acts_by_ms

    def _resource_term_derived(self, terms, resource_ms_ids, acts_by_ms, cost_by_activity):
        """``{term_id: (value, percent)}`` for resource (cost-driven) terms.

        ``value`` = Σ the term milestone's activities' snapshotted resource cost;
        ``percent`` = ``value / Σ(this phase's resource-term values) × 100`` — so a
        lone resource milestone in a phase reads 100% and two unequal ones read
        their true cost share (33.33 / 66.67), never a blank or even-split %.
        Non-resource terms are omitted."""
        val: dict = {}
        for t in terms:
            if t.milestone_id in resource_ms_ids:
                v = sum((cost_by_activity.get(a.id, Decimal("0"))
                         for a in acts_by_ms.get(t.milestone_id, [])), Decimal("0"))
                val[t.id] = (t.phase, payment_calc.to_2dp(v))
        phase_total: dict = {}
        for phase, v in val.values():
            phase_total[phase] = phase_total.get(phase, Decimal("0")) + v
        out: dict = {}
        for tid, (phase, v) in val.items():
            tot = phase_total.get(phase, Decimal("0"))
            out[tid] = (v, payment_calc.to_2dp(v / tot * Decimal("100")) if tot > 0 else Decimal("0"))
        return out

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project


def _cost_item_response(row, milestone_ids: List[str], schedule=None) -> CostItemResponse:
    resp = CostItemResponse.model_validate(row)
    # Transaction rows carry no stored ``cost`` (the value is perTxn × planned),
    # so surface that computed subtotal as the row cost — otherwise the finance
    # page shows 0 for the row.
    if str(getattr(row, "cost_type_code", None) or "").lower() == payment_calc.TRANSACTION_COST:
        resp.cost = payment_calc.transaction_total(
            row.per_transaction_cost, row.planned_transactions
        )
    # Transaction rows total = perTxn × planned + tax; every other type = cost + tax.
    resp.total = payment_calc.line_total(row)
    resp.milestone_ids = list(milestone_ids)
    # Recurring rows carry their own dated installment schedule (built from the
    # row's OWN frequency); every other type leaves it empty.
    resp.schedule = [
        CfPoolInstallmentResponse(
            period_index=inst["period_index"],
            period_start=inst["period_start"],
            period_end=inst["period_end"],
            amount=payment_calc.to_2dp(inst["amount"]),
        )
        for inst in (schedule or [])
    ]
    return resp


def _build_recurring_schedules(cost_rows, phase_dates, project_freq=None, project_start=None):
    """Build every recurring row's dated installment schedule using the row's
    OWN ``frequency_code``, defaulting to yearly (annual) when a row has none.

    Recurring rows are created with a mandatory frequency (defaulted to yearly),
    so the fallback here only guards legacy rows. ``project_freq`` is retained
    for signature stability but no longer drives the default — the default is
    annual, per product rule. ``project_start`` anchors the schedule on the
    contract start so the periods follow the contract, not the calendar (bug
    #327); None keeps the legacy calendar buckets.

    Returns ``(by_cost_item, by_phase)``:
      * ``by_cost_item[ci_id]`` — that row's raw installment list at the row's
        own frequency (for the per-row ``schedule`` on the cost-item response).
      * ``by_phase[phase]``     — the phase's recurring rows merged into ONE
        overlay schedule (see :func:`_merge_phase_recurring`).
    """
    by_ci: dict = {}
    phase_entries: dict = {}
    for r in cost_rows:
        if not payment_calc.is_recurring(r):
            continue
        phase = getattr(r, "phase", None)
        start_date, end_date = phase_dates.get(phase, (None, None))
        r_total = payment_calc.line_total(r)
        # Per-row frequency wins; default to yearly (annual) when a row has none.
        freq = getattr(r, "frequency_code", None) or "yearly"
        sched = (cf_pool.build_schedule(r_total, start_date, end_date, freq, anchor=project_start)
                 if r_total > Decimal("0") else [])
        by_ci[r.id] = sched
        phase_entries.setdefault(phase, {"scheds": [], "freqs": [],
                                         "start": start_date, "end": end_date,
                                         "anchor": project_start})
        phase_entries[phase]["scheds"].append(sched)
        phase_entries[phase]["freqs"].append(freq)
    by_phase = {phase: _merge_phase_recurring(e) for phase, e in phase_entries.items()}
    return by_ci, by_phase


def _merge_phase_recurring(entry) -> list:
    """Merge a phase's recurring rows into one overlay schedule.

    Frequencies are hierarchical (a year holds 12 months, 4 quarters, 2
    half-years), so the overlay is rendered on the FINEST cadence present in the
    phase. Each row's own-frequency installments are placed onto the granular
    bucket that contains the installment's period END (its due date): a coarser
    row (e.g. yearly) shows up as a single lump on the granular timeline while a
    finer row (e.g. monthly) fills every bucket. Amounts are summed per bucket
    and the phase total is conserved exactly.

    Falls back to a date-union merge when there is no recognised cadence to
    align on (e.g. an unknown frequency), or the phase span is unknown."""
    scheds = entry["scheds"]
    granular = cf_pool.finest_frequency(entry["freqs"])
    span_start, span_end = entry.get("start"), entry.get("end")
    anchor = entry.get("anchor")  # contract-relative overlay buckets (bug #327)

    if granular is not None and span_start and span_end:
        start_i = cf_pool.bucket_index(span_start, granular, anchor=anchor)
        end_i = cf_pool.bucket_index(span_end, granular, anchor=anchor)
        if start_i is not None and end_i is not None and end_i >= start_i:
            # Seed the full granular timeline over the phase span, then drop each
            # row's installments onto the bucket holding their period end.
            amounts = {i: Decimal("0") for i in range(start_i, end_i + 1)}
            for sched in scheds:
                for inst in sched:
                    gi = cf_pool.bucket_index(inst["period_end"], granular, anchor=anchor)
                    if gi is None:
                        continue
                    gi = min(max(gi, start_i), end_i)
                    amounts[gi] = payment_calc.to_2dp(amounts[gi] + inst["amount"])
            out = []
            for i in range(start_i, end_i + 1):
                s, e = cf_pool.bucket_bounds(i, granular, anchor=anchor)
                out.append({"period_index": i, "period_start": s,
                            "period_end": e, "amount": amounts[i]})
            return out

    # Fallback: union distinct calendar buckets, summing overlaps.
    buckets: dict = {}
    for sched in scheds:
        for inst in sched:
            key = (inst["period_start"], inst["period_end"])
            slot = buckets.get(key)
            if slot is None:
                buckets[key] = dict(inst)
            else:
                slot["amount"] = payment_calc.to_2dp(slot["amount"] + inst["amount"])
    return sorted(buckets.values(), key=lambda x: x["period_start"])


def _even_split(total: Decimal, n: int) -> List[Decimal]:
    """Split ``total`` into ``n`` 2dp shares that sum to it exactly (the last
    share absorbs the rounding remainder)."""
    if n <= 0:
        return []
    share = payment_calc.to_2dp(total / Decimal(n))
    out: List[Decimal] = []
    running = Decimal("0")
    for i in range(n):
        s = payment_calc.to_2dp(total - running) if i == n - 1 else share
        running += s
        out.append(s)
    return out


def _last_phase_percent_overrides(ordered, term_rows) -> dict:
    """Strictly fully-utilise the LAST phase — its milestone weightages always
    total 100%. Each milestone with an explicit percent keeps it; the remaining
    (``100 − Σ explicit``, floored at 0) is split EVENLY across the null-percent
    milestones. The terminal phase can't carry leftover forward, so it is always
    fully utilised (e.g. one milestone set to 60% auto-fills the other to 40%).
    Returns ``{term_id: percent}`` for the null terms it fills — empty for every
    non-last phase, or a last phase whose terms are all explicit.

    "Last" means the last BILLING phase: any trailing phase that carries no
    payment terms (a recurring-only phase, which is out of the billing
    sequence) is walked past, so the real terminal phase still auto-fills."""
    if not ordered:
        return {}
    phases_with_terms = {t.phase for t in term_rows}
    last = next((p for p in reversed(list(ordered)) if p in phases_with_terms), None)
    if last is None:
        return {}
    last_terms = [t for t in term_rows if t.phase == last]
    null_terms = [t for t in last_terms if t.percent_of_payment is None]
    if not null_terms:
        return {}
    explicit_sum = sum(
        (t.percent_of_payment for t in last_terms if t.percent_of_payment is not None),
        Decimal("0"),
    )
    remaining = Decimal("100") - explicit_sum
    if remaining < Decimal("0"):
        remaining = Decimal("0")
    shares = _even_split(remaining, len(null_terms))
    return {t.id: p for t, p in zip(null_terms, shares)}


def _ld_basis_overrides(term_rows, recurring_phases=frozenset()) -> dict:
    """Resolve the LD-basis ALLOTMENT for terms that have none stored.

    A phase's allotment is its FULL 100% distribution to milestones and is the
    basis penalties / LD are computed on — so, unlike the pay-% even split (which
    fills only the LAST phase), this fills EVERY billing phase: terms with an
    explicit ``ld_basis_percent`` keep it, and the remaining (``100 − Σ explicit``,
    floored at 0) is split EVENLY across the null-allotment terms so each phase
    totals 100%. Recurring-only phases are outside the billing sequence and are
    skipped. Returns ``{term_id: percent}`` for the null terms it fills."""
    out: dict = {}
    by_phase: dict = {}
    for t in term_rows:
        by_phase.setdefault(t.phase, []).append(t)
    for phase, terms in by_phase.items():
        if phase in recurring_phases:
            continue
        null_terms = [t for t in terms if t.ld_basis_percent is None]
        if not null_terms:
            continue
        explicit_sum = sum(
            (t.ld_basis_percent for t in terms if t.ld_basis_percent is not None),
            Decimal("0"),
        )
        remaining = Decimal("100") - explicit_sum
        if remaining < Decimal("0"):
            remaining = Decimal("0")
        shares = _even_split(remaining, len(null_terms))
        for t, p in zip(null_terms, shares):
            out[t.id] = p
    return out


def _payment_term_response(
    row, phase_base: Decimal, row_base: Decimal, cycle_count: Optional[int] = None,
    start_date=None, end_date=None, carry_received: Decimal = Decimal("0"),
    percent_override: Optional[Decimal] = None,
    ld_basis_override: Optional[Decimal] = None,
) -> PaymentTermResponse:
    """``value`` = ``percent × phase EFFECTIVE total`` (fixed [+ one-time on
    first] + phase-wise received) PLUS any milestone-wise ``carry_received``
    paid directly to this milestone. ``percent_override`` (the last-phase
    even-split default) wins over the stored percent when set. ``row_base`` is
    the term's own cost-row total, surfaced as ``rowTotal`` for info only.

    ``ld_basis_percent`` is the milestone's phase allotment (stored value, or the
    even-split ``ld_basis_override`` when unset); ``ld_basis_value`` = that
    allotment × the phase EFFECTIVE base — the money penalties / LD are computed
    against (independent of the reduced ``value`` actually paid)."""
    resp = PaymentTermResponse.model_validate(row)
    resp.row_total = payment_calc.to_2dp(row_base)
    pct = percent_override if percent_override is not None else row.percent_of_payment
    resp.percent_of_payment = pct
    base_value = payment_calc.payment_value(pct, phase_base)
    cr = payment_calc.to_2dp(carry_received)
    resp.carry_received = cr
    resp.value = payment_calc.to_2dp(base_value + cr)
    ld_basis = ld_basis_override if ld_basis_override is not None else row.ld_basis_percent
    resp.ld_basis_percent = ld_basis
    resp.ld_basis_value = payment_calc.payment_value(ld_basis, phase_base)
    resp.start_date = start_date
    resp.end_date = end_date
    resp.cycle_count = cycle_count
    return resp


def _build_term_activities(
    phase_base: Decimal, activities, allocations, term_percent=None, milestone_position=None,
    cost_by_activity=None, is_resource=False,
) -> List[PaymentTermActivityResponse]:
    """One response per milestone ACTIVITY (so the FE can show the full set).

    For a **resource-based** milestone (``is_resource`` — decided at the MILESTONE
    level by the caller, i.e. it is bound to a ``resource_cost`` line), each
    activity's ``value`` is its RESOURCE COST (rate × qty × duration, snapshotted)
    and its ``percent_of_payment`` is derived (``activityCost / Σ costs × 100``);
    an activity with no resources reads ₹0. Otherwise percent comes from the stored
    split (``allocations``) or an EVEN division of ``term_percent``, and value =
    ``percent × phase base``. Display code is ``A<milestonePos>.<activityPos>``.

    NOTE: ``is_resource`` is NO LONGER inferred from "some activity has a cost" — a
    resource milestone with no resource-bearing activities must still price each
    activity at its resource cost (0), never percent × base (which fabricated large
    ₹ amounts from the phase base)."""
    out: List[PaymentTermActivityResponse] = []
    if not activities:
        return out

    cost_by_activity = cost_by_activity or {}
    resource_total = sum(
        (cost_by_activity.get(a.id, Decimal("0")) for a in activities), Decimal("0"),
    )

    pct_by_act = {a.activity_id: a.percent_of_payment for a in allocations}
    even: dict = {}
    if not is_resource and not allocations and term_percent is not None:
        even = {
            act.id: s for act, s in
            zip(activities, _even_split(payment_calc.to_2dp(term_percent), len(activities)))
        }

    for act in activities:
        act_pos = getattr(act, "position", None)
        disp = (
            f"A{milestone_position}.{act_pos}"
            if milestone_position is not None and act_pos is not None else None
        )
        if is_resource:
            value = cost_by_activity.get(act.id, Decimal("0"))
            pct = (
                payment_calc.to_2dp(value / resource_total * Decimal("100"))
                if resource_total > 0 else Decimal("0")
            )
        else:
            pct = even.get(act.id) if even else pct_by_act.get(act.id)
            value = payment_calc.payment_value(pct, phase_base)
        out.append(PaymentTermActivityResponse(
            activity_id=act.id,
            activity_name=getattr(act, "name", None),
            activity_display_code=disp,
            percent_of_payment=pct,
            value=payment_calc.to_2dp(value),
        ))
    return out


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
