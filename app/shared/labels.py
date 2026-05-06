"""Display label generation + parsing for M/A/T/S (doc 22, nesting in doc 24).

Labels surface in API responses so the FE doesn't need to compute them
client-side from raw ``position`` numbers, and they're accepted on the
``dependsOn`` input so the FE can send what its picker shows.

Format
------
``M{m}``               — milestone rank m
``A{m}.{a}``           — activity rank a under milestone rank m
``T{m}.{a}.{t}``       — task rank t
``S{m}.{a}.{t}.{s1}[.{s2}.{s3}…]``
                       — subtask: ``s1`` is the rank of the top-level
                         subtask under task t; ``s2`` is the rank of the
                         child under that subtask; and so on. Subtask
                         labels are **variable-depth** — minimum 4
                         segments (one ``s``), unlimited beyond that.

Where each rank is the **1-based index** of the entity by
``ORDER BY position ASC, id ASC`` among its **live** (non-soft-deleted)
siblings. Partial-unique indexes on ``(parent_id, position) WHERE
deleted_at IS NULL`` (Alembic ``c4d9a1b3e201`` for M/A/T and
``e9f1a2b3c4d5`` for the doc-24 split on subtasks) guarantee siblings
never share a position, so resolution is unambiguous.

Single-entity callers (GET /activities/{id}) use ``compute_*_label`` —
small focused queries.

List / tree callers (GET /milestones/{id}/activities, GET /tree) build
``LabelIndex`` once per project (constant queries) and dict-lookup each
entity's label.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import re

from sqlalchemy import asc
from sqlalchemy.orm import Session

from ..infrastructure.db.models.activity import ActivityModel
from ..infrastructure.db.models.milestone import MilestoneModel
from ..infrastructure.db.models.subtask import SubtaskModel
from ..infrastructure.db.models.task import TaskModel


# ---------------------------------------------------------------------------
# Kind constants (string keys to keep call sites readable)
# ---------------------------------------------------------------------------

KIND_MILESTONE = "milestone"
KIND_ACTIVITY = "activity"
KIND_TASK = "task"
KIND_SUBTASK = "subtask"

_PREFIX_BY_KIND = {
    KIND_MILESTONE: "M",
    KIND_ACTIVITY: "A",
    KIND_TASK: "T",
    KIND_SUBTASK: "S",
}
_KIND_BY_PREFIX = {v: k for k, v in _PREFIX_BY_KIND.items()}

# Minimum rank-segment count per kind. Subtasks are variable-depth (see
# ``parse_label`` — ranks must be >= this number; only the subtask kind
# allows extra segments for nesting).
_MIN_DEPTH_BY_KIND = {
    KIND_MILESTONE: 1,
    KIND_ACTIVITY: 2,
    KIND_TASK: 3,
    KIND_SUBTASK: 4,
}

# Backwards-compat alias used elsewhere in the module for non-variable
# kinds. Subtasks must NOT use this — they have no fixed depth.
_DEPTH_BY_KIND = _MIN_DEPTH_BY_KIND

# Subtask labels accept any depth >= 4 (one s segment minimum, no upper
# bound — matches doc 24's unlimited nesting).
_VARIABLE_DEPTH_KINDS = frozenset({KIND_SUBTASK})

# ``M5``, ``A1.2``, ``T1.2.3``, ``S1.2.3.4`` (and ``S1.2.3.4.5...``) —
# strict whole-string match.
_LABEL_RE = re.compile(r"^([MATS])(\d+(?:\.\d+)*)$")


# ---------------------------------------------------------------------------
# Parse / format
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedLabel:
    kind: str
    ranks: Tuple[int, ...]

    def expected_depth(self) -> int:
        # Reflects the actual length of ``ranks`` (constant for fixed
        # kinds, equal to the parsed depth for variable-depth kinds).
        return len(self.ranks)


def parse_label(s: object) -> Optional[ParsedLabel]:
    """Parse ``"M1"`` / ``"A1.2"`` / ``"T1.2.3"`` / ``"S1.2.3.4"``
    (and any number of ``.{sN}`` segments beyond the first for subtasks).

    Returns ``None`` when the input doesn't match the format (so the
    caller can treat it as a UUID and proceed with the existing UUID
    path). Returns ``None`` for any rank ``< 1``, the wrong number of
    digits for fixed-depth prefixes (M/A/T), or non-string input.
    Subtasks accept any depth ``>= 4``.
    """
    if not isinstance(s, str):
        return None
    m = _LABEL_RE.match(s.strip())
    if not m:
        return None
    prefix, digits = m.group(1), m.group(2)
    kind = _KIND_BY_PREFIX[prefix]
    ranks = tuple(int(x) for x in digits.split("."))
    min_depth = _MIN_DEPTH_BY_KIND[kind]
    if kind in _VARIABLE_DEPTH_KINDS:
        if len(ranks) < min_depth:
            return None
    else:
        if len(ranks) != min_depth:
            return None
    if any(r < 1 for r in ranks):
        return None
    return ParsedLabel(kind=kind, ranks=ranks)


def format_label(kind: str, ranks: Tuple[int, ...]) -> str:
    """Build a label string from a (kind, ranks) tuple."""
    min_depth = _MIN_DEPTH_BY_KIND[kind]
    if kind in _VARIABLE_DEPTH_KINDS:
        if len(ranks) < min_depth:
            raise ValueError(
                f"Insufficient ranks for {kind}: need at least {min_depth}, got {len(ranks)}"
            )
    elif len(ranks) != min_depth:
        raise ValueError(
            f"Wrong rank depth for {kind}: expected {min_depth}, got {len(ranks)}"
        )
    return _PREFIX_BY_KIND[kind] + ".".join(str(r) for r in ranks)


# ---------------------------------------------------------------------------
# Single-entity rank queries (for resolve_* + compute_*_label)
# ---------------------------------------------------------------------------

def _live_milestones_in_project(db: Session, project_id: str) -> List[MilestoneModel]:
    return (
        db.query(MilestoneModel)
        .filter(MilestoneModel.project_id == project_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .order_by(asc(MilestoneModel.position), asc(MilestoneModel.id))
        .all()
    )


def _live_activities_under_milestone(db: Session, milestone_id: str) -> List[ActivityModel]:
    return (
        db.query(ActivityModel)
        .filter(ActivityModel.milestone_id == milestone_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .order_by(asc(ActivityModel.position), asc(ActivityModel.id))
        .all()
    )


def _live_tasks_under_activity(db: Session, activity_id: str) -> List[TaskModel]:
    return (
        db.query(TaskModel)
        .filter(TaskModel.activity_id == activity_id)
        .filter(TaskModel.deleted_at.is_(None))
        .order_by(asc(TaskModel.position), asc(TaskModel.id))
        .all()
    )


def _live_subtasks_under_task(db: Session, task_id: str) -> List[SubtaskModel]:
    """Live TOP-LEVEL subtasks of a task (parent_subtask_id IS NULL).

    Doc 24: nested subtasks share ``task_id`` with their root, so we
    must filter to direct children of the task here — anchors the
    ``s1`` segment of ``S{m}.{a}.{t}.{s1}.{...}``.
    """
    return (
        db.query(SubtaskModel)
        .filter(SubtaskModel.task_id == task_id)
        .filter(SubtaskModel.parent_subtask_id.is_(None))
        .filter(SubtaskModel.deleted_at.is_(None))
        .order_by(asc(SubtaskModel.position), asc(SubtaskModel.id))
        .all()
    )


def _live_children_of_subtask(db: Session, parent_subtask_id: str) -> List[SubtaskModel]:
    """Live subtasks whose direct parent is ``parent_subtask_id``.
    Anchors a single nesting segment of the subtask label."""
    return (
        db.query(SubtaskModel)
        .filter(SubtaskModel.parent_subtask_id == parent_subtask_id)
        .filter(SubtaskModel.deleted_at.is_(None))
        .order_by(asc(SubtaskModel.position), asc(SubtaskModel.id))
        .all()
    )


# ---------------------------------------------------------------------------
# Resolve label → UUID (used at write time on dependsOn input)
# ---------------------------------------------------------------------------

def resolve_milestone_label_to_id(
    db: Session, project_id: str, label: str,
) -> Optional[str]:
    """Resolve ``"M{m}"`` to a milestone id within ``project_id``.

    Returns ``None`` if the format is wrong, the rank is out of range,
    or no matching live milestone exists.
    """
    parsed = parse_label(label)
    if not parsed or parsed.kind != KIND_MILESTONE:
        return None
    (m_rank,) = parsed.ranks
    milestones = _live_milestones_in_project(db, project_id)
    if m_rank > len(milestones):
        return None
    return milestones[m_rank - 1].id


def resolve_activity_label_to_id(
    db: Session, project_id: str, label: str,
) -> Optional[str]:
    parsed = parse_label(label)
    if not parsed or parsed.kind != KIND_ACTIVITY:
        return None
    m_rank, a_rank = parsed.ranks
    milestones = _live_milestones_in_project(db, project_id)
    if m_rank > len(milestones):
        return None
    activities = _live_activities_under_milestone(db, milestones[m_rank - 1].id)
    if a_rank > len(activities):
        return None
    return activities[a_rank - 1].id


def resolve_task_label_to_id(
    db: Session, project_id: str, label: str,
) -> Optional[str]:
    parsed = parse_label(label)
    if not parsed or parsed.kind != KIND_TASK:
        return None
    m_rank, a_rank, t_rank = parsed.ranks
    milestones = _live_milestones_in_project(db, project_id)
    if m_rank > len(milestones):
        return None
    activities = _live_activities_under_milestone(db, milestones[m_rank - 1].id)
    if a_rank > len(activities):
        return None
    tasks = _live_tasks_under_activity(db, activities[a_rank - 1].id)
    if t_rank > len(tasks):
        return None
    return tasks[t_rank - 1].id


def resolve_subtask_label_to_id(
    db: Session, project_id: str, label: str,
) -> Optional[str]:
    """Variable-depth subtask resolver: ``S{m}.{a}.{t}.{s1}[.{s2}.{s3}…]``.

    Walks M → A → T as before, then s1 within the task's top-level
    subtasks, then each subsequent segment within the previous subtask's
    children. Returns ``None`` for any out-of-range rank.
    """
    parsed = parse_label(label)
    if not parsed or parsed.kind != KIND_SUBTASK:
        return None
    m_rank, a_rank, t_rank, *s_ranks = parsed.ranks
    milestones = _live_milestones_in_project(db, project_id)
    if m_rank > len(milestones):
        return None
    activities = _live_activities_under_milestone(db, milestones[m_rank - 1].id)
    if a_rank > len(activities):
        return None
    tasks = _live_tasks_under_activity(db, activities[a_rank - 1].id)
    if t_rank > len(tasks):
        return None
    subtasks = _live_subtasks_under_task(db, tasks[t_rank - 1].id)
    if not s_ranks or s_ranks[0] > len(subtasks):
        return None
    cursor = subtasks[s_ranks[0] - 1]
    for nested_rank in s_ranks[1:]:
        children = _live_children_of_subtask(db, cursor.id)
        if nested_rank > len(children):
            return None
        cursor = children[nested_rank - 1]
    return cursor.id


# Generic dispatcher — accepts UUID or any kind of label, returns the
# resolved UUID (or None if neither). Service layers use the per-kind
# resolvers above; this helper is for the input-validation pass that
# normalizes a mixed list before per-kind validation runs.

_RESOLVER_BY_KIND = {
    KIND_MILESTONE: resolve_milestone_label_to_id,
    KIND_ACTIVITY: resolve_activity_label_to_id,
    KIND_TASK: resolve_task_label_to_id,
    KIND_SUBTASK: resolve_subtask_label_to_id,
}

_KIND_HUMAN_NAME = {
    KIND_MILESTONE: "milestone",
    KIND_ACTIVITY: "activity",
    KIND_TASK: "task",
    KIND_SUBTASK: "subtask",
}

# Proper plural forms for error messages (avoids "activitys").
_KIND_HUMAN_NAME_PLURAL = {
    KIND_MILESTONE: "milestones",
    KIND_ACTIVITY: "activities",
    KIND_TASK: "tasks",
    KIND_SUBTASK: "subtasks",
}

_KIND_FORMAT_HINT = {
    KIND_MILESTONE: "M{m}",
    KIND_ACTIVITY: "A{m}.{a}",
    KIND_TASK: "T{m}.{a}.{t}",
    KIND_SUBTASK: "S{m}.{a}.{t}.{s}",
}


def resolve_dependency_input(
    db: Session,
    project_id: str,
    expected_kind: str,
    raw: str,
) -> Optional[str]:
    """Normalize a single dependsOn input string to a UUID.

    Returns:
      * the input unchanged if it doesn't parse as a label (assume UUID;
        the existing per-kind exists check downstream rejects bogus UUIDs)
      * the resolved UUID if it's a well-formed label of ``expected_kind``
      * ``None`` if it's a label of the wrong kind (e.g. caller is creating
        an activity dep but the input is "M1") or the label resolves to
        nothing — caller treats this as "unknown target"
    """
    parsed = parse_label(raw)
    if parsed is None:
        # Not a label — assume UUID (or garbage). Pass through; downstream
        # ``existing_target_*`` will reject if unknown.
        return raw
    if parsed.kind != expected_kind:
        # Label of the wrong kind — caller wants an activity but got "M1".
        return None
    resolver = _RESOLVER_BY_KIND[parsed.kind]
    return resolver(db, project_id, raw)


# ---------------------------------------------------------------------------
# Single-entity compute (for individual GET / create / update responses)
# ---------------------------------------------------------------------------

def compute_milestone_label(db: Session, milestone: MilestoneModel) -> Optional[str]:
    """Return the display label for one milestone, or None if it's deleted."""
    if milestone.deleted_at is not None:
        return None
    siblings = _live_milestones_in_project(db, milestone.project_id)
    for idx, m in enumerate(siblings, start=1):
        if m.id == milestone.id:
            return f"M{idx}"
    return None


