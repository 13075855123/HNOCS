"""CLI runner for the Thermal-SA-TAS-Mapping baseline."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_EXP = _HERE.parent
_PROJ = _EXP.parent

for _d in (_HERE, _EXP, _PROJ):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from mapping.csv_writer import write_static_csv
from mapping.omnet_cost_model import SimParams
from mapping.task_graph import TaskGraph
from thermal_rc_ls_baseline.common import (
    BENCHMARKS,
    CostWeights,
    OmnetRunConfig,
    build_cost_model,
    build_omnet_evaluator,
    cost_from_metrics,
    evaluate_original_reference,
    extract_original_assignment,
    grouped_metrics,
    make_original_static_tasks_mappable,
    require_valid_scalars,
    validate_assignment,
    write_csv_rows,
    write_json,
)
from thermal_rc_ls_baseline.thermal_rc_proxy import (
    RCProxyConfig,
    aggregate_power,
    base_power_vector,
    calibrate_or_synthetic_R,
    power_vector_rows,
    resistance_matrix_rows,
    task_power_proxy,
)

from thermal_sa_tas_mapper import ThermalSATASMapper, ThermalSATASearchConfig
from thermal_sa_tas_proxy import (
    TASScheduleConfig,
    TASObjectiveWeights,
    baseline_hotspot_risk_from_temperatures,
    tas_proxy_score,
)


METHOD_DIR = "thermal_sa_tas"


PRESET_OVERRIDES: dict[str, dict[str, Any]] = {
    "v2_dynamic_thermal": {
        "init": "original",
        "thermal_mode": "dynamic_rc",
        "selection_mode": "thermal_lexicographic",
        "restarts": 3,
        "max_total_iter": 5000,
        "patience": 800,
        "center_cooling_penalty": 0.35,
        "neighborhood_heat_penalty": 0.08,
        "peak_window_ns": 5000.0,
        "baseline_hotspot_penalty": 0.0,
        "baseline_hotspot_neighbor_penalty": 0.0,
        "tas_w_tmax": 0.80,
        "tas_w_sigma": 0.18,
        "tas_w_hot": 0.02,
        "tas_w_makespan": 0.0,
        "tas_w_comm": 0.0,
        "tas_w_max_load": 0.0,
        "tas_w_load_imbalance": 0.0,
        "tas_w_peak_window": 0.0,
        "tas_w_peak_window_sigma": 0.0,
        "tas_w_neighbor_peak_window": 0.0,
    },
    "vopd_steady_sigma": {
        "init": "multi",
        "thermal_mode": "steady_rc",
        "selection_mode": "score",
        "restarts": 6,
        "max_total_iter": 7000,
        "patience": 1200,
        "center_cooling_penalty": 0.0,
        "neighborhood_heat_penalty": 0.0,
        "peak_window_ns": 5000.0,
        "baseline_hotspot_penalty": 0.0,
        "baseline_hotspot_neighbor_penalty": 0.0,
        "tas_w_tmax": 0.45,
        "tas_w_sigma": 0.30,
        "tas_w_hot": 0.02,
        "tas_w_makespan": 0.08,
        "tas_w_comm": 0.30,
        "tas_w_max_load": 0.04,
        "tas_w_load_imbalance": 0.02,
        "tas_w_peak_window": 0.04,
        "tas_w_peak_window_sigma": 0.02,
        "tas_w_neighbor_peak_window": 0.06,
        "comm_guard_ratio": 1.00,
        "makespan_guard_ratio": 1.05,
        "max_load_guard_ratio": 1.10,
        "load_imbalance_guard_ratio": 1.25,
        "sigma_guard_ratio": 1.0,
        "tmax_guard_delta_K": 0.0,
    },
    "hnn_dynamic_score": {
        "init": "multi",
        "thermal_mode": "dynamic_rc",
        "selection_mode": "score",
        "restarts": 8,
        "max_total_iter": 12000,
        "patience": 2000,
        "center_cooling_penalty": 0.35,
        "neighborhood_heat_penalty": 0.08,
        "peak_window_ns": 10000.0,
        "baseline_hotspot_penalty": 0.6,
        "baseline_hotspot_neighbor_penalty": 0.2,
        "tas_w_tmax": 0.55,
        "tas_w_sigma": 0.25,
        "tas_w_hot": 0.02,
        "tas_w_makespan": 0.10,
        "tas_w_comm": 0.08,
        "tas_w_max_load": 0.08,
        "tas_w_load_imbalance": 0.04,
        "tas_w_peak_window": 0.08,
        "tas_w_peak_window_sigma": 0.04,
        "tas_w_neighbor_peak_window": 0.08,
        "comm_guard_ratio": 1.05,
        "makespan_guard_ratio": 1.15,
        "max_load_guard_ratio": 1.05,
        "load_imbalance_guard_ratio": 1.10,
        "sigma_guard_ratio": 1.20,
        "tmax_guard_delta_K": 0.0,
    },
}

V3_INTEGRATED_PRESETS = {
    "gemm": "v2_dynamic_thermal",
    "mpeg4": "v2_dynamic_thermal",
    "vopd": "vopd_steady_sigma",
    "hnn": "hnn_dynamic_score",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        benchmarks = selected_benchmarks(args)
        params = SimParams(rows=args.rows, cols=args.cols)
        if params.num_pes != 16:
            raise ValueError("Thermal-SA-TAS is currently scoped to the 4x4 / 16 PE setup")

        baseline_temp_payload = load_baseline_temp_payload(args.baseline_temp_json)
        output_dir = Path(args.out)

        if args.dry_run:
            dry_run(
                benchmarks,
                params,
                args,
                output_dir,
            )
            return 0

        guard_output_path(
            _PROJ,
            output_dir,
            benchmarks,
            force=args.force,
            will_write_metrics=not args.proxy_only,
        )

        records: list[dict[str, Any]] = []
        for benchmark in benchmarks:
            run_args = args_with_preset(args, benchmark)
            (
                proxy_config,
                schedule_config,
                objective_weights,
                search_config,
                weights,
                omnet_config,
            ) = build_run_configs(run_args, params)
            csv_path = resolve_csv_path(benchmark)
            baseline_temp = baseline_temp_for_workload(baseline_temp_payload, benchmark)
            if args.proxy_only:
                record = run_proxy_only(
                    benchmark,
                    csv_path,
                    output_dir,
                    params,
                    proxy_config,
                    schedule_config,
                    objective_weights,
                    search_config,
                    run_args.resolved_preset,
                    baseline_temp if args.calibration == "auto" else None,
                )
            else:
                record = run_full_workload(
                    benchmark,
                    csv_path,
                    output_dir,
                    params,
                    weights,
                    omnet_config,
                    proxy_config,
                    schedule_config,
                    objective_weights,
                    search_config,
                    run_args.resolved_preset,
                    baseline_temp,
                    use_synthetic_calibration=args.calibration == "synthetic",
                )
            records.append(record)

        write_summaries(output_dir, records)
        print(f"\nWrote Thermal-SA-TAS results to {output_dir.resolve()}")
        return 0
    except Exception as exc:
        parser.exit(1, f"ERROR: {exc}\n")


def args_with_preset(args: argparse.Namespace, benchmark: str) -> argparse.Namespace:
    run_args = argparse.Namespace(**vars(args))
    preset = args.preset
    if preset == "v3_integrated":
        preset = V3_INTEGRATED_PRESETS.get(benchmark.lower(), "v2_dynamic_thermal")
    if preset != "none":
        overrides = PRESET_OVERRIDES.get(preset)
        if overrides is None:
            raise ValueError(f"unsupported preset: {preset}")
        for name, value in overrides.items():
            setattr(run_args, name, value)
    run_args.resolved_preset = preset
    return run_args


def build_run_configs(
    args: argparse.Namespace,
    params: SimParams,
) -> tuple[
    RCProxyConfig,
    TASScheduleConfig,
    TASObjectiveWeights,
    ThermalSATASearchConfig,
    CostWeights,
    OmnetRunConfig,
]:
    proxy_config = RCProxyConfig(
        rows=args.rows,
        cols=args.cols,
        Tambient=params.Tambient,
        T_hot=args.T_hot if args.T_hot is not None else params.Tthrottle,
        power_idle=args.power_idle,
        power_compute=args.power_compute,
        leakage_base_power=args.leakage_base_power,
        ridge_lambda=args.ridge_lambda,
        synthetic_self_R=args.synthetic_self_R,
        synthetic_decay=args.synthetic_decay,
    )
    schedule_config = TASScheduleConfig(
        comm_delay_per_byte_hop_ns=args.comm_delay_per_byte_hop_ns,
        use_critical_path_priority=not args.no_critical_path_priority,
        thermal_mode=args.thermal_mode,
        thermal_tau_ns=args.thermal_tau_ns,
        center_cooling_penalty_K_per_W=args.center_cooling_penalty,
        neighborhood_heat_penalty_K_per_W=args.neighborhood_heat_penalty,
        dynamic_power_mode=args.dynamic_power_mode,
        peak_window_ns=args.peak_window_ns,
        peak_window_neighbor_weight=args.peak_window_neighbor_weight,
        baseline_hotspot_penalty_K_per_W=args.baseline_hotspot_penalty,
        baseline_hotspot_neighbor_penalty_K_per_W=args.baseline_hotspot_neighbor_penalty,
    )
    objective_weights = TASObjectiveWeights(
        w_tmax=args.tas_w_tmax,
        w_sigma=args.tas_w_sigma,
        w_hot=args.tas_w_hot,
        w_makespan=args.tas_w_makespan,
        w_comm=args.tas_w_comm,
        w_max_load=args.tas_w_max_load,
        w_load_imbalance=args.tas_w_load_imbalance,
        w_peak_window=args.tas_w_peak_window,
        w_peak_window_sigma=args.tas_w_peak_window_sigma,
        w_neighbor_peak_window=args.tas_w_neighbor_peak_window,
    )
    search_config = ThermalSATASearchConfig(
        seed=args.seed,
        init_mode=args.init,
        init_temperature=args.init_temperature,
        final_temperature=args.final_temperature,
        alpha=args.alpha,
        iterations_per_temperature=args.iterations_per_temperature,
        max_total_iter=args.max_total_iter,
        restarts=args.restarts,
        no_improve_patience=args.patience,
        time_limit_s=args.time_limit,
        hot_pe_count=args.hot_pes,
        cool_pe_count=args.cool_pes,
        dependency_aware_rate=args.dependency_aware_rate,
        selection_mode=args.selection_mode,
        comm_guard_ratio=args.comm_guard_ratio,
        comm_guard_weight=args.comm_guard_weight,
        makespan_guard_ratio=args.makespan_guard_ratio,
        makespan_guard_weight=args.makespan_guard_weight,
        max_load_guard_ratio=args.max_load_guard_ratio,
        max_load_guard_weight=args.max_load_guard_weight,
        load_imbalance_guard_ratio=args.load_imbalance_guard_ratio,
        load_imbalance_guard_weight=args.load_imbalance_guard_weight,
        tmax_guard_delta_K=args.tmax_guard_delta_K,
        tmax_guard_weight=args.tmax_guard_weight,
        sigma_guard_ratio=args.sigma_guard_ratio,
        sigma_guard_weight=args.sigma_guard_weight,
    )
    weights = CostWeights(
        w_T=args.w_T,
        w_sigma=args.w_sigma,
        w_hot=args.w_hot,
        w_makespan=args.w_makespan,
        w_H=args.w_H,
        w_congestion=args.w_congestion,
        w_D=args.w_D,
        w_L=args.w_L,
        w_E=args.w_E,
    )
    omnet_config = OmnetRunConfig(
        omnet_bin=args.omnet_bin,
        omnet_ned_paths=args.omnet_ned_paths,
        omnet_workdir=args.omnet_workdir,
        omnet_ini=args.omnet_ini,
        omnet_base_config=args.omnet_base_config,
        omnetpp_root=args.omnetpp_root,
        omnet_timeout_s=args.omnet_timeout,
        verbose=args.verbose,
    )
    return proxy_config, schedule_config, objective_weights, search_config, weights, omnet_config


def run_proxy_only(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
    objective_weights: TASObjectiveWeights,
    search_config: ThermalSATASearchConfig,
    resolved_preset: str,
    baseline_temperature: list[float] | None,
) -> dict[str, Any]:
    start = time.perf_counter()
    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    validate_assignment(graph, original_assignment, params.num_pes)

    powers = task_power_proxy(graph, proxy_config)
    baseline_power = aggregate_power(original_assignment, powers, proxy_config)
    resistance_matrix, calibration = calibrate_or_synthetic_R(
        proxy_config,
        baseline_power,
        baseline_temperature,
    )
    baseline_hotspot_risk = baseline_hotspot_risk_from_temperatures(
        baseline_temperature,
        proxy_config.num_pes,
    )
    original_score = tas_proxy_score(
        graph,
        original_assignment,
        powers,
        resistance_matrix,
        proxy_config,
        schedule_config,
        objective_weights,
        baseline_hotspot_risk=baseline_hotspot_risk,
    )
    denominators = {
        "Tmax_proxy": float(original_score["Tmax_proxy"]),
        "SigmaT_proxy": float(original_score["SigmaT_proxy"]),
        "HotCount_proxy": float(original_score["HotCount_proxy"]),
        "MakespanProxy_ns": float(original_score["MakespanProxy_ns"]),
        "CommProxy": float(original_score["CommProxy"]),
        "MaxLoadProxy_ns": float(original_score["MaxLoadProxy_ns"]),
        "LoadImbalanceProxy": float(original_score["LoadImbalanceProxy"]),
        "PeakWindowEnergyProxy": float(original_score["PeakWindowEnergyProxy"]),
        "PeakWindowSigmaProxy": float(original_score["PeakWindowSigmaProxy"]),
        "NeighborPeakWindowEnergyProxy": float(original_score["NeighborPeakWindowEnergyProxy"]),
    }
    mapper = ThermalSATASMapper(
        graph,
        original_assignment,
        powers,
        resistance_matrix,
        proxy_config,
        schedule_config,
        objective_weights,
        search_config,
        denominators,
        baseline_hotspot_risk=baseline_hotspot_risk,
    )
    result = mapper.run()
    validate_assignment(graph, result.assignment, params.num_pes)
    result.proxy["calibration"] = calibration.as_dict()
    result.proxy["config"]["preset"] = resolved_preset
    result.proxy["baseline_temperature_vector_K"] = baseline_temperature or []
    result.proxy["baseline_hotspot_risk"] = baseline_hotspot_risk or []

    workload_dir = output_dir / benchmark
    original_dir = workload_dir / "original"
    tas_dir = workload_dir / METHOD_DIR
    original_dir.mkdir(parents=True, exist_ok=True)
    tas_dir.mkdir(parents=True, exist_ok=True)

    write_static_csv(
        graph,
        original_assignment,
        original_dir / "mapping.csv",
        comment="Original static mapping for Thermal-SA-TAS proxy-only check",
    )
    write_static_csv(
        graph,
        result.assignment,
        tas_dir / "mapping.csv",
        comment="Thermal-SA-TAS-Mapping; proxy-only output",
    )
    write_static_csv(
        graph,
        result.assignment,
        tas_dir / "remapped.csv",
        comment="Thermal-SA-TAS-Mapping remapped; proxy-only output",
    )
    write_method_artifacts(tas_dir, result, resistance_matrix)

    summary = proxy_summary_text(benchmark, result.proxy)
    (original_dir / "summary.txt").write_text(
        f"[{benchmark}] Original mapping written for Thermal-SA-TAS proxy-only check\n",
        encoding="utf-8",
    )
    (tas_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)

    return {
        "benchmark": benchmark,
        "mode": "proxy_only",
        "original_proxy_score": result.proxy["original"]["score"],
        "thermal_sa_tas_proxy_score": result.proxy[METHOD_DIR]["score"],
        "preset": resolved_preset,
        "iterations": result.iterations,
        "converged": result.converged,
        "elapsed_s": time.perf_counter() - start,
    }


def run_full_workload(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    final_weights: CostWeights,
    omnet_config: OmnetRunConfig,
    proxy_config: RCProxyConfig,
    schedule_config: TASScheduleConfig,
    objective_weights: TASObjectiveWeights,
    search_config: ThermalSATASearchConfig,
    resolved_preset: str,
    baseline_temperature_override: list[float] | None,
    use_synthetic_calibration: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    validate_assignment(graph, original_assignment, params.num_pes)

    evaluator = build_omnet_evaluator(omnet_config)
    cost_model = build_cost_model(graph, params, final_weights)

    if omnet_config.verbose:
        print(f"\n[{benchmark}] Original OMNeT++ simulation...")
    original_ref = evaluate_original_reference(
        graph,
        original_assignment,
        evaluator,
        cost_model,
        params,
        benchmark,
    )

    powers = task_power_proxy(graph, proxy_config)
    baseline_power = aggregate_power(original_assignment, powers, proxy_config)
    calibration_temperature = None
    if not use_synthetic_calibration:
        calibration_temperature = (
            baseline_temperature_override
            or original_ref.scalars.pe_max_temp_K
            or original_ref.scalars.pe_temps_final_K
        )
    resistance_matrix, calibration = calibrate_or_synthetic_R(
        proxy_config,
        baseline_power,
        calibration_temperature,
    )
    baseline_hotspot_risk = baseline_hotspot_risk_from_temperatures(
        calibration_temperature,
        proxy_config.num_pes,
    )
    original_score = tas_proxy_score(
        graph,
        original_assignment,
        powers,
        resistance_matrix,
        proxy_config,
        schedule_config,
        objective_weights,
        baseline_hotspot_risk=baseline_hotspot_risk,
    )
    denominators = {
        "Tmax_proxy": float(original_score["Tmax_proxy"]),
        "SigmaT_proxy": float(original_score["SigmaT_proxy"]),
        "HotCount_proxy": float(original_score["HotCount_proxy"]),
        "MakespanProxy_ns": float(original_score["MakespanProxy_ns"]),
        "CommProxy": float(original_score["CommProxy"]),
        "MaxLoadProxy_ns": float(original_score["MaxLoadProxy_ns"]),
        "LoadImbalanceProxy": float(original_score["LoadImbalanceProxy"]),
        "PeakWindowEnergyProxy": float(original_score["PeakWindowEnergyProxy"]),
        "PeakWindowSigmaProxy": float(original_score["PeakWindowSigmaProxy"]),
        "NeighborPeakWindowEnergyProxy": float(original_score["NeighborPeakWindowEnergyProxy"]),
    }

    mapper = ThermalSATASMapper(
        graph,
        original_assignment,
        powers,
        resistance_matrix,
        proxy_config,
        schedule_config,
        objective_weights,
        search_config,
        denominators,
        baseline_hotspot_risk=baseline_hotspot_risk,
    )
    result = mapper.run()
    validate_assignment(graph, result.assignment, params.num_pes)
    result.proxy["calibration"] = calibration.as_dict()
    result.proxy["config"]["preset"] = resolved_preset
    result.proxy["baseline_temperature_vector_K"] = calibration_temperature or []
    result.proxy["baseline_hotspot_risk"] = baseline_hotspot_risk or []

    if omnet_config.verbose:
        print(f"[{benchmark}] Thermal-SA-TAS final OMNeT++ simulation...")
    tas_scalars = evaluator.evaluate(graph, result.assignment)
    require_valid_scalars(benchmark, "Thermal-SA-TAS", tas_scalars)
    tas_metrics = grouped_metrics(
        graph,
        result.assignment,
        tas_scalars,
        cost_model,
        params,
        baseline_makespan_s=original_ref.scalars.makespan_s,
    )

    workload_dir = output_dir / benchmark
    original_dir = workload_dir / "original"
    tas_dir = workload_dir / METHOD_DIR
    original_dir.mkdir(parents=True, exist_ok=True)
    tas_dir.mkdir(parents=True, exist_ok=True)

    write_static_csv(
        graph,
        original_assignment,
        original_dir / "mapping.csv",
        comment="Original static mapping for Thermal-SA-TAS reference",
    )
    write_static_csv(
        graph,
        result.assignment,
        tas_dir / "mapping.csv",
        comment="Thermal-SA-TAS-Mapping",
    )
    write_static_csv(
        graph,
        result.assignment,
        tas_dir / "remapped.csv",
        comment="Thermal-SA-TAS-Mapping remapped",
    )
    write_method_artifacts(tas_dir, result, resistance_matrix)

    write_json(
        original_dir / "metrics.json",
        {
            "name": benchmark,
            "method": "original",
            "metrics": original_ref.metrics,
            "config": {
                "source_csv": str(csv_path),
                "final_evaluation_weights": asdict(final_weights),
                "cost_reference": asdict(original_ref.cost_reference),
            },
        },
    )
    write_json(
        tas_dir / "metrics.json",
        {
            "name": benchmark,
            "method": METHOD_DIR,
            "method_label": "Thermal-SA-TAS-Mapping",
            "metrics": tas_metrics,
            "proxy": result.proxy,
            "config": {
                "source_csv": str(csv_path),
                "rows": params.rows,
                "cols": params.cols,
                "num_pes": params.num_pes,
                "final_evaluation_weights": asdict(final_weights),
                "proxy_config": asdict(proxy_config),
                "schedule_config": asdict(schedule_config),
                "objective_weights": asdict(objective_weights),
                "search_config": asdict(search_config),
                "preset": resolved_preset,
                "cost_reference": asdict(original_ref.cost_reference),
                "calibration": calibration.as_dict(),
                "baseline_temperature_vector_K": calibration_temperature or [],
                "baseline_hotspot_risk": baseline_hotspot_risk or [],
                "not_exact_reproduction": True,
            },
        },
    )

    original_summary = f"[{benchmark}] Original cost={cost_from_metrics(original_ref.metrics):.4f}"
    tas_summary = full_summary_text(benchmark, original_ref.metrics, tas_metrics, result.proxy)
    (original_dir / "summary.txt").write_text(original_summary + "\n", encoding="utf-8")
    (tas_dir / "summary.txt").write_text(tas_summary + "\n", encoding="utf-8")
    print(tas_summary)

    return {
        "benchmark": benchmark,
        "mode": "full",
        "original_cost": cost_from_metrics(original_ref.metrics),
        "thermal_sa_tas_cost": cost_from_metrics(tas_metrics),
        "original_proxy_score": result.proxy["original"]["score"],
        "thermal_sa_tas_proxy_score": result.proxy[METHOD_DIR]["score"],
        "preset": resolved_preset,
        "iterations": result.iterations,
        "converged": result.converged,
        "elapsed_s": time.perf_counter() - start,
    }


def write_method_artifacts(
    tas_dir: Path,
    result,
    resistance_matrix: list[list[float]],
) -> None:
    write_json(tas_dir / "proxy.json", result.proxy)
    write_json(tas_dir / "proxy_score_breakdown.json", result.proxy)
    write_json(tas_dir / "history.json", result.history)
    write_csv_rows(tas_dir / "history.csv", result.history)
    write_csv_rows(tas_dir / "schedule_proxy.csv", result.schedule)
    write_csv_rows(tas_dir / "rc_matrix.csv", resistance_matrix_rows(resistance_matrix))
    final = result.proxy[METHOD_DIR]
    write_csv_rows(tas_dir / "power_vector.csv", power_vector_rows(final["power_W"], final["temperatures_K"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the TAS-inspired Thermal-SA-TAS-Mapping baseline"
    )
    parser.add_argument("--workload", choices=sorted(BENCHMARKS), help="Run one benchmark")
    parser.add_argument("--benchmarks", default="gemm,mpeg4,vopd,hnn")
    parser.add_argument("--csv", help="Path to one static task CSV")
    parser.add_argument("--out", default="out/thermal-sa-tas-v1")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--preset",
        choices=["none", "v2_dynamic_thermal", "vopd_steady_sigma", "hnn_dynamic_score", "v3_integrated"],
        default="none",
        help="Apply a named Thermal-SA-TAS parameter preset; v3_integrated dispatches per workload",
    )
    parser.add_argument("--init", choices=["original", "thermal_greedy", "comm_aware", "random_balanced", "multi"], default="original")
    parser.add_argument("--proxy-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")

    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--calibration", choices=["auto", "synthetic"], default="auto")
    parser.add_argument("--baseline-temp-json", help="Optional JSON list or workload-to-list baseline PE temperature vector")
    parser.add_argument("--T-hot", type=float, default=None)
    parser.add_argument("--power-idle", type=float, default=0.3)
    parser.add_argument("--power-compute", type=float, default=2.5)
    parser.add_argument("--leakage-base-power", type=float, default=0.3)
    parser.add_argument("--ridge-lambda", type=float, default=1e-3)
    parser.add_argument("--synthetic-self-R", type=float, default=2.5)
    parser.add_argument("--synthetic-decay", type=float, default=0.55)

    parser.add_argument("--comm-delay-per-byte-hop-ns", type=float, default=0.01)
    parser.add_argument("--no-critical-path-priority", action="store_true")
    parser.add_argument("--thermal-mode", choices=["steady_rc", "dynamic_rc"], default="dynamic_rc")
    parser.add_argument("--thermal-tau-ns", type=float, default=10000.0)
    parser.add_argument("--center-cooling-penalty", type=float, default=0.35)
    parser.add_argument("--neighborhood-heat-penalty", type=float, default=0.08)
    parser.add_argument("--dynamic-power-mode", choices=["compute_power", "task_power"], default="compute_power")
    parser.add_argument("--peak-window-ns", type=float, default=5000.0)
    parser.add_argument("--peak-window-neighbor-weight", type=float, default=0.25)
    parser.add_argument("--baseline-hotspot-penalty", type=float, default=0.0)
    parser.add_argument("--baseline-hotspot-neighbor-penalty", type=float, default=0.0)

    parser.add_argument("--tas-w-tmax", type=float, default=0.80)
    parser.add_argument("--tas-w-sigma", type=float, default=0.18)
    parser.add_argument("--tas-w-hot", type=float, default=0.02)
    parser.add_argument("--tas-w-makespan", type=float, default=0.0)
    parser.add_argument("--tas-w-comm", type=float, default=0.0)
    parser.add_argument("--tas-w-max-load", type=float, default=0.0)
    parser.add_argument("--tas-w-load-imbalance", type=float, default=0.0)
    parser.add_argument("--tas-w-peak-window", type=float, default=0.0)
    parser.add_argument("--tas-w-peak-window-sigma", type=float, default=0.0)
    parser.add_argument("--tas-w-neighbor-peak-window", type=float, default=0.0)

    parser.add_argument("--init-temperature", type=float, default=0.10)
    parser.add_argument("--final-temperature", type=float, default=1e-4)
    parser.add_argument("--alpha", type=float, default=0.95)
    parser.add_argument("--iterations-per-temperature", type=int, default=0)
    parser.add_argument("--max-total-iter", type=int, default=5000)
    parser.add_argument("--restarts", type=int, default=3)
    parser.add_argument("--patience", type=int, default=800)
    parser.add_argument("--time-limit", type=float, default=0.0)
    parser.add_argument("--hot-pes", type=int, default=4)
    parser.add_argument("--cool-pes", type=int, default=4)
    parser.add_argument("--dependency-aware-rate", type=float, default=0.15)
    parser.add_argument("--selection-mode", choices=["score", "thermal_lexicographic", "pareto_safe_thermal"], default="pareto_safe_thermal")
    parser.add_argument("--comm-guard-ratio", type=float, default=1.10)
    parser.add_argument("--comm-guard-weight", type=float, default=0.25)
    parser.add_argument("--makespan-guard-ratio", type=float, default=1.10)
    parser.add_argument("--makespan-guard-weight", type=float, default=0.20)
    parser.add_argument("--max-load-guard-ratio", type=float, default=1.10)
    parser.add_argument("--max-load-guard-weight", type=float, default=0.10)
    parser.add_argument("--load-imbalance-guard-ratio", type=float, default=1.25)
    parser.add_argument("--load-imbalance-guard-weight", type=float, default=0.05)
    parser.add_argument("--tmax-guard-delta-K", type=float, default=0.0)
    parser.add_argument("--tmax-guard-weight", type=float, default=0.10)
    parser.add_argument("--sigma-guard-ratio", type=float, default=1.0)
    parser.add_argument("--sigma-guard-weight", type=float, default=0.10)

    # Final OMNeT++ reporting weights only; not used by SA search.
    parser.add_argument("--w-T", type=float, default=1.0)
    parser.add_argument("--w-sigma", type=float, default=1.0)
    parser.add_argument("--w-hot", type=float, default=0.6)
    parser.add_argument("--w-makespan", type=float, default=1.2)
    parser.add_argument("--w-H", type=float, default=0.4)
    parser.add_argument("--w-congestion", type=float, default=0.7)
    parser.add_argument("--w-D", type=float, default=0.4)
    parser.add_argument("--w-L", type=float, default=0.2)
    parser.add_argument("--w-E", type=float, default=0.5)

    parser.add_argument("--omnet-bin", default="D:/HNOCS/libhnocs.exe")
    parser.add_argument("--omnet-ned-paths", default="D:/HNOCS/src;D:/HNOCS/examples/task_driven")
    parser.add_argument("--omnet-workdir", default="D:/HNOCS/examples/task_driven")
    parser.add_argument("--omnet-ini", default="D:/HNOCS/examples/task_driven/omnetpp.ini")
    parser.add_argument("--omnet-base-config", default="ONoCGeneral")
    parser.add_argument("--omnetpp-root", default="D:/omnetpp/omnetpp-6.3.0")
    parser.add_argument("--omnet-timeout", type=float, default=60.0)
    return parser


def selected_benchmarks(args: argparse.Namespace) -> list[str]:
    if args.csv:
        path = Path(args.csv)
        name = path.stem.replace("tasks_", "").replace("_static", "").lower()
        BENCHMARKS[name] = str(path)
        return [name]
    if args.workload:
        return [args.workload.lower()]
    names = [part.strip().lower() for part in args.benchmarks.split(",") if part.strip()]
    if not names:
        raise ValueError("no benchmarks selected")
    unknown = [name for name in names if name not in BENCHMARKS]
    if unknown:
        raise ValueError(f"unknown benchmarks: {unknown}")
    return names


def resolve_csv_path(benchmark: str) -> Path:
    path = Path(BENCHMARKS[benchmark])
    return path if path.is_absolute() else _PROJ / path


def load_baseline_temp_payload(path: str | None) -> Any:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def baseline_temp_for_workload(payload: Any, benchmark: str) -> list[float] | None:
    if payload is None:
        return None
    if isinstance(payload, list):
        return [float(value) for value in payload]
    if isinstance(payload, dict):
        values = payload.get(benchmark) or payload.get(benchmark.upper())
        if values is None:
            return None
        return [float(value) for value in values]
    raise ValueError("--baseline-temp-json must be a list or object")


def dry_run(
    benchmarks: list[str],
    params: SimParams,
    args: argparse.Namespace,
    output_dir: Path,
) -> None:
    print("Planned Thermal-SA-TAS baseline runs:")
    print(f"  output={output_dir.resolve()}")
    print(f"  mode={'proxy_only' if args.proxy_only else 'full'}")
    print(f"  rows={params.rows} cols={params.cols} num_pes={params.num_pes}")
    print(f"  requested_preset={args.preset}")
    print(f"  OMNeT++ runs={0 if args.proxy_only else len(benchmarks) * 2}")

    first_args = args_with_preset(args, benchmarks[0])
    _, _, _, _, _, omnet_config = build_run_configs(first_args, params)
    if not args.proxy_only:
        print("  path checks:")
        for label, path in [
            ("omnet_bin", omnet_config.omnet_bin),
            ("omnet_workdir", omnet_config.omnet_workdir),
            ("omnet_ini", omnet_config.omnet_ini),
            ("omnetpp_root", omnet_config.omnetpp_root),
        ]:
            print(f"    {label}: {Path(path).exists()}  {path}")
        for idx, path in enumerate(omnet_config.omnet_ned_paths.split(";")):
            item = path.strip()
            if item:
                print(f"    omnet_ned_paths[{idx}]: {Path(item).exists()}  {item}")
    for benchmark in benchmarks:
        run_args = args_with_preset(args, benchmark)
        proxy_config, schedule_config, objective_weights, search_config, _, _ = build_run_configs(run_args, params)
        csv_path = resolve_csv_path(benchmark)
        graph = TaskGraph.from_csv(csv_path)
        original_assignment = extract_original_assignment(graph)
        original_pes = sorted(set(original_assignment.values()))
        make_original_static_tasks_mappable(graph)
        print(
            f"  {benchmark}: preset={run_args.resolved_preset} csv={csv_path} tasks={graph.num_tasks} "
            f"gb={len(graph.gb_task_ids)} mappable={len(graph.mappable_task_ids)} "
            f"original_pe_set={original_pes}"
        )
        print(f"    schedule_config={json.dumps(asdict(schedule_config), sort_keys=True)}")
        print(f"    objective_weights={json.dumps(asdict(objective_weights), sort_keys=True)}")
        print(f"    search_config={json.dumps(asdict(search_config), sort_keys=True)}")
        print(f"    proxy_config={json.dumps(asdict(proxy_config), sort_keys=True)}")


def guard_output_path(
    project_root: Path,
    output_dir: Path,
    benchmarks: list[str],
    force: bool,
    will_write_metrics: bool,
) -> None:
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
        raise RuntimeError("refusing to write Thermal-SA-TAS output into any out/B-2* path")

    if force:
        return

    collisions: list[Path] = []
    common_files = ["mapping.csv", "remapped.csv", "summary.txt"]
    metric_files = ["metrics.json"] if will_write_metrics else []
    method_files = [
        "proxy.json",
        "proxy_score_breakdown.json",
        "history.json",
        "history.csv",
        "schedule_proxy.csv",
        "rc_matrix.csv",
        "power_vector.csv",
    ]
    for benchmark in benchmarks:
        for method in ("original", METHOD_DIR):
            for name in common_files + metric_files:
                candidate = output_dir / benchmark / method / name
                if candidate.exists():
                    collisions.append(candidate)
        for name in method_files:
            candidate = output_dir / benchmark / METHOD_DIR / name
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
            "refusing to overwrite existing Thermal-SA-TAS outputs. "
            "Choose a new --out directory or pass --force:\n"
            f"{details}{extra}"
        )


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def write_summaries(output_dir: Path, records: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(output_dir / "runs_summary.csv", records)
    write_json(output_dir / "runs_summary.json", records)
    write_json(
        output_dir / "aggregate_summary.json",
        {
            "method": METHOD_DIR,
            "method_label": "Thermal-SA-TAS-Mapping",
            "not_exact_reproduction": True,
            "records": records,
        },
    )


def proxy_summary_text(benchmark: str, proxy: dict[str, Any]) -> str:
    original = proxy["original"]
    tas = proxy[METHOD_DIR]
    return "\n".join([
        f"[{benchmark}] Thermal-SA-TAS proxy-only",
        f"  proxy score: {original['score']:.4f} -> {tas['score']:.4f}",
        f"  Tmax proxy:  {original['Tmax_proxy']:.3f}K -> {tas['Tmax_proxy']:.3f}K",
        f"  Sigma proxy: {original['SigmaT_proxy']:.3f}K -> {tas['SigmaT_proxy']:.3f}K",
        f"  Makespan:    {original['MakespanProxy_ns']:.1f}ns -> {tas['MakespanProxy_ns']:.1f}ns",
    ])


def full_summary_text(
    benchmark: str,
    original_metrics: dict[str, Any],
    tas_metrics: dict[str, Any],
    proxy: dict[str, Any],
) -> str:
    original_cost = cost_from_metrics(original_metrics)
    tas_cost = cost_from_metrics(tas_metrics)
    return "\n".join([
        f"[{benchmark}] Thermal-SA-TAS",
        f"  TR2 cost:    {original_cost:.4f} -> {tas_cost:.4f}",
        f"  proxy score: {proxy['original']['score']:.4f} -> {proxy[METHOD_DIR]['score']:.4f}",
        f"  T_max K:     {original_metrics['thermal']['T1_pe_peak_temp_K']:.3f} -> "
        f"{tas_metrics['thermal']['T1_pe_peak_temp_K']:.3f}",
        f"  sigma_T K:   {original_metrics['thermal']['T3_temp_std_K']:.3f} -> "
        f"{tas_metrics['thermal']['T3_temp_std_K']:.3f}",
        f"  makespan s:  {original_metrics['performance']['P1_makespan_s']:.6g} -> "
        f"{tas_metrics['performance']['P1_makespan_s']:.6g}",
    ])


if __name__ == "__main__":
    sys.exit(main())
