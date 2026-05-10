"""One-shot script — create or upgrade a user to ``super_admin``.

Bypasses the API gate (round 7 closed the API path entirely — only
``init_db`` writes super_admin role rows). This script is **NOT**
wired into init_db / the auto-seed loop, so the account it creates
will NOT be self-healed on every boot. If the row is later deleted
the user simply won't exist anymore.

Idempotent:
  * If a user with ``--login`` already exists, the script leaves the
    user fields alone and only ensures the global super_admin
    assignment is present.
  * If the user already holds super_admin globally, the script is a
    no-op.

Run on the **server** (the DATABASE_URL from the env / .env is
respected). Not for use in tests or CI.

Examples
--------
::

    python scripts/grant_super_admin.py \\
        --login ram \\
        --email Ram@xyz.com \\
        --first-name Ram \\
        --vendor UIDAI \\
        --division-other Admin \\
        --password 'ChangeMe@1' \\
        --phone '+919999999999'

    # Promote an existing user (no user-field changes — just grants):
    python scripts/grant_super_admin.py --login someone_existing
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make the ``app`` package importable when running from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("grant_super_admin")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grant_super_admin.py",
        description=(
            "Create or upgrade a user to super_admin. NOT idempotently "
            "self-healing (unlike the bootstrap super_admin). Run once "
            "on the server."
        ),
    )
    p.add_argument(
        "--login", required=True,
        help="Login (case-sensitive). If a user with this login exists, "
             "user fields are left alone — only the role is granted.",
    )
    p.add_argument("--email", help="Email. Required if creating a new user.")
    p.add_argument(
        "--password",
        help=(
            "Initial password. Required if creating a new user. The user "
            "should be told to change it on first login."
        ),
    )
    p.add_argument("--first-name", default=None)
    p.add_argument("--last-name", default=None)
    p.add_argument(
        "--phone",
        help="Phone number. Required if creating a new user.",
    )
    p.add_argument(
        "--vendor",
        help=(
            "Vendor identifier — accepts UUID, vendor_code (VN-...), or "
            "exact case-insensitive name. Optional for super_admin (the "
            "bootstrap super_admin user has no vendor either). When "
            "supplied, the vendor must already exist; the script never "
            "creates vendors."
        ),
    )
    p.add_argument(
        "--division", default="others",
        help="Division — one of tmd1 / tmd2 / others (default: others).",
    )
    p.add_argument(
        "--division-other",
        help=(
            "Free-text label when division == 'others'. Defaulted to "
            "'Admin' when --division=others and --division-other is omitted."
        ),
    )
    p.add_argument(
        "--allow-2fa-off", action="store_true",
        help=(
            "Create the user with two_factor_enabled=False. Default is "
            "True (mandatory 2FA per doc 33). Only useful for service "
            "accounts; super_admin should generally have 2FA on."
        ),
    )
    return p


def _resolve_vendor(db, identifier: str):
    """Find a vendor by id, vendor_code, or case-insensitive name."""
    from app.infrastructure.db.models.vendor import VendorModel
    from sqlalchemy import func

    if identifier is None:
        return None
    # UUID-ish (36 chars) or vendor_code
    row = (
        db.query(VendorModel)
        .filter(VendorModel.id == identifier)
        .first()
    )
    if row:
        return row
    row = (
        db.query(VendorModel)
        .filter(VendorModel.vendor_code == identifier)
        .first()
    )
    if row:
        return row
    # case-insensitive name match
    row = (
        db.query(VendorModel)
        .filter(func.lower(VendorModel.name) == identifier.lower())
        .first()
    )
    return row


def main() -> int:
    args = _build_arg_parser().parse_args()

    from app.core.security import hash_password
    from app.infrastructure.db.session import SessionLocal
    from app.infrastructure.db.models.user import UserModel
    from app.infrastructure.db.models.role import RoleModel
    from app.infrastructure.db.models.user_role_assignment import (
        UserRoleAssignmentModel,
    )

    db = SessionLocal()
    try:
        existing = (
            db.query(UserModel)
            .filter(UserModel.login == args.login)
            .first()
        )

        if existing is None:
            # Creating a new user — minimum-required user fields. Vendor
            # is optional for super_admin (the bootstrap super_admin
            # has no vendor either; users.vendor_id is NULL there).
            missing = [
                f for f, v in (
                    ("--email", args.email),
                    ("--password", args.password),
                    ("--phone", args.phone),
                ) if not v
            ]
            if missing:
                log.error(
                    "User '%s' does not exist; cannot create without %s.",
                    args.login, ", ".join(missing),
                )
                return 2

            vendor = None
            if args.vendor:
                vendor = _resolve_vendor(db, args.vendor)
                if vendor is None:
                    log.error("Vendor not found: %r", args.vendor)
                    return 2

            div = args.division
            div_other = args.division_other
            if div == "others" and not div_other:
                div_other = "Admin"

            user = UserModel(
                login=args.login,
                email=args.email,
                hashed_password=hash_password(args.password),
                first_name=args.first_name,
                last_name=args.last_name,
                status="active",
                vendor_id=(vendor.id if vendor else None),
                division=div,
                division_other=div_other,
                phone_number=args.phone,
                two_factor_enabled=not args.allow_2fa_off,
                # Doc 45 round 9b — store the FE-friendly tier label so
                # GET /users/{id} returns orgRole=super_admin even when
                # the role-assignment row hasn't been hydrated yet.
                org_role="super_admin",
            )
            db.add(user)
            db.flush()
            log.info(
                "Created user id=%s login=%s vendor=%s",
                user.id, user.login,
                vendor.name if vendor else "(none)",
            )
        else:
            user = existing
            log.info(
                "User '%s' already exists (id=%s) — leaving fields alone.",
                args.login, user.id,
            )
            # Update org_role to super_admin so the FE projection is
            # consistent post-grant. Round-9b column.
            if getattr(user, "org_role", None) != "super_admin":
                user.org_role = "super_admin"
                log.info("Set users.org_role = 'super_admin' for '%s'.", args.login)

        sa_role = (
            db.query(RoleModel)
            .filter(RoleModel.name == "super_admin")
            .first()
        )
        if sa_role is None:
            log.error(
                "super_admin role not found in roles table — "
                "is the RBAC seed loop healthy?"
            )
            db.rollback()
            return 3

        existing_assignment = (
            db.query(UserRoleAssignmentModel)
            .filter(
                UserRoleAssignmentModel.user_id == user.id,
                UserRoleAssignmentModel.role_id == sa_role.id,
                UserRoleAssignmentModel.organization_id.is_(None),
                UserRoleAssignmentModel.project_id.is_(None),
            )
            .first()
        )
        if existing_assignment is None:
            db.add(UserRoleAssignmentModel(
                user_id=user.id,
                role_id=sa_role.id,
            ))
            log.info(
                "Granted global super_admin to user '%s' (id=%s).",
                user.login, user.id,
            )
        else:
            log.info(
                "User '%s' already holds global super_admin — no-op.",
                user.login,
            )

        db.commit()
        log.info("Done.")
        return 0
    except Exception as exc:
        db.rollback()
        log.exception("grant_super_admin failed: %s", exc)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
