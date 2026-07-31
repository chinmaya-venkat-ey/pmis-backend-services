"""FastAPI dependency providers (DI factories).

Centralizes the wiring so route files stay thin. Each `get_<resource>_controller`
builds a controller with its service + DB session.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.controllers.activity_status_controller import ActivityStatusController
from app.controllers.activity_type_controller import ActivityTypeController
from app.controllers.cost_type_controller import CostTypeController
from app.controllers.division_controller import DivisionController
from app.controllers.frequency_controller import FrequencyController
from app.controllers.milestone_status_controller import MilestoneStatusController
from app.controllers.notification_template_controller import (
    NotificationTemplateController,
)
from app.controllers.carry_forward_method_controller import CarryForwardMethodController
from app.controllers.payment_type_controller import PaymentTypeController
from app.controllers.priority_controller import PriorityController
from app.controllers.project_category_controller import ProjectCategoryController
from app.controllers.project_status_transition_controller import (
    ProjectStatusTransitionController,
)
from app.controllers.resource_type_controller import ResourceTypeController
from app.controllers.vendor_controller import VendorController
from app.db import get_db
from app.services.activity_status_service import ActivityStatusService
from app.services.activity_type_service import ActivityTypeService
from app.services.cost_type_service import CostTypeService
from app.services.division_service import DivisionService
from app.services.carry_forward_method_service import CarryForwardMethodService
from app.services.payment_type_service import PaymentTypeService
from app.services.frequency_service import FrequencyService
from app.services.milestone_status_service import MilestoneStatusService
from app.services.notification_template_service import NotificationTemplateService
from app.services.priority_service import PriorityService
from app.services.project_category_service import ProjectCategoryService
from app.services.project_status_transition_service import (
    ProjectStatusTransitionService,
)
from app.services.resource_type_service import ResourceTypeService
from app.services.vendor_service import VendorService


def get_division_controller(db: Session = Depends(get_db)) -> DivisionController:
    return DivisionController(DivisionService(db))


def get_vendor_controller(db: Session = Depends(get_db)) -> VendorController:
    return VendorController(VendorService(db))


def get_resource_type_controller(
    db: Session = Depends(get_db),
) -> ResourceTypeController:
    return ResourceTypeController(ResourceTypeService(db))


def get_priority_controller(db: Session = Depends(get_db)) -> PriorityController:
    return PriorityController(PriorityService(db))


def get_cost_type_controller(db: Session = Depends(get_db)) -> CostTypeController:
    return CostTypeController(CostTypeService(db))


def get_frequency_controller(db: Session = Depends(get_db)) -> FrequencyController:
    return FrequencyController(FrequencyService(db))


def get_payment_type_controller(db: Session = Depends(get_db)) -> PaymentTypeController:
    return PaymentTypeController(PaymentTypeService(db))


def get_carry_forward_method_controller(
    db: Session = Depends(get_db),
) -> CarryForwardMethodController:
    return CarryForwardMethodController(CarryForwardMethodService(db))


def get_project_category_controller(
    db: Session = Depends(get_db),
) -> ProjectCategoryController:
    return ProjectCategoryController(ProjectCategoryService(db))


def get_activity_type_controller(
    db: Session = Depends(get_db),
) -> ActivityTypeController:
    return ActivityTypeController(ActivityTypeService(db))


def get_activity_status_controller(
    db: Session = Depends(get_db),
) -> ActivityStatusController:
    return ActivityStatusController(ActivityStatusService(db))


def get_milestone_status_controller(
    db: Session = Depends(get_db),
) -> MilestoneStatusController:
    return MilestoneStatusController(MilestoneStatusService(db))


def get_project_status_transition_controller(
    db: Session = Depends(get_db),
) -> ProjectStatusTransitionController:
    return ProjectStatusTransitionController(ProjectStatusTransitionService(db))


def get_notification_template_controller(
    db: Session = Depends(get_db),
) -> NotificationTemplateController:
    return NotificationTemplateController(NotificationTemplateService(db))
