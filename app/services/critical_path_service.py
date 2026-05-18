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
    ed = act.get("end_date")
    aed = act.get("actual_end_date")
    if ed and aed and aed > ed:
        return (aed - ed).days
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

        # Apply overrides (what-if scenario support)
        override_map: Dict[str, CpaActivityOverride] = {}
        if overrides:
            override_map = {o.activity_id: o for o in overrides}

        def get_duration(aid: str) -> Tuple[int, int]:
            act = act_by_id[aid]
            ov = override_map.get(aid)
            dn = ov.days_needed if (ov and ov.days_needed is not None) else _days_needed(act)
            dd = ov.days_delayed if (ov and ov.days_delayed is not None) else _days_delayed(act)
            return dn, dd

        # Build predecessor/successor adjacency
        predecessors: Dict[str, Set[str]] = defaultdict(set)
        successors: Dict[str, Set[str]] = defaultdict(set)
        valid_ids = set(act_by_id.keys())
        for from_id, to_id in edges:
            if from_id in valid_ids and to_id in valid_ids:
                predecessors[from_id].add(to_id)   # from depends on to
                successors[to_id].add(from_id)

        activity_ids = list(act_by_id.keys())
        topo_order, has_cycle = _topological_sort(activity_ids, predecessors, successors)

        # Forward pass
        ES: Dict[str, int] = {}
        EF: Dict[str, int] = {}
        for aid in topo_order:
            dn, dd = get_duration(aid)
            dur = _effective_duration(dn, dd)
            if not predecessors.get(aid):
                ES[aid] = 1
            else:
                ES[aid] = max(EF[pred] for pred in predecessors[aid]) + 1
            EF[aid] = ES[aid] + dur - 1

        project_end = max(EF.values()) if EF else 1

        # Backward pass
        LF: Dict[str, int] = {}
        LS: Dict[str, int] = {}
        for aid in reversed(topo_order):
            dn, dd = get_duration(aid)
            dur = _effective_duration(dn, dd)
            if not successors.get(aid):
                LF[aid] = project_end
            else:
                LF[aid] = min(LS[succ] for succ in successors[aid]) - 1
            LS[aid] = LF[aid] - dur + 1

        # Slack + critical path
        slack_map: Dict[str, int] = {aid: LS[aid] - ES[aid] for aid in activity_ids}
        critical_ids: Set[str] = {aid for aid, s in slack_map.items() if s == 0}

        # Build ordered critical path (topological order, critical only)
        critical_path_ordered: List[str] = []
        for aid in topo_order:
            if aid in critical_ids:
                ms = milestones.get(act_by_id[aid]["milestone_id"], {})
                critical_path_ordered.append(
                    _display_code(ms.get("position", 0), act_by_id[aid]["position"])
                )

        # Activity schedule
        schedule: List[CpaActivitySchedule] = []
        for act in activities:
            aid = act["id"]
            ms = milestones.get(act["milestone_id"], {})
            ms_pos = ms.get("position", 0)
            dn, dd = get_duration(aid)
            schedule.append(CpaActivitySchedule(
                activity_id=aid,
                display_code=_display_code(ms_pos, act["position"]),
                name=act["name"],
                milestone_id=act["milestone_id"],
                milestone_display_code=_milestone_code(ms_pos),
                milestone_name=ms.get("name", ""),
                status=act.get("status"),
                days_needed=dn,
                days_delayed=dd,
                effective_duration=_effective_duration(dn, dd),
                early_start=ES.get(aid, 1),
                early_finish=EF.get(aid, 1),
                late_start=LS.get(aid, 1),
                late_finish=LF.get(aid, 1),
                slack=slack_map.get(aid, 0),
                on_critical_path=aid in critical_ids,
            ))

        # Flow diagram nodes (grid layout: column=ES, row by milestone order)
        ms_order = {mid: i for i, mid in enumerate(
            sorted(milestones.keys(), key=lambda mid: milestones[mid].get("position", 0))
        )}
        nodes: List[CpaFlowNode] = []
        for act in activities:
            aid = act["id"]
            ms = milestones.get(act["milestone_id"], {})
            ms_pos = ms.get("position", 0)
            col = ES.get(aid, 1)
            row = ms_order.get(act["milestone_id"], 0)
            nodes.append(CpaFlowNode(
                id=aid,
                label=_display_code(ms_pos, act["position"]),
                display_code=_display_code(ms_pos, act["position"]),
                name=act["name"],
                milestone_display_code=_milestone_code(ms_pos),
                effective_duration=_effective_duration(*get_duration(aid)),
                early_start=ES.get(aid, 1),
                early_finish=EF.get(aid, 1),
                late_start=LS.get(aid, 1),
                late_finish=LF.get(aid, 1),
                slack=slack_map.get(aid, 0),
                on_critical_path=aid in critical_ids,
                status=act.get("status"),
                position={"x": (col - 1) * 220, "y": row * 160},
            ))

        # Flow diagram edges
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

        total_buffer = sum(max(0, s) for s in slack_map.values())
        # Project delay: how many days the last activity exceeds the planned span
        # Use planned span = max(EF) if all delays were 0
        plain_durations = {aid: max(1, _days_needed(act_by_id[aid])) for aid in activity_ids}
        plain_EF: Dict[str, int] = {}
        for aid in topo_order:
            dur = plain_durations[aid]
            if not predecessors.get(aid):
                plain_EF[aid] = dur
            else:
                plain_EF[aid] = max(plain_EF[pred] for pred in predecessors[aid]) + dur
        planned_end = max(plain_EF.values()) if plain_EF else project_end
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
