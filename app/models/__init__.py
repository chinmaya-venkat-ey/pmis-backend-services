"""Owned model registry — imported by alembic env.py for metadata population.

Mirror declarations live in `_cross_schema.py` and are imported here too
so SQLAlchemy resolves them, but they are filtered out of alembic autogenerate
by env.py:include_object (schema != 'project').
"""
from __future__ import annotations

from app.models.project import Project  # noqa: F401
from app.models.project_vendor import ProjectVendor  # noqa: F401
from app.models.project_audit_log import ProjectAuditLog  # noqa: F401
from app.models.milestone import Milestone  # noqa: F401
from app.models.milestone_dependency import MilestoneDependency  # noqa: F401
from app.models.milestone_vendor import MilestoneVendor  # noqa: F401
from app.models.activity import Activity  # noqa: F401
from app.models.activity_dependency import ActivityDependency  # noqa: F401
from app.models.activity_resource import ActivityResource  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.task_dependency import TaskDependency  # noqa: F401
from app.models.task_resource import TaskResource  # noqa: F401
from app.models.subtask import Subtask  # noqa: F401
from app.models.subtask_dependency import SubtaskDependency  # noqa: F401
from app.models.subtask_resource import SubtaskResource  # noqa: F401
from app.models.comment import Comment  # noqa: F401
from app.models.document_access_rule import DocumentAccessRule  # noqa: F401
from app.models.project_ownership import ProjectOwnership  # noqa: F401
from app.models.activity_assignment import ActivityAssignment  # noqa: F401
from app.models.activity_workflow_tracker import ActivityWorkflowTracker  # noqa: F401
from app.models.project_cf_pool_installment import ProjectCfPoolInstallment  # noqa: F401
from app.models.dashboard_metric_snapshot import DashboardMetricSnapshot  # noqa: F401
from app.models.activity_planned_resource import ActivityPlannedResource  # noqa: F401

# Phase A — QGR config for NPQP.
# NOTE: resource_deployment_plan + resource_attendance_month were dropped in
# migration p1a000000030 — leave-management service owns those data
# authoritatively via GET /leaves/api/resources and .../attendance/report/*.
# Contract-management's NpqpService calls those endpoints instead.
from app.models.project_qgr_config import ProjectQgrConfig  # noqa: F401

# Mirror declarations (read-only)
from app.models import _cross_schema  # noqa: F401
