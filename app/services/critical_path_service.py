"""CriticalPathService — CPM algorithm + dependency table builder.

Algorithm (activity-on-node, day-based):
  Forward pass  — ES=1 for sources; EF=ES+duration-1
                  ES of successor = max(EF of all predecessors) + 1
  Backward pass — LF=project_end for sinks; LS=LF-duration+1
                  LF of predecessor = min(LS of all successors) - 1
  Slack         — LS - ES  (0 = on critical path)

Duration model:
  days_needed       = max(0, (end_date - start_date).days)
  days_delayed      = max(0, (actual_end_date - end_date).days)  if set
  effective_duration = max(1, days_needed + days_delayed)

Display codes:
  Milestone  → M{milestone.position}
  Activity   → A{milestone.position}.{activity.position}
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.repositories.critical_path_repository import CriticalPathRepository
from app.schemas.critical_path import (
    CpaActivityOverride,
    CpaActivitySchedule,
    CpaAnalysisResponse,
    CpaCalcDetail,
    CpaCalculationSteps,
    CpaCriticalPathActivity,
    CpaDependencyResponse,
    CpaDependencyRow,
    CpaDependsOn,
    CpaFlowEdge,
    CpaFlowNode,
    CpaMetadata,
)


def _days_needed(act: Dict[str, Any]) -> int:
    sd, ed = act.get("start_date"), act.get("end_date")
    if sd and ed:
        delta = (ed - sd).days
        return max(0, delta)
    return 0


def _days_delayed(act: Dict[str, Any]) -> int:
    """Two-case delay calculation:

    1. Completed late — actual_end_date is set AND exceeds planned end_date.
       Delay = actual_end - planned_end.
    2. Running late — activity is not yet completed AND today is past the
       planned end_date. Delay = today - planned_end (calendar-date math).

    On-time / not-yet-due / completed-on-time all return 0.
    """
    from datetime import datetime, date
    from app.utilities.timezones import IST

    ed = act.get("end_date")
    aed = act.get("actual_end_date")
    status = (act.get("status") or "").lower()

    # Case 1: completed late (actual exceeded planned)
    if ed and aed and aed > ed:
        return (aed - ed).days

    # Case 2: still running and past planned end_date — accrue delay daily.
    # Skip when status is already "completed" (data anomaly where actual_end
    # wasn't recorded — don't double-count against today's date).
    # Normalize both sides to IST before extracting the date component so
    # UTC-stored end_dates (with +05:30 offset) don't slip back a calendar
    # day during the comparison.
    if ed and status != "completed":
        today = datetime.now(IST)
        if hasattr(ed, "tzinfo") and ed.tzinfo is not None:
            ed_d = ed.astimezone(IST).date()
        else:
            ed_d = ed.date() if hasattr(ed, "date") else ed
        today_d = today.date()
        if isinstance(ed_d, date) and today_d > ed_d:
            return (today_d - ed_d).days

    return 0


def _effective_duration(days_needed: int, days_delayed: int) -> int:
    return max(1, days_needed + days_delayed)


def _display_code(milestone_position: int, activity_position: int) -> str:
    return f"A{milestone_position}.{activity_position}"


def _milestone_code(position: int) -> str:
    return f"M{position}"


def _topological_sort(
    activity_ids: List[str],
    predecessors: Dict[str, Set[str]],
    successors: Dict[str, Set[str]],
) -> Tuple[List[str], bool]:
    """Kahn's algorithm. Returns (order, has_cycle)."""
    in_degree = {aid: len(predecessors.get(aid, set())) for aid in activity_ids}
    queue: deque = deque(aid for aid in activity_ids if in_degree[aid] == 0)
    order: List[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for succ in successors.get(node, set()):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)
    has_cycle = len(order) < len(activity_ids)
    return order, has_cycle


