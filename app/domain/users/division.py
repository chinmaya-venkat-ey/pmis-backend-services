"""Division enum constants for the User aggregate.

These are wire-level enum values used by user create/update flows. The
monolith keeps the same constants in
``app/domain/resource_types/resource_type.py``; we duplicate them here
because user-service does NOT own the resource_types / divisions
master-data CRUD (per Q1 of the drift port — master-data stays in the
monolith / project-service).

If product later admits new divisions, the source of truth is the
``divisions`` catalog table — but the well-known codes below are
accepted unconditionally so the bootstrap admin and any catalog-less
test DB still validate.
"""
from typing import Tuple


DIVISION_TMD1 = "tmd1"
DIVISION_TMD2 = "tmd2"
DIVISION_OTHERS = "others"

DIVISION_CHOICES: Tuple[str, ...] = (DIVISION_TMD1, DIVISION_TMD2, DIVISION_OTHERS)
