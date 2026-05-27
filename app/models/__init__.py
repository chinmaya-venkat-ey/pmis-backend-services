"""Owned model registry — imported by alembic env.py for metadata population."""
from __future__ import annotations

from app.models.formula_library import FormulaLibrary  # noqa: F401
from app.models.contract import Contract  # noqa: F401
from app.models.contract_scoring_config import ContractScoringConfig  # noqa: F401
from app.models.contract_phase import ContractPhase  # noqa: F401
from app.models.sla_definition import SlaDefinition  # noqa: F401
from app.models.sla_template import SlaTemplate  # noqa: F401
from app.models.sla_metric import SlaMetric  # noqa: F401
from app.models.sla_guard_condition import SlaGuardCondition  # noqa: F401
from app.models.sla_parameter_value import SlaParameterValue  # noqa: F401
from app.models.sla_condition_band import SlaConditionBand  # noqa: F401
from app.models.sla_lookup_row import SlaLookupRow  # noqa: F401
from app.models.sla_dsl_version import SlaDslVersion  # noqa: F401
from app.models.sla_asl_snapshot import SlaAslSnapshot  # noqa: F401
from app.models.metric_observation import MetricObservation  # noqa: F401
from app.models.sla_observation_band_count import SlaObservationBandCount  # noqa: F401
from app.models.evaluation_result import EvaluationResult  # noqa: F401
from app.models.evaluation_sla_result import EvaluationSlaResult  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401

# Mirror declarations (read-only; excluded from alembic autogenerate by env.py:include_object)
from app.models import _cross_schema  # noqa: F401