def compute_activity_label(db: Session, activity: ActivityModel) -> Optional[str]:
    if activity.deleted_at is not None:
        return None
    # Find the parent milestone's rank.
    project_milestones = _live_milestones_in_project(db, activity.project_id)
    m_rank = None
    for idx, m in enumerate(project_milestones, start=1):
        if m.id == activity.milestone_id:
            m_rank = idx
            break
    if m_rank is None:
        return None
    siblings = _live_activities_under_milestone(db, activity.milestone_id)
    for idx, a in enumerate(siblings, start=1):
        if a.id == activity.id:
            return f"A{m_rank}.{idx}"
    return None


def compute_task_label(db: Session, task: TaskModel) -> Optional[str]:
    if task.deleted_at is not None:
        return None
    # Walk up via the parent activity.
    parent_activity = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == task.activity_id)
        .first()
    )
    if parent_activity is None:
        return None
    parent_label = compute_activity_label(db, parent_activity)
    if parent_label is None:
        return None
    # parent_label is "A{m}.{a}"; we want "T{m}.{a}.{t}".
    siblings = _live_tasks_under_activity(db, task.activity_id)
    for idx, t in enumerate(siblings, start=1):
        if t.id == task.id:
            # Strip the "A" prefix, prepend "T".
            return f"T{parent_label[1:]}.{idx}"
    return None


