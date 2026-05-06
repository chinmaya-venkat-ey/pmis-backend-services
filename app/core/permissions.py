"""Permission codes — minimal subset (doc 38).

Only the codes this service's routes reference. The user-service is
the authoritative writer for the permission catalog; this file just
mirrors the constants this service needs at import time for route
decorators.

If a code is added here, it must also exist in:
  - PMIS-user-management/app/core/permissions.py
  - PMIS-OpenProject/app/core/permissions.py
"""

# Master-data router gate (doc 20). Single coarse pair gates every
# /api/v3/master/* endpoint across the platform.
MASTER_DATA_VIEW = "master_data:view"
MASTER_DATA_MANAGE = "master_data:manage"
