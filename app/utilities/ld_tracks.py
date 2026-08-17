"""Single source of truth for the SLA settlement TRACK taxonomy.

The (corrigendum-amended) RFP runs **two** LD regimes, charged on **different money
bases**, which must never be summed together:

  * **Track A** — deliverable/milestone LD (RFP §5.28.2, Phase 1, D1-D8). SLA
    001/002: ``LD = % × that deliverable's own cost`` per week of delay, billed on
    the deliverable's own invoice. **No** quarterly cap. Rule:
    ``PER_UNIT_TIME_DELIVERABLE``.
  * **Track B** — resource/quarterly LD (RFP §5.28.1 + §5.28.3, Phase 2/3, D9/D10).
    SLA 003-011: ``LD = Σ(%LD) × PQP``, capped at 10% of PQP per quarter, deducted
    from PA (``AQP = (PA − LD) + QGR``). Rules: the points-ladder / per-day /
    occurrence / threshold family.

An SLA's ``ld_formula_rule`` classifies it into a track. That one classification was
historically encoded in FOUR places — ``quarterly_settlement_service._TRACK_B_RULES``,
``sla_service._VALID_LD_FORMULA_RULES`` and ``._derive_ld_formula_rule``, and
migration ``0031`` — which had to be kept in sync by hand; a drift silently charges
an SLA on the wrong base or drops it from the settlement entirely. **This module is
the one place the taxonomy is defined; everything else derives from it.**
"""
from __future__ import annotations

from typing import Optional

# The ONLY place a rule's settlement track is decided. rule -> "A" | "B".
_RULE_TRACK = {
    "PER_UNIT_TIME_DELIVERABLE": "A",   # §5.28.2 deliverable LD (per-week × deliverable cost)
    "LADDER": "B",                      # §5.28.1 points ladder × PQP
    "PER_UNIT_TIME_QUARTERLY": "B",     # §5.28.3.a SLA003 per-day × PQP
    "PER_OCCURRENCE": "B",              # occurrence-count → severity
    "PER_UNIT_OVER_THRESHOLD": "B",     # §5.28.3.b SLA005
    "AVAILABILITY_UPTIME": "B",         # MSIP §1.5.4
    "DAYS_WEIGHTED": "B",               # BSP
}

# Track B = the rules that participate in the quarterly settlement's LD sum + 10% cap.
TRACK_B_RULES = frozenset(r for r, t in _RULE_TRACK.items() if t == "B")
# Track A = per-deliverable LD, billed on the deliverable's own invoice (no quarter cap).
TRACK_A_RULES = frozenset(r for r, t in _RULE_TRACK.items() if t == "A")
# Every rule a settlement can classify into a track; anything else is a config bug
# (onboarding rejects it so an SLA is never stored that would silently produce no LD).
VALID_LD_FORMULA_RULES = frozenset(_RULE_TRACK)


def track_of(ld_formula_rule: Optional[str]) -> Optional[str]:
    """The settlement track (``"A"`` / ``"B"``) a rule belongs to, or ``None`` when
    the rule is unclassified (falls out of BOTH tracks → produces no LD)."""
    return _RULE_TRACK.get(ld_formula_rule or "")


def default_ld_formula_rule(ld_computation_base: Optional[str]) -> str:
    """Track-correct default rule when onboarding doesn't specify one, derived from
    the (already-captured) LD base: ``FIXED_AMOUNT`` (deliverable, §5.28.2) → Track A
    (``PER_UNIT_TIME_DELIVERABLE``); otherwise (``QUARTERLY_PAYMENT`` /
    ``ANNUAL_PAYMENT``, resource/quarterly §5.28.3/4) → Track B (``LADDER``). Within
    Track B the money sums identically regardless of the specific rule."""
    return (
        "PER_UNIT_TIME_DELIVERABLE"
        if (ld_computation_base or "").upper() == "FIXED_AMOUNT"
        else "LADDER"
    )
