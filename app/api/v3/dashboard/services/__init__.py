"""Dashboard service layer — read-only aggregations over live data."""
from .common import build_project_card, division_label
from .organisations import get_organisation_detail, list_organisations
from .project_detail import get_project_detail
from .project_items import get_project_items
from .projects_list import list_dashboard_projects
from .summary import get_summary

__all__ = [
    "build_project_card",
    "division_label",
    "get_organisation_detail",
    "get_project_detail",
    "get_project_items",
    "get_summary",
    "list_dashboard_projects",
    "list_organisations",
]
