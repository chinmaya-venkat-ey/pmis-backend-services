"""ResourceType domain entity + domain-level constants for activity-resource
classification."""
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple
from ...shared.datetime import iso_utc


# Canonical well-known codes. The `resource_types` table is the source of
# truth; this tuple is only used as a "seed on init" list and a default
# display-order for the picker. Admins may add more via /resource_types.
RESOURCE_TYPE_SEED = (
    ("rfp", "RFP"),
    ("asg", "ASG"),
    ("ccn", "CCN"),
)


# Division choices for activity-resource rows. Same 'others + free text' idiom
# as project.category:
#   - one of ('tmd1', 'tmd2', 'others')
#   - when 'others', a free-text label must be supplied (division_other)
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
            "created_at": iso_utc(self.created_at),
            "updated_at": iso_utc(self.updated_at),
        }
