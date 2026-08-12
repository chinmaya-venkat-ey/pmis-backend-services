"""Structural onboarding guards — reject match-all bands, COMBINED-without-bands,
and unknown ld_formula_rule (defence-in-depth behind the FE onboarding fixes).

These are the exact defects that reached live data via the wizard and had to be
remediated by migrations 0032/0034; _validate_structural stops new ones."""
from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.schemas.sla import SlaConditionBandInput, SlaMetricInput, SlaOnboardRequest
from app.services.sla_service import _VALID_LD_FORMULA_RULES, _validate_structural


def _req(**over) -> SlaOnboardRequest:
    base = dict(
        formula_type="point_accumulation",
        sla_ref="ZZ-SLA999",
        title="test",
        metrics=[SlaMetricInput(metric_key="m1", display_name="M1")],
        condition_bands=[],
    )
    base.update(over)
    return SlaOnboardRequest(**base)


def _band(metric_key="m1", rmin=None, rmax=None, label="b", sev=0) -> SlaConditionBandInput:
    return SlaConditionBandInput(
        metric_key=metric_key, band_label=label,
        range_min=rmin, range_max=rmax, severity_level=sev,
    )


# 1. match-all band ---------------------------------------------------------
def test_rejects_both_null_band():
    with pytest.raises(ValidationError) as e:
        _validate_structural(_req(condition_bands=[_band(rmin=None, rmax=None)]))
    assert e.value.code == "unbounded_condition_band"


def test_allows_single_null_lower_bound():
    # "<= 1" (baseline) — legitimate, must NOT be rejected.
    _validate_structural(_req(condition_bands=[_band(rmin=None, rmax=1), _band(rmin=1, rmax=None, sev=4)]))


def test_allows_single_null_upper_bound():
    # "> 15" — legitimate.
    _validate_structural(_req(condition_bands=[_band(rmin=15, rmax=None)]))


# 2. COMBINED compound must band every metric -------------------------------
def test_rejects_combined_with_unbanded_metric():
    req = _req(
        compound_metric_rule="COMBINED",
        metrics=[SlaMetricInput(metric_key="m1", display_name="M1"),
                 SlaMetricInput(metric_key="m2", display_name="M2", is_primary=False)],
        condition_bands=[_band(metric_key="m1", rmin=15, rmax=None)],  # only m1 banded
    )
    with pytest.raises(ValidationError) as e:
        _validate_structural(req)
    assert e.value.code == "combined_metric_without_bands"


def test_allows_combined_with_all_metrics_banded():
    req = _req(
        compound_metric_rule="COMBINED",
        metrics=[SlaMetricInput(metric_key="m1", display_name="M1"),
                 SlaMetricInput(metric_key="m2", display_name="M2", is_primary=False)],
        condition_bands=[_band(metric_key="m1", rmin=15, rmax=None),
                         _band(metric_key="m2", rmin=143, rmax=None)],
    )
    _validate_structural(req)  # no raise


def test_independent_compound_not_required_to_band_all_metrics():
    # INDEPENDENT (default) scores only the primary; a secondary without bands is fine.
    req = _req(
        metrics=[SlaMetricInput(metric_key="m1", display_name="M1"),
                 SlaMetricInput(metric_key="m2", display_name="M2", is_primary=False)],
        condition_bands=[_band(metric_key="m1", rmin=15, rmax=None)],
    )
    _validate_structural(req)  # no raise


# 3. ld_formula_rule vocabulary --------------------------------------------
def test_rejects_unknown_ld_formula_rule():
    with pytest.raises(ValidationError) as e:
        _validate_structural(_req(ld_formula_rule="NONSENSE_RULE",
                                  condition_bands=[_band(rmin=15, rmax=None)]))
    assert e.value.code == "unknown_ld_formula_rule"


@pytest.mark.parametrize("rule", sorted(_VALID_LD_FORMULA_RULES))
def test_allows_every_known_ld_formula_rule(rule):
    _validate_structural(_req(ld_formula_rule=rule,
                              condition_bands=[_band(rmin=15, rmax=None)]))


def test_allows_null_ld_formula_rule():
    # NULL is fine — a track-correct default is derived downstream.
    _validate_structural(_req(ld_formula_rule=None,
                              condition_bands=[_band(rmin=15, rmax=None)]))


# valid end-to-end shape ----------------------------------------------------
def test_valid_two_band_ladder_passes():
    _validate_structural(_req(condition_bands=[
        _band(rmin=None, rmax=1, sev=0), _band(rmin=1, rmax=None, sev=4),
    ]))
