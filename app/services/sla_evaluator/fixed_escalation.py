"""fixed_escalation evaluator — milestone / delay-tier classification
and per-unit-time linear escalation.

Two modes, dispatched on ``ctx.sla.ld_formula_rule``:

  * ``PER_UNIT_TIME_DELIVERABLE`` (SLA 001/002 — RFP §5.28.2.b/c):
      LD % = rate_pct_per_week × weeks_of_delay
      base = mapping.overrides.ld_base_amount (deliverable cost)
      rate looked up from contract.contract_ld_rules by rule_key
      derived from sla_ref (sla_001 -> ``sla_001_rate_pct_per_week``).

  * ``PER_UNIT_TIME_QUARTERLY`` (SLA 003 — RFP §5.28.3.a):
      LD % = rate_pct_per_day × days_of_delay
      base = PQP (folded in at quarter settlement, not here)
      rate looked up from contract.contract_ld_rules
      (``sla_003_rate_pct_per_day``).

  * Anything else falls through to the legacy tier-lookup mode: pick
    the highest ``sla_lookup_rows`` tier whose ``sort_order`` threshold
    is <= observed_value, surface that tier's ``lookup_value`` as
    ``rate_percent`` and let downstream compute the amount.

Cap: the contract's ``quarterly_ld_cap_pct`` (from contract_ld_rules) is
applied to the QUARTERLY track (``PER_UNIT_TIME_QUARTERLY``, §5.28.1) ONLY,
so a single day-count can't push a quarter's LD past that ceiling. The
DELIVERABLE track (``PER_UNIT_TIME_DELIVERABLE``, §5.28.2) is UNCAPPED — its
LD is rate × weeks-late in full (the RFP prescribes no quarterly cap on
deliverable LDs). Missing config → raw % surfaced (settlement blocks on the
same missing rule).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.schemas.sla_evaluation import BreachDetail
from app.services.sla_evaluator.base import (
    EvaluatedResult,
    EvaluationContext,
    FormulaEvaluator,
)


# Extract the SLA family number from ``PMU-SLA001`` / ``PMU_SLA002_20260715...``
# to build the contract_ld_rules key (``sla_001_rate_pct_per_week``).
_SLA_FAMILY_RE = re.compile(r"SLA[-_]?0*(\d+)", re.IGNORECASE)

# Extract the numeric suffix from a lookup_key like "week_12" / "day_5".
# from-rfp seeds sort_order = (index + 1), so using sort_order as the
# value-threshold produces an off-by-one (observed=12 picks week_11=5.5%
# instead of week_12=6.0%). We take the true threshold from the key
# suffix and fall back to sort_order-1 for any legacy row that doesn't
# carry the "{unit}_{n}" convention.
_LOOKUP_KEY_SUFFIX_RE = re.compile(r"_(-?\d+)$")


def _sla_family_number(sla_ref: Optional[str]) -> Optional[int]:
    if not sla_ref:
        return None
    m = _SLA_FAMILY_RE.search(sla_ref)
    return int(m.group(1)) if m else None


def _tier_threshold(row) -> Decimal:
    """Prefer the numeric suffix in ``lookup_key`` (``week_12`` → 12) as
    the value-threshold this tier fires at; fall back to sort_order - 1
    when the key lacks the convention (sort_order is 1-indexed row
    position, so subtracting 1 recovers the 0-indexed threshold)."""
    key = row.lookup_key or ""
    m = _LOOKUP_KEY_SUFFIX_RE.search(key)
    if m:
        return Decimal(m.group(1))
    return Decimal(max(0, (row.sort_order or 1) - 1))


class FixedEscalationEvaluator(FormulaEvaluator):
    formula_type = "fixed_escalation"

    def evaluate(self, ctx: EvaluationContext) -> EvaluatedResult:
        result = EvaluatedResult()
        result.guards = self._evaluate_guards(ctx)

        primary = self._primary_metric(ctx)
        if primary is None:
            result.notes.append("No primary metric defined; cannot evaluate.")
            return result

        obs = self._observation_for(ctx, primary.metric_key)
        if obs is None:
            result.notes.append(f"No observation for primary metric '{primary.metric_key}'.")
            return result

        if obs.shape != "SINGLE_VALUE" or obs.single_value is None:
            result.notes.append(
                f"fixed_escalation expects SINGLE_VALUE observation, got '{obs.shape}'."
            )
            return result

        observed_value = Decimal(str(obs.single_value))

        # Phase F1 — linear-per-unit mode dispatches on ld_formula_rule.
        rule = (getattr(ctx.sla, "ld_formula_rule", "") or "").upper()
        if rule in ("PER_UNIT_TIME_DELIVERABLE", "PER_UNIT_TIME_QUARTERLY"):
            return self._per_unit_time(ctx, result, primary.metric_key,
                                        observed_value, rule)

        # Legacy tier-lookup mode — kept intact for SLAs configured with
        # sla_lookup_rows tiers (band-style escalation).
        rows = sorted(ctx.lookup_rows, key=lambda r: r.sort_order)
        if not rows:
            result.notes.append("No lookup rows defined for fixed_escalation.")
            return result

        chosen = None
        for row in rows:
            threshold = _tier_threshold(row)
            if observed_value >= threshold:
                chosen = row

        if chosen is None:
            result.notes.append("No lookup tier matched the observation.")
            return result

        tier_rate = Decimal(chosen.lookup_value or 0)
        result.breaches.append(
            BreachDetail(
                metric_key=primary.metric_key,
                band_label=chosen.lookup_key,
                observed_value=observed_value,
                rate_percent=tier_rate,
                note="fixed_escalation tier matched",
            )
        )
        return result

    # ------------------------------------------------------------------ per-unit-time

    def _per_unit_time(
        self,
        ctx: EvaluationContext,
        result: EvaluatedResult,
        metric_key: str,
        observed_units: Decimal,
        rule: str,
    ) -> EvaluatedResult:
        """LD % = rate × observed_units.

        The quarterly cap (§5.28.1) applies to the QUARTERLY track (Track B)
        only; the DELIVERABLE track (Track A, §5.28.2) is UNCAPPED.
        - PER_UNIT_TIME_DELIVERABLE: rule_key = sla_<n>_rate_pct_per_week (Track A, uncapped)
        - PER_UNIT_TIME_QUARTERLY:   rule_key = sla_<n>_rate_pct_per_day  (Track B, 10% cap)
        """
        family = _sla_family_number(getattr(ctx.sla, "sla_ref", None))
        if family is None:
            result.notes.append(
                f"per-unit-time mode needs a numeric SLA family in sla_ref "
                f"(got '{getattr(ctx.sla, 'sla_ref', None)}')."
            )
            return result

        unit_key = "per_week" if rule == "PER_UNIT_TIME_DELIVERABLE" else "per_day"
        rule_key = f"sla_{family:03d}_rate_pct_{unit_key}"
        rate = ctx.contract_ld_rules.get(rule_key)
        if rate is None:
            result.notes.append(
                f"per-unit-time rate missing in contract_ld_rules for "
                f"{ctx.sla.contract_type}/{rule_key} — evaluation skipped."
            )
            return result

        # LD % = rate × units. Weeks/days should be a whole non-negative
        # number; guard against negatives just in case.
        units = max(observed_units, Decimal("0"))
        raw_pct = rate * units

        # Quarterly cap (§5.28.1) applies to the QUARTERLY track (Track B) ONLY:
        # no single day-count can push a quarter's LD past the contract's 10%
        # ceiling. The DELIVERABLE track (Track A, §5.28.2) has NO such cap — its
        # LD is rate × weeks-late, uncapped. Missing config → surface the raw %
        # (settlement layer blocks on the same missing rule).
        cap_pct = ctx.contract_ld_rules.get("quarterly_ld_cap_pct")
        apply_cap = (
            rule == "PER_UNIT_TIME_QUARTERLY"
            and cap_pct is not None
            and raw_pct > cap_pct
        )
        ld_pct = cap_pct if apply_cap else raw_pct

        result.breaches.append(
            BreachDetail(
                metric_key=metric_key,
                band_label=f"per-unit-time ({unit_key.replace('_', '/')})",
                observed_value=observed_units,
                rate_percent=ld_pct,
                note=(
                    f"LD% = {rate} × {units} = {raw_pct}"
                    + (f" -> capped at {cap_pct}%" if apply_cap else "")
                ),
            )
        )
        return result
