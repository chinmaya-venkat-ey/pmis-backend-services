"""Consolidated master-data router (doc 20).

Surfaces full CRUD for the four catalog tables under one URL prefix
``/api/v3/master/*``:

- ``divisions``                    (project owner / user / resource division picker)
- ``project_status_transitions``   (legal edges in the project lifecycle)
- ``resource_types``               (activity-resource classification picker)
- ``vendors``                      (delegates to the existing VendorController)

The legacy per-catalog endpoints (``/api/v3/divisions``,
``/api/v3/resource_types``, ``/api/v3/project_status_transitions``,
``/api/v3/vendors/*``) remain functional during the FE migration window
and emit a ``Deprecation: true`` HTTP header pointing at the new path.
"""
from .routes import router as master_data_router  # noqa: F401