def _build_calculation_steps(
    aid: str,
    predecessors: Dict[str, Set[str]],
    successors: Dict[str, Set[str]],
    es: Dict[str, int],
    ef: Dict[str, int],
    ls: Dict[str, int],
    lf: Dict[str, int],
    dur: int,
    project_end: int,
    slack: int,
    code_map: Dict[str, str],   # aid -> display_code
) -> CpaCalculationSteps:
    """Build the step-by-step CPM calculation card for one activity.

    Parameter names are lowercased for PEP-8 compliance (Sonar S117); the
    user-visible formula strings ("ES + Duration − 1", etc.) keep the
    standard CPM uppercase notation in the API response.
    """
    preds = sorted(predecessors.get(aid, set()))
    succs = sorted(successors.get(aid, set()))

    # Early Start
    if not preds:
        es_detail = CpaCalcDetail(
            formula="No predecessors → ES = 1",
            substituted="= 1",
            result=es[aid],
            note="First activity — can start on Day 1",
        )
    else:
        sym = ", ".join(f"EF[{code_map.get(p, p)}]" for p in preds)
        vals = ", ".join(str(ef[p]) for p in preds)
        es_detail = CpaCalcDetail(
            formula=f"max({sym}) + 1",
            substituted=f"max({vals}) + 1",
            result=es[aid],
        )

    # Early Finish
    ef_detail = CpaCalcDetail(
        formula="ES + Duration − 1",
        substituted=f"{es[aid]} + {dur} − 1",
        result=ef[aid],
    )

    # Late Finish
    if not succs:
        lf_detail = CpaCalcDetail(
            formula="No successors → LF = Project End",
            substituted=f"= {project_end}",
            result=lf[aid],
            note="Last activity — must finish by Project End Day",
        )
    else:
        sym = ", ".join(f"LS[{code_map.get(s, s)}]" for s in succs)
        vals = ", ".join(str(ls[s]) for s in succs)
        lf_detail = CpaCalcDetail(
            formula=f"min({sym}) − 1",
            substituted=f"min({vals}) − 1",
            result=lf[aid],
        )

    # Late Start
    ls_detail = CpaCalcDetail(
        formula="LF − Duration + 1",
        substituted=f"{lf[aid]} − {dur} + 1",
        result=ls[aid],
    )

    # Slack
    slack_detail = CpaCalcDetail(
        formula="LS − ES",
        substituted=f"{ls[aid]} − {es[aid]}",
        result=slack,
    )

    if slack == 0:
        verdict = "Slack = 0 → ON CRITICAL PATH"
    else:
        day_word = "day" if slack == 1 else "days"
        verdict = f"Slack = {slack} → Not on critical path (can slip up to {slack} {day_word})"

    return CpaCalculationSteps(
        early_start=es_detail,
        early_finish=ef_detail,
        late_finish=lf_detail,
        late_start=ls_detail,
        slack=slack_detail,
        verdict=verdict,
        on_critical_path=(slack == 0),
    )


def _build_override_map(
    overrides: Optional[List[CpaActivityOverride]],
) -> Dict[str, CpaActivityOverride]:
    return {o.activity_id: o for o in overrides} if overrides else {}


def _resolve_duration(
    aid: str,
    act_by_id: Dict[str, Dict[str, Any]],
    override_map: Dict[str, CpaActivityOverride],
) -> Tuple[int, int]:
    act = act_by_id[aid]
    ov = override_map.get(aid)
    dn = ov.days_needed if (ov and ov.days_needed is not None) else _days_needed(act)
    dd = ov.days_delayed if (ov and ov.days_delayed is not None) else _days_delayed(act)
    return dn, dd


