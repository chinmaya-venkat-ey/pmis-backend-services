"""Master-data router (user-mgmt slim slice).

Hosts the catalog endpoints user-management owns:
  - /api/v3/master/roles                  (delegates to legacy /roles handlers)
  - /api/v3/master/permissions            (delegates to legacy /permissions)
  - /api/v3/master/permissions/by-module

``/api/v3/master/notification_templates`` is owned by
PMIS-notification-service (doc 38). The other master-data slices
(divisions, project_status_transitions, resource_types, vendors,
project_categories, activity_types, milestone_statuses,
activity_statuses) stay on the monolith.
"""
from .routes import router

__all__ = ["router"]
