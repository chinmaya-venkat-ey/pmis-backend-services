"""wac evaluator — Weighted Average defect Count with rolling baseline.

WAC = (w1*blocker + w2*critical + w3*major + w4*minor) / (total_defects * apps)

Variance is computed against the previous_wac (or `baseline` from the
observation). Each variance_step_percent (parameter, default 5%) shifts the
severity by 1. Final severity drives LD% using the standard points-to-LD
table (same as point_accumulation).

Observation shape: WAC_BREAKDOWN with keys:
  blocker, critical, major, minor, applications, baseline (optional),
  previous_wac (optional — if absent, baseline is used).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional

from app.schemas.sla_evaluation import BreachDetail
from app.services.sla_evaluator.base import (
    EvaluatedResult,
    EvaluationContext,
    FormulaEvaluator,
)
from app.services.sla_evaluator.point_accumulation import _ld_percent_for_points


DEFAULT_WEIGHTS = {"blocker": Decimal("8"), "critical": Decimal("4"), "major": Decimal("2"), "minor": Decimal("1")}


class WacEvaluator(FormulaEvaluator):
    formula_type = "wac"

    def evaluate(self, ctx: EvaluationContext) -> EvaluatedResult:
        result = EvaluatedResult()
        result.guards = self._evaluate_guards(ctx)

        primary = self._primary_metric(ctx)
        if primary is None:
            result.notes.append("No primary metric defined; cannot evaluate.")
            return result

        obs = self._observation_for(ctx, primary.metric_key)
        if obs is None or obs.shape != "WAC_BREAKDOWN" or not obs.wac_breakdown:
            result.notes.append(
                f"wac expects WAC_BREAKDOWN observation for '{primary.metric_key}'."
            )
            return result

        weights = self._weights(ctx)
        variance_step = self._variance_step(ctx)

        wb = obs.wac_breakdown
        blocker = Decimal(wb.get("blocker", 0))
        critical = Decimal(wb.get("critical", 0))
        major = Decimal(wb.get("major", 0))
        minor = Decimal(wb.get("minor", 0))
        applications = Decimal(wb.get("applications", 0))
        baseline = Decimal(wb.get("baseline", 0))
        previous_wac = Decimal(wb.get("previous_wac", baseline))

        total_defects = blocker + critical + major + minor
        if total_defects == 0 or applications == 0:
            result.notes.append("Zero total defects or zero applications; LD = 0%.")
            result.ld_percent = Decimal("0")
            result.severity_level = 0
            result.accumulated_points = Decimal("0")
            return result

        wac = (
            (weights["blocker"] * blocker)
            + (weights["critical"] * critical)
            + (weights["major"] * major)
            + (weights["minor"] * minor)
        ) / (total_defects * applications)

        # Variance in percent points relative to previous_wac.
        variance_pct = Decimal("0")
        if previous_wac > 0:
            variance_pct = ((wac - previous_wac) / previous_wac) * Decimal("100")

        # Each variance_step_percent shifts severity by 1.
        # Treat fractional steps by integer truncation toward zero.
        steps = int(variance_pct // variance_step) if variance_step > 0 else 0
        # Severity bounded [0, 4] per RFP.
        severity = max(0, min(4, steps))

        # Points for severity, accumulated for the period (single measurement).
        from app.services.sla_evaluator.point_accumulation import _points_for_level
        points = _points_for_level(severity)
        ld_percent = _ld_percent_for_points(points)

        result.accumulated_points = points
        result.severity_level = severity
        result.ld_percent = ld_percent
        if ctx.ld_base_amount is not None:
            result.ld_amount = (ctx.ld_base_amount * ld_percent) / Decimal("100")

        result.breaches.append(
            BreachDetail(
                metric_key=primary.metric_key,
                band_label=f"WAC={wac:.4f} prev={previous_wac:.4f} variance={variance_pct:.2f}%",
                observed_value=wac,
                severity_level=severity,
                points_contribution=points,
                rate_percent=ld_percent,
                note=(
                    f"variance_step={variance_step}%, steps={steps}, "
                    f"weights={ {k: str(v) for k, v in weights.items()} }"
                ),
            )
        )
        return result

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _weights(ctx: EvaluationContext) -> Dict[str, Decimal]:
        """Read severity_weights parameter '1:1,2:2,3:3,4:4' style, mapping
        positions 1..4 to blocker/critical/major/minor. If not provided, use
        the default 8/4/2/1 from the RFP."""
        raw = next(
            (p.param_value for p in ctx.parameters if p.param_key == "severity_weights"),
            None,
        )
        if not raw:
            return dict(DEFAULT_WEIGHTS)
        # Parse "1:8,2:4,3:2,4:1" or any order.
        mapping = {}
        for pair in raw.split(","):
            if ":" not in pair:
                continue
            k, v = pair.split(":", 1)
            try:
                mapping[int(k.strip())] = Decimal(v.strip())
            except (ValueError, ArithmeticError):
                continue
        return {
            "blocker": mapping.get(1, DEFAULT_WEIGHTS["blocker"]),
            "critical": mapping.get(2, DEFAULT_WEIGHTS["critical"]),
            "major": mapping.get(3, DEFAULT_WEIGHTS["major"]),
            "minor": mapping.get(4, DEFAULT_WEIGHTS["minor"]),
        }

    @staticmethod
    def _variance_step(ctx: EvaluationContext) -> Decimal:
        raw = next(
            (p.param_value for p in ctx.parameters if p.param_key == "variance_step_percent"),
            None,
        )
        if not raw:
            return Decimal("5")
        try:
            return Decimal(raw)
        except (ValueError, ArithmeticError):
            return Decimal("5")