def compute_subtask_label(db: Session, subtask: SubtaskModel) -> Optional[str]:
    """Variable-depth subtask label.

    Walks up ``parent_subtask_id`` from this subtask to the top-level
    ancestor, then composes ``S{m}.{a}.{t}.{s1}[.{s2}…]`` by ranking
    each step against its live siblings.
    """
    if subtask.deleted_at is not None:
        return None
    # Build the ancestor chain from root subtask down to this one.
    chain: List[SubtaskModel] = [subtask]
    cursor = subtask
    seen = {cursor.id}
    while cursor.parent_subtask_id is not None:
        parent = (
            db.query(SubtaskModel)
            .filter(SubtaskModel.id == cursor.parent_subtask_id)
            .first()
        )
        if parent is None or parent.id in seen:
            return None
        seen.add(parent.id)
        chain.append(parent)
        cursor = parent
    chain.reverse()  # root subtask first

    # Compose nested-rank suffix by walking the chain.
    nested_ranks: List[int] = []
    siblings = _live_subtasks_under_task(db, subtask.task_id)
    for idx, s in enumerate(siblings, start=1):
        if s.id == chain[0].id:
            nested_ranks.append(idx)
            break
    if not nested_ranks:
        return None
    for depth_idx in range(1, len(chain)):
        children = _live_children_of_subtask(db, chain[depth_idx - 1].id)
        for idx, c in enumerate(children, start=1):
            if c.id == chain[depth_idx].id:
                nested_ranks.append(idx)
                break
        else:
            return None

    # Get the parent task's "T{m}.{a}.{t}" prefix.
    parent_task = (
        db.query(TaskModel).filter(TaskModel.id == subtask.task_id).first()
    )
    if parent_task is None:
        return None
    task_label = compute_task_label(db, parent_task)
    if task_label is None:
        return None
    return f"S{task_label[1:]}." + ".".join(str(r) for r in nested_ranks)


