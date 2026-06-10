"""Owned model registry — imported by alembic env.py for metadata population."""
from __future__ import annotations

from app.models.formula_library import FormulaLibrary  # noqa: F401
from app.models.severity_master import SeverityMaster  # noqa: F401
from app.models.project_ld_band import ProjectLdBand  # noqa: F401
from app.models.contract_type_master import ContractTypeMaster  # noqa: F401
from app.models.data_field_master import DataFieldMaster  # noqa: F401
from app.models.sla_category_master import SlaCategoryMaster  # noqa: F401

# SLA master tables
from app.models.sla_definition import SlaDefinition  # noqa: F401
from app.models.sla_metric import SlaMetric  # noqa: F401
from app.models.sla_condition_band import SlaConditionBand  # noqa: F401
from app.models.sla_guard_condition import SlaGuardCondition  # noqa: F401
from app.models.sla_parameter_value import SlaParameterValue  # noqa: F401
from app.models.sla_lookup_row import SlaLookupRow  # noqa: F401

# Activity binding
from app.models.sla_activity_mapping import SlaActivityMapping  # noqa: F401

# Image attachments per SLA template (bytes live in pmis-file-store).
from app.models.sla_attachment import SlaAttachment  # noqa: F401

# Cross-schema users.* mirrors removed: RBAC is now resolved by calling
# user-management's /authz/context (see app/middleware/auth_middleware.py),
# so this service no longer declares read-only mirrors of the users schema.
