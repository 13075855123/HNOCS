"""Thermal proxy functions for the TAPP-inspired ThermalGreedy baseline.

This module intentionally does not call OMNeT++ and does not use final
simulation metrics such as peak temperature, DVFS penalty, makespan, optical
energy, or TR2 composite cost.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from mapping.task_graph import TaskGraph


@dataclass(frozen=True)
class ThermalProxyConfig:
    rows: int = 4
    cols: int = 4
    alpha_sigma: float = 0.5
    alpha_center: float = 0.1
    alpha_temp_placement: float = 0.0
    beta_comm: float = 0.05
    heat_weight_mode: str = "compute_time"

    @property
    def num_pes(self) -> int:
        return self.rows * self.cols

    def validate(self) -> None:
        if self.rows <= 0 or self.cols <= 0:
            raise ValueError(f"invalid mesh dimensions: rows={self.rows}, cols={self.cols}")
        if self.heat_weight_mode not in ("compute_time", "baseline_temp"):
            raise ValueError(
                "heat_weight_mode must be 'compute_time' or 'baseline_temp', "
                f"got {self.heat_weight_mode}"
            )
        for name, value in [
            ("alpha_sigma", self.alpha_sigma),
            ("alpha_center", self.alpha_center),
            ("alpha_temp_placement", self.alpha_temp_placement),
            ("beta_comm", self.beta_comm),
        ]:
            if value < 0:
                raise ValueError(f"{name} must be non-negative, got {value}")


def pe_closeness_to_center(rows: int, cols: int) -> list[float]:
    """Return normalized center closeness for each PE.

    In a 4x4 mesh, the geometric center is (1.5, 1.5), so PE 5, 6, 9,
    and 10 are closest to the center and receive the largest penalty.
    """
    center_r = (rows - 1) / 2.0
    center_c = (cols - 1) / 2.0
    distances: list[float] = []
    for pe in range(rows * cols):
        r, c = divmod(pe, cols)
        distances.append(math.hypot(r - center_r, c - center_c))
    max_d = max(distances) if distances else 1.0
    if max_d <= 0:
        return [1.0 for _ in distances]
    return [1.0 - d / max_d for d in distances]


def heat_weights(
    graph: TaskGraph,
    config: ThermalProxyConfig,
    original_assignment: dict[int, int] | None = None,
    baseline_temperature_factor: dict[int, float] | None = None,
) -> dict[int, float]:
    """Compute task heat weights from compute time and optional static factors."""
    config.validate()
    weights: dict[int, float] = {}
    for tid in graph.mappable_task_ids:
        node = graph.tasks[tid]
        weight = max(float(node.compute_time_ns), 0.0)
        if config.heat_weight_mode == "baseline_temp":
            if original_assignment is None or baseline_temperature_factor is None:
                raise ValueError("baseline_temp mode requires original assignment and PE factors")
            original_pe = original_assignment.get(tid)
            if original_pe is None:
                raise ValueError(f"task {tid} missing from original assignment")
            weight *= float(baseline_temperature_factor.get(original_pe, 1.0))
        weights[tid] = weight
    return weights


def estimated_heat_load(
    assignment: dict[int, int],
    weights: dict[int, float],
    num_pes: int,
) -> list[float]:
    loads = [0.0] * num_pes
    for tid, pe in assignment.items():
        if 0 <= pe < num_pes:
            loads[pe] += weights.get(tid, 0.0)
    return loads


def load_std(loads: list[float]) -> float:
    if not loads:
        return 0.0
    avg = sum(loads) / len(loads)
    var = sum((value - avg) ** 2 for value in loads) / len(loads)
    return math.sqrt(var)


def hop_distance(pe_a: int, pe_b: int, cols: int) -> int:
    if pe_a == pe_b:
        return 0
    r1, c1 = divmod(pe_a, cols)
    r2, c2 = divmod(pe_b, cols)
    return abs(r1 - r2) + abs(c1 - c2)


def communication_cost(graph: TaskGraph, assignment: dict[int, int], cols: int) -> float:
    """Partial or full producer-bytes times hop-distance cost."""
    total = 0.0
    for tid, node in graph.tasks.items():
        if node.is_gb_task:
            continue
        src_pe = assignment.get(tid)
        if src_pe is None:
            continue
        for succ_id in node.successors:
            if succ_id == -1:
                continue
            succ = graph.tasks.get(succ_id)
            if succ is None or succ.is_gb_task:
                continue
            dst_pe = assignment.get(succ_id)
            if dst_pe is None:
                continue
            total += hop_distance(src_pe, dst_pe, cols) * node.output_data_size
    return total


def incremental_comm_cost(
    graph: TaskGraph,
    task_id: int,
    pe: int,
    assignment: dict[int, int],
    cols: int,
) -> float:
    """Communication added by placing one task against already placed neighbors."""
    node = graph.tasks[task_id]
    total = 0.0
    for pred_id in node.predecessor_set:
        pred = graph.tasks.get(pred_id)
        if pred is None or pred.is_gb_task:
            continue
        pred_pe = assignment.get(pred_id)
        if pred_pe is not None:
            total += hop_distance(pred_pe, pe, cols) * pred.output_data_size
    for succ_id in node.successors:
        if succ_id == -1:
            continue
        succ = graph.tasks.get(succ_id)
        if succ is None or succ.is_gb_task:
            continue
        succ_pe = assignment.get(succ_id)
        if succ_pe is not None:
            total += hop_distance(pe, succ_pe, cols) * node.output_data_size
    return total


def center_heat_penalty(loads: list[float], closeness: list[float]) -> float:
    total_heat = sum(loads)
    if total_heat <= 0:
        return 0.0
    return sum(load * closeness[pe] for pe, load in enumerate(loads)) / total_heat


def temperature_placement_penalty(
    loads: list[float],
    placement_temperature_factor: dict[int, float] | None,
) -> float:
    """Weighted static Original-temperature placement penalty."""
    total_heat = sum(loads)
    if total_heat <= 0 or not placement_temperature_factor:
        return 0.0
    return sum(
        load * float(placement_temperature_factor.get(pe, 1.0))
        for pe, load in enumerate(loads)
    ) / total_heat


def thermal_proxy_score(
    graph: TaskGraph,
    assignment: dict[int, int],
    weights: dict[int, float],
    config: ThermalProxyConfig,
    baseline_comm_cost: float,
    placement_temperature_factor: dict[int, float] | None = None,
) -> dict[str, Any]:
    """Return normalized ThermalProxy score and component diagnostics."""
    config.validate()
    loads = estimated_heat_load(assignment, weights, config.num_pes)
    assigned_heat = sum(weights.get(tid, 0.0) for tid in assignment)
    ideal = assigned_heat / config.num_pes if assigned_heat > 0 else 1.0
    max_load = max(loads) if loads else 0.0
    sigma = load_std(loads)
    closeness = pe_closeness_to_center(config.rows, config.cols)
    center_penalty = center_heat_penalty(loads, closeness)
    temp_penalty = temperature_placement_penalty(loads, placement_temperature_factor)
    raw_comm = communication_cost(graph, assignment, config.cols)
    normalized_comm = raw_comm / baseline_comm_cost if baseline_comm_cost > 1e-12 else 0.0

    max_norm = max_load / ideal if ideal > 0 else 0.0
    sigma_norm = sigma / ideal if ideal > 0 else 0.0
    score = (
        max_norm
        + config.alpha_sigma * sigma_norm
        + config.alpha_center * center_penalty
        + config.alpha_temp_placement * temp_penalty
        + config.beta_comm * normalized_comm
    )
    return {
        "score": score,
        "max_load": max_load,
        "std_load": sigma,
        "ideal_load": ideal,
        "max_load_norm": max_norm,
        "std_load_norm": sigma_norm,
        "center_heat_penalty": center_penalty,
        "temperature_placement_penalty": temp_penalty,
        "raw_comm_cost": raw_comm,
        "normalized_comm": normalized_comm,
        "estimated_heat_load": loads,
    }


def proxy_payload(
    graph: TaskGraph,
    original_assignment: dict[int, int],
    thermal_assignment: dict[int, int],
    weights: dict[int, float],
    config: ThermalProxyConfig,
    task_order: list[int],
    local_swap: dict[str, Any],
    placement_temperature_factor: dict[int, float] | None = None,
) -> dict[str, Any]:
    baseline_comm = max(communication_cost(graph, original_assignment, config.cols), 1.0)
    original_score = thermal_proxy_score(
        graph,
        original_assignment,
        weights,
        config,
        baseline_comm,
        placement_temperature_factor=placement_temperature_factor,
    )
    thermal_score = thermal_proxy_score(
        graph,
        thermal_assignment,
        weights,
        config,
        baseline_comm,
        placement_temperature_factor=placement_temperature_factor,
    )
    return {
        "method": "thermal_greedy",
        "method_label": "TAPP-inspired ThermalGreedy",
        "not_exact_reproduction": True,
        "search_objective": (
            "compute_time heat proxy plus center penalty and weak communication tie-breaker"
        ),
        "forbidden_search_inputs": [
            "OMNeT++ final peak temperature",
            "DVFS penalty",
            "optical tuning energy",
            "makespan",
            "TR2_composite_cost",
        ],
        "config": asdict(config),
        "task_order": task_order,
        "heat_weights": {str(tid): weight for tid, weight in sorted(weights.items())},
        "baseline_comm_cost": baseline_comm,
        "placement_temperature_factor": (
            {str(pe): factor for pe, factor in sorted(placement_temperature_factor.items())}
            if placement_temperature_factor else None
        ),
        "original": original_score,
        "thermal_greedy": thermal_score,
        "assignment": {str(tid): pe for tid, pe in sorted(thermal_assignment.items())},
        "local_swap": local_swap,
    }
