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
from app.repositories.project_payment_term_repository import ProjectPaymentTermRepository
from app.repositories.project_phase_qrg_repository import ProjectPhaseQrgRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.payment import (
    CarryForwardResponse,
    CcnBlock,
    CostItemResponse,
    PaymentPageResponse,
    PaymentTermActivityResponse,
    PaymentTermResponse,
    PaymentTotals,
    PhaseBlock,
)
from app.utilities import cycle_calc, payment_calc
from app.utilities.payment_lock import assert_payment_writable, is_payment_locked
from app.utilities.payment_masters import validate_frequency_code

_PARTIAL = "partial_payment"


def _safe_cycle_count(start, end, frequency) -> Optional[int]:
    """Resilient cycle count for a project / phase / milestone span — null (never
    raises) when a frequency isn't applied yet, isn't a cycle frequency
    (one_time/daily), the dates are missing, or the range is unusable. Keeps the
    read endpoints from ever 500ing."""
    if start is None or end is None or not frequency:
        return None
    try:
        return cycle_calc.count_cycles_from_datetimes(start, end, frequency)
    except ValidationError:
        return None


def _seq_key(phase, config):
    """Sort key for a phase: explicit sequence first, else numeric name, else
    non-numeric names last (lexical)."""
    seq = getattr(config, "sequence", None) if config is not None else None
    if seq is not None:
        return (0, seq, str(phase))
    if str(phase).isdigit():
        return (0, int(phase), str(phase))
    return (1, 0, str(phase))


