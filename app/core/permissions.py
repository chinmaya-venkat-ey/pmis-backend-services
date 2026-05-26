"""Permission code constants for pmis-contract-management."""
from __future__ import annotations

from typing import Final

# Contract domain
CONTRACTS_READ: Final[str] = "contracts:read"
CONTRACTS_CREATE: Final[str] = "contracts:create"
CONTRACTS_UPDATE: Final[str] = "contracts:update"
CONTRACTS_DELETE: Final[str] = "contracts:delete"

# SLA definitions
SLAS_READ: Final[str] = "slas:read"
SLAS_CREATE: Final[str] = "slas:create"
SLAS_UPDATE: Final[str] = "slas:update"
SLAS_DELETE: Final[str] = "slas:delete"

# Formula library (admin only)
FORMULAS_READ: Final[str] = "formulas:read"
FORMULAS_MANAGE: Final[str] = "formulas:manage"

# Metric observations
OBSERVATIONS_READ: Final[str] = "observations:read"
OBSERVATIONS_CREATE: Final[str] = "observations:create"
OBSERVATIONS_APPROVE: Final[str] = "observations:approve"

# Evaluations
EVALUATIONS_READ: Final[str] = "evaluations:read"
EVALUATIONS_TRIGGER: Final[str] = "evaluations:trigger"
EVALUATIONS_APPROVE: Final[str] = "evaluations:approve"
