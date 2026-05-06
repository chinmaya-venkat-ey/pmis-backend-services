"""Catalogs module (LEGACY — superseded by doc 20).

Two read-only endpoints kept for FE backwards-compat:

- ``GET /api/v3/divisions``                    (use ``/api/v3/master/divisions`` instead)
- ``GET /api/v3/project_status_transitions``   (use ``/api/v3/master/project_status_transitions`` instead)

Both stamp ``Deprecation: true`` and ``Link: <successor>`` so the FE can
detect and migrate. The ``project_owners`` endpoints (GET / POST / DELETE)
that previously lived here were removed in doc 20 along with the
underlying table; the project_owner whitelist had been dead since doc 18.
"""
from .routes import router as catalogs_router  # noqa: F401
