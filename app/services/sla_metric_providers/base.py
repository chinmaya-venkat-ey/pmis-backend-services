"""Auto-evaluation metric providers — the pluggable seam that lets SLAs which
today need a **manual observation** (SLA004-011) instead source their observed
value automatically during the normal rollup.

A provider is resolved for an SLA by the metric_keys it produces (so it applies
only to SLAs that actually declare those metrics — e.g. the leave-attendance
provider matches PMU/PMC-SLA007 but NOT BSP-SLA007, which measures something
else). It returns the same **raw caller-friendly value** a human would POST to
``/sla-compliance/observations`` — a scalar, or a dict keyed by the SLA's
metric_keys for compound SLAs — which the evaluator's ``_translate_simple_value``
normalises. Returning ``None`` means "no value this period" → the runner falls
through to the existing manual ``pending_observation`` behaviour, so a provider
is always safe to register.

Providers are **opt-in**: they only run when ``settings.sla_auto_providers_enabled``
is true AND the provider's data feed is actually configured/reachable (otherwise
``provide`` returns ``None``). This keeps a live penalty module from
auto-scoring off an absent or half-built feed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.sla_activity_mapping import SlaActivityMapping
from app.models.sla_definition import SlaDefinition
from app.utilities.quarter import QuarterKey


@dataclass
class ProviderContext:
    """Everything a provider needs to source one mapping's observation for one
    period. ``bearer_token`` is the caller's JWT, forwarded to any cross-service
    feed (like NpqpService does); it is ``None`` on the cron path, which keeps
    feed-backed providers inert there until a service token exists."""
    db: Session
    mapping: SlaActivityMapping
    sla: SlaDefinition
    activity: Dict[str, Any]
    project_id: Optional[str]
    quarter: QuarterKey
    bearer_token: Optional[str] = None


class MetricProvider(ABC):
    """Supplies the observed value for the SLAs whose metric_keys it ``produces``."""

    #: The exact ``metric_key``s this provider supplies a value for. A provider
    #: is applied to an SLA only when ``produces`` ⊆ the SLA's declared metrics.
    produces: Set[str] = frozenset()

    @abstractmethod
    def provide(self, ctx: ProviderContext) -> Optional[Any]:
        """Return the raw observed value (scalar for single-metric SLAs, or a
        ``{metric_key: value}`` dict for compound SLAs), or ``None`` to fall
        through to the manual observation path."""
        raise NotImplementedError


# ---------------------------------------------------------------- registry

_REGISTRY: List[MetricProvider] = []


def register(provider: MetricProvider) -> None:
    _REGISTRY.append(provider)


def resolve_provider(metric_keys: Set[str]) -> Optional[MetricProvider]:
    """The first registered provider whose produced metric_keys are all present
    on the SLA (matched by metric identity, so it never mis-applies across
    contract families that reuse an SLA number for a different metric)."""
    for provider in _REGISTRY:
        if provider.produces and provider.produces.issubset(metric_keys):
            return provider
    return None


def clear_registry() -> None:
    """Test helper — empties the registry."""
    _REGISTRY.clear()


def months_of_quarter(qk: QuarterKey) -> List[Tuple[int, int]]:
    """The (year, month) pairs a quarter spans, from its bounds (usually 3)."""
    out: List[Tuple[int, int]] = []
    y, m = qk.quarter_start.year, qk.quarter_start.month
    end: date = qk.quarter_end
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out
