"""ResourceType domain entity + domain-level constants for activity-resource
classification.

Ported verbatim from the monolith. The seed values (rfp / asg / ccn) are
mirrored here so init-time seeding (when needed) and domain-level
validators see the same canonical list.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple

# Canonical well-known codes. The `resource_types` table is the source of
# truth; this tuple is only used as a "seed on init" list and a default
# display-order for the picker. Admins may add more via the resource_types
# admin router.
RESOURCE_TYPE_SEED = (
    ("rfp", "RFP"),
    ("asg", "ASG"),
    ("ccn", "CCN"),
    )

# Division choices for activity-resource rows. Same 'others + free text' idiom
# as project.category:
# - one of ('tmd1', 'tmd2', 'others')
# - when 'others', a free-text label must be supplied (division_other)
DIVISION_TMD1 = "tmd1"
DIVISION_TMD2 = "tmd2"
DIVISION_OTHERS = "others"
DIVISION_CHOICES: Tuple[str, ...] = (DIVISION_TMD1, DIVISION_TMD2, DIVISION_OTHERS)

@dataclass
class ResourceType:
    id: str
    code: str
    name: str
    active: bool
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            }