# ---------------------------------------------------------------------------
# Batch label index (for list + tree responses)
# ---------------------------------------------------------------------------

@dataclass
class LabelIndex:
    """Complete id → label maps for one project, built in 4 queries.

    Use this whenever a response includes more than ~3 entities.
    For single-entity responses the per-kind ``compute_*_label`` helpers
    are cheaper.
    """
    milestone_id_to_label: Dict[str, str] = field(default_factory=dict)
    activity_id_to_label: Dict[str, str] = field(default_factory=dict)
    task_id_to_label: Dict[str, str] = field(default_factory=dict)
    subtask_id_to_label: Dict[str, str] = field(default_factory=dict)

    def for_kind(self, kind: str) -> Dict[str, str]:
        return {
            KIND_MILESTONE: self.milestone_id_to_label,
            KIND_ACTIVITY: self.activity_id_to_label,
            KIND_TASK: self.task_id_to_label,
            KIND_SUBTASK: self.subtask_id_to_label,
        }[kind]

    def label_of(self, kind: str, entity_id: Optional[str]) -> Optional[str]:
        if entity_id is None:
            return None
        return self.for_kind(kind).get(entity_id)

    def labels_of(self, kind: str, ids: List[str]) -> List[str]:
        """Map a list of UUIDs to labels (in input order). Unknown ids
        are silently dropped — they're either soft-deleted parents or
        cross-project references that shouldn't be in dep lists at all."""
        m = self.for_kind(kind)
        out = []
        for i in ids or []:
            label = m.get(i)
            if label is not None:
                out.append(label)
        return out


