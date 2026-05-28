"""Owned model registry — imported by alembic env.py for metadata population."""
from __future__ import annotations

from app.models.formula_library import FormulaLibrary  # noqa: F401
from app.models.severity_master import SeverityMaster  # noqa: F401
from app.models.contract_type_master import ContractTypeMaster  # noqa: F401
from app.models.data_field_master import DataFieldMaster  # noqa: F401

# Mirror declarations (read-only; excluded from alembic autogenerate by env.py:include_object)
from app.models import _cross_schema  # noqa: F401
