"""
Cross-dependency date rule (doc 27).

Rule: a SOURCE entity that depends on a TARGET entity must not start
before the target ends.

    source.start_date >= target.end_date  (equality allowed — same-day handoff)

Equality is allowed for consistency with other date rules in this
codebase (entity start can equal parent start; see ``date_rules.py``).
A successor that begins on the same day a predecessor ends is treated
as a clean handoff, not a conflict.

The rule applies uniformly to:
- activity_dependencies
- task_dependencies
- subtask_dependencies
- milestone_dependencies (doc 21A)

Both directions of the edit must be guarded:
- FORWARD: when (re)assigning ``dependsOn`` on a source, validate the
  source's planned start vs each target's end.
- REVERSE: when editing the target's start_date or end_date, walk every
  live source pointing AT it and re-validate.

Either direction can produce multiple violations at once. Helpers here
collect all of them and produce one ``ValidationError`` listing every
offender, so the FE can render a single, complete error rather than
forcing the user through a whack-a-mole loop.
"""
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from ..core.errors import ValidationError
from .datetime import to_ist_calendar_midnight


def _normalize(v: Optional[datetime]) -> Optional[datetime]:
    """Normalize for cross-comparison on IST calendar-date semantics.

    Mirrors ``date_rules._normalize`` (kept aligned post the doc 30
    follow-up that switched the parent-floor checks to IST calendar
    midnight). Two inputs that represent the same IST calendar date —
    regardless of how they were originally encoded — produce the same
    return value, so dep-date comparisons honour calendar-day semantics
    even on legacy rows stored as raw UTC midnight before doc 29's
    ``IstCalendarDate`` schema annotation existed.

    None passes through. Non-datetime inputs aren't expected (validators
    upstream coerce to datetime); ``to_ist_calendar_midnight`` returns
    them unchanged so any downstream comparison fires the same TypeError
    it would have pre-fix.
    """
    if v is None:
        return None
    return to_ist_calendar_midnight(v)


