"""DSL Parser — converts DSL YAML text to a normalized ParsedDSL + ASL JSON.

Does NOT touch the database. Raises DslParseError on any validation failure.
The caller (SlaService) is responsible for DB writes.

Parser version: 1.0
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import yaml

from app.core.errors import DslParseError

PARSER_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Valid enum sets (mirrors the plan's schema constants)
# ---------------------------------------------------------------------------

VALID_FORMULAS = {
    "band_accumulation", "point_accumulation", "fixed_escalation", "wac",
}
VALID_MEASUREMENT_INTERVALS = {
    "5_MINUTE", "DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY",
    "QUARTERLY", "BIANNUAL", "ANNUAL", "ONE_TIME", "ON_REVISION",
}
VALID_REPORTING_INTERVALS = {
    "MONTHLY", "QUARTERLY", "BIANNUAL", "ANNUAL", "ONE_TIME",
}
VALID_BASELINE_TYPES = {"STATIC", "ROLLING_WAC", "ROLLING_AVG"}
VALID_COMPOUND_RULES = {"INDEPENDENT", "ANY_BREACH", "ALL_BREACH", "AVERAGE"}
VALID_LD_AGG_METHODS = {"SUM", "AVERAGE"}
VALID_LD_BASES = {
    "QUARTERLY_PAYMENT", "DELIVERABLE_COST", "MILESTONE_INVOICE", "FIRST_PAYMENT",
}
VALID_UNITS = {
    "PERCENT", "COUNT", "DAYS", "BUSINESS_DAYS", "DATE", "RATIO",
    "HOURS", "MINUTES", "SECONDS", "MILLISECONDS", "BUSINESS_WEEKS", "INSTANCES",
}
VALID_DIRECTIONS = {"LOWER_BETTER", "HIGHER_BETTER", "TARGET_DATE"}
VALID_OPERATORS = {"GT", "GTE", "LT", "LTE", "EQ", "NEQ"}
VALID_GUARD_ACTIONS = {"OBSERVATION_MODE", "SUSPEND_LD", "ESCALATE", "EXEMPT"}


# ---------------------------------------------------------------------------
# ParsedDSL dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ParsedMetric:
    key: str
    display_name: str
    unit: str
    target_numeric: Optional[Decimal]
    target_date: Optional[date]
    direction: str
    is_primary: bool


@dataclass
class ParsedGuard:
    metric_key: str
    operator: str
    threshold_value: Decimal
    threshold_unit: Optional[str]
    action: str
    action_description: Optional[str]
    guard_group_id: Optional[int]


@dataclass
class ParsedBand:
    metric_key: str
    band_label: str
    range_min: Optional[Decimal]
    range_max: Optional[Decimal]
    range_unit: Optional[str]
    rate_percent: Optional[Decimal]
    points_contribution: Optional[Decimal]
    fixed_amount: Optional[Decimal]
    sort_order: int
    band_group_id: Optional[int]


@dataclass
class ParsedLookupRow:
    lookup_key: str
    lookup_value: Decimal
    sort_order: int


@dataclass
class ParsedDSL:
    sla_ref: str
    title: str
    description: Optional[str]
    formula_type: str
    measurement_interval: str
    reporting_interval: str
    baseline_type: str
    compound_metric_rule: str
    ld_aggregation_method: str
    ld_computation_base: str
    parameters: Dict[str, str]       # key → str(value) for sla_parameter_values
    metrics: List[ParsedMetric]
    guard_conditions: List[ParsedGuard]
    bands: List[ParsedBand]
    lookup_table: List[ParsedLookupRow]
    # asl_json is built without sla_id; service injects it after row creation
    asl_json: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(doc: dict, key: str, context: str = "") -> Any:
    val = doc.get(key)
    if val is None:
        prefix = f"[{context}] " if context else ""
        raise DslParseError(f"{prefix}Missing required field '{key}'")
    return val


def _enum(val: str, valid: set, field_name: str) -> str:
    v = str(val).upper()
    if v not in valid:
        raise DslParseError(
            f"Invalid value '{val}' for '{field_name}'. "
            f"Valid: {', '.join(sorted(valid))}"
        )
    return v


def _to_decimal(val: Any, field_name: str) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except InvalidOperation:
        raise DslParseError(f"'{field_name}' must be numeric, got: {val!r}")


def _to_date(val: Any, field_name: str) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        raise DslParseError(f"'{field_name}' must be ISO date (YYYY-MM-DD), got: {val!r}")


# ---------------------------------------------------------------------------
# Sub-section parsers
# ---------------------------------------------------------------------------

def _parse_metrics(raw: list) -> List[ParsedMetric]:
    if not raw or not isinstance(raw, list):
        raise DslParseError("'metrics' must be a non-empty list")
    out = []
    for i, m in enumerate(raw):
        ctx = f"metrics[{i}]"
        key = str(_require(m, "key", ctx))
        display_name = str(_require(m, "display_name", ctx))
        unit = _enum(_require(m, "unit", ctx), VALID_UNITS, f"{ctx}.unit")
        direction = _enum(
            m.get("direction", "LOWER_BETTER"), VALID_DIRECTIONS, f"{ctx}.direction"
        )
        target_numeric = _to_decimal(m.get("target_numeric"), f"{ctx}.target_numeric")
        target_date = _to_date(m.get("target_date"), f"{ctx}.target_date")
        if unit == "DATE" and target_numeric is not None:
            raise DslParseError(f"{ctx}: unit=DATE metrics must use target_date, not target_numeric")
        is_primary = bool(m.get("is_primary", True))
        out.append(ParsedMetric(
            key=key,
            display_name=display_name,
            unit=unit,
            target_numeric=target_numeric,
            target_date=target_date,
            direction=direction,
            is_primary=is_primary,
        ))
    return out


def _parse_guards(raw: Any) -> List[ParsedGuard]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise DslParseError("'guard_conditions' must be a list")
    out = []
    for i, g in enumerate(raw):
        ctx = f"guard_conditions[{i}]"
        out.append(ParsedGuard(
            metric_key=str(_require(g, "metric_key", ctx)),
            operator=_enum(_require(g, "operator", ctx), VALID_OPERATORS, f"{ctx}.operator"),
            threshold_value=_to_decimal(_require(g, "threshold_value", ctx), f"{ctx}.threshold_value"),
            threshold_unit=g.get("threshold_unit"),
            action=_enum(_require(g, "action", ctx), VALID_GUARD_ACTIONS, f"{ctx}.action"),
            action_description=g.get("action_description"),
            guard_group_id=g.get("guard_group_id"),
        ))
    return out


def _parse_bands(raw: Any, formula_type: str) -> List[ParsedBand]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise DslParseError("'bands' must be a list")
    out = []
    for gi, group in enumerate(raw):
        ctx = f"bands[{gi}]"
        metric_key = str(_require(group, "metric_key", ctx))
        items = group.get("items", [])
        if not items:
            raise DslParseError(f"{ctx}: 'items' must be a non-empty list")
        for si, item in enumerate(items):
            ictx = f"{ctx}.items[{si}]"
            label = str(_require(item, "label", ictx))
            rate_percent = _to_decimal(item.get("rate_percent"), f"{ictx}.rate_percent")
            points_contribution = _to_decimal(
                item.get("points_contribution"), f"{ictx}.points_contribution"
            )
            out.append(ParsedBand(
                metric_key=metric_key,
                band_label=label,
                range_min=_to_decimal(item.get("range_min"), f"{ictx}.range_min"),
                range_max=_to_decimal(item.get("range_max"), f"{ictx}.range_max"),
                range_unit=item.get("range_unit"),
                rate_percent=rate_percent,
                points_contribution=points_contribution,
                fixed_amount=_to_decimal(item.get("fixed_amount"), f"{ictx}.fixed_amount"),
                sort_order=si,
                band_group_id=item.get("band_group_id"),
            ))
    return out


def _parse_lookup(raw: Any) -> List[ParsedLookupRow]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise DslParseError("'lookup_table' must be a list")
    out = []
    for i, row in enumerate(raw):
        ctx = f"lookup_table[{i}]"
        out.append(ParsedLookupRow(
            lookup_key=str(_require(row, "key", ctx)),
            lookup_value=_to_decimal(_require(row, "value", ctx), f"{ctx}.value"),
            sort_order=i,
        ))
    return out


def _build_asl(parsed: ParsedDSL) -> Dict[str, Any]:
    """Build the normalized ASL JSON dict (without sla_id — injected by service)."""
    bands_by_metric: Dict[str, list] = {}
    for b in parsed.bands:
        bands_by_metric.setdefault(b.metric_key, []).append({
            "label": b.band_label,
            "range_min": float(b.range_min) if b.range_min is not None else None,
            "range_max": float(b.range_max) if b.range_max is not None else None,
            "rate_percent": float(b.rate_percent) if b.rate_percent is not None else None,
            "points_contribution": float(b.points_contribution) if b.points_contribution is not None else None,
            "band_group_id": b.band_group_id,
        })

    return {
        "$schema": "pmis:asl:v1",
        "sla_id": None,  # injected by SlaService after row creation
        "sla_ref": parsed.sla_ref,
        "formula_type": parsed.formula_type,
        "measurement_interval": parsed.measurement_interval,
        "reporting_interval": parsed.reporting_interval,
        "baseline_type": parsed.baseline_type,
        "compound_metric_rule": parsed.compound_metric_rule,
        "ld_aggregation_method": parsed.ld_aggregation_method,
        "ld_computation_base": parsed.ld_computation_base,
        "parameters": {k: v for k, v in parsed.parameters.items()},
        "metrics": [
            {
                "key": m.key,
                "display_name": m.display_name,
                "unit": m.unit,
                "target_numeric": float(m.target_numeric) if m.target_numeric is not None else None,
                "target_date": m.target_date.isoformat() if m.target_date else None,
                "direction": m.direction,
                "is_primary": m.is_primary,
            }
            for m in parsed.metrics
        ],
        "guard_conditions": [
            {
                "metric_key": g.metric_key,
                "operator": g.operator,
                "threshold_value": float(g.threshold_value),
                "threshold_unit": g.threshold_unit,
                "action": g.action,
                "action_description": g.action_description,
                "guard_group_id": g.guard_group_id,
            }
            for g in parsed.guard_conditions
        ],
        "bands": bands_by_metric or None,
        "lookup_table": (
            [{"key": r.lookup_key, "value": float(r.lookup_value)} for r in parsed.lookup_table]
            if parsed.lookup_table else None
        ),
        "scoring_config_ref": None,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse(dsl_text: str) -> ParsedDSL:
    """Parse and validate a DSL YAML string. Returns ParsedDSL on success.
    Raises DslParseError on any validation failure.
    """
    try:
        doc = yaml.safe_load(dsl_text)
    except yaml.YAMLError as exc:
        raise DslParseError(f"YAML parse error: {exc}")

    if not isinstance(doc, dict):
        raise DslParseError("DSL must be a YAML mapping at the top level")

    sla_ref = str(_require(doc, "sla_ref"))
    title = str(_require(doc, "title"))
    description = doc.get("description")
    formula_type = _enum(_require(doc, "formula"), VALID_FORMULAS, "formula")
    measurement_interval = _enum(
        _require(doc, "measurement_interval"), VALID_MEASUREMENT_INTERVALS, "measurement_interval"
    )
    reporting_interval = _enum(
        _require(doc, "reporting_interval"), VALID_REPORTING_INTERVALS, "reporting_interval"
    )
    baseline_type = _enum(
        doc.get("baseline_type", "STATIC"), VALID_BASELINE_TYPES, "baseline_type"
    )
    compound_metric_rule = _enum(
        doc.get("compound_metric_rule", "INDEPENDENT"), VALID_COMPOUND_RULES, "compound_metric_rule"
    )
    ld_aggregation_method = _enum(
        doc.get("ld_aggregation_method", "SUM"), VALID_LD_AGG_METHODS, "ld_aggregation_method"
    )
    ld_computation_base = _enum(
        doc.get("ld_computation_base", "QUARTERLY_PAYMENT"), VALID_LD_BASES, "ld_computation_base"
    )

    # parameters — stored as str(value) in sla_parameter_values
    raw_params = doc.get("parameters") or {}
    if not isinstance(raw_params, dict):
        raise DslParseError("'parameters' must be a mapping")
    parameters = {str(k): str(v) for k, v in raw_params.items()}

    metrics = _parse_metrics(_require(doc, "metrics"))
    guard_conditions = _parse_guards(doc.get("guard_conditions"))
    bands = _parse_bands(doc.get("bands"), formula_type)
    lookup_table = _parse_lookup(doc.get("lookup_table"))

    parsed = ParsedDSL(
        sla_ref=sla_ref,
        title=title,
        description=description,
        formula_type=formula_type,
        measurement_interval=measurement_interval,
        reporting_interval=reporting_interval,
        baseline_type=baseline_type,
        compound_metric_rule=compound_metric_rule,
        ld_aggregation_method=ld_aggregation_method,
        ld_computation_base=ld_computation_base,
        parameters=parameters,
        metrics=metrics,
        guard_conditions=guard_conditions,
        bands=bands,
        lookup_table=lookup_table,
    )
    parsed.asl_json = _build_asl(parsed)
    return parsed
