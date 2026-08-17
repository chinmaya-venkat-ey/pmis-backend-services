"""ld_tracks is the single source of truth for the SLA settlement Track taxonomy.
The settlement's Track-B set, onboarding's valid set, and the default classifier
all DERIVE from it — this pins that they can never drift (the historical 4-place
duplication that silently charged SLAs on the wrong base or dropped them)."""
from __future__ import annotations

from app.utilities import ld_tracks
from app.services.quarterly_settlement_service import _TRACK_B_RULES
from app.services.sla_service import _VALID_LD_FORMULA_RULES, _derive_ld_formula_rule


def test_track_sets_are_the_expected_taxonomy():
    assert ld_tracks.TRACK_B_RULES == {
        "LADDER", "PER_UNIT_TIME_QUARTERLY", "PER_OCCURRENCE",
        "PER_UNIT_OVER_THRESHOLD", "AVAILABILITY_UPTIME", "DAYS_WEIGHTED",
    }
    assert ld_tracks.TRACK_A_RULES == {"PER_UNIT_TIME_DELIVERABLE"}
    assert ld_tracks.VALID_LD_FORMULA_RULES == (
        ld_tracks.TRACK_A_RULES | ld_tracks.TRACK_B_RULES
    )


def test_settlement_and_onboarding_share_one_source():
    # The settlement classifier and the onboarding-valid set both come from ld_tracks.
    assert _TRACK_B_RULES is ld_tracks.TRACK_B_RULES
    assert _VALID_LD_FORMULA_RULES is ld_tracks.VALID_LD_FORMULA_RULES


def test_every_track_rule_is_onboarding_valid():
    # A rule the settlement counts but onboarding rejects would strand SLAs.
    assert ld_tracks.TRACK_B_RULES <= _VALID_LD_FORMULA_RULES
    assert ld_tracks.TRACK_A_RULES <= _VALID_LD_FORMULA_RULES


def test_default_classifier_is_track_correct():
    assert _derive_ld_formula_rule("FIXED_AMOUNT") == "PER_UNIT_TIME_DELIVERABLE"
    assert ld_tracks.track_of(_derive_ld_formula_rule("FIXED_AMOUNT")) == "A"
    for base in ("QUARTERLY_PAYMENT", "ANNUAL_PAYMENT", None, ""):
        assert ld_tracks.track_of(_derive_ld_formula_rule(base)) == "B"


def test_track_of_unclassified_is_none():
    assert ld_tracks.track_of("NOPE") is None
    assert ld_tracks.track_of(None) is None