def _build_adjacency(
    edges: List[Tuple[str, str]],
    valid_ids: Set[str],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """``from depends on to`` edges → (predecessors, successors)."""
    predecessors: Dict[str, Set[str]] = defaultdict(set)
    successors: Dict[str, Set[str]] = defaultdict(set)
    for from_id, to_id in edges:
        if from_id in valid_ids and to_id in valid_ids:
            predecessors[from_id].add(to_id)
            successors[to_id].add(from_id)
    return predecessors, successors


def _forward_pass(
    topo_order: List[str],
    predecessors: Dict[str, Set[str]],
    get_duration,
) -> Tuple[Dict[str, int], Dict[str, int], int]:
    es: Dict[str, int] = {}
    ef: Dict[str, int] = {}
    for aid in topo_order:
        dn, dd = get_duration(aid)
        dur = _effective_duration(dn, dd)
        if not predecessors.get(aid):
            es[aid] = 1
        else:
            es[aid] = max(ef[pred] for pred in predecessors[aid]) + 1
        ef[aid] = es[aid] + dur - 1
    project_end = max(ef.values()) if ef else 1
    return es, ef, project_end


def _backward_pass(
    topo_order: List[str],
    successors: Dict[str, Set[str]],
    project_end: int,
    get_duration,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    lf: Dict[str, int] = {}
    ls: Dict[str, int] = {}
    for aid in reversed(topo_order):
        dn, dd = get_duration(aid)
        dur = _effective_duration(dn, dd)
        if not successors.get(aid):
            lf[aid] = project_end
        else:
            lf[aid] = min(ls[succ] for succ in successors[aid]) - 1
        ls[aid] = lf[aid] - dur + 1
    return ls, lf


def _build_code_map(
    activities: List[Dict[str, Any]],
    milestones: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    code_map: Dict[str, str] = {}
    for act in activities:
        ms = milestones.get(act["milestone_id"], {})
        code_map[act["id"]] = _display_code(ms.get("position", 0), act["position"])
    return code_map


def _build_critical_path_ordered(
    topo_order: List[str],
    critical_ids: Set[str],
    act_by_id: Dict[str, Dict[str, Any]],
    milestones: Dict[str, Dict[str, Any]],
    get_duration,
) -> List[CpaCriticalPathActivity]:
    out: List[CpaCriticalPathActivity] = []
    for aid in topo_order:
        if aid not in critical_ids:
            continue
        act = act_by_id[aid]
        ms = milestones.get(act["milestone_id"], {})
        dn, dd = get_duration(aid)
        out.append(CpaCriticalPathActivity(
            display_code=_display_code(ms.get("position", 0), act["position"]),
            name=act["name"],
            duration=_effective_duration(dn, dd),
            days_needed=dn,
            days_delayed=dd,
        ))
    return out


def _build_schedule_row(
    act: Dict[str, Any],
    *,
    act_by_id: Dict[str, Dict[str, Any]],
    milestones: Dict[str, Dict[str, Any]],
    predecessors: Dict[str, Set[str]],
    successors: Dict[str, Set[str]],
    es: Dict[str, int],
    ef: Dict[str, int],
    ls: Dict[str, int],
    lf: Dict[str, int],
    slack_map: Dict[str, int],
    critical_ids: Set[str],
    code_map: Dict[str, str],
    project_end: int,
    get_duration,
) -> CpaActivitySchedule:
    aid = act["id"]
    ms = milestones.get(act["milestone_id"], {})
    ms_pos = ms.get("position", 0)
    dn, dd = get_duration(aid)
    dur = _effective_duration(dn, dd)
    slk = slack_map.get(aid, 0)

    depends_on: List[CpaDependsOn] = []
    for pred_id in sorted(predecessors.get(aid, set())):
        pred = act_by_id.get(pred_id)
        if pred:
            depends_on.append(CpaDependsOn(
                activity_id=pred_id,
                display_code=code_map.get(pred_id, pred_id),
                name=pred["name"],
            ))

    calc_steps = _build_calculation_steps(
        aid=aid,
        predecessors=predecessors,
        successors=successors,
        es=es, ef=ef, ls=ls, lf=lf,
        dur=dur,
        project_end=project_end,
        slack=slk,
        code_map=code_map,
    )

    return CpaActivitySchedule(
        activity_id=aid,
        display_code=_display_code(ms_pos, act["position"]),
        name=act["name"],
        milestone_id=act["milestone_id"],
        milestone_display_code=_milestone_code(ms_pos),
        milestone_name=ms.get("name", ""),
        status=act.get("status"),
        days_needed=dn,
        days_delayed=dd,
        effective_duration=dur,
        depends_on=depends_on,
        early_start=es.get(aid, 1),
        early_finish=ef.get(aid, 1),
        late_start=ls.get(aid, 1),
        late_finish=lf.get(aid, 1),
        slack=slk,
        on_critical_path=aid in critical_ids,
        calculation_steps=calc_steps,
    )


def _build_activity_schedule(
    *,
    activities: List[Dict[str, Any]],
    act_by_id: Dict[str, Dict[str, Any]],
    milestones: Dict[str, Dict[str, Any]],
    predecessors: Dict[str, Set[str]],
    successors: Dict[str, Set[str]],
    es: Dict[str, int],
    ef: Dict[str, int],
    ls: Dict[str, int],
    lf: Dict[str, int],
    slack_map: Dict[str, int],
    critical_ids: Set[str],
    code_map: Dict[str, str],
    project_end: int,
    get_duration,
) -> List[CpaActivitySchedule]:
    return [
        _build_schedule_row(
            act,
            act_by_id=act_by_id,
            milestones=milestones,
            predecessors=predecessors,
            successors=successors,
            es=es, ef=ef, ls=ls, lf=lf,
            slack_map=slack_map,
            critical_ids=critical_ids,
            code_map=code_map,
            project_end=project_end,
            get_duration=get_duration,
        )
        for act in activities
    ]


def _build_flow_nodes(
    *,
    activities: List[Dict[str, Any]],
    milestones: Dict[str, Dict[str, Any]],
    es: Dict[str, int],
    ef: Dict[str, int],
    ls: Dict[str, int],
    lf: Dict[str, int],
    slack_map: Dict[str, int],
    critical_ids: Set[str],
    get_duration,
) -> List[CpaFlowNode]:
    """Grid layout: column = ES, row = milestone display-order."""
    ms_order = {mid: i for i, mid in enumerate(
        sorted(milestones.keys(), key=lambda mid: milestones[mid].get("position", 0))
    )}
    nodes: List[CpaFlowNode] = []
    for act in activities:
        aid = act["id"]
        ms = milestones.get(act["milestone_id"], {})
        ms_pos = ms.get("position", 0)
        col = es.get(aid, 1)
        row = ms_order.get(act["milestone_id"], 0)
        dn, dd = get_duration(aid)
        nodes.append(CpaFlowNode(
            id=aid,
            label=_display_code(ms_pos, act["position"]),
            display_code=_display_code(ms_pos, act["position"]),
            name=act["name"],
            milestone_display_code=_milestone_code(ms_pos),
            days_needed=dn,
            days_delayed=dd,
            effective_duration=_effective_duration(dn, dd),
            early_start=es.get(aid, 1),
            early_finish=ef.get(aid, 1),
            late_start=ls.get(aid, 1),
            late_finish=lf.get(aid, 1),
            slack=slack_map.get(aid, 0),
            on_critical_path=aid in critical_ids,
            status=act.get("status"),
            position={"x": (col - 1) * 220, "y": row * 160},
        ))
    return nodes


def _build_flow_edges(
    edges: List[Tuple[str, str]],
    valid_ids: Set[str],
    critical_ids: Set[str],
) -> List[CpaFlowEdge]:
    flow_edges: List[CpaFlowEdge] = []
    for from_id, to_id in edges:
        if from_id in valid_ids and to_id in valid_ids:
            on_cp = from_id in critical_ids and to_id in critical_ids
            flow_edges.append(CpaFlowEdge(
                id=f"{to_id}->{from_id}",
                source=to_id,
                target=from_id,
                on_critical_path=on_cp,
            ))
    return flow_edges


def _compute_planned_end(
    topo_order: List[str],
    predecessors: Dict[str, Set[str]],
    act_by_id: Dict[str, Dict[str, Any]],
    *,
    fallback: int,
) -> int:
    """``max(EF)`` if all override delays were zero — used for project_delay."""
    plain_durations = {aid: max(1, _days_needed(act_by_id[aid])) for aid in topo_order}
    plain_ef: Dict[str, int] = {}
    for aid in topo_order:
        dur = plain_durations[aid]
        if not predecessors.get(aid):
            plain_ef[aid] = dur
        else:
            plain_ef[aid] = max(plain_ef[pred] for pred in predecessors[aid]) + dur
    return max(plain_ef.values()) if plain_ef else fallback


class CriticalPathService:
    def __init__(self, db: Session):
        self.repo = CriticalPathRepository(db)

    # ------------------------------------------------------------------
    # API 1 — dependency table
    # ------------------------------------------------------------------

    def get_dependencies(self, project_id: str) -> CpaDependencyResponse:
        activities = self.repo.get_project_activities(project_id)
        if not activities:
            raise NotFoundError(f"Project {project_id} has no activities")

        milestones = self.repo.get_project_milestones(project_id)
        edges = self.repo.get_activity_dependencies(project_id)

        act_by_id: Dict[str, Dict[str, Any]] = {a["id"]: a for a in activities}

        # Build predecessor map: from_id → [to_ids] (predecessors)
        preds: Dict[str, List[str]] = defaultdict(list)
        for from_id, to_id in edges:
            if to_id in act_by_id:
                preds[from_id].append(to_id)

        rows: List[CpaDependencyRow] = []
        for act in activities:
            ms = milestones.get(act["milestone_id"], {})
            ms_pos = ms.get("position", 0)
            dn = _days_needed(act)
            dd = _days_delayed(act)

            depends_on: List[CpaDependsOn] = []
            for pred_id in preds.get(act["id"], []):
                pred = act_by_id.get(pred_id)
                if pred:
                    pred_ms = milestones.get(pred["milestone_id"], {})
                    depends_on.append(CpaDependsOn(
                        activity_id=pred_id,
                        display_code=_display_code(pred_ms.get("position", 0), pred["position"]),
                        name=pred["name"],
                    ))

            rows.append(CpaDependencyRow(
                activity_id=act["id"],
                display_code=_display_code(ms_pos, act["position"]),
                name=act["name"],
                milestone_id=act["milestone_id"],
                milestone_display_code=_milestone_code(ms_pos),
                milestone_name=ms.get("name", ""),
                days_needed=dn,
                days_delayed=dd,
                effective_duration=_effective_duration(dn, dd),
                status=act.get("status"),
                depends_on=depends_on,
            ))

        return CpaDependencyResponse(
            project_id=project_id,
            total_activities=len(rows),
            dependencies=rows,
        )

    # ------------------------------------------------------------------
    # API 2 — full CPM analysis
    # ------------------------------------------------------------------

    def get_analysis(
        self,
        project_id: str,
        overrides: Optional[List[CpaActivityOverride]] = None,
    ) -> CpaAnalysisResponse:
        activities = self.repo.get_project_activities(project_id)
        if not activities:
            raise NotFoundError(f"Project {project_id} has no activities")

        milestones = self.repo.get_project_milestones(project_id)
        edges = self.repo.get_activity_dependencies(project_id)

        act_by_id: Dict[str, Dict[str, Any]] = {a["id"]: a for a in activities}
        override_map = _build_override_map(overrides)

        def get_duration(aid: str) -> Tuple[int, int]:
            return _resolve_duration(aid, act_by_id, override_map)

        valid_ids = set(act_by_id.keys())
        predecessors, successors = _build_adjacency(edges, valid_ids)

        activity_ids = list(act_by_id.keys())
        topo_order, has_cycle = _topological_sort(activity_ids, predecessors, successors)

        es, ef, project_end = _forward_pass(topo_order, predecessors, get_duration)
        ls, lf = _backward_pass(topo_order, successors, project_end, get_duration)

        slack_map: Dict[str, int] = {aid: ls[aid] - es[aid] for aid in activity_ids}
        critical_ids: Set[str] = {aid for aid, s in slack_map.items() if s == 0}

        code_map = _build_code_map(activities, milestones)

        critical_path_ordered = _build_critical_path_ordered(
            topo_order, critical_ids, act_by_id, milestones, get_duration,
        )

        schedule = _build_activity_schedule(
            activities=activities,
            act_by_id=act_by_id,
            milestones=milestones,
            predecessors=predecessors,
            successors=successors,
            es=es, ef=ef, ls=ls, lf=lf,
            slack_map=slack_map,
            critical_ids=critical_ids,
            code_map=code_map,
            project_end=project_end,
            get_duration=get_duration,
        )

        nodes = _build_flow_nodes(
            activities=activities,
            milestones=milestones,
            es=es, ef=ef, ls=ls, lf=lf,
            slack_map=slack_map,
            critical_ids=critical_ids,
            get_duration=get_duration,
        )
        flow_edges = _build_flow_edges(edges, valid_ids, critical_ids)

        total_buffer = sum(max(0, s) for s in slack_map.values())
        planned_end = _compute_planned_end(
            topo_order, predecessors, act_by_id, fallback=project_end,
        )
        project_delay = max(0, project_end - planned_end)

        metadata = CpaMetadata(
            total_project_days=project_end,
            activities_on_critical_path=len(critical_ids),
            total_activities=len(activity_ids),
            total_buffer_slack=total_buffer,
            project_delay_days=project_delay,
            has_cycle=has_cycle,
        )

        return CpaAnalysisResponse(
            project_id=project_id,
            metadata=metadata,
            critical_path=critical_path_ordered,
            activity_schedule=schedule,
            flow_diagram={
                "nodes": [n.model_dump() for n in nodes],
                "edges": [e.model_dump() for e in flow_edges],
            },
        )
