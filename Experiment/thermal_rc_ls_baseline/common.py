"""Shared helpers for the ThermalRC-LS baseline runner."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mapping.omnet_cost_model import CostReference, OmnetCostModel, OmnetScalars, SimParams
from mapping.omnet_evaluator import OmnetEvaluator
from mapping.task_graph import TaskGraph


PE_OPTICAL_ENERGY_KEY = "E7_pe_optical_comm_energy_J"
LEGACY_TOTAL_ENERGY_KEY = "E7_total_energy_J"

BENCHMARKS = {
    "gemm": "examples/task_driven/static/tasks_gemm_static.csv",
    "mpeg4": "examples/task_driven/static/tasks_mpeg4_static.csv",
    "vopd": "examples/task_driven/static/tasks_vopd_static.csv",
    "hnn": "examples/task_driven/static/tasks_hnn_static.csv",
}


@dataclass(frozen=True)
class CostWeights:
    """B-2-compatible final-evaluation weights.

    These weights are used only after ThermalRC-LS has selected one mapping.
    They are not used by the ThermalRC-LS search objective.
    """

    w_T: float = 1.0
    w_sigma: float = 1.0
    w_hot: float = 0.6
    w_makespan: float = 1.2
    w_H: float = 0.4
    w_congestion: float = 0.7
    w_D: float = 0.4
    w_L: float = 0.2
    w_E: float = 0.5


@dataclass(frozen=True)
class OmnetRunConfig:
    """OMNeT++ execution paths and runtime settings."""

    omnet_bin: str = "D:/HNOCS/libhnocs.exe"
    omnet_ned_paths: str = "D:/HNOCS/src;D:/HNOCS/examples/task_driven"
    omnet_workdir: str = "D:/HNOCS/examples/task_driven"
    omnet_ini: str = "D:/HNOCS/examples/task_driven/omnetpp.ini"
    omnet_base_config: str = "ONoCGeneral"
    omnetpp_root: str = "D:/omnetpp/omnetpp-6.3.0"
    omnet_timeout_s: float = 60.0
    verbose: bool = False


@dataclass
class OriginalReference:
    """Original mapping evaluation and normalized final-metrics reference."""

    assignment: dict[int, int]
    scalars: OmnetScalars
    cost_reference: CostReference
    metrics: dict[str, Any]


def extract_original_assignment(graph: TaskGraph) -> dict[int, int]:
    """Extract Original static mapping with the same rule as B-2."""
    return {
        tid: node.assigned_pe
        for tid, node in graph.tasks.items()
        if not node.is_gb_task and node.assigned_pe >= 0
    }


def make_original_static_tasks_mappable(graph: TaskGraph) -> None:
    """Turn static non-GB tasks into B-2-style mappable tasks."""
    for node in graph.tasks.values():
        if not node.is_gb_task and node.assigned_pe >= 0:
            node.assigned_pe = -2
    graph._topo_order = None


def validate_assignment(
    graph: TaskGraph,
    assignment: dict[int, int],
    num_pes: int,
) -> None:
    """Validate exact mappable-task coverage and PE range."""
    expected = set(graph.mappable_task_ids)
    actual = set(assignment)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ValueError(
            "assignment keys must exactly match graph.mappable_task_ids; "
            f"missing={missing}, extra={extra}"
        )
    bad = {
        tid: pe
        for tid, pe in assignment.items()
        if not isinstance(pe, int) or pe < 0 or pe >= num_pes
    }
    if bad:
        raise ValueError(f"assignment contains PE ids outside 0..{num_pes - 1}: {bad}")
    gb_tasks = [tid for tid in assignment if graph.tasks[tid].is_gb_task]
    if gb_tasks:
        raise ValueError(f"assignment must not contain GB tasks: {gb_tasks}")


def manhattan_hops(pe_a: int, pe_b: int, cols: int) -> int:
    if pe_a == pe_b:
        return 0
    r1, c1 = divmod(pe_a, cols)
    r2, c2 = divmod(pe_b, cols)
    return abs(r1 - r2) + abs(c1 - c2)


def analytical_comm_cost(
    graph: TaskGraph,
    assignment: dict[int, int],
    rows: int,
    cols: int,
) -> float:
    """B-2 analytical C1 communication cost: hops * producer output bytes."""
    del rows
    total = 0.0
    for tid in graph.mappable_task_ids:
        node = graph.tasks[tid]
        dst_pe = assignment.get(tid)
        if dst_pe is None:
            continue
        for pred_id in node.predecessor_set:
            pred = graph.tasks.get(pred_id)
            if pred is None or pred.is_gb_task:
                continue
            src_pe = assignment.get(pred_id)
            if src_pe is None:
                continue
            total += manhattan_hops(src_pe, dst_pe, cols) * pred.output_data_size
    return total


def build_omnet_evaluator(config: OmnetRunConfig) -> OmnetEvaluator:
    return OmnetEvaluator(
        omnet_bin=config.omnet_bin,
        ned_paths=config.omnet_ned_paths,
        work_dir=config.omnet_workdir,
        base_ini=config.omnet_ini,
        base_config=config.omnet_base_config,
        omnetpp_root=config.omnetpp_root,
        timeout_s=config.omnet_timeout_s,
        verbose=config.verbose,
    )


def build_cost_model(
    graph: TaskGraph,
    params: SimParams,
    weights: CostWeights,
    reference: CostReference | None = None,
) -> OmnetCostModel:
    return OmnetCostModel(
        graph,
        rows=params.rows,
        cols=params.cols,
        w_T=weights.w_T,
        w_H=weights.w_H,
        w_D=weights.w_D,
        w_L=weights.w_L,
        w_E=weights.w_E,
        w_sigma=weights.w_sigma,
        w_hot=weights.w_hot,
        w_makespan=weights.w_makespan,
        w_congestion=weights.w_congestion,
        Tambient=params.Tambient,
        T_throttle=params.Tthrottle,
        reference=reference,
    )


def evaluate_original_reference(
    graph: TaskGraph,
    assignment: dict[int, int],
    evaluator: OmnetEvaluator,
    cost_model: OmnetCostModel,
    params: SimParams,
    workload_name: str,
) -> OriginalReference:
    scalars = evaluator.evaluate(graph, assignment)
    require_valid_scalars(workload_name, "Original", scalars)
    reference = cost_model.make_reference(assignment, scalars)
    cost_model.reference = reference
    metrics = grouped_metrics(graph, assignment, scalars, cost_model, params)
    return OriginalReference(
        assignment=assignment,
        scalars=scalars,
        cost_reference=reference,
        metrics=metrics,
    )


def require_valid_scalars(workload_name: str, stage: str, scalars: OmnetScalars) -> None:
    if scalars.valid_for_cost:
        return
    reason = scalars.failure_reason or "unknown evaluator failure"
    raise RuntimeError(
        f"{workload_name} {stage} OMNeT++ run is invalid: {reason}. "
        f"makespan={scalars.makespan_s}, "
        f"T_max={scalars.pe_peak_temp_K}, "
        f"E_pe_opt={scalars.pe_optical_comm_energy_J}, "
        f"temperature_source={scalars.temperature_source}, "
        f"parsed_pe_count={scalars.parsed_pe_count}"
    )


def scalars_status(scalars: OmnetScalars) -> dict[str, Any]:
    return {
        "run_ok": scalars.run_ok,
        "valid_for_cost": scalars.valid_for_cost,
        "failure_reason": scalars.failure_reason,
        "temperature_source": scalars.temperature_source,
        "temperature_complete": scalars.temperature_complete,
        "parsed_pe_count": scalars.parsed_pe_count,
        "parsed_temp_timepoints": scalars.parsed_temp_timepoints,
    }


def grouped_metrics(
    graph: TaskGraph,
    assignment: dict[int, int],
    scalars: OmnetScalars,
    cost_model: OmnetCostModel,
    params: SimParams,
    baseline_makespan_s: float | None = None,
) -> dict[str, Any]:
    composite_cost = cost_model.total_cost(assignment, scalars)
    cost_terms = cost_model.cost_breakdown(assignment, scalars)
    c1 = analytical_comm_cost(graph, assignment, params.rows, params.cols)
    performance: dict[str, float] = {
        "P1_makespan_s": scalars.makespan_s,
        "P3_dvfs_penalty_pct": scalars.eta_dvfs_pct,
    }
    if baseline_makespan_s and baseline_makespan_s > 0 and scalars.makespan_s > 0:
        performance["P2_speedup"] = baseline_makespan_s / scalars.makespan_s

    return {
        "thermal": {
            "T1_pe_peak_temp_K": scalars.pe_peak_temp_K,
            "T3_temp_std_K": scalars.sigma_T_K,
            "T5_over_throttle_count": scalars.N_hot,
        },
        "performance": performance,
        "communication": {
            "C1_total_comm_cost": c1,
        },
        "optical": {
            "O1_budget_count": scalars.optical_budget_count,
            "O2_min_signal_margin_dB": scalars.optical_min_signal_margin_dB,
            "O3_min_snr_dB": scalars.optical_min_snr_dB,
            "O4_max_ber": scalars.optical_max_ber,
            "O5_max_temp_adjusted_loss_dB": scalars.optical_max_temp_adjusted_loss_dB,
            "O6_max_ring_detuning_nm": scalars.optical_max_ring_detuning_nm,
            "O7_max_path_tuning_power_mW": scalars.optical_max_path_tuning_power_mW,
            "O8_max_waveguide_crossing_loss_dB": scalars.optical_max_waveguide_crossing_loss_dB,
        },
        "energy": {
            "E1_pe_total_energy_J": scalars.pe_total_energy_J,
            "E4_soa_energy_J": scalars.soa_energy_J,
            "E5_tuning_energy_J": scalars.tuning_energy_J,
            "E6_laser_energy_J": scalars.laser_energy_J,
            PE_OPTICAL_ENERGY_KEY: scalars.pe_optical_comm_energy_J,
        },
        "tradeoff": {
            "TR2_composite_cost": composite_cost,
            "cost_terms": cost_terms,
        },
        "run_status": scalars_status(scalars),
    }


def baseline_temperature_factors(scalars: OmnetScalars) -> dict[int, float]:
    temps = scalars.pe_max_temp_K or scalars.pe_temps_final_K
    if not temps:
        return {}
    values = [float(t) for t in temps]
    mean_temp = sum(values) / len(values)
    if mean_temp <= 0:
        return {idx: 1.0 for idx in range(len(values))}
    variance = sum((temp - mean_temp) ** 2 for temp in values) / len(values)
    sigma = variance ** 0.5
    if sigma <= 1e-12:
        return {idx: 1.0 for idx in range(len(values))}
    return {
        idx: 1.0 + max(0.0, temp - mean_temp) / sigma
        for idx, temp in enumerate(values)
    }


def cost_from_metrics(metrics: dict[str, Any]) -> float:
    value = metrics.get("tradeoff", {}).get("TR2_composite_cost", float("nan"))
    return float(value) if isinstance(value, (int, float)) else float("nan")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def guard_output_path(
    project_root: Path,
    output_dir: Path,
    benchmarks: list[str],
    force: bool,
    will_write_metrics: bool,
) -> None:
    """Refuse protected paper result paths and accidental B-2 outputs."""
    resolved = output_dir.resolve()
    protected_dirs = (
        (project_root / "out" / "B-2-v3-g60-seed42").resolve(),
        (project_root / "out" / "B-2-v3-g60-seed43").resolve(),
        (project_root / "out" / "B-2-v3" / "B-2-v3-g60-seed42").resolve(),
        (project_root / "out" / "B-2-v3" / "B-2-v3-g60-seed43").resolve(),
    )
    for protected in protected_dirs:
        if resolved == protected or is_under(resolved, protected):
            raise RuntimeError(f"refusing to write into protected result directory: {protected}")

    try:
        rel_parts = resolved.relative_to((project_root / "out").resolve()).parts
    except ValueError:
        rel_parts = resolved.parts
    if any(part.startswith("B-2") for part in rel_parts):
        raise RuntimeError("refusing to write ThermalRC-LS output into any out/B-2* path")

    if force:
        return

    collisions: list[Path] = []
    common_files = ["mapping.csv", "remapped.csv", "summary.txt"]
    metric_files = ["metrics.json"] if will_write_metrics else []
    for benchmark in benchmarks:
        for method in ("original", "thermal_rc_ls", "thermal_only_rc_ls"):
            for name in common_files + metric_files:
                candidate = output_dir / benchmark / method / name
                if candidate.exists():
                    collisions.append(candidate)
        for name in ("proxy.json", "history.json", "rc_matrix.csv", "power_vector.csv"):
            candidate = output_dir / benchmark / "thermal_rc_ls" / name
            if candidate.exists():
                collisions.append(candidate)

    for name in ("runs_summary.csv", "runs_summary.json", "aggregate_summary.json"):
        candidate = output_dir / name
        if candidate.exists():
            collisions.append(candidate)

    if collisions:
        details = "\n".join(f"  {path.resolve()}" for path in collisions[:20])
        extra = "" if len(collisions) <= 20 else f"\n  ... and {len(collisions) - 20} more"
        raise RuntimeError(
            "refusing to overwrite existing ThermalRC-LS outputs. "
            "Choose a new --out directory or pass --force:\n"
            f"{details}{extra}"
        )


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def dataclass_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)
