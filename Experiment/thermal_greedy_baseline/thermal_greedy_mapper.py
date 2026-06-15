"""Deterministic ThermalGreedy mapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mapping.task_graph import TaskGraph

from common import validate_assignment
from thermal_proxy import (
    ThermalProxyConfig,
    communication_cost,
    heat_weights,
    incremental_comm_cost,
    proxy_payload,
    thermal_proxy_score,
)


@dataclass
class ThermalGreedyResult:
    assignment: dict[int, int]
    proxy: dict[str, Any]


class ThermalGreedyMapper:
    """TAPP-inspired thermal spreading mapper.

    This mapper uses only static task compute times, PE center penalty, and a
    weak communication tie-breaker. It never evaluates candidates with OMNeT++.
    """

    def __init__(
        self,
        graph: TaskGraph,
        config: ThermalProxyConfig,
        original_assignment: dict[int, int],
        baseline_temperature_factor: dict[int, float] | None = None,
        local_swap_passes: int = 0,
    ):
        self.graph = graph
        self.config = config
        self.original_assignment = dict(original_assignment)
        self.baseline_temperature_factor = baseline_temperature_factor
        self.local_swap_passes = max(0, int(local_swap_passes))
        self.config.validate()

    def run(self) -> ThermalGreedyResult:
        weights = heat_weights(
            self.graph,
            self.config,
            original_assignment=self.original_assignment,
            baseline_temperature_factor=self.baseline_temperature_factor,
        )
        task_order = self._task_order(weights)
        baseline_comm = max(
            communication_cost(self.graph, self.original_assignment, self.config.cols),
            1.0,
        )

        assignment: dict[int, int] = {}
        for tid in task_order:
            best_pe = 0
            best_key: tuple[float, float, float, float, int] | None = None
            for pe in range(self.config.num_pes):
                candidate = dict(assignment)
                candidate[tid] = pe
                score = thermal_proxy_score(
                    self.graph,
                    candidate,
                    weights,
                    self.config,
                    baseline_comm,
                    placement_temperature_factor=self.baseline_temperature_factor,
                )
                inc_comm = incremental_comm_cost(
                    self.graph, tid, pe, assignment, self.config.cols,
                ) / baseline_comm
                key = (
                    float(score["score"]),
                    float(score["max_load_norm"]),
                    float(score["std_load_norm"]),
                    float(inc_comm),
                    pe,
                )
                if best_key is None or key < best_key:
                    best_key = key
                    best_pe = pe
            assignment[tid] = best_pe

        swap_info = self._local_swap(assignment, weights, baseline_comm)
        validate_assignment(self.graph, assignment, self.config.num_pes)
        payload = proxy_payload(
            self.graph,
            self.original_assignment,
            assignment,
            weights,
            self.config,
            task_order,
            swap_info,
            placement_temperature_factor=self.baseline_temperature_factor,
        )
        return ThermalGreedyResult(assignment=assignment, proxy=payload)

    def _task_order(self, weights: dict[int, float]) -> list[int]:
        return sorted(
            self.graph.mappable_task_ids,
            key=lambda tid: (
                -weights.get(tid, 0.0),
                -self._communication_degree(tid),
                tid,
            ),
        )

    def _communication_degree(self, task_id: int) -> float:
        node = self.graph.tasks[task_id]
        total = 0.0
        for pred_id in node.predecessor_set:
            pred = self.graph.tasks.get(pred_id)
            if pred is not None and not pred.is_gb_task:
                total += pred.output_data_size
        for succ_id in node.successors:
            if succ_id == -1:
                continue
            succ = self.graph.tasks.get(succ_id)
            if succ is not None and not succ.is_gb_task:
                total += node.output_data_size
        return total

    def _local_swap(
        self,
        assignment: dict[int, int],
        weights: dict[int, float],
        baseline_comm: float,
    ) -> dict[str, Any]:
        if self.local_swap_passes <= 0:
            return {
                "enabled": False,
                "passes": 0,
                "accepted_swaps": 0,
            }

        accepted = 0
        tasks = list(self.graph.mappable_task_ids)
        current = thermal_proxy_score(
            self.graph,
            assignment,
            weights,
            self.config,
            baseline_comm,
            placement_temperature_factor=self.baseline_temperature_factor,
        )
        current_score = float(current["score"])
        eps = 1e-12
        for _ in range(self.local_swap_passes):
            improved_this_pass = False
            for idx, a in enumerate(tasks):
                for b in tasks[idx + 1:]:
                    if assignment[a] == assignment[b]:
                        continue
                    candidate = dict(assignment)
                    candidate[a], candidate[b] = candidate[b], candidate[a]
                    score = thermal_proxy_score(
                        self.graph,
                        candidate,
                        weights,
                        self.config,
                        baseline_comm,
                        placement_temperature_factor=self.baseline_temperature_factor,
                    )
                    new_score = float(score["score"])
                    if new_score + eps < current_score:
                        assignment[a], assignment[b] = assignment[b], assignment[a]
                        current_score = new_score
                        accepted += 1
                        improved_this_pass = True
            if not improved_this_pass:
                break

        return {
            "enabled": True,
            "passes": self.local_swap_passes,
            "accepted_swaps": accepted,
            "final_score": current_score,
        }
