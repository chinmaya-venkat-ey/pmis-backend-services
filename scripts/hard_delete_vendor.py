"""One-shot script — HARD DELETE a vendor and its FK fanout.

Unlike DELETE /vendors/{id} (which soft-deletes by setting
``deleted_at``), this script removes the row from ``vendors`` outright
plus everything that references it. Use ONLY when a vendor was created
in error and you want it completely gone from the catalog.

Run on the **server** with the live ``DATABASE_URL``. Defaults to
``--dry-run`` so an accidental wrong name prints the impact without
touching anything; pass ``--apply`` to actually delete.

Fanout (per FK survey of the schema):

  * ``project_vendors``         — DELETE rows where vendor_id matches
  * ``milestone_vendors``       — DELETE rows where vendor_id matches
  * ``activities.vendor_id``    — UPDATE to NULL (FK is nullable; the
                                  activity stays, just loses its vendor
                                  tag)
  * ``users.vendor_id``         — UPDATE to NULL (FK is nullable; the
                                  user stays but is no longer mapped to
                                  this vendor)
  * ``user_role_assignments``   — DELETE rows where organization_id
                                  matches (org_admin / admin grants
                                  scoped to this vendor are gone; the
                                  exactly-one-scope CHECK constraint
                                  forbids NULL-ing organization_id on a
                                  non-project row)
  * ``vendors``                 — DELETE the row itself

Examples
--------
::

    # See what would be removed without changing anything:
    python scripts/hard_delete_vendor.py --name TCS

    # Actually delete:
    python scripts/hard_delete_vendor.py --name TCS --apply

    # By id:
    python scripts/hard_delete_vendor.py --id 7f9ec285-... --apply
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("hard_delete_vendor")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hard_delete_vendor.py",
        description=(
            "Hard-delete a vendor row and its FK fanout. Defaults to "
            "dry-run; pass --apply to actually delete."
        ),
    )
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument(
        "--name",
        help="Vendor name (case-insensitive exact match).",
    )
    sel.add_argument(
        "--id", dest="vendor_id",
        help="Vendor UUID.",
    )
    p.add_argument(
        "--apply", action="store_true",
        help="Actually perform the deletion. Without this flag the "
             "script only prints the impact and exits without changes.",
    )
    return p


def _resolve_vendor(db, *, name=None, vendor_id=None):
    from app.infrastructure.db.models.vendor import VendorModel
    from sqlalchemy import func

    if vendor_id:
        return (
            db.query(VendorModel)
            .filter(VendorModel.id == vendor_id)
            .first()
        )
    return (
        db.query(VendorModel)
        .filter(func.lower(VendorModel.name) == name.lower())
        .first()
    )


def main() -> int:
    args = _build_arg_parser().parse_args()

    from app.infrastructure.db.session import SessionLocal
    from app.infrastructure.db.models.activity import ActivityModel
    from app.infrastructure.db.models.milestone_vendor import (
        MilestoneVendorModel,
    )
    from app.infrastructure.db.models.project_vendor import (
        ProjectVendorModel,
    )
    from app.infrastructure.db.models.user import UserModel
    from app.infrastructure.db.models.user_role_assignment import (
        UserRoleAssignmentModel,
    )
    from app.infrastructure.db.models.vendor import VendorModel

    db = SessionLocal()
    try:
        vendor = _resolve_vendor(db, name=args.name, vendor_id=args.vendor_id)
        if vendor is None:
            log.warning(
                "No vendor found for %s — nothing to do.",
                f"name={args.name!r}" if args.name else f"id={args.vendor_id!r}",
            )
            return 0

        log.info(
            "Resolved vendor: id=%s name=%r vendor_code=%s",
            vendor.id, vendor.name, vendor.vendor_code,
        )

        n_pv = (
            db.query(ProjectVendorModel)
            .filter(ProjectVendorModel.vendor_id == vendor.id)
            .count()
        )
        n_mv = (
            db.query(MilestoneVendorModel)
            .filter(MilestoneVendorModel.vendor_id == vendor.id)
            .count()
        )
        n_act = (
            db.query(ActivityModel)
            .filter(ActivityModel.vendor_id == vendor.id)
            .count()
        )
        n_users = (
            db.query(UserModel)
            .filter(UserModel.vendor_id == vendor.id)
            .count()
        )
        n_ura = (
            db.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.organization_id == vendor.id)
            .count()
        )

        log.info("Fanout summary:")
        log.info("  project_vendors        DELETE  %d row(s)", n_pv)
        log.info("  milestone_vendors      DELETE  %d row(s)", n_mv)
        log.info("  activities.vendor_id   NULL    %d row(s)", n_act)
        log.info("  users.vendor_id        NULL    %d row(s)", n_users)
        log.info("  user_role_assignments  DELETE  %d row(s)", n_ura)
        log.info("  vendors                DELETE  1 row")

        if not args.apply:
            log.info(
                "Dry-run (no --apply) — no rows were modified. "
                "Re-run with --apply to actually delete.",
            )
            return 0

        # ---- Apply ----
        (
            db.query(ProjectVendorModel)
            .filter(ProjectVendorModel.vendor_id == vendor.id)
            .delete(synchronize_session=False)
        )
        (
            db.query(MilestoneVendorModel)
            .filter(MilestoneVendorModel.vendor_id == vendor.id)
            .delete(synchronize_session=False)
        )
        (
            db.query(ActivityModel)
            .filter(ActivityModel.vendor_id == vendor.id)
            .update({ActivityModel.vendor_id: None}, synchronize_session=False)
        )
        (
            db.query(UserModel)
            .filter(UserModel.vendor_id == vendor.id)
            .update({UserModel.vendor_id: None}, synchronize_session=False)
        )
        (
            db.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.organization_id == vendor.id)
            .delete(synchronize_session=False)
        )
        db.delete(vendor)
        db.commit()
        log.info("Hard-deleted vendor id=%s name=%r.", vendor.id, vendor.name)
        return 0
    except Exception as exc:
        db.rollback()
        log.exception("hard_delete_vendor failed: %s", exc)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
