"""SLA auto-evaluation metric providers.

Public surface: ``ProviderContext``, ``MetricProvider``, ``resolve_provider``.
Importing this package registers the built-in providers. Add a provider by
implementing ``MetricProvider`` and calling ``register`` here.

Registered today (both stub-backed, inert until their feed is configured — see
each provider's docstring):
  * LeaveAvailabilityProvider  → SLA007 (resource_business_days + resource_logged_hours)
  * LeaveReplacementProvider   → SLA005 (resource_replacements_count)

Not yet registered (blocked on later-shared info, documented in
``changes to implement/3``): SLA003 ticket-resolution feed; SLA008/009
notification/approval dates; SLA010 needs a project-mgmt D11 milestone marker.
A future ticket/project provider must be feed/HTTP-backed (never a new
cross-schema read) per the module's integration rules.
"""
from __future__ import annotations

from app.services.sla_metric_providers.base import (  # noqa: F401
    MetricProvider,
    ProviderContext,
    clear_registry,
    register,
    resolve_provider,
)
from app.services.sla_metric_providers.leave_availability_provider import (
    LeaveAvailabilityProvider,
)
from app.services.sla_metric_providers.leave_replacement_provider import (
    LeaveReplacementProvider,
)

register(LeaveAvailabilityProvider())
register(LeaveReplacementProvider())

__all__ = [
    "MetricProvider",
    "ProviderContext",
    "resolve_provider",
    "register",
    "clear_registry",
]
