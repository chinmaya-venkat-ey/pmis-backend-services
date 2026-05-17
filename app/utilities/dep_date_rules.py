"""Dependency-date rules — milestone-style outlasting (forward + reverse).

Mirrors the monolith's ``app/shared/dep_date_rules.py`` for milestone-,
activity-, task-, and subtask-level dependencies. All four levels use
the **milestone-style** rule (doc-31):

  * ``source.start_date >= target.start_date``  (equality allowed)
  * ``source.end_date   >  target.end_date``    (strict — equality REJECTED)

Why outlasting: a phase that depends on another must wrap around it,
finishing strictly later. The start-floor allows them to begin in
parallel (phases often overlap).

Error messages match the monolith byte-for-byte — the FE renders them
directly.

Calendar-date semantics: all comparisons go through
``app.utilities.date_rules._to_ist_calendar_midnight`` so any tz-encoding
mismatch (IST midnight vs UTC midnight vs end-of-day) compares equal.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from app.core.errors import ValidationError
from app.utilities.date_rules import _fmt, _to_ist_calendar_midnight


# (label, target_start, target_end)
ForwardTarget = Tuple[str, Optional[datetime], Optional[datetime]]
# (label, source_start, source_end)
ReverseSource = Tuple[str, Optional[datetime], Optional[datetime]]


def _normalize(v: Optional[datetime]) -> Optional[datetime]:
    return _to_ist_calendar_midnight(v)


def collect_forward_violations(
    *,
    source_start: Optional[datetime],
    source_end: Optional[datetime],
    targets: Iterable[ForwardTarget],
) -> Tuple[
    List[Tuple[str, datetime]],  # start violations: (label, target_start)
    List[Tuple[str, datetime]],  # end violations:   (label, target_end)
]:
    """Walk every target; collect (label, date) pairs where the source's
    proposed start / end would breach the rule.

    A target whose own start AND end are both null is skipped (defensive
    — the entity shouldn't be in a state with neither date).
    """
    src_start = _normalize(source_start)
    src_end = _normalize(source_end)
    starts: List[Tuple[str, datetime]] = []
    ends: List[Tuple[str, datetime]] = []
    for label, target_start, target_end in targets:
        tgt_s = _normalize(target_start)
        tgt_e = _normalize(target_end)
        if src_start is not None and tgt_s is not None and src_start < tgt_s:
            starts.append((label, tgt_s))
        if src_end is not None and tgt_e is not None and src_end <= tgt_e:
            ends.append((label, tgt_e))
    return starts, ends


def collect_reverse_violations(
    *,
    target_start: Optional[datetime],
    target_end: Optional[datetime],
    sources: Iterable[ReverseSource],
) -> Tuple[
    List[Tuple[str, datetime]],  # start violations: (label, source_start)
    List[Tuple[str, datetime]],  # end violations:   (label, source_end)
]:
    """Walk every source pointing at this target; collect violations the
    target's new start / end would create.

    Used when a milestone / activity / task / subtask's own dates move
    and we need to ensure downstream dependents still hold.
    """
    tgt_s = _normalize(target_start)
    tgt_e = _normalize(target_end)
    starts: List[Tuple[str, datetime]] = []
    ends: List[Tuple[str, datetime]] = []
    for label, source_start, source_end in sources:
        src_s = _normalize(source_start)
        src_e = _normalize(source_end)
        if tgt_s is not None and src_s is not None and src_s < tgt_s:
            starts.append((label, src_s))
        if tgt_e is not None and src_e is not None and src_e <= tgt_e:
            ends.append((label, src_e))
    return starts, ends


def raise_forward_if_violations(
    starts: List[Tuple[str, datetime]],
    ends: List[Tuple[str, datetime]],
    *,
    source_label: str,
    source_start: Optional[datetime],
    source_end: Optional[datetime],
    kind_singular: str = "milestone",
) -> None:
    """Raise ``ValidationError`` (HTTP 422) when either rule has
    violations. Combined message so the FE can render every violation
    in one shot.

    Error format matches monolith exactly:
      ``{source} cannot start on YYYY-MM-DD — it must start on or after
      every {kind} it depends on: '{target}' (starts YYYY-MM-DD), ...``
    """
    if not starts and not ends:
        return
    parts: List[str] = []
    if starts:
        labels = ", ".join(f"'{lbl}' (starts {_fmt(s)})" for lbl, s in starts)
        parts.append(
            f"{source_label} cannot start on {_fmt(_normalize(source_start))} "
            f"— it must start on or after every {kind_singular} it depends on: "
            f"{labels}"
        )
    if ends:
        labels = ", ".join(f"'{lbl}' (ends {_fmt(e)})" for lbl, e in ends)
        parts.append(
            f"{source_label} cannot end on {_fmt(_normalize(source_end))} "
            f"— it must end strictly after every {kind_singular} it depends on: "
            f"{labels}"
        )
    raise ValidationError(". ".join(parts) + ".")


def raise_reverse_if_violations(
    starts: List[Tuple[str, datetime]],
    ends: List[Tuple[str, datetime]],
    *,
    target_label: str,
    target_start: Optional[datetime],
    target_end: Optional[datetime],
    kind_singular: str = "milestone",
) -> None:
    if not starts and not ends:
        return
    parts: List[str] = []
    if starts:
        labels = ", ".join(f"'{lbl}' (starts {_fmt(s)})" for lbl, s in starts)
        parts.append(
            f"{target_label} cannot start on {_fmt(_normalize(target_start))} "
            f"— the following dependent {kind_singular}(s) would then start "
            f"before it: {labels}"
        )
    if ends:
        labels = ", ".join(f"'{lbl}' (ends {_fmt(e)})" for lbl, e in ends)
        parts.append(
            f"{target_label} cannot end on {_fmt(_normalize(target_end))} "
            f"— the following dependent {kind_singular}(s) would no longer end "
            f"strictly after this target: {labels}"
        )
    raise ValidationError(". ".join(parts) + ".")
