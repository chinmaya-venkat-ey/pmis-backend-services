"""#362 — contract_type derivation from the sla_ref prefix."""
from __future__ import annotations

from app.services.sla_service import _derive_contract_type


def test_derives_known_contract_prefixes():
    assert _derive_contract_type("BSP-SLA001") == "BSP"
    assert _derive_contract_type("MSAP-SLA012") == "MSAP"
    assert _derive_contract_type("MSIP-SLA003") == "MSIP"
    assert _derive_contract_type("PMU-SLA007") == "PMU"


def test_case_insensitive_prefix():
    assert _derive_contract_type("pmu-sla007") == "PMU"


def test_pmc_alias_maps_to_pmu():
    # "PMC" (Project Management Consultants) is the PMU-for-MSP engagement, a
    # project label → PMU rules. Without this, PMC-SLA* onboarded with a NULL
    # contract_type and settlement blocked on the missing cap.
    assert _derive_contract_type("PMC-SLA001") == "PMU"
    assert _derive_contract_type("pmc-sla007") == "PMU"
    assert _derive_contract_type("PMC-SLA001_") == "PMU"


def test_unknown_or_missing_prefix_returns_none():
    # A non-standard / project-scoped ref keeps contract_type NULL (as before).
    assert _derive_contract_type("custom-ref-99") is None
    assert _derive_contract_type("nodash") is None
    assert _derive_contract_type("") is None
    assert _derive_contract_type(None) is None