def resolve_labels_to_ids(
    db: Session,
    *,
    project_id: str,
    expected_kind: str,
    raw_inputs: List[str],
) -> Tuple[List[str], Dict[str, str]]:
    """Resolve a mixed list of UUIDs / labels to UUIDs only.

    - Drops blanks + dupes.
    - Wrong-kind labels (e.g. "M1" when expecting an activity) → raise.
    - Unresolved labels (good format but no matching entity) → kept in
      a separate ``unresolved`` list returned to the caller so the
      existence-check step can fold them into a single error message
      using the user's original input strings.

    Returns ``(resolved_uuids, id_to_raw_input)``. ``id_to_raw_input``
    maps each resolved UUID back to whatever the caller originally
    supplied — used to surface friendly errors when the existence check
    rejects a UUID that came from a label.

    Pure UUIDs that don't match any entity are NOT detected here; that's
    the existence-check step's job. They're returned in ``resolved_uuids``
    and left for downstream rejection.
    """
    raw_candidates = [d for d in dict.fromkeys(raw_inputs or []) if d]

    # Wrong-kind labels rejected eagerly with a precise error.
    for raw in raw_candidates:
        parsed = parse_label(raw)
        if parsed is not None and parsed.kind != expected_kind:
            humans = _KIND_HUMAN_NAME_PLURAL[expected_kind]
            hint = _KIND_FORMAT_HINT[expected_kind]
            raise _ValidationError(
                f"Invalid dependency label '{raw}': {humans} can only "
                f"depend on other {humans} (use {hint} or a UUID)."
            )

    resolved_pairs = [
        (raw, resolve_dependency_input(db, project_id, expected_kind, raw))
        for raw in raw_candidates
    ]
    resolved = list(dict.fromkeys(
        r for _raw, r in resolved_pairs if r is not None
    ))
    unresolved_labels = [raw for raw, r in resolved_pairs if r is None]
    id_to_raw: Dict[str, str] = {}
    for raw, r in resolved_pairs:
        if r is not None:
            id_to_raw.setdefault(r, raw)
    # Unresolved labels feed straight into the "unknown target" message
    # — we add them to id_to_raw under a sentinel so the caller can pull
    # them out via the same path. Simpler: raise here when we have any
    # unresolved labels — the caller's existence check would yield the
    # same outcome but slower.
    if unresolved_labels:
        human = _KIND_HUMAN_NAME[expected_kind]
        raise _ValidationError(
            f"Unknown or out-of-project {human} dependency target(s): "
            f"{', '.join(unresolved_labels)}"
        )
    return resolved, id_to_raw