def _fmt(d: Optional[datetime]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


# (target_label, target_end) — used by the forward direction.
ForwardTarget = Tuple[str, Optional[datetime]]
# (source_label, source_start) — used by the reverse direction.
ReverseSource = Tuple[str, Optional[datetime]]


def collect_forward_violations(
    *,
    source_start: Optional[datetime],
    targets: Iterable[ForwardTarget],
) -> List[Tuple[str, datetime]]:
    """Return [(target_label, target_end), ...] for every target that the
    source's start_date violates.

    A target with no end_date is skipped (defensive — end_date is
    NOT NULL in the schema, but a malformed row should not crash).
    A source with no start_date is skipped (caller didn't supply one).
    """
    src = _normalize(source_start)
    if src is None:
        return []
    out: List[Tuple[str, datetime]] = []
    for label, target_end in targets:
        tgt = _normalize(target_end)
        if tgt is None:
            continue
        if src < tgt:
            out.append((label, tgt))
    return out


def collect_reverse_violations(
    *,
    target_end: Optional[datetime],
    sources: Iterable[ReverseSource],
) -> List[Tuple[str, datetime]]:
    """Return [(source_label, source_start), ...] for every source whose
    start_date the new target_end would violate."""
    tgt = _normalize(target_end)
    if tgt is None:
        return []
    out: List[Tuple[str, datetime]] = []
    for label, source_start in sources:
        src = _normalize(source_start)
        if src is None:
            continue
        if src < tgt:
            out.append((label, src))
    return out


def raise_forward_if_violations(
    violations: List[Tuple[str, datetime]],
    *,
    source_label: str,
    source_start: datetime,
    kind_singular: str = "dependency",
) -> None:
    """Raise ValidationError listing every target the source starts
    before. No-op on empty input."""
    if not violations:
        return
    parts = [f"'{lbl}' (ends {_fmt(end)})" for lbl, end in violations]
    raise ValidationError(
        f"{source_label} cannot start on {_fmt(_normalize(source_start))} — "
        f"the following {kind_singular} target(s) end after that date: "
        f"{', '.join(parts)}."
    )


def raise_reverse_if_violations(
    violations: List[Tuple[str, datetime]],
    *,
    target_label: str,
    target_end: datetime,
    kind_singular: str = "dependent",
) -> None:
    """Raise ValidationError listing every source the new target_end
    would push past. No-op on empty input."""
    if not violations:
        return
    parts = [f"'{lbl}' (starts {_fmt(start)})" for lbl, start in violations]
    raise ValidationError(
        f"{target_label} cannot end on {_fmt(_normalize(target_end))} — "
        f"the following {kind_singular}(s) would then start before this "
        f"target ends: {', '.join(parts)}."
    )


# ---------------------------------------------------------------------------
# Milestone-specific rule (doc 31)
# ---------------------------------------------------------------------------
#
# Milestones model high-level project phases that often overlap in time.
# The generic rule (source.start >= target.end) is too restrictive for
# them — it would forbid a phase from starting before its predecessor
# finishes, which is the normal case for parallel workstreams.
#
# The milestone-specific rule splits into a start-floor and an
# end-strict bound:
#
#     source.start_date >= target.start_date    (equality allowed)
#     source.end_date   >  target.end_date      (strict — equality REJECTED)
#
# The "outlasting" end requirement encodes the semantic meaning of the
# dependency: a phase that depends on another must wrap around it,
# finishing strictly later. The start-floor allows them to begin in
# parallel.
#
# Both must hold per (source, target) pair. Violations are collected
# separately for start vs end so the error message can name which rule
# each offender breaks.
#
# (Activity / task / subtask deps continue to use the generic
# source.start >= target.end rule above.)


# (target_label, target_start, target_end) — used by milestone forward.
MilestoneForwardTarget = Tuple[str, Optional[datetime], Optional[datetime]]
# (source_label, source_start, source_end) — used by milestone reverse.
MilestoneReverseSource = Tuple[str, Optional[datetime], Optional[datetime]]


def collect_milestone_forward_violations(
    *,
    source_start: Optional[datetime],
    source_end: Optional[datetime],
    targets: Iterable[MilestoneForwardTarget],
) -> Tuple[
    List[Tuple[str, datetime]],   # start violations: (label, target_start)
    List[Tuple[str, datetime]],   # end violations:   (label, target_end)
]:
    """For each target, collect start-rule and end-rule violations
    separately. A target with both columns null is skipped."""
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


def collect_milestone_reverse_violations(
    *,
    target_start: Optional[datetime],
    target_end: Optional[datetime],
    sources: Iterable[MilestoneReverseSource],
) -> Tuple[
    List[Tuple[str, datetime]],   # start violations: (label, source_start)
    List[Tuple[str, datetime]],   # end violations:   (label, source_end)
]:
    """For each source pointing at this target, collect violations the
    new target_start / target_end would create."""
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


def raise_milestone_forward_if_violations(
    starts: List[Tuple[str, datetime]],
    ends: List[Tuple[str, datetime]],
    *,
    source_label: str,
    source_start: Optional[datetime],
    source_end: Optional[datetime],
) -> None:
    """Raise ValidationError if either rule has violations.

    The two rules produce one combined message so the FE can display
    every violation from a single response, in one render."""
    if not starts and not ends:
        return
    parts: List[str] = []
    if starts:
        labels = ", ".join(
            f"'{lbl}' (starts {_fmt(s)})" for lbl, s in starts
        )
        parts.append(
            f"{source_label} cannot start on {_fmt(_normalize(source_start))} "
            f"— it must start on or after every milestone it depends on: "
            f"{labels}"
        )
    if ends:
        labels = ", ".join(
            f"'{lbl}' (ends {_fmt(e)})" for lbl, e in ends
        )
        parts.append(
            f"{source_label} cannot end on {_fmt(_normalize(source_end))} "
            f"— it must end strictly after every milestone it depends on: "
            f"{labels}"
        )
    raise ValidationError(". ".join(parts) + ".")


def raise_milestone_reverse_if_violations(
    starts: List[Tuple[str, datetime]],
    ends: List[Tuple[str, datetime]],
    *,
    target_label: str,
    target_start: Optional[datetime],
    target_end: Optional[datetime],
) -> None:
    """Reverse direction: target's start_date or end_date moved and an
    existing source pointing at it would now violate one of the rules."""
    if not starts and not ends:
        return
    parts: List[str] = []
    if starts:
        labels = ", ".join(
            f"'{lbl}' (starts {_fmt(s)})" for lbl, s in starts
        )
        parts.append(
            f"{target_label} cannot start on {_fmt(_normalize(target_start))} "
            f"— the following dependent milestone(s) would then start before "
            f"it: {labels}"
        )
    if ends:
        labels = ", ".join(
            f"'{lbl}' (ends {_fmt(e)})" for lbl, e in ends
        )
        parts.append(
            f"{target_label} cannot end on {_fmt(_normalize(target_end))} "
            f"— the following dependent milestone(s) would no longer end "
            f"strictly after this target: {labels}"
        )
    raise ValidationError(". ".join(parts) + ".")