class PaymentPageService:
    def __init__(self, db: Session):
        self.db = db
        self.projects = ProjectRepository(db)
        self.cost_items = ProjectCostItemRepository(db)
        self.payment_terms = ProjectPaymentTermRepository(db)
        self.phase_qrg = ProjectPhaseQrgRepository(db)
        self.milestones = MilestoneRepository(db)
        self.activities = ActivityRepository(db)
        self.term_activities = ProjectPaymentTermActivityRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------- phase order

    def _order_phases(self, phases, config_by_phase) -> List[str]:
        return sorted(phases, key=lambda p: _seq_key(p, config_by_phase.get(p)))

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
        distinct = {c.phase for c in cost_rows if c.phase is not None}
        distinct |= {t.phase for t in term_rows if t.phase is not None}
        distinct |= {q.phase for q in configs if q.phase is not None}
        ordered = self._order_phases(distinct, config_by_phase)
        cf_config = {
            p: {
                "enabled": bool(getattr(config_by_phase.get(p), "carry_forward_enabled", False)),
                "mode": getattr(config_by_phase.get(p), "carry_forward_mode", None),
            }
            for p in ordered
        }
        cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ordered, cf_config)
        return ordered, config_by_phase, cf, cost_rows, term_rows

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

    def build_page(self, project_id: str) -> PaymentPageResponse:
        project = self._require_project(project_id)

        ordered, config_by_phase, cf, cost_rows, term_rows = self._load_phase_state(project_id)
        ms_map = self.cost_items.milestone_ids_by_cost_item([c.id for c in cost_rows])
        phase_dates = self.cost_items.phase_milestone_date_bounds(project_id)
        ms_dates = self.cost_items.milestone_date_map(project_id)

        # Partial-payment activity enrichment (bulk; no N+1).
        term_ms_ids = [t.milestone_id for t in term_rows if t.milestone_id]
        payment_type_map = self.milestones.payment_type_by_ids(term_ms_ids)
        partial_ms_ids = [m for m in term_ms_ids if payment_type_map.get(m) == _PARTIAL]
        activities_by_ms = self.activities.list_by_milestone_ids(partial_ms_ids)
        ms_pos = self.milestones.position_by_ids(partial_ms_ids)
        term_acts = self.term_activities.list_for_terms([t.id for t in term_rows])
        ms_received = cf["milestone_received"]

        row_total_by_ci = {
            c.id: payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows
        }

        totals_d = payment_calc.contract_totals(cost_rows)
        totals = PaymentTotals(
            total_contract_cost=totals_d["total_contract_cost"],
            fixed_cost=totals_d["fixed_cost"],
            one_time_cost=totals_d["one_time_cost"],
        )

        cost_items = [
            _cost_item_response(c, ms_map.get(c.id, [])) for c in cost_rows
        ]

        phase_blocks: List[PhaseBlock] = []
        for idx, phase in enumerate(ordered):
            cfg = config_by_phase.get(phase)
            phase_fixed = payment_calc.phase_fixed_total(cost_rows, phase)
            effective_total = cf["effective_base"].get(phase, phase_fixed)
            terms_in_phase = [t for t in term_rows if t.phase == phase]
            term_responses = []
            for t in terms_in_phase:
                m_start, m_end = ms_dates.get(t.milestone_id, (None, None))
                resp = _payment_term_response(
                    t, effective_total, row_total_by_ci.get(t.cost_item_id, Decimal("0")),
                    cycle_count=_safe_cycle_count(m_start, m_end, t.frequency_code),
                    start_date=m_start, end_date=m_end,
                    carry_received=ms_received.get(t.milestone_id, Decimal("0")),
                )
                resp.payment_type = payment_type_map.get(t.milestone_id)
                if resp.payment_type == _PARTIAL:
                    resp.activities = _build_term_activities(
                        effective_total,
                        activities_by_ms.get(t.milestone_id, []),
                        term_acts.get(t.id, []),
                        t.percent_of_payment,
                        ms_pos.get(t.milestone_id),
                    )
                term_responses.append(resp)

            start_date, end_date = phase_dates.get(phase, (None, None))
            phase_frequency = next(
                (t.frequency_code for t in terms_in_phase if t.frequency_code), None,
            )
            # Milestone-wise inflow to THIS phase = Σ add-ons paid to its
            # milestones (proportional to its milestone count).
            received_ms = sum(
                (ms_received.get(t.milestone_id, Decimal("0")) for t in terms_in_phase),
                Decimal("0"),
            )
            cf_block = CarryForwardResponse(
                enabled=bool(getattr(cfg, "carry_forward_enabled", False)),
                mode=getattr(cfg, "carry_forward_mode", None),
                leftover=cf["leftover"].get(phase, Decimal("0.00")),
                carried_out=cf["carried_out"].get(phase, Decimal("0.00")),
                received=cf["phase_received"].get(phase, Decimal("0.00")),
                received_milestone=payment_calc.to_2dp(received_ms),
                is_last_phase=(idx == len(ordered) - 1),
            )
            phase_blocks.append(PhaseBlock(
                phase=phase,
                sequence=getattr(cfg, "sequence", None),
                phase_fixed_total=phase_fixed,
                effective_phase_total=effective_total,
                start_date=start_date,
                end_date=end_date,
                cycle_count=_safe_cycle_count(start_date, end_date, phase_frequency),
                payment_terms=term_responses,
                carry_forward=cf_block,
            ))

        cap_pct = payment_calc.to_2dp(project.ccn_cap_percent)
        ccn = CcnBlock(
            cap_percent=cap_pct,
            value=payment_calc.ccn_value(totals.total_contract_cost, cap_pct),
        )

        return PaymentPageResponse(
            project_id=project.id,
            project_code=project.project_code,
            status=project.status,
            is_locked=is_payment_locked(project.status),
            start_date=project.start_date,
            end_date=project.end_date,
            cycle_count=_safe_cycle_count(
                project.start_date, project.end_date, cycle_calc.QUARTERLY,
            ),
            cost_items=cost_items,
            totals=totals,
            phases=phase_blocks,
            ccn=ccn,
        )

    def term_response(self, term_id: str) -> PaymentTermResponse:
        """Public: one payment-term response with the per-activity split."""
        return self._single_term_response(term_id)

    def list_term_responses(self, project_id: str, term_rows) -> List[PaymentTermResponse]:
        """Build responses for a set of term rows under one carry-forward pass
        (used by the payment-term list endpoint). Enriches partial-payment
        milestones with their activity split."""
        ordered, _, cf, cost_rows, _ = self._load_phase_state(project_id)
        row_total_by_ci = {
            c.id: payment_calc.row_total(c.cost, c.tax_amount) for c in cost_rows
        }
        ms_dates = self.cost_items.milestone_date_map(project_id)
        term_ms_ids = [t.milestone_id for t in term_rows if t.milestone_id]
        payment_type_map = self.milestones.payment_type_by_ids(term_ms_ids)
        partial_ms_ids = [m for m in term_ms_ids if payment_type_map.get(m) == _PARTIAL]
        activities_by_ms = self.activities.list_by_milestone_ids(partial_ms_ids)
        ms_pos = self.milestones.position_by_ids(partial_ms_ids)
        term_acts = self.term_activities.list_for_terms([t.id for t in term_rows])
        ms_received = cf["milestone_received"]
        out: List[PaymentTermResponse] = []
        for t in term_rows:
            eff = cf["effective_base"].get(t.phase, Decimal("0"))
            m_start, m_end = ms_dates.get(t.milestone_id, (None, None))
            resp = _payment_term_response(
                t, eff, row_total_by_ci.get(t.cost_item_id, Decimal("0")),
                cycle_count=_safe_cycle_count(m_start, m_end, t.frequency_code),
                start_date=m_start, end_date=m_end,
                carry_received=ms_received.get(t.milestone_id, Decimal("0")),
            )
            resp.payment_type = payment_type_map.get(t.milestone_id)
            if resp.payment_type == _PARTIAL:
                resp.activities = _build_term_activities(
                    eff, activities_by_ms.get(t.milestone_id, []), term_acts.get(t.id, []),
                    t.percent_of_payment, ms_pos.get(t.milestone_id),
                )
            out.append(resp)
        return out

    # ----------------------------------------------------------------- write

    def set_phase_frequency(
        self, project_id: str, phase: str, frequency_code: str, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Set ONE frequency for the WHOLE phase — applied to every live payment
        term in it. Returns the recomputed page."""
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        code = validate_frequency_code(self.db, frequency_code)

        terms = [t for t in self.payment_terms.list_all_live(project_id) if t.phase == phase]
        for t in terms:
            self.payment_terms.update(t, frequency_code=code, updated_by=caller_user_id)
        self.audit.write(
            project_id=project_id, target_kind="project", target_id=project_id,
            action="set_phase_frequency", actor_user_id=caller_user_id,
            changes={"phase": phase, "frequency_code": code, "terms_updated": len(terms)},
        )
        self.db.commit()
        return self.build_page(project_id)

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
        enabled: bool, mode: Optional[str], caller_user_id: Optional[str],
        caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        """Configure carry-forward for a phase. A carrying phase always carries
        its ENTIRE leftover, split equally across all SUBSEQUENT phases
        (mode='phase') or all subsequent milestones (mode='milestone').

        Validations: the phase must exist; mode must be 'phase'|'milestone'; and
        there must be eligible recipients (a phase with no subsequent phase
        can't carry phase-wise; with no subsequent milestones, can't carry
        milestone-wise).
        """
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)
        self.ensure_phase_configs(project_id)

        ordered, config_by_phase, cf, _, term_rows = self._load_phase_state(project_id)
        if phase not in ordered:
            raise ValidationError(
                f"Phase '{phase}' has no cost rows to carry forward from.",
                code="validation_error",
            )
        if enabled:
            if mode not in (payment_calc.CF_PHASE, payment_calc.CF_MILESTONE):
                raise ValidationError(
                    "mode must be 'phase' or 'milestone'.", code="validation_error",
                )
            subsequent = ordered[ordered.index(phase) + 1:]
            if mode == payment_calc.CF_PHASE and not subsequent:
                raise ValidationError(
                    "Cannot carry forward phase-wise from the last phase — no subsequent phase.",
                    code="validation_error",
                )
            if mode == payment_calc.CF_MILESTONE:
                sub_ms = [
                    t.milestone_id for t in term_rows
                    if t.phase in subsequent and t.milestone_id is not None
                ]
                if not sub_ms:
                    raise ValidationError(
                        "Cannot carry forward milestone-wise — no subsequent milestones.",
                        code="validation_error",
                    )

        fields = dict(
            carry_forward_enabled=enabled,
            carry_forward_mode=mode if enabled else None,
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

        self.audit.write(
            project_id=project_id, target_kind="phase_config", target_id=row.id,
            action="set_carry_forward", actor_user_id=caller_user_id,
            changes={"phase": phase, "enabled": enabled, "mode": mode},
        )
        self.db.commit()
        return self.build_page(project_id)

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
        self, project_id: str, ccn_cap_percent: Decimal, *,
        caller_user_id: Optional[str], caller_is_admin: bool = False,
    ) -> PaymentPageResponse:
        project = self._require_project(project_id)
        assert_payment_writable(project, caller_is_admin=caller_is_admin)

        before = project.ccn_cap_percent
        self.projects.update(project, updated_by=caller_user_id, ccn_cap_percent=ccn_cap_percent)
        self.audit.write(
            project_id=project_id, target_kind="project", target_id=project_id,
            action="update_ccn_cap", actor_user_id=caller_user_id,
            changes={"ccn_cap_percent": {"before": _s(before), "after": _s(ccn_cap_percent)}},
        )
        self.db.commit()
        return self.build_page(project_id)

    # --------------------------------------------------------------- helpers

    def _single_term_response(self, term_id: str) -> PaymentTermResponse:
        """Build one payment-term response (with the per-activity split) using
        the live carry-forward state for the term's phase."""
        term = self.payment_terms.get_by_id(term_id)
        if term is None:
            raise ValidationError("Payment term not found.", code="not_found")
        ordered, _, cf, cost_rows, _ = self._load_phase_state(term.project_id)
        effective_total = cf["effective_base"].get(term.phase, Decimal("0"))
        row_total = next(
            (payment_calc.row_total(c.cost, c.tax_amount)
             for c in cost_rows if c.id == term.cost_item_id), Decimal("0"),
        )
        ms_dates = self.cost_items.milestone_date_map(term.project_id)
        m_start, m_end = ms_dates.get(term.milestone_id, (None, None))
        resp = _payment_term_response(
            term, effective_total, row_total,
            cycle_count=_safe_cycle_count(m_start, m_end, term.frequency_code),
            start_date=m_start, end_date=m_end,
            carry_received=cf["milestone_received"].get(term.milestone_id, Decimal("0")),
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
                term.percent_of_payment, ms_position,
            )
        return resp

    def _require_project(self, project_id: str):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        return project


def _cost_item_response(row, milestone_ids: List[str]) -> CostItemResponse:
    resp = CostItemResponse.model_validate(row)
    resp.total = payment_calc.row_total(row.cost, row.tax_amount)
    resp.milestone_ids = list(milestone_ids)
    return resp


def _payment_term_response(
    row, phase_base: Decimal, row_base: Decimal, cycle_count: Optional[int] = None,
    start_date=None, end_date=None, carry_received: Decimal = Decimal("0"),
) -> PaymentTermResponse:
    """``value`` = ``percent × phase EFFECTIVE total`` (fixed [+ one-time on
    first] + phase-wise received) PLUS any milestone-wise ``carry_received``
    paid directly to this milestone. ``row_base`` is the term's own cost-row
    total, surfaced as ``rowTotal`` for info only."""
    resp = PaymentTermResponse.model_validate(row)
    resp.row_total = payment_calc.to_2dp(row_base)
    base_value = payment_calc.payment_value(row.percent_of_payment, phase_base)
    cr = payment_calc.to_2dp(carry_received)
    resp.carry_received = cr
    resp.value = payment_calc.to_2dp(base_value + cr)
    resp.start_date = start_date
    resp.end_date = end_date
    resp.cycle_count = cycle_count
    return resp


def _build_term_activities(
    phase_base: Decimal, activities, allocations, term_percent=None, milestone_position=None,
) -> List[PaymentTermActivityResponse]:
    """One response per milestone ACTIVITY (so the FE can show the full set).

    Percent comes from the stored split (``allocations``); with NO stored split
    it defaults to an EVEN division of ``term_percent`` across the activities
    (the last absorbs the rounding remainder so the sum is exact). Display code
    is ``A<milestonePos>.<activityPos>``."""
    out: List[PaymentTermActivityResponse] = []
    if not activities:
        return out

    pct_by_act = {a.activity_id: a.percent_of_payment for a in allocations}
    even: dict = {}
    if not allocations and term_percent is not None:
        n = len(activities)
        tp = payment_calc.to_2dp(term_percent)
        share = payment_calc.to_2dp(tp / Decimal(n))
        running = Decimal("0")
        for idx, act in enumerate(activities):
            s = payment_calc.to_2dp(tp - running) if idx == n - 1 else share
            running += s
            even[act.id] = s

    for act in activities:
        pct = even.get(act.id) if even else pct_by_act.get(act.id)
        act_pos = getattr(act, "position", None)
        disp = (
            f"A{milestone_position}.{act_pos}"
            if milestone_position is not None and act_pos is not None else None
        )
        out.append(PaymentTermActivityResponse(
            activity_id=act.id,
            activity_name=getattr(act, "name", None),
            activity_display_code=disp,
            percent_of_payment=pct,
            value=payment_calc.payment_value(pct, phase_base),
        ))
    return out


def _s(value) -> Optional[str]:
    return None if value is None else str(value)
