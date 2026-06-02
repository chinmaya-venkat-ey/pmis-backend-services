"""Q24 — cross-schema mirror drift test.

This is the CANONICAL drift-detector. It compares every column declared on a
mirror table in another service's `_cross_schema.py` against the same-named
column on the OWNING model (here in pmis-user-management) and asserts:

  - the column exists in the canonical model
  - the SQLAlchemy column type matches (compared by string repr)
  - the primary-key flag matches

This catches the failure mode where someone widens `users.users.email` from
VARCHAR(255) to TEXT in the canonical model but forgets to update the mirror
in masters-svc / project-svc / notification-svc, leading to silent truncation
on cross-schema reads.

Note: this test imports each foreign service via filesystem path manipulation
because they're sibling packages (no namespace sharing).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES_DIR = REPO_ROOT / "services"


# Tables this service OWNS — these are the canonical declarations to compare
# all mirrors against.
_OWNED_TABLES = {
    ("users", "users"): "user",
    ("users", "roles"): "role",
    ("users", "permissions"): "permission",
    ("users", "user_roles"): "user_role",
    ("users", "role_permissions"): "role_permission",
    ("users", "user_permissions"): "user_permission",
    ("users", "user_role_assignments"): "user_role_assignment",
    ("users", "revoked_tokens"): "revoked_token",
}

# Other services that may declare mirrors of users.*
_PEER_SERVICES = [
    "pmis-masters-management",
    "pmis-notification-management",
    "pmis-project-management",
]


def _load_canonical_metadata() -> Dict[Tuple[str, str], object]:
    """Return {(schema, table_name): Table} for tables owned by this service."""
    # In-process import — this test runs from inside pmis-user-management.
    from app.db import Base
    import app.models  # noqa: F401 — populate metadata

    return {
        (t.schema, t.name): t
        for t in Base.metadata.sorted_tables
        if t.schema == "users"
    }


def _load_peer_mirror_metadata(service_name: str) -> Dict[Tuple[str, str], object]:
    """Import {service_name}/app/models/_cross_schema.py and return its tables.

    We import via spec so we don't pollute sys.modules with a foreign `app`.
    """
    target = SERVICES_DIR / service_name / "app" / "models" / "_cross_schema.py"
    if not target.exists():
        return {}

    # Build a unique module name to avoid colliding with this service's `app`.
    mod_name = f"_peer_xs_{service_name.replace('-', '_')}"

    # The peer file does `from app.db import MirrorBase` — we need to stub
    # `app.db` for that import to resolve. The minimum surface area is a
    # MirrorBase declarative_base. We avoid actually executing the peer's
    # real app package because it would re-bind `app` for the rest of pytest.
    from sqlalchemy.orm import DeclarativeBase

    class _PeerMirrorBase(DeclarativeBase):
        pass

    fake_app = type(sys)("app")
    fake_app_db = type(sys)("app.db")
    fake_app_db.MirrorBase = _PeerMirrorBase
    fake_app.db = fake_app_db

    saved_app = sys.modules.pop("app", None)
    saved_app_db = sys.modules.pop("app.db", None)
    sys.modules["app"] = fake_app
    sys.modules["app.db"] = fake_app_db
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(target))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return {
            (t.schema, t.name): t
            for t in _PeerMirrorBase.metadata.sorted_tables
            if t.schema == "users"
        }
    finally:
        sys.modules.pop("app", None)
        sys.modules.pop("app.db", None)
        if saved_app is not None:
            sys.modules["app"] = saved_app
        if saved_app_db is not None:
            sys.modules["app.db"] = saved_app_db


def _column_signature(col) -> Tuple[str, bool]:
    """A normalized fingerprint to compare across declarative bases."""
    # str(type) gives e.g. 'VARCHAR(36)' which is what we want — concrete
    # widths matter (Q24 motivation).
    return (str(col.type), bool(col.primary_key))


@pytest.mark.parametrize("peer_service", _PEER_SERVICES)
def test_peer_mirror_columns_match_canonical(peer_service):
    canonical = _load_canonical_metadata()
    mirrors = _load_peer_mirror_metadata(peer_service)

    if not mirrors:
        pytest.skip(f"{peer_service} declares no users.* mirrors")

    errors: list[str] = []
    for key, peer_table in mirrors.items():
        if key not in canonical:
            errors.append(
                f"[{peer_service}] mirror references unknown table {key!r} "
                f"— canonical model removed but mirror not?"
            )
            continue

        owner_table = canonical[key]
        for peer_col in peer_table.columns:
            if peer_col.name not in owner_table.columns:
                errors.append(
                    f"[{peer_service}] mirror {key[0]}.{key[1]} declares column "
                    f"{peer_col.name!r} which the canonical model no longer has"
                )
                continue
            canonical_col = owner_table.columns[peer_col.name]
            peer_sig = _column_signature(peer_col)
            canonical_sig = _column_signature(canonical_col)
            if peer_sig != canonical_sig:
                errors.append(
                    f"[{peer_service}] {key[0]}.{key[1]}.{peer_col.name} drift: "
                    f"mirror declares {peer_sig}, canonical declares {canonical_sig}"
                )

    if errors:
        pytest.fail(
            "Cross-schema drift detected (Q24). Update either the canonical "
            "model or the peer mirror so they match:\n  - "
            + "\n  - ".join(errors)
        )
