"""Human-readable identifier codes for vendors + users (doc 25).

Format
------
``{prefix}-{slug4}-{ist_timestamp}``

Where:

  * ``prefix``         — short literal that names the entity kind:
                          ``"VN"`` for vendors, ``"US"`` for users.
  * ``slug``           — uppercase alphanumeric slug extracted from the
                          source string (vendor name / user full name).
                          Stripped of all non-``[A-Z0-9]`` characters and
                          truncated at ``SLUG_LENGTH`` (4) chars; shorter
                          sources keep their natural length (e.g. a
                          vendor named "fsv" → ``FSV``, not ``FSV0``).
                          Falls back to ``"0000"`` only when the source
                          has zero alphanumeric characters at all
                          (None / empty / pure punctuation).
  * ``ist_timestamp``  — 12 chars ``YYMMDDHHMMSS`` in IST (UTC+05:30).
                          Matches the convention already used by
                          ``project_code`` (e.g. ``UIDAI-PR260501143927``).

Examples:

  ``VN-ACME-260502143015`` — vendor "Acme Corp" created 2026-05-02 14:30:15 IST
  ``VN-3MIN-260502143015`` — vendor "3M India" created same instant
  ``VN-FSV-260502143015``  — short vendor name "fsv" → 3-char slug, no padding
  ``US-RAVI-260502143015`` — user "Ravi Kumar" created 2026-05-02 IST
  ``US-PRIY-260502143015`` — user "Priya Sharma" created same instant
  ``US-ADMI-260101000000`` — bootstrap admin (no name → falls back to ``login``)
  ``US-Z-260502143015``    — single-char source (e.g. login "z"), kept as-is
  ``VN-0000-260502143015`` — fallback when source has zero alphanumeric chars

Stability
---------
The code is a SNAPSHOT taken at create time. Renaming the source vendor /
user does NOT regenerate the code — the code stays whatever was assigned
on insert. This is intentional: external systems / FE bookmarks / audit
logs may reference the code, and silently rewriting it would break those.

Uniqueness
----------
Two rows with the same first-4-alphanumeric-name-chars created in the
same second would naturally collide. ``generate_unique_code`` handles
this by appending ``-2``, ``-3``, ... until the resulting code is free.
The DB-level UNIQUE constraint on the column is the ultimate source of
truth — this helper just avoids the IntegrityError.

Usage
-----
Service layer (live create path) — pass an open connection + the
already-set ``created_at``::

    base = build_code("VN", vendor.name, vendor.created_at)
    code = generate_unique_code(
        db.connection(), table="vendors", code_column="vendor_code",
        base_code=base,
    )

Migration layer (one-time backfill) — same interface, ``op.get_bind()``
returns a Connection::

    bind = op.get_bind()
    for row in bind.execute(text("SELECT id, name, created_at FROM vendors")):
        base = build_code("VN", row.name, row.created_at)
        code = generate_unique_code(bind, table="vendors",
                                    code_column="vendor_code", base_code=base)
        bind.execute(text("UPDATE vendors SET vendor_code = :c WHERE id = :i"),
                     {"c": code, "i": row.id})
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# India Standard Time — UTC+05:30. Hard-coded (no DST) to match
# project_code, which has used the same offset since the codebase began.
IST = timezone(timedelta(hours=5, minutes=30))

# Strip pattern for the 4-char slug. Anything outside [A-Z0-9] is dropped.
_SLUG_DROP_RE = re.compile(r"[^A-Z0-9]")

# Maximum length of the slug segment. Decision recorded in
# planned_changes/25 — short enough to keep the total code <= 21 chars,
# long enough to carry recognizable name context. Sources with fewer
# alphanumeric chars produce a shorter slug (e.g. "fsv" → "FSV", no
# padding) — see ``slug4`` for the rationale.
SLUG_LENGTH = 4

# Maximum collision-suffix attempts before raising. ``-2`` to ``-100``
# covers any realistic collision; if we can't find a free slot in 99
# tries something is very wrong.
_MAX_SUFFIX = 99


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def slug4(source: str) -> str:
    """Extract an uppercase alphanumeric slug from any input string.

    Variable length: up to ``SLUG_LENGTH`` (4) characters when the
    source has that many alphanumerics; shorter sources keep their
    natural length so codes don't carry awkward filler digits like
    ``"FSV0"`` for a 3-char name. The format's ``-`` separator is the
    only thing the parser cares about — variable slug length is
    parse-safe (``looks_like_*_code`` only checks the prefix).

    ``"Acme Corporation"``  → ``"ACME"``     (truncated at 4)
    ``"3M India"``          → ``"3MIN"``
    ``"AT&T Inc"``          → ``"ATTI"``
    ``"fsv"``               → ``"FSV"``      (kept at natural length)
    ``"z"``                 → ``"Z"``        (kept at natural length)
    ``""`` or ``"...."``    → ``"0000"``     (last-resort filler when
                                              source has zero alphanumerics)
    ``None``                → ``"0000"``
    """
    if not source:
        return "0" * SLUG_LENGTH
    stripped = _SLUG_DROP_RE.sub("", source.upper())
    if not stripped:
        return "0" * SLUG_LENGTH
    # Truncate at SLUG_LENGTH; do NOT pad shorter sources — let them
    # appear at their natural length (e.g. "FSV", not "FSV0").
    return stripped[:SLUG_LENGTH]


def ist_timestamp(when) -> str:
    """Format a datetime as ``YYMMDDHHMMSS`` in IST (UTC+05:30).

    Tz-aware inputs are converted to IST. Naive inputs are assumed to be
    UTC (which is what SQLAlchemy returns from a Postgres TIMESTAMP after
    round-trip without explicit tz info on the column).

    Strings are tolerated so the alembic backfill loop (which reads
    ``created_at`` via raw ``SELECT`` and gets back a string from SQLite
    even though ORM-fetched rows give a real datetime) doesn't have to
    coerce manually. Common ISO + ``YYYY-MM-DD HH:MM:SS[.fff[fff]]``
    forms are recognized; anything else raises ``ValueError`` to keep the
    failure visible during migration.

    12-char output regardless of input shape.
    """
    if isinstance(when, str):
        # SQLite returns DATETIME columns as ISO strings via raw SQL.
        # Try the two shapes we actually see in the wild: with and
        # without sub-second precision, optional trailing 'Z'.
        s = when.strip()
        # Normalize "Z" suffix → "+00:00" so fromisoformat accepts it.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # SQLite often stores "YYYY-MM-DD HH:MM:SS" — fromisoformat
        # accepts that on 3.11+. The ".000000" suffix is also fine.
        when = datetime.fromisoformat(s)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(IST).strftime("%y%m%d%H%M%S")


def build_code(prefix: str, source: str, when: datetime) -> str:
    """Compose a base code (no collision suffix yet)."""
    return f"{prefix}-{slug4(source)}-{ist_timestamp(when)}"


def generate_unique_code(
    bind: Connection,
    *,
    table: str,
    code_column: str,
    base_code: str,
    exclude_id: Optional[str] = None,
) -> str:
    """Return a code unique within ``table.code_column``.

    Tries ``base_code`` first. If a row already has it, tries
    ``base_code-2``, ``base_code-3``, ... until a free slot is found.

    ``exclude_id`` lets callers restate a row's own code without it
    appearing as a self-collision (used during backfill if we re-run the
    migration on a partially-completed DB).
    """
    candidate = base_code
    suffix = 1
    while True:
        params = {"c": candidate}
        sql = (
            f"SELECT 1 FROM {table} "
            f"WHERE {code_column} = :c"
        )
        if exclude_id is not None:
            sql += " AND id <> :exclude_id"
            params["exclude_id"] = exclude_id
        sql += " LIMIT 1"
        if bind.execute(text(sql), params).first() is None:
            return candidate
        suffix += 1
        if suffix > _MAX_SUFFIX:
            raise RuntimeError(
                f"Could not generate unique code for base '{base_code}' "
                f"in {table}.{code_column} after {_MAX_SUFFIX} attempts."
            )
        candidate = f"{base_code}-{suffix}"


# ---------------------------------------------------------------------------
# Recognizers — used by lookup endpoints to dispatch UUID/int vs code
# ---------------------------------------------------------------------------

# A vendor code starts with the literal "VN-" prefix. A UUID has 4
# hyphens at fixed positions and is all hex; using the prefix as the
# distinguishing test is simpler and unambiguous (UUIDs don't start
# with "VN-" because the first hex char is 0-9 / a-f).
def looks_like_vendor_code(s: object) -> bool:
    """Cheap heuristic: does ``s`` look like a vendor code, not a UUID?

    Used by the vendor get/patch/delete endpoints to dispatch the path
    parameter to the right repository lookup. False does NOT mean
    "definitely a UUID" — it means "treat as id".
    """
    return isinstance(s, str) and s.startswith("VN-")


def looks_like_user_code(s: object) -> bool:
    """Cheap heuristic: does ``s`` look like a user code, not an integer
    user id? Pure-digit input is treated as the integer id.
    """
    return isinstance(s, str) and s.startswith("US-")