def normalize_dependency_inputs(
    db: Session,
    *,
    project_id: str,
    expected_kind: str,
    raw_inputs: List[str],
    existence_check,
) -> List[str]:
    """One-stop normalize+validate pipeline for ``dependsOn`` payloads.

    1. Drop blanks + duplicates while preserving order.
    2. Reject wrong-kind labels with a precise ValidationError.
    3. Resolve labels (e.g. ``"A1.2"``) to UUIDs; UUIDs pass through.
    4. Run ``existence_check(project_id, candidates)`` (the per-kind
       ``DependencyRepository.existing_target_*`` set returner).
    5. Raise ValidationError when any input failed to resolve OR
       resolved to an unknown UUID — using the original input string
       in the message.

    For services with custom existence/hierarchy logic (tasks, subtasks),
    use ``resolve_labels_to_ids`` directly + your custom check.
    """
    candidates, id_to_raw = resolve_labels_to_ids(
        db,
        project_id=project_id,
        expected_kind=expected_kind,
        raw_inputs=raw_inputs,
    )
    ok = existence_check(project_id, candidates) if candidates else set()
    missing_inputs = [id_to_raw.get(c, c) for c in candidates if c not in ok]
    if missing_inputs:
        human = _KIND_HUMAN_NAME[expected_kind]
        raise _ValidationError(
            f"Unknown or out-of-project {human} dependency target(s): "
            f"{', '.join(missing_inputs)}"
        )
    return candidates


# We import ValidationError lazily to avoid a circular import: the core
# errors module pulls from response, which pulls from shared in some
# callers. A local alias inside the function would re-import on every
# call; this module-level lazy stub avoids that.

class _DeferredValidationError:
    """Placeholder until first use; resolved on first call."""
    _real = None

    def __call__(self, *args, **kwargs):
        if _DeferredValidationError._real is None:
            from ..core.errors import ValidationError
            _DeferredValidationError._real = ValidationError
        return _DeferredValidationError._real(*args, **kwargs)


_ValidationError = _DeferredValidationError()


