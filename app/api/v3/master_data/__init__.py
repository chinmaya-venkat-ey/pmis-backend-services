"""Master-data router (user-mgmt slim slice — doc 37 part 2).

Hosts the catalog endpoints user-management owns:
  - /api/v3/master/roles                  (delegates to legacy /roles handlers)
  - /api/v3/master/permissions            (delegates to legacy /permissions)
  - /api/v3/master/permissions/by-module  (doc 33 change 2)
  - /api/v3/master/notification_templates (doc 36)

The other master-data slices (divisions, project_status_transitions,
resource_types, vendors, project_categories, activity_types,
milestone_statuses, activity_statuses) stay in the monolith — they
belong to project-management concerns, not user-management.
"""
from .routes import router

__all__ = ["router"]
