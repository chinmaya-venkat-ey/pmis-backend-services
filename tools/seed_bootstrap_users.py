"""
seed_bootstrap_users.py — Bootstrap data helper for alembic data-migrations.

Per Q21 + Q33, the bootstrap admin/superadmin is seeded by a one-time alembic
data-migration in pmis-user-management (NOT by boot-time code as in the old monolith).
This script is imported by that migration and provides:

    seed_superadmin(connection, login, email, password_hash) -> None
    seed_default_roles(connection) -> None
    seed_builtin_permissions(connection) -> None

The migration calls these helpers, passing the alembic connection.

The PASSWORD HASH is computed inside the migration from the env var
SUPERADMIN_BOOTSTRAP_PASSWORD (Q33) using argon2; the env var is then unset
after the migration completes.

This is a SKELETON. Real implementation lives in:
  services/pmis-user-management/alembic/versions/<bootstrap_rev>_seed_bootstrap.py
"""
from __future__ import annotations


def seed_superadmin(connection, login: str, email: str, password_hash: str) -> None:
    """Insert the bootstrap superadmin user + grant the super_admin role."""
    raise NotImplementedError("Phase 3 — implemented in pmis-user-management bootstrap migration")


def seed_default_roles(connection) -> None:
    """Insert the built-in roles: super_admin, admin, org_admin, project_admin, project_member, division_member."""
    raise NotImplementedError("Phase 3 — implemented in pmis-user-management bootstrap migration")


def seed_builtin_permissions(connection) -> None:
    """Insert every permission code from `users.permissions.BUILTIN_PERMISSIONS`."""
    raise NotImplementedError("Phase 3 — implemented in pmis-user-management bootstrap migration")