def build_label_index_for_project(db: Session, project_id: str) -> LabelIndex:
    """One pass through a project's M/A/T/S — returns an id→label map for each level.

    4 queries total (one per kind). Each query loads only `id`, `position`,
    and parent id columns to keep the result set tight.
    """
    idx = LabelIndex()

    # ---- Milestones ----
    milestones = (
        db.query(MilestoneModel.id, MilestoneModel.position, MilestoneModel.project_id)
        .filter(MilestoneModel.project_id == project_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .order_by(asc(MilestoneModel.position), asc(MilestoneModel.id))
        .all()
    )
    m_id_to_rank: Dict[str, int] = {}
    for m_idx, (mid, _pos, _pid) in enumerate(milestones, start=1):
        idx.milestone_id_to_label[mid] = f"M{m_idx}"
        m_id_to_rank[mid] = m_idx

    # ---- Activities (project-scoped query, group + rank in Python) ----
    activities = (
        db.query(ActivityModel.id, ActivityModel.position, ActivityModel.milestone_id)
        .filter(ActivityModel.project_id == project_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .all()
    )
    acts_by_milestone: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for aid, pos, mid in activities:
        acts_by_milestone[mid].append((aid, pos))
    a_id_to_rank: Dict[str, Tuple[int, int]] = {}  # value: (m_rank, a_rank)
    for mid, pairs in acts_by_milestone.items():
        m_rank = m_id_to_rank.get(mid)
        if m_rank is None:
            continue  # parent milestone soft-deleted; activity orphaned
        # Sort by (position, id) — same order as the indexed query would give.
        pairs.sort(key=lambda x: (x[1], x[0]))
        for a_idx, (aid, _pos) in enumerate(pairs, start=1):
            idx.activity_id_to_label[aid] = f"A{m_rank}.{a_idx}"
            a_id_to_rank[aid] = (m_rank, a_idx)

    # ---- Tasks ----
    tasks = (
        db.query(TaskModel.id, TaskModel.position, TaskModel.activity_id)
        .filter(TaskModel.project_id == project_id)
        .filter(TaskModel.deleted_at.is_(None))
        .all()
    )
    tasks_by_activity: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for tid, pos, aid in tasks:
        tasks_by_activity[aid].append((tid, pos))
    t_id_to_rank: Dict[str, Tuple[int, int, int]] = {}
    for aid, pairs in tasks_by_activity.items():
        m_a = a_id_to_rank.get(aid)
        if m_a is None:
            continue
        m_rank, a_rank = m_a
        pairs.sort(key=lambda x: (x[1], x[0]))
        for t_idx, (tid, _pos) in enumerate(pairs, start=1):
            idx.task_id_to_label[tid] = f"T{m_rank}.{a_rank}.{t_idx}"
            t_id_to_rank[tid] = (m_rank, a_rank, t_idx)

    # ---- Subtasks (variable-depth, doc 24) -----------------------------
    # One project-scoped query loads all subtask rows. We then walk the
    # tree per-task: top-level (parent_subtask_id IS NULL) anchors the
    # ``s1`` segment; each subsequent depth ranks among that subtask's
    # children. The whole pass is in-Python, no extra DB roundtrips.
    subtasks = (
        db.query(
            SubtaskModel.id,
            SubtaskModel.position,
            SubtaskModel.task_id,
            SubtaskModel.parent_subtask_id,
        )
        .filter(SubtaskModel.project_id == project_id)
        .filter(SubtaskModel.deleted_at.is_(None))
        .all()
    )
    # Two adjacency maps: top-level under each task, and children under
    # each subtask. ``(position, id)`` tuples drive sibling ordering.
    top_by_task: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    children_by_parent: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for sid, pos, tid, pid in subtasks:
        if pid is None:
            top_by_task[tid].append((sid, pos))
        else:
            children_by_parent[pid].append((sid, pos))
    for bucket in top_by_task.values():
        bucket.sort(key=lambda x: (x[1], x[0]))
    for bucket in children_by_parent.values():
        bucket.sort(key=lambda x: (x[1], x[0]))

    # DFS from each top-level subtask, accumulating the rank suffix as
    # we descend. Iterative (stack of (subtask_id, suffix_str)) so the
    # depth-cap env var doesn't have to fight Python's recursion limit.
    for tid, top_pairs in top_by_task.items():
        m_a_t = t_id_to_rank.get(tid)
        if m_a_t is None:
            continue
        m_rank, a_rank, t_rank = m_a_t
        prefix = f"S{m_rank}.{a_rank}.{t_rank}"
        for top_idx, (top_sid, _pos) in enumerate(top_pairs, start=1):
            stack: List[Tuple[str, str]] = [(top_sid, f"{prefix}.{top_idx}")]
            while stack:
                node_id, label = stack.pop()
                idx.subtask_id_to_label[node_id] = label
                children = children_by_parent.get(node_id, [])
                # Push in reverse so order isn't critical for correctness;
                # ranking is done by the sorted pairs above.
                for child_idx, (child_sid, _cpos) in enumerate(
                    children, start=1,
                ):
                    stack.append((child_sid, f"{label}.{child_idx}"))

    return idx
