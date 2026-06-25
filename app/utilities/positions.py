"""Position-assignment concurrency guard.

Each ``next_position_*`` repo method reads ``max(position) + 1`` and the
caller then inserts a row at that position. Two concurrent creates under the
same parent can read the same ``max`` before either commits and assign a
duplicate position — tripping the per-parent partial-unique position index
(``uq_*_position_live``) with an ``IntegrityError``.

A transaction-scoped PostgreSQL advisory lock keyed on the parent serializes
that read-then-insert window: the second create blocks until the first
commits (releasing the lock and exposing its new ``max``). The lock releases
automatically at commit/rollback, so there is nothing to unlock by hand.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_position_scope(db: Session, scope: str) -> None:
    """Serialize position assignment for ``scope`` within this transaction.

    ``scope`` is a stable string identifying the parent collection, e.g.
    ``"task_pos:<activity_id>"``. No-op on non-PostgreSQL backends: advisory
    locks are PG-specific, and the test suite assigns positions
    single-threaded so correctness holds there without the lock.
    """
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
        {"scope": scope},
    )
