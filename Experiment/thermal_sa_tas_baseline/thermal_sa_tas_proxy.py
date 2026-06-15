"""Lightweight TAS-inspired thermal and scheduling proxy.

This module intentionally does not evaluate candidate mappings with OMNeT++ and
does not use the proposed full composite cost.  It uses a thermal resistance
proxy, DAG list scheduling, and weak communication/makespan terms.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass
from typing import Any

from mapping.task_graph import TaskGraph
from thermal_rc_ls_baseline.thermal_rc_proxy import (
    RCProxyConfig,
    aggregate_power,
    base_power_vector,
    communication_proxy,
    stddev,
    temperature_proxy,
)


@dataclass(frozen=True)
class TASScheduleConfig:
    """Controls for the lightweight list-scheduling proxy."""

    comm_delay_per_byte_hop_ns: float = 0.01
    use_critical_path_priority: bool = True
    thermal_mode: str = "dynamic_rc"
    thermal_tau_ns: float = 10000.0
    center_cooling_penalty_K_per_W: float = 0.35
    neighborhood_heat_penalty_K_per_W: float = 0.08
    dynamic_power_mode: str = "compute_power"
    peak_window_ns: float = 5000.0
    peak_window_neighbor_weight: float = 0.25
    baseline_hotspot_penalty_K_per_W: float = 0.0
    baseline_hotspot_neighbor_penalty_K_per_W: float = 0.0

    def validate(self) -> None:
        if self.comm_delay_per_byte_hop_ns < 0.0:
            raise ValueError("comm_delay_per_byte_hop_ns must be non-negative")
        if self.thermal_mode not in ("steady_rc", "dynamic_rc"):
            raise ValueError("thermal_mode must be 'steady_rc' or 'dynamic_rc'")
        if self.thermal_tau_ns <= 0.0:
            raise ValueError("thermal_tau_ns must be positive")
        if self.center_cooling_penalty_K_per_W < 0.0:
            raise ValueError("center_cooling_penalty_K_per_W must be non-negative")
        if self.neighborhood_heat_penalty_K_per_W < 0.0:
            raise ValueError("neighborhood_heat_penalty_K_per_W must be non-negative")
        if self.dynamic_power_mode not in ("compute_power", "task_power"):
            raise ValueError("dynamic_power_mode must be 'compute_power' or 'task_power'")
        if self.peak_window_ns < 0.0:
            raise ValueError("peak_window_ns must be non-negative")
        if self.peak_window_neighbor_weight < 0.0:
            raise ValueError("peak_window_neighbor_weight must be non-negative")
        if self.baseline_hotspot_penalty_K_per_W < 0.0:
            raise ValueError("baseline_hotspot_penalty_K_per_W must be non-negative")
        if self.baseline_hotspot_neighbor_penalty_K_per_W < 0.0:
            raise ValueError("baseline_hotspot_neighbor_penalty_K_per_W must be non-negative")


@dataclass(frozen=True)
class TASObjectiveWeights:
    """Search weights for Thermal-SA-TAS-Mapping.

    These weights are used only by the proxy search objective.  They are
    deliberately narrower than the proposed GA composite objective.
    """

    w_tmax: float = 0.60
    w_sigma: float = 0.25
    w_hot: float = 0.10
    w_makespan: float = 0.05
    w_comm: float = 0.0
    w_max_load: float = 0.0
    w_load_imbalance: float = 0.0
    w_peak_window: float = 0.0
    w_peak_window_sigma: float = 0.0
    w_neighbor_peak_window: float = 0.0

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative, got {value}")
        total = (
            self.w_tmax
            + self.w_sigma
            + self.w_hot
            + self.w_makespan
            + self.w_comm
            + self.w_max_load
            + self.w_load_imbalance
            + self.w_peak_window
            + self.w_peak_window_sigma
            + self.w_neighbor_peak_window
        )
        if total <= 0.0:
            raise ValueError("at least one TAS objective weight must be positive")


def task_pe(graph: TaskGraph, assignment: dict[int, int], task_id: int) -> int:
    node = graph.tasks[task_id]
    if task_id in assignment:
        return assignment[task_id]
    if node.assigned_pe >= 0:
        return node.assigned_pe
    raise ValueError(f"task {task_id} has no PE assignment")


def edge_delay_ns(
    graph: TaskGraph,
    assignment: dict[int, int],
    src_id: int,
    dst_id: int,
    cols: int,
    schedule_config: TASScheduleConfig,
) -> float:
    src = graph.tasks.get(src_id)
    dst = graph.tasks.get(dst_id)
    if src is None or dst is None or src.is_gb_task or dst.is_gb_task:
        return 0.0
    src_pe = task_pe(graph, assignment, src_id)
    dst_pe = task_pe(graph, assignment, dst_id)
    hops = manhattan(src_pe, dst_pe, cols)
    return src.output_data_size * hops * schedule_config.comm_delay_per_byte_hop_ns


def list_schedule_proxy(
    graph: TaskGraph,
    assignment: dict[int, int],
    rows: int,
    cols: int,
    schedule_config: TASScheduleConfig,
    pe_speed: list[float] | None = None,
) -> dict[str, Any]:
    """List-schedule non-GB tasks on their mapped PEs.

    The mapping is fixed.  Scheduling only estimates task start/finish times
    using DAG dependencies, PE availability, and hop-distance communication
    delay.
    """

    schedule_config.validate()
    speeds = pe_speed or [1.0] * (rows * cols)
    topo = graph.topological_order()
    schedulable = [tid for tid in topo if not graph.tasks[tid].is_gb_task]
    schedulable_set = set(schedulable)
    topo_rank = {tid: idx for idx, tid in enumerate(topo)}
    bottom_level = critical_path_priority_ns(graph, assignment, cols, schedule_config)

    unscheduled_pred_count = {
        tid: sum(1 for pred in graph.tasks[tid].predecessor_set if pred in schedulable_set)
        for tid in schedulable
    }
    ready: list[tuple[float, int, int]] = []
    for tid in schedulable:
        if unscheduled_pred_count[tid] == 0:
            priority = -bottom_level.get(tid, graph.tasks[tid].compute_time_ns)
            if not schedule_config.use_critical_path_priority:
                priority = 0.0
            heapq.heappush(ready, (priority, topo_rank[tid], tid))

    pe_available = [0.0 for _ in range(max(assignment.values(), default=15) + 1)]
    if len(pe_available) < 16:
        pe_available.extend([0.0] * (16 - len(pe_available)))
    finish_ns: dict[int, float] = {}
    rows_out: list[dict[str, float | int]] = []

    while ready:
        _, _, tid = heapq.heappop(ready)
        node = graph.tasks[tid]
        pe = task_pe(graph, assignment, tid)
        if pe < 0:
            raise ValueError(f"task {tid} has invalid PE {pe}")
        while pe >= len(pe_available):
            pe_available.append(0.0)

        data_ready = 0.0
        for pred_id in node.predecessor_set:
            pred = graph.tasks.get(pred_id)
            if pred is None or pred.is_gb_task:
                continue
            pred_finish = finish_ns[pred_id]
            data_ready = max(
                data_ready,
                pred_finish + edge_delay_ns(graph, assignment, pred_id, tid, cols, schedule_config),
            )

        speed = speeds[pe] if pe < len(speeds) and speeds[pe] > 0 else 1.0
        duration = max(float(node.compute_time_ns), 0.0) / speed
        start = max(data_ready, pe_available[pe])
        finish = start + duration
        pe_available[pe] = finish
        finish_ns[tid] = finish
        rows_out.append({
            "task_id": tid,
            "pe_id": pe,
            "start_time_proxy_ns": start,
            "finish_time_proxy_ns": finish,
            "duration_proxy_ns": duration,
            "data_ready_time_proxy_ns": data_ready,
            "priority_bottom_level_ns": bottom_level.get(tid, duration),
        })

        for succ_id in node.successors:
            if succ_id not in unscheduled_pred_count:
                continue
            unscheduled_pred_count[succ_id] -= 1
            if unscheduled_pred_count[succ_id] == 0:
                priority = -bottom_level.get(succ_id, graph.tasks[succ_id].compute_time_ns)
                if not schedule_config.use_critical_path_priority:
                    priority = 0.0
                heapq.heappush(ready, (priority, topo_rank[succ_id], succ_id))

    if len(rows_out) != len(schedulable):
        scheduled = {int(row["task_id"]) for row in rows_out}
        missing = sorted(schedulable_set - scheduled)
        raise ValueError(f"list scheduling failed; unscheduled tasks: {missing}")

    makespan = max((float(row["finish_time_proxy_ns"]) for row in rows_out), default=0.0)
    return {
        "schedule": rows_out,
        "MakespanProxy_ns": makespan,
        "pe_available_ns": pe_available,
    }


def critical_path_priority_ns(
    graph: TaskGraph,
    assignment: dict[int, int],
    cols: int,
    schedule_config: TASScheduleConfig,
) -> dict[int, float]:
    """Return bottom-level priority for each non-GB task."""

    memo: dict[int, float] = {}

    def visit(tid: int) -> float:
        if tid in memo:
            return memo[tid]
        node = graph.tasks[tid]
        best_child = 0.0
        for succ_id in node.successors:
            succ = graph.tasks.get(succ_id)
            if succ is None or succ.is_gb_task:
                continue
            child = edge_delay_ns(graph, assignment, tid, succ_id, cols, schedule_config) + visit(succ_id)
            best_child = max(best_child, child)
        memo[tid] = max(float(node.compute_time_ns), 0.0) + best_child
        return memo[tid]

    for tid in graph.topological_order():
        if not graph.tasks[tid].is_gb_task:
            visit(tid)
    return memo


def tas_proxy_score(
    graph: TaskGraph,
    assignment: dict[int, int],
    task_power: dict[int, float],
    resistance_matrix: list[list[float]],
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
    weights: TASObjectiveWeights,
    denominators: dict[str, float] | None = None,
    base_power: list[float] | None = None,
    baseline_hotspot_risk: list[float] | None = None,
) -> dict[str, Any]:
    """Evaluate one mapping using only lightweight proxy terms."""

    proxy_config.validate()
    schedule_config.validate()
    weights.validate()
    schedule = list_schedule_proxy(
        graph,
        assignment,
        proxy_config.rows,
        proxy_config.cols,
        schedule_config,
    )
    if schedule_config.thermal_mode == "dynamic_rc":
        thermal = dynamic_temperature_proxy(
            graph,
            assignment,
            task_power,
            resistance_matrix,
            proxy_config,
            schedule_config,
            schedule["schedule"],
            base_power=base_power,
            baseline_hotspot_risk=baseline_hotspot_risk,
        )
        temps = thermal["pe_peak_temp_K"]
        power = thermal["peak_power_W"]
        sigma_for_score = thermal["max_sigma_T_K"]
        hot_for_score = thermal["max_hot_count"]
        tmax_for_score = thermal["Tmax_proxy"]
    else:
        power = aggregate_power(assignment, task_power, proxy_config, base_power=base_power)
        temps = apply_spatial_heat_penalties(
            temperature_proxy(resistance_matrix, power, proxy_config.Tambient),
            power,
            proxy_config,
            schedule_config,
            baseline_hotspot_risk=baseline_hotspot_risk,
        )
        sigma_for_score = None
        hot_for_score = None
        tmax_for_score = None
    comm = communication_proxy(graph, assignment, proxy_config.cols)
    load_terms = load_proxy_terms(graph, assignment, proxy_config.num_pes)
    peak_terms = peak_window_activity_proxy(
        schedule["schedule"],
        task_power,
        proxy_config,
        schedule_config,
    )
    raw = raw_tas_terms(
        temps,
        schedule["MakespanProxy_ns"],
        comm,
        proxy_config,
        max_load_proxy=load_terms["MaxLoadProxy_ns"],
        load_imbalance_proxy=load_terms["LoadImbalanceProxy"],
        peak_window_energy_proxy=peak_terms["PeakWindowEnergyProxy"],
        peak_window_sigma_proxy=peak_terms["PeakWindowSigmaProxy"],
        neighbor_peak_window_energy_proxy=peak_terms["NeighborPeakWindowEnergyProxy"],
        sigma_override=sigma_for_score,
        hot_override=hot_for_score,
        tmax_override=tmax_for_score,
    )
    den = denominators or raw
    score = score_from_terms(raw, den, weights)
    score["temperatures_K"] = temps
    score["power_W"] = power
    score["schedule"] = schedule["schedule"]
    score["peak_window_summary"] = peak_terms
    if schedule_config.thermal_mode == "dynamic_rc":
        score["thermal_trace_summary"] = {
            "thermal_mode": "dynamic_rc",
            "max_sigma_T_K": sigma_for_score,
            "max_hot_count": hot_for_score,
            "peak_power_W": power,
            "peak_window": peak_terms,
        }
    return score


def raw_tas_terms(
    temps: list[float],
    makespan_proxy_ns: float,
    comm_proxy: float,
    config: RCProxyConfig,
    max_load_proxy: float,
    load_imbalance_proxy: float,
    peak_window_energy_proxy: float,
    peak_window_sigma_proxy: float,
    neighbor_peak_window_energy_proxy: float,
    sigma_override: float | None = None,
    hot_override: float | None = None,
    tmax_override: float | None = None,
) -> dict[str, float]:
    return {
        "Tmax_proxy": tmax_override if tmax_override is not None else (max(temps) if temps else config.Tambient),
        "SigmaT_proxy": sigma_override if sigma_override is not None else stddev(temps),
        "HotCount_proxy": hot_override if hot_override is not None else float(sum(1 for temp in temps if temp >= config.T_hot)),
        "MakespanProxy_ns": float(makespan_proxy_ns),
        "CommProxy": float(comm_proxy),
        "MaxLoadProxy_ns": float(max_load_proxy),
        "LoadImbalanceProxy": float(load_imbalance_proxy),
        "PeakWindowEnergyProxy": float(peak_window_energy_proxy),
        "PeakWindowSigmaProxy": float(peak_window_sigma_proxy),
        "NeighborPeakWindowEnergyProxy": float(neighbor_peak_window_energy_proxy),
    }


def dynamic_temperature_proxy(
    graph: TaskGraph,
    assignment: dict[int, int],
    task_power: dict[int, float],
    resistance_matrix: list[list[float]],
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
    schedule_rows: list[dict[str, float | int]],
    base_power: list[float] | None = None,
    baseline_hotspot_risk: list[float] | None = None,
) -> dict[str, Any]:
    """Event-driven first-order RC proxy from a list schedule.

    This approximates time overlap: only tasks active during a time segment
    contribute compute power.  It is still a lightweight proxy and does not use
    OMNeT++ candidate results.
    """

    base = list(base_power) if base_power is not None else base_power_vector(proxy_config)
    if len(base) != proxy_config.num_pes:
        raise ValueError(f"base power length must be {proxy_config.num_pes}")

    events = {0.0}
    intervals: list[tuple[float, float, int, int]] = []
    for row in schedule_rows:
        tid = int(row["task_id"])
        pe = int(row["pe_id"])
        start = float(row["start_time_proxy_ns"])
        finish = float(row["finish_time_proxy_ns"])
        if finish <= start:
            continue
        events.add(start)
        events.add(finish)
        intervals.append((start, finish, pe, tid))

    sorted_events = sorted(events)
    if len(sorted_events) < 2:
        temps = apply_spatial_heat_penalties(
            temperature_proxy(resistance_matrix, base, proxy_config.Tambient),
            base,
            proxy_config,
            schedule_config,
            baseline_hotspot_risk=baseline_hotspot_risk,
        )
        return {
            "Tmax_proxy": max(temps) if temps else proxy_config.Tambient,
            "pe_peak_temp_K": temps,
            "max_sigma_T_K": stddev(temps),
            "max_hot_count": float(sum(1 for temp in temps if temp >= proxy_config.T_hot)),
            "peak_power_W": base,
        }

    current_temp = [proxy_config.Tambient for _ in range(proxy_config.num_pes)]
    pe_peak = list(current_temp)
    max_sigma = 0.0
    max_hot = 0.0
    peak_power = list(base)
    peak_power_total = sum(base)

    for idx in range(len(sorted_events) - 1):
        start = sorted_events[idx]
        end = sorted_events[idx + 1]
        duration = end - start
        if duration <= 0.0:
            continue
        mid = (start + end) / 2.0
        power = list(base)
        for task_start, task_finish, pe, tid in intervals:
            if task_start <= mid < task_finish:
                if schedule_config.dynamic_power_mode == "task_power":
                    dynamic = task_power.get(tid, 0.0)
                else:
                    dynamic = proxy_config.power_compute - proxy_config.power_idle
                power[pe] += max(0.0, dynamic)

        steady = apply_spatial_heat_penalties(
            temperature_proxy(resistance_matrix, power, proxy_config.Tambient),
            power,
            proxy_config,
            schedule_config,
            baseline_hotspot_risk=baseline_hotspot_risk,
        )
        decay = math.exp(-duration / schedule_config.thermal_tau_ns)
        current_temp = [
            steady_temp + (old_temp - steady_temp) * decay
            for old_temp, steady_temp in zip(current_temp, steady)
        ]
        pe_peak = [max(old, new) for old, new in zip(pe_peak, current_temp)]
        sigma = stddev(current_temp)
        hot = float(sum(1 for temp in current_temp if temp >= proxy_config.T_hot))
        max_sigma = max(max_sigma, sigma)
        max_hot = max(max_hot, hot)
        total_power = sum(power)
        if total_power > peak_power_total:
            peak_power_total = total_power
            peak_power = power

    return {
        "Tmax_proxy": max(pe_peak) if pe_peak else proxy_config.Tambient,
        "pe_peak_temp_K": pe_peak,
        "max_sigma_T_K": max_sigma,
        "max_hot_count": max_hot,
        "peak_power_W": peak_power,
    }


def apply_spatial_heat_penalties(
    temps: list[float],
    power: list[float],
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
    baseline_hotspot_risk: list[float] | None = None,
) -> list[float]:
    if (
        schedule_config.center_cooling_penalty_K_per_W <= 0.0
        and schedule_config.neighborhood_heat_penalty_K_per_W <= 0.0
        and schedule_config.baseline_hotspot_penalty_K_per_W <= 0.0
        and schedule_config.baseline_hotspot_neighbor_penalty_K_per_W <= 0.0
    ):
        return temps
    risk = _normalized_risk(baseline_hotspot_risk, proxy_config.num_pes)
    closeness = pe_closeness_to_center(proxy_config.rows, proxy_config.cols)
    out = list(temps)
    for pe in range(proxy_config.num_pes):
        dynamic_power = max(0.0, power[pe] - proxy_config.leakage_base_power)
        out[pe] += schedule_config.center_cooling_penalty_K_per_W * closeness[pe] * dynamic_power
        out[pe] += schedule_config.baseline_hotspot_penalty_K_per_W * risk[pe] * dynamic_power
        if schedule_config.neighborhood_heat_penalty_K_per_W > 0.0:
            neighbor_power = 0.0
            row, col = divmod(pe, proxy_config.cols)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = row + dr, col + dc
                if 0 <= rr < proxy_config.rows and 0 <= cc < proxy_config.cols:
                    npe = rr * proxy_config.cols + cc
                    neighbor_power += max(0.0, power[npe] - proxy_config.leakage_base_power)
            out[pe] += schedule_config.neighborhood_heat_penalty_K_per_W * neighbor_power
        if schedule_config.baseline_hotspot_neighbor_penalty_K_per_W > 0.0:
            neighbor_risk_power = 0.0
            row, col = divmod(pe, proxy_config.cols)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = row + dr, col + dc
                if 0 <= rr < proxy_config.rows and 0 <= cc < proxy_config.cols:
                    npe = rr * proxy_config.cols + cc
                    neighbor_risk_power += risk[npe] * max(0.0, power[npe] - proxy_config.leakage_base_power)
            out[pe] += schedule_config.baseline_hotspot_neighbor_penalty_K_per_W * neighbor_risk_power
    return out


def peak_window_activity_proxy(
    schedule_rows: list[dict[str, float | int]],
    task_power: dict[int, float],
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
) -> dict[str, float]:
    """Return per-window PE activity burst terms from the proxy schedule."""

    window_ns = float(schedule_config.peak_window_ns)
    if window_ns <= 0.0:
        return {
            "PeakWindowEnergyProxy": 0.0,
            "PeakWindowSigmaProxy": 0.0,
            "NeighborPeakWindowEnergyProxy": 0.0,
            "PeakWindowNs": 0.0,
            "PeakWindowCount": 0.0,
        }

    intervals: list[tuple[float, float, int, int]] = []
    makespan = 0.0
    for row in schedule_rows:
        tid = int(row["task_id"])
        pe = int(row["pe_id"])
        start = float(row["start_time_proxy_ns"])
        finish = float(row["finish_time_proxy_ns"])
        if finish <= start or pe < 0 or pe >= proxy_config.num_pes:
            continue
        intervals.append((start, finish, pe, tid))
        makespan = max(makespan, finish)

    if not intervals:
        return {
            "PeakWindowEnergyProxy": 0.0,
            "PeakWindowSigmaProxy": 0.0,
            "NeighborPeakWindowEnergyProxy": 0.0,
            "PeakWindowNs": window_ns,
            "PeakWindowCount": 0.0,
        }

    latest_start = max(0.0, makespan - window_ns)
    starts = {0.0, latest_start}
    for start, finish, _, _ in intervals:
        for candidate in (start, finish, start - window_ns, finish - window_ns):
            starts.add(min(max(candidate, 0.0), latest_start))

    max_energy = 0.0
    max_sigma = 0.0
    max_neighbor_energy = 0.0
    evaluated = 0
    for window_start in sorted(starts):
        window_end = window_start + window_ns
        energy = [0.0 for _ in range(proxy_config.num_pes)]
        for task_start, task_finish, pe, tid in intervals:
            overlap = min(task_finish, window_end) - max(task_start, window_start)
            if overlap <= 0.0:
                continue
            if schedule_config.dynamic_power_mode == "task_power":
                dynamic = task_power.get(tid, 0.0)
            else:
                dynamic = proxy_config.power_compute - proxy_config.power_idle
            energy[pe] += max(0.0, dynamic) * overlap

        neighbor_energy = 0.0
        for pe in range(proxy_config.num_pes):
            row, col = divmod(pe, proxy_config.cols)
            local = energy[pe]
            adjacent = 0.0
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = row + dr, col + dc
                if 0 <= rr < proxy_config.rows and 0 <= cc < proxy_config.cols:
                    adjacent += energy[rr * proxy_config.cols + cc]
            neighbor_energy = max(
                neighbor_energy,
                local + schedule_config.peak_window_neighbor_weight * adjacent,
            )

        max_energy = max(max_energy, max(energy) if energy else 0.0)
        max_sigma = max(max_sigma, stddev(energy))
        max_neighbor_energy = max(max_neighbor_energy, neighbor_energy)
        evaluated += 1

    return {
        "PeakWindowEnergyProxy": max_energy,
        "PeakWindowSigmaProxy": max_sigma,
        "NeighborPeakWindowEnergyProxy": max_neighbor_energy,
        "PeakWindowNs": window_ns,
        "PeakWindowCount": float(evaluated),
    }


def score_from_terms(
    terms: dict[str, float],
    denominators: dict[str, float],
    weights: TASObjectiveWeights,
) -> dict[str, Any]:
    f_tmax = terms["Tmax_proxy"] / _positive(denominators.get("Tmax_proxy", 0.0), 1.0)
    f_sigma = terms["SigmaT_proxy"] / _positive(denominators.get("SigmaT_proxy", 0.0), 1.0)
    f_hot = terms["HotCount_proxy"] / max(1.0, float(denominators.get("HotCount_proxy", 0.0)))
    f_makespan = terms["MakespanProxy_ns"] / _positive(denominators.get("MakespanProxy_ns", 0.0), 1.0)
    f_comm = terms["CommProxy"] / _positive(denominators.get("CommProxy", 0.0), 1.0)
    f_max_load = terms["MaxLoadProxy_ns"] / _positive(denominators.get("MaxLoadProxy_ns", 0.0), 1.0)
    f_load_imbalance = terms["LoadImbalanceProxy"] / _positive(denominators.get("LoadImbalanceProxy", 0.0), 1.0)
    f_peak_window = terms["PeakWindowEnergyProxy"] / _positive(denominators.get("PeakWindowEnergyProxy", 0.0), 1.0)
    f_peak_window_sigma = terms["PeakWindowSigmaProxy"] / _positive(denominators.get("PeakWindowSigmaProxy", 0.0), 1.0)
    f_neighbor_peak_window = (
        terms["NeighborPeakWindowEnergyProxy"]
        / _positive(denominators.get("NeighborPeakWindowEnergyProxy", 0.0), 1.0)
    )
    score = (
        weights.w_tmax * f_tmax
        + weights.w_sigma * f_sigma
        + weights.w_hot * f_hot
        + weights.w_makespan * f_makespan
        + weights.w_comm * f_comm
        + weights.w_max_load * f_max_load
        + weights.w_load_imbalance * f_load_imbalance
        + weights.w_peak_window * f_peak_window
        + weights.w_peak_window_sigma * f_peak_window_sigma
        + weights.w_neighbor_peak_window * f_neighbor_peak_window
    )
    return {
        "score": score,
        "Tmax_proxy": terms["Tmax_proxy"],
        "SigmaT_proxy": terms["SigmaT_proxy"],
        "HotCount_proxy": terms["HotCount_proxy"],
        "MakespanProxy_ns": terms["MakespanProxy_ns"],
        "CommProxy": terms["CommProxy"],
        "MaxLoadProxy_ns": terms["MaxLoadProxy_ns"],
        "LoadImbalanceProxy": terms["LoadImbalanceProxy"],
        "PeakWindowEnergyProxy": terms["PeakWindowEnergyProxy"],
        "PeakWindowSigmaProxy": terms["PeakWindowSigmaProxy"],
        "NeighborPeakWindowEnergyProxy": terms["NeighborPeakWindowEnergyProxy"],
        "f_tmax": f_tmax,
        "f_sigma": f_sigma,
        "f_hot": f_hot,
        "f_makespan": f_makespan,
        "f_comm": f_comm,
        "f_max_load": f_max_load,
        "f_load_imbalance": f_load_imbalance,
        "f_peak_window": f_peak_window,
        "f_peak_window_sigma": f_peak_window_sigma,
        "f_neighbor_peak_window": f_neighbor_peak_window,
        "weights": asdict(weights),
    }


def proxy_payload(
    graph: TaskGraph,
    original_assignment: dict[int, int],
    final_assignment: dict[int, int],
    task_power: dict[int, float],
    resistance_matrix: list[list[float]],
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
    objective_weights: TASObjectiveWeights,
    denominators: dict[str, float],
    baseline_hotspot_risk: list[float] | None = None,
) -> dict[str, Any]:
    original = tas_proxy_score(
        graph,
        original_assignment,
        task_power,
        resistance_matrix,
        proxy_config,
        schedule_config,
        objective_weights,
        denominators=denominators,
        baseline_hotspot_risk=baseline_hotspot_risk,
    )
    final = tas_proxy_score(
        graph,
        final_assignment,
        task_power,
        resistance_matrix,
        proxy_config,
        schedule_config,
        objective_weights,
        denominators=denominators,
        baseline_hotspot_risk=baseline_hotspot_risk,
    )
    return {
        "method": "thermal_sa_tas",
        "method_label": "Thermal-SA-TAS-Mapping",
        "not_exact_reproduction": True,
        "search_objective": (
            "TAS-inspired thermal simulated annealing with RC temperature proxy "
            "and DAG list-scheduling proxy"
        ),
        "forbidden_search_inputs": [
            "OMNeT++ candidate full simulation",
            "B-2 full composite cost",
            "congestion",
            "DVFS penalty",
            "PE plus optical communication energy",
            "SOA, laser, or MRR tuning energy",
        ],
        "denominators": denominators,
        "config": {
            "proxy": asdict(proxy_config),
            "schedule": asdict(schedule_config),
            "objective_weights": asdict(objective_weights),
        },
        "original": _strip_schedule(original),
        "thermal_sa_tas": _strip_schedule(final),
        "assignment": {str(tid): pe for tid, pe in sorted(final_assignment.items())},
    }


def baseline_hotspot_risk_from_temperatures(
    temperatures_K: list[float] | None,
    num_pes: int,
) -> list[float] | None:
    if not temperatures_K or len(temperatures_K) != num_pes:
        return None
    values = [float(value) for value in temperatures_K]
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 1e-12:
        return [0.0 for _ in values]
    return [(value - lo) / span for value in values]


def load_proxy_terms(
    graph: TaskGraph,
    assignment: dict[int, int],
    num_pes: int,
) -> dict[str, float]:
    loads = [0.0 for _ in range(num_pes)]
    for tid, pe in assignment.items():
        if 0 <= pe < num_pes:
            loads[pe] += max(float(graph.tasks[tid].compute_time_ns), 0.0)
    total = sum(loads)
    ideal = total / num_pes if num_pes > 0 else 0.0
    if ideal <= 1e-12:
        imbalance = 0.0
    else:
        imbalance = sum((load - ideal) ** 2 for load in loads) / num_pes / (ideal * ideal)
    return {
        "MaxLoadProxy_ns": max(loads) if loads else 0.0,
        "LoadImbalanceProxy": imbalance,
    }


def manhattan(pe_a: int, pe_b: int, cols: int) -> int:
    r1, c1 = divmod(pe_a, cols)
    r2, c2 = divmod(pe_b, cols)
    return abs(r1 - r2) + abs(c1 - c2)


def pe_closeness_to_center(rows: int, cols: int) -> list[float]:
    center_r = (rows - 1) / 2.0
    center_c = (cols - 1) / 2.0
    distances: list[float] = []
    for pe in range(rows * cols):
        r, c = divmod(pe, cols)
        distances.append(math.hypot(r - center_r, c - center_c))
    max_dist = max(distances) if distances else 1.0
    if max_dist <= 0.0:
        return [1.0 for _ in distances]
    return [1.0 - distance / max_dist for distance in distances]


def _normalized_risk(values: list[float] | None, expected: int) -> list[float]:
    if values is None or len(values) != expected:
        return [0.0 for _ in range(expected)]
    return [min(1.0, max(0.0, float(value))) for value in values]


def _strip_schedule(score: dict[str, Any]) -> dict[str, Any]:
    out = dict(score)
    out.pop("schedule", None)
    return out


def _positive(value: float, fallback: float) -> float:
    return value if value > 1e-12 else fallback
