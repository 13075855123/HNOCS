"""CLI runner for the ThermalGreedy / TAPP-inspired baseline."""

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

from common import (
    CostWeights,
    OmnetRunConfig,
    baseline_temperature_factors,
    build_cost_model,
    build_omnet_evaluator,
    cost_from_metrics,
    dataclass_dict,
    evaluate_original_reference,
    extract_original_assignment,
    grouped_metrics,
    guard_output_path,
    make_original_static_tasks_mappable,
    require_valid_scalars,
    validate_assignment,
    write_csv_rows,
    write_json,
)
from thermal_greedy_mapper import ThermalGreedyMapper
from thermal_proxy import ThermalProxyConfig


BENCHMARKS = {
    "gemm": "examples/task_driven/static/tasks_gemm_static.csv",
    "mpeg4": "examples/task_driven/static/tasks_mpeg4_static.csv",
    "vopd": "examples/task_driven/static/tasks_vopd_static.csv",
    "hnn": "examples/task_driven/static/tasks_hnn_static.csv",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        benchmarks = parse_benchmarks(args.benchmarks)
        params = SimParams(rows=args.rows, cols=args.cols)
        if params.num_pes != 16:
            raise ValueError("ThermalGreedy v1 is scoped to the current 4x4 / 16 PE setup")

        proxy_config = ThermalProxyConfig(
            rows=args.rows,
            cols=args.cols,
            alpha_sigma=args.alpha_sigma,
            alpha_center=args.alpha_center,
            alpha_temp_placement=args.alpha_temp_placement,
            beta_comm=args.beta_comm,
            heat_weight_mode=args.heat_weight_mode,
        )
        proxy_config.validate()
        if args.proxy_only and (
            args.heat_weight_mode == "baseline_temp"
            or args.alpha_temp_placement > 0
        ):
            raise ValueError(
                "--proxy-only cannot use baseline temperature factors; "
                "disable --alpha-temp-placement and use compute_time mode"
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

        output_dir = Path(args.out)
        if args.dry_run:
            dry_run(benchmarks, params, proxy_config, args, omnet_config, output_dir)
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
            csv_path = _PROJ / BENCHMARKS[benchmark]
            if args.proxy_only:
                record = run_proxy_only(
                    benchmark,
                    csv_path,
                    output_dir,
                    params,
                    proxy_config,
                    args.local_swap_passes,
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
                    args.local_swap_passes,
                )
            records.append(record)

        write_summaries(output_dir, records)
        print(f"\nWrote ThermalGreedy results to {output_dir.resolve()}")
        return 0
    except Exception as exc:
        parser.exit(1, f"ERROR: {exc}\n")


def run_proxy_only(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    proxy_config: ThermalProxyConfig,
    local_swap_passes: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    validate_assignment(graph, original_assignment, params.num_pes)

    mapper = ThermalGreedyMapper(
        graph,
        proxy_config,
        original_assignment=original_assignment,
        local_swap_passes=local_swap_passes,
    )
    result = mapper.run()
    validate_assignment(graph, result.assignment, params.num_pes)

    workload_dir = output_dir / benchmark
    original_dir = workload_dir / "original"
    thermal_dir = workload_dir / "thermal_greedy"
    original_dir.mkdir(parents=True, exist_ok=True)
    thermal_dir.mkdir(parents=True, exist_ok=True)

    write_static_csv(
        graph,
        original_assignment,
        original_dir / "mapping.csv",
        comment="Original static mapping for ThermalGreedy proxy-only check",
    )
    write_static_csv(
        graph,
        result.assignment,
        thermal_dir / "mapping.csv",
        comment="TAPP-inspired ThermalGreedy mapping; proxy-only output",
    )
    write_json(thermal_dir / "proxy.json", result.proxy)

    summary = proxy_summary_text(benchmark, result.proxy)
    (original_dir / "summary.txt").write_text(
        f"[{benchmark}] Original mapping written for proxy-only check\n",
        encoding="utf-8",
    )
    (thermal_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)

    elapsed_s = time.perf_counter() - start
    return {
        "benchmark": benchmark,
        "mode": "proxy_only",
        "original_proxy_score": result.proxy["original"]["score"],
        "thermal_greedy_proxy_score": result.proxy["thermal_greedy"]["score"],
        "original_max_load": result.proxy["original"]["max_load"],
        "thermal_greedy_max_load": result.proxy["thermal_greedy"]["max_load"],
        "original_std_load": result.proxy["original"]["std_load"],
        "thermal_greedy_std_load": result.proxy["thermal_greedy"]["std_load"],
        "elapsed_s": elapsed_s,
    }


def run_full_workload(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    weights: CostWeights,
    omnet_config: OmnetRunConfig,
    proxy_config: ThermalProxyConfig,
    local_swap_passes: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    validate_assignment(graph, original_assignment, params.num_pes)

    evaluator = build_omnet_evaluator(omnet_config)
    cost_model = build_cost_model(graph, params, weights)

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

    temp_factors = None
    if proxy_config.heat_weight_mode == "baseline_temp" or proxy_config.alpha_temp_placement > 0:
        temp_factors = baseline_temperature_factors(original_ref.scalars)

    mapper = ThermalGreedyMapper(
        graph,
        proxy_config,
        original_assignment=original_assignment,
        baseline_temperature_factor=temp_factors,
        local_swap_passes=local_swap_passes,
    )
    result = mapper.run()
    validate_assignment(graph, result.assignment, params.num_pes)

    if omnet_config.verbose:
        print(f"[{benchmark}] ThermalGreedy OMNeT++ simulation...")
    tg_scalars = evaluator.evaluate(graph, result.assignment)
    require_valid_scalars(benchmark, "ThermalGreedy", tg_scalars)
    tg_metrics = grouped_metrics(
        graph,
        result.assignment,
        tg_scalars,
        cost_model,
        params,
        baseline_makespan_s=original_ref.scalars.makespan_s,
    )

    workload_dir = output_dir / benchmark
    original_dir = workload_dir / "original"
    thermal_dir = workload_dir / "thermal_greedy"
    original_dir.mkdir(parents=True, exist_ok=True)
    thermal_dir.mkdir(parents=True, exist_ok=True)

    write_static_csv(
        graph,
        original_assignment,
        original_dir / "mapping.csv",
        comment="Original static mapping for ThermalGreedy reference",
    )
    write_static_csv(
        graph,
        result.assignment,
        thermal_dir / "mapping.csv",
        comment="TAPP-inspired ThermalGreedy mapping",
    )
    write_json(thermal_dir / "proxy.json", result.proxy)

    original_payload = {
        "name": benchmark,
        "method": "original",
        "metrics": original_ref.metrics,
        "config": {
            "source_csv": str(csv_path),
            "weights": dataclass_dict(weights),
            "cost_reference": asdict(original_ref.cost_reference),
        },
    }
    thermal_payload = {
        "name": benchmark,
        "method": "thermal_greedy",
        "method_label": "TAPP-inspired ThermalGreedy",
        "metrics": tg_metrics,
        "proxy": result.proxy,
        "config": {
            "source_csv": str(csv_path),
            "rows": params.rows,
            "cols": params.cols,
            "num_pes": params.num_pes,
            "weights": dataclass_dict(weights),
            "proxy_config": asdict(proxy_config),
            "local_swap_passes": local_swap_passes,
            "cost_reference": asdict(original_ref.cost_reference),
            "baseline_temperature_factor": temp_factors,
            "not_exact_reproduction": True,
        },
    }
    write_json(original_dir / "metrics.json", original_payload)
    write_json(thermal_dir / "metrics.json", thermal_payload)

    original_summary = f"[{benchmark}] Original cost={cost_from_metrics(original_ref.metrics):.4f}"
    thermal_summary = full_summary_text(benchmark, original_ref.metrics, tg_metrics, result.proxy)
    (original_dir / "summary.txt").write_text(original_summary + "\n", encoding="utf-8")
    (thermal_dir / "summary.txt").write_text(thermal_summary + "\n", encoding="utf-8")
    print(thermal_summary)

    elapsed_s = time.perf_counter() - start
    return {
        "benchmark": benchmark,
        "mode": "full",
        "original_cost": cost_from_metrics(original_ref.metrics),
        "thermal_greedy_cost": cost_from_metrics(tg_metrics),
        "original_proxy_score": result.proxy["original"]["score"],
        "thermal_greedy_proxy_score": result.proxy["thermal_greedy"]["score"],
        "elapsed_s": elapsed_s,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the TAPP-inspired ThermalGreedy baseline"
    )
    parser.add_argument(
        "--benchmarks",
        default="gemm,mpeg4,vopd,hnn",
        help="Comma-separated benchmark names: gemm,mpeg4,vopd,hnn",
    )
    parser.add_argument("--out", default="out/thermal-greedy-baseline-v1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--proxy-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")

    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--alpha-sigma", type=float, default=0.5)
    parser.add_argument("--alpha-center", type=float, default=0.1)
    parser.add_argument("--alpha-temp-placement", type=float, default=0.0)
    parser.add_argument("--beta-comm", type=float, default=0.05)
    parser.add_argument("--local-swap-passes", type=int, default=2)
    parser.add_argument(
        "--heat-weight-mode",
        choices=["compute_time", "baseline_temp"],
        default="compute_time",
    )

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


def parse_benchmarks(value: str) -> list[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise ValueError("no benchmarks selected")
    unknown = [name for name in names if name not in BENCHMARKS]
    if unknown:
        raise ValueError(f"unknown benchmarks: {unknown}")
    return names


def dry_run(
    benchmarks: list[str],
    params: SimParams,
    proxy_config: ThermalProxyConfig,
    args: argparse.Namespace,
    omnet_config: OmnetRunConfig,
    output_dir: Path,
) -> None:
    print("Planned ThermalGreedy baseline runs:")
    print(f"  output={output_dir.resolve()}")
    print(f"  mode={'proxy_only' if args.proxy_only else 'full'}")
    print(f"  rows={params.rows} cols={params.cols} num_pes={params.num_pes}")
    print(f"  proxy_config={json.dumps(asdict(proxy_config), sort_keys=True)}")
    print(f"  local_swap_passes={args.local_swap_passes}")
    print(f"  OMNeT++ runs={0 if args.proxy_only else len(benchmarks) * 2}")
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
        csv_path = _PROJ / BENCHMARKS[benchmark]
        graph = TaskGraph.from_csv(csv_path)
        original_assignment = extract_original_assignment(graph)
        original_pes = sorted(set(original_assignment.values()))
        make_original_static_tasks_mappable(graph)
        print(
            f"  {benchmark}: csv={csv_path} tasks={graph.num_tasks} "
            f"gb={len(graph.gb_task_ids)} mappable={len(graph.mappable_task_ids)} "
            f"original_pe_set={original_pes}"
        )


def write_summaries(output_dir: Path, records: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(output_dir / "runs_summary.csv", records)
    write_json(output_dir / "runs_summary.json", records)
    aggregate = {
        "method": "thermal_greedy",
        "method_label": "TAPP-inspired ThermalGreedy",
        "records": records,
    }
    write_json(output_dir / "aggregate_summary.json", aggregate)


def proxy_summary_text(benchmark: str, proxy: dict[str, Any]) -> str:
    original = proxy["original"]
    thermal = proxy["thermal_greedy"]
    return "\n".join([
        f"[{benchmark}] ThermalGreedy proxy-only",
        f"  proxy score: {original['score']:.4f} -> {thermal['score']:.4f}",
        f"  max load:    {original['max_load']:.1f} -> {thermal['max_load']:.1f}",
        f"  std load:    {original['std_load']:.1f} -> {thermal['std_load']:.1f}",
        f"  comm proxy:  {original['raw_comm_cost']:.1f} -> {thermal['raw_comm_cost']:.1f}",
    ])


def full_summary_text(
    benchmark: str,
    original_metrics: dict[str, Any],
    thermal_metrics: dict[str, Any],
    proxy: dict[str, Any],
) -> str:
    original_cost = cost_from_metrics(original_metrics)
    thermal_cost = cost_from_metrics(thermal_metrics)
    return "\n".join([
        f"[{benchmark}] ThermalGreedy",
        f"  TR2 cost:    {original_cost:.4f} -> {thermal_cost:.4f}",
        f"  proxy score: {proxy['original']['score']:.4f} -> {proxy['thermal_greedy']['score']:.4f}",
        f"  T_max K:     {original_metrics['thermal']['T1_pe_peak_temp_K']:.3f} -> "
        f"{thermal_metrics['thermal']['T1_pe_peak_temp_K']:.3f}",
        f"  sigma_T K:   {original_metrics['thermal']['T3_temp_std_K']:.3f} -> "
        f"{thermal_metrics['thermal']['T3_temp_std_K']:.3f}",
        f"  makespan s:  {original_metrics['performance']['P1_makespan_s']:.6g} -> "
        f"{thermal_metrics['performance']['P1_makespan_s']:.6g}",
    ])


if __name__ == "__main__":
    sys.exit(main())
