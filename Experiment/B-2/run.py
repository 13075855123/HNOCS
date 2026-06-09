"""
B-2 CLI — run genetic algorithm thermal-aware mapping on benchmarks.

Usage:
    python Experiment/B-2/run.py --csv tasks_gemm_static.csv
    python Experiment/B-2/run.py --all
    python Experiment/B-2/run.py --all --verbose -o out/B-2/
    python Experiment/B-2/run.py --all --workers 8 --generations 30
    python Experiment/B-2/run.py --all --workers 8 --seeds 42,43,44 -o out/B-2-seeds
    python Experiment/B-2/run.py --all --workers 8 --credibility -o out/B-2-credibility

Fitness evaluation runs OMNeT++ for each GA individual.
Output per benchmark: {name}_remapped.csv, {name}_metrics.json,
{name}_history.json, {name}_summary.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path
from statistics import mean, stdev

_HERE = Path(__file__).resolve().parent          # .../Experiment/B-2
_EXP = _HERE.parent                              # .../Experiment
_PROJ = _EXP.parent                              # .../HNOCS

for _d in (_PROJ, _HERE, _EXP):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from mapping.task_graph import TaskGraph
from mapping.omnet_cost_model import OmnetCostModel, SimParams
from mapping.omnet_evaluator import OmnetEvaluator
from mapping.csv_writer import write_static_csv
from ga_mapper import GAMapper, GAConfig

BENCHMARKS = {
    "GEMM":   "examples/task_driven/static/tasks_gemm_static.csv",
    "MPEG4":  "examples/task_driven/static/tasks_mpeg4_static.csv",
    "VOPD":   "examples/task_driven/static/tasks_vopd_static.csv",
    "HNN":    "examples/task_driven/static/tasks_hnn_static.csv",
}

DEFAULT_SEEDS = [42, 43, 44]
DEFAULT_LONG_BENCHMARKS = {"GEMM", "VOPD", "HNN"}


def _extract_baseline(graph: TaskGraph) -> dict[int, int]:
    return {
        tid: node.assigned_pe
        for tid, node in graph.tasks.items()
        if not node.is_gb_task and node.assigned_pe >= 0
    }


def _make_mappable(graph: TaskGraph) -> None:
    for node in graph.tasks.values():
        if not node.is_gb_task and node.assigned_pe >= 0:
            node.assigned_pe = -2
    graph._topo_order = None


def _benchmark_name(csv_path: str) -> str:
    return Path(csv_path).stem.replace("tasks_", "").replace("_static", "")


def _benchmark_key(csv_path: str) -> str:
    return _benchmark_name(csv_path).upper()


def _parse_int_list(value: str | None, option_name: str) -> list[int]:
    if value is None or not value.strip():
        return []
    out: list[int] = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            out.append(int(item))
        except ValueError as exc:
            raise ValueError(f"{option_name} contains a non-integer value: {item}") from exc
    if not out:
        raise ValueError(f"{option_name} did not contain any integer values")
    return out


def _parse_benchmark_set(value: str | None) -> set[str]:
    if value is None or not value.strip():
        return set(DEFAULT_LONG_BENCHMARKS)
    return {part.strip().upper() for part in value.split(",") if part.strip()}


def _safe_pct(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return (after / before - 1.0) * 100.0


def _safe_stdev(values: list[float]) -> float:
    return stdev(values) if len(values) > 1 else 0.0


def _metric(full: dict, side: str, section: str, key: str) -> float:
    value = full.get(side, {}).get(section, {}).get(key, 0.0)
    return value if isinstance(value, (int, float)) else 0.0


def _result_record(full: dict, seed: int | None, generations: int, run_type: str) -> dict:
    """Flatten one metrics.json payload for cross-seed CSV/JSON summaries."""
    bl_cost = _metric(full, "baseline", "tradeoff", "TR2_composite_cost")
    b2_cost = _metric(full, "b2", "tradeoff", "TR2_composite_cost")
    bl_t = _metric(full, "baseline", "thermal", "T1_pe_peak_temp_K") - 273.15
    b2_t = _metric(full, "b2", "thermal", "T1_pe_peak_temp_K") - 273.15
    bl_sigma = _metric(full, "baseline", "thermal", "T3_temp_std_K")
    b2_sigma = _metric(full, "b2", "thermal", "T3_temp_std_K")
    bl_hot = _metric(full, "baseline", "thermal", "T5_over_throttle_count")
    b2_hot = _metric(full, "b2", "thermal", "T5_over_throttle_count")
    bl_ms = _metric(full, "baseline", "performance", "P1_makespan_s") * 1e6
    b2_ms = _metric(full, "b2", "performance", "P1_makespan_s") * 1e6
    bl_comm = _metric(full, "baseline", "communication", "C1_total_comm_cost")
    b2_comm = _metric(full, "b2", "communication", "C1_total_comm_cost")
    bl_energy = _metric(full, "baseline", "energy", "E7_total_energy_J") * 1e3
    b2_energy = _metric(full, "b2", "energy", "E7_total_energy_J") * 1e3

    return {
        "benchmark": str(full.get("name", "")).upper(),
        "seed": "" if seed is None else seed,
        "run_type": run_type,
        "configured_generations": generations,
        "actual_generations": full.get("b2_generations", 0),
        "converged": bool(full.get("b2_converged", False)),
        "elapsed_min": float(full.get("b2_elapsed_s", 0.0)) / 60.0,
        "cost_baseline": bl_cost,
        "cost_b2": b2_cost,
        "cost_delta_pct": _safe_pct(bl_cost, b2_cost),
        "tmax_baseline_C": bl_t,
        "tmax_b2_C": b2_t,
        "tmax_delta_C": b2_t - bl_t,
        "sigma_baseline_K": bl_sigma,
        "sigma_b2_K": b2_sigma,
        "sigma_delta_pct": _safe_pct(bl_sigma, b2_sigma),
        "hot_baseline": bl_hot,
        "hot_b2": b2_hot,
        "makespan_baseline_us": bl_ms,
        "makespan_b2_us": b2_ms,
        "makespan_delta_pct": _safe_pct(bl_ms, b2_ms),
        "comm_baseline": bl_comm,
        "comm_b2": b2_comm,
        "comm_delta_pct": _safe_pct(bl_comm, b2_comm),
        "energy_baseline_mJ": bl_energy,
        "energy_b2_mJ": b2_energy,
        "energy_delta_pct": _safe_pct(bl_energy, b2_energy),
    }


def _write_run_summaries(output_dir: str, records: list[dict]) -> None:
    """Write per-run and grouped mean/std summaries for multi-run experiments."""
    if not records:
        return

    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    fieldnames = list(records[0].keys())
    with open(od / "runs_summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    grouped: dict[tuple[str, str, int], list[dict]] = {}
    for rec in records:
        key = (rec["benchmark"], rec["run_type"], int(rec["configured_generations"]))
        grouped.setdefault(key, []).append(rec)

    aggregate_rows: list[dict] = []
    numeric_fields = [
        "cost_delta_pct", "tmax_delta_C", "sigma_delta_pct",
        "makespan_delta_pct", "comm_delta_pct", "energy_delta_pct",
        "cost_b2", "tmax_b2_C", "sigma_b2_K", "makespan_b2_us",
        "comm_b2", "energy_b2_mJ", "elapsed_min",
    ]
    for (benchmark, run_type, generations), group in sorted(grouped.items()):
        row: dict[str, object] = {
            "benchmark": benchmark,
            "run_type": run_type,
            "configured_generations": generations,
            "n": len(group),
            "seeds": ",".join(str(g["seed"]) for g in group),
            "converged_count": sum(1 for g in group if g["converged"]),
        }
        for field in numeric_fields:
            values = [
                float(g[field])
                for g in group
                if isinstance(g.get(field), (int, float)) and math.isfinite(float(g[field]))
            ]
            row[f"{field}_mean"] = mean(values) if values else ""
            row[f"{field}_std"] = _safe_stdev(values) if values else ""
        aggregate_rows.append(row)

    with open(od / "aggregate_summary.json", "w", encoding="utf-8") as f:
        json.dump(aggregate_rows, f, indent=2)

    if aggregate_rows:
        with open(od / "aggregate_summary.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(aggregate_rows[0].keys()))
            writer.writeheader()
            writer.writerows(aggregate_rows)


def run_benchmark(
    csv_path: str,
    output_dir: str,
    params: SimParams | None = None,
    config: GAConfig | None = None,
    seed_assignment: dict[int, int] | None = None,
    verbose: bool = False,
) -> dict:
    """Run B-2 GA on one benchmark, compare with baseline."""
    if params is None:
        params = SimParams()
    if config is None:
        config = GAConfig()

    name = _benchmark_name(csv_path)
    t_start = time.perf_counter()

    # 1. Load
    graph = TaskGraph.from_csv(csv_path)
    baseline_asgn = _extract_baseline(graph)
    _make_mappable(graph)

    # 2. Baseline OMNeT++ simulation
    if verbose:
        print(f"\n[{name}] Baseline OMNeT++ simulation...")
    evaluator = OmnetEvaluator(
        omnet_bin=config.omnet_bin,
        ned_paths=config.omnet_ned_paths,
        work_dir=config.omnet_work_dir,
        base_ini=config.omnet_base_ini,
        base_config=config.omnet_base_config,
        omnetpp_root=config.omnetpp_root,
        timeout_s=config.omnet_timeout_s,
        verbose=verbose,
    )
    cm_omnet = OmnetCostModel(
        graph,
        w_T=config.w_T, w_H=config.w_H, w_D=config.w_D, w_L=config.w_L,
        w_E=config.w_E, w_sigma=config.w_sigma, w_hot=config.w_hot,
        w_makespan=config.w_makespan, w_congestion=config.w_congestion,
        Tambient=params.Tambient, T_throttle=params.Tthrottle,
    )
    bl_scalars = evaluator.evaluate(graph, baseline_asgn)
    cost_reference = cm_omnet.make_reference(baseline_asgn, bl_scalars)
    config.cost_reference = cost_reference
    cm_omnet.reference = cost_reference
    bl_composite = cm_omnet.total_cost(baseline_asgn, bl_scalars)
    bl_cost_terms = cm_omnet.cost_breakdown(baseline_asgn, bl_scalars)
    bl_c1 = _analytical_comm_cost(graph, baseline_asgn, params.rows, params.cols)
    baseline_metrics = {
        "thermal": {
            "T1_pe_peak_temp_K": bl_scalars.pe_peak_temp_K,
            "T3_temp_std_K": bl_scalars.sigma_T_K,
            "T5_over_throttle_count": bl_scalars.N_hot,
        },
        "performance": {
            "P1_makespan_s": bl_scalars.makespan_s,
            "P3_dvfs_penalty_pct": bl_scalars.eta_dvfs_pct,
        },
        "communication": {"C1_total_comm_cost": bl_c1},
        "energy": {
            "E1_pe_total_energy_J": bl_scalars.pe_total_energy_J,
            "E4_soa_energy_J": bl_scalars.soa_energy_J,
            "E5_tuning_energy_J": bl_scalars.tuning_energy_J,
            "E6_laser_energy_J": bl_scalars.laser_energy_J,
            "E7_total_energy_J": bl_scalars.total_energy_J,
        },
        "tradeoff": {
            "TR2_composite_cost": bl_composite,
            "cost_terms": bl_cost_terms,
        },
    }

    # 3. B-2 GA optimization
    if verbose:
        print(f"[{name}] B-2 GA optimization "
              f"(pop={config.population_size}, gen={config.num_generations})...")
    ga = GAMapper(graph, params, config, verbose=verbose)
    result = ga.run(seed_assignment=seed_assignment)

    # 4. Final OMNeT++ evaluation of best mapping
    if verbose:
        print(f"[{name}] B-2 final OMNeT++ evaluation...")
    b2_scalars = evaluator.evaluate(graph, result.best_assignment)
    b2_composite = cm_omnet.total_cost(result.best_assignment, b2_scalars)
    b2_cost_terms = cm_omnet.cost_breakdown(result.best_assignment, b2_scalars)
    b2_c1 = _analytical_comm_cost(graph, result.best_assignment, params.rows, params.cols)
    b2_metrics = {
        "thermal": {
            "T1_pe_peak_temp_K": b2_scalars.pe_peak_temp_K,
            "T3_temp_std_K": b2_scalars.sigma_T_K,
            "T5_over_throttle_count": b2_scalars.N_hot,
        },
        "performance": {
            "P1_makespan_s": b2_scalars.makespan_s,
            "P3_dvfs_penalty_pct": b2_scalars.eta_dvfs_pct,
        },
        "communication": {"C1_total_comm_cost": b2_c1},
        "energy": {
            "E1_pe_total_energy_J": b2_scalars.pe_total_energy_J,
            "E4_soa_energy_J": b2_scalars.soa_energy_J,
            "E5_tuning_energy_J": b2_scalars.tuning_energy_J,
            "E6_laser_energy_J": b2_scalars.laser_energy_J,
            "E7_total_energy_J": b2_scalars.total_energy_J,
        },
        "tradeoff": {
            "TR2_composite_cost": b2_composite,
            "cost_terms": b2_cost_terms,
        },
    }

    # 5. Speedup
    bl_makespan = baseline_metrics["performance"]["P1_makespan_s"]
    b2_makespan = b2_metrics["performance"]["P1_makespan_s"]
    if bl_makespan > 0 and b2_makespan > 0:
        b2_metrics["performance"]["P2_speedup"] = bl_makespan / b2_makespan

    baseline_metrics["tradeoff"]["TR2_composite_cost"] = bl_composite
    b2_metrics["tradeoff"]["TR2_composite_cost"] = b2_composite

    # 6. Write outputs
    od = Path(output_dir) / name
    od.mkdir(parents=True, exist_ok=True)

    write_static_csv(
        graph, result.best_assignment,
        od / "remapped.csv",
        comment=f"B-2 GA remapped (gen={result.num_generations}, "
                f"converged={result.converged})",
    )

    with open(od / "history.json", "w", encoding="utf-8") as f:
        json.dump(result.generation_history, f, indent=2)

    full = {
        "name": name,
        "baseline": baseline_metrics,
        "b2": b2_metrics,
        "b2_generations": result.num_generations,
        "b2_converged": result.converged,
        "b2_elapsed_s": result.elapsed_time_s,
        "b2_best_fitness": result.best_fitness,
        "config": {
            "population_size": config.population_size,
            "num_generations": config.num_generations,
            "crossover_rate": config.crossover_rate,
            "mutation_rate": config.mutation_rate,
            "w_T": config.w_T,
            "w_sigma": config.w_sigma,
            "w_hot": config.w_hot,
            "w_makespan": config.w_makespan,
            "w_H": config.w_H,
            "w_congestion": config.w_congestion,
            "w_D": config.w_D,
            "w_L": config.w_L,
            "w_E": config.w_E,
            "w_peak": config.w_peak,
            "seed": config.seed,
            "fitness": "baseline_normalized_v2",
            "cost_reference": cost_reference.__dict__,
        },
    }
    with open(od / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(full, f, indent=2, default=str)

    elapsed = time.perf_counter() - t_start
    lines = [_summary_text(name, full, elapsed)]
    with open(od / "summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(lines[0])
    return full


def _analytical_comm_cost(
    graph: TaskGraph, assignment: dict[int, int], rows: int, cols: int,
) -> float:
    hops_cache: dict[tuple[int, int], int] = {}

    def _hops(a: int, b: int) -> int:
        if a == b:
            return 0
        k = (a, b) if a < b else (b, a)
        if k not in hops_cache:
            r1, c1 = divmod(a, cols)
            r2, c2 = divmod(b, cols)
            hops_cache[k] = abs(r1 - r2) + abs(c1 - c2)
        return hops_cache[k]

    total = 0.0
    for tid in graph.mappable_task_ids:
        node = graph.tasks[tid]
        for pred_id in node.predecessor_set:
            pn = graph.tasks.get(pred_id)
            if pn is None or pn.is_gb_task:
                continue
            pa = assignment.get(pred_id)
            ta = assignment.get(tid)
            if pa is not None and ta is not None:
                total += _hops(pa, ta) * pn.output_data_size
    return total


def _summary_text(name: str, full: dict, elapsed: float) -> str:
    bl = full["baseline"]
    b2 = full["b2"]

    def _k(d, *keys):
        for k in keys:
            d = d.get(k, {})
        return d

    def _f(d, *keys):
        v = _k(d, *keys)
        return v if isinstance(v, (int, float)) else 0

    bl_t1 = _f(bl, "thermal", "T1_pe_peak_temp_K") - 273.15
    b2_t1 = _f(b2, "thermal", "T1_pe_peak_temp_K") - 273.15
    bl_t3 = _f(bl, "thermal", "T3_temp_std_K")
    b2_t3 = _f(b2, "thermal", "T3_temp_std_K")
    bl_t5 = _f(bl, "thermal", "T5_over_throttle_count")
    b2_t5 = _f(b2, "thermal", "T5_over_throttle_count")
    bl_p1 = _f(bl, "performance", "P1_makespan_s") * 1e6
    b2_p1 = _f(b2, "performance", "P1_makespan_s") * 1e6
    bl_eta = _f(bl, "performance", "P3_dvfs_penalty_pct")
    b2_eta = _f(b2, "performance", "P3_dvfs_penalty_pct")
    bl_c1 = _f(bl, "communication", "C1_total_comm_cost")
    b2_c1 = _f(b2, "communication", "C1_total_comm_cost")
    bl_e7 = _f(bl, "energy", "E7_total_energy_J") * 1e3
    b2_e7 = _f(b2, "energy", "E7_total_energy_J") * 1e3

    return "\n".join([
        f"[{name}] gen={full['b2_generations']} conv={full['b2_converged']} "
        f"elapsed={elapsed:.1f}s",
        f"  T_max:    {bl_t1:.1f}C -> {b2_t1:.1f}C  (delta={b2_t1 - bl_t1:+.1f}C)",
        f"  sigma_T:  {bl_t3:.2f}K -> {b2_t3:.2f}K",
        f"  N_hot:    {int(bl_t5)} -> {int(b2_t5)}",
        f"  Makespan: {bl_p1:.1f}us -> {b2_p1:.1f}us  (delta={b2_p1 - bl_p1:+.1f}us)",
        f"  eta_dvfs: {bl_eta:.2f}% -> {b2_eta:.2f}%",
        f"  Comm:     {bl_c1:.0f} -> {b2_c1:.0f}",
        f"  E_total:  {bl_e7:.3f}mJ -> {b2_e7:.3f}mJ",
    ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="B-2 Genetic Algorithm Thermal-Aware Task Mapping"
    )
    p.add_argument("--csv", help="Path to task CSV file")
    p.add_argument("--all", action="store_true", help="Run all benchmarks")
    p.add_argument("--output", "-o", default="out/B-2", help="Output directory")

    # GA parameters
    p.add_argument("--population", type=int, default=50)
    p.add_argument("--generations", type=int, default=30)
    p.add_argument("--crossover-rate", type=float, default=0.8)
    p.add_argument("--mutation-rate", type=float, default=0.1)
    p.add_argument("--elite", type=int, default=2)
    p.add_argument("--tournament", type=int, default=3)
    p.add_argument("--patience", type=int, default=10)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument(
        "--seeds",
        help="Comma-separated replicate seeds, e.g. 42,43,44. "
             "When set, outputs are written under seed_<n>/gen_<g>/.",
    )
    p.add_argument(
        "--credibility",
        action="store_true",
        help="Shortcut for paper credibility runs: seeds 42,43,44 at the "
             "configured generation count plus 60-generation long runs for "
             "GEMM,VOPD,HNN using seed 42.",
    )
    p.add_argument(
        "--long-generations",
        type=int,
        default=None,
        help="Also run selected long-run benchmarks with this generation count, "
             "e.g. 60.",
    )
    p.add_argument(
        "--long-benchmarks",
        default="GEMM,VOPD,HNN",
        help="Comma-separated benchmark names for --long-generations "
             "(default: GEMM,VOPD,HNN). Ignored for a single --csv run.",
    )
    p.add_argument(
        "--long-seeds",
        help="Comma-separated seeds for --long-generations. Defaults to the "
             "first seed in --seeds/--seed.",
    )
    p.add_argument(
        "--long-only",
        action="store_true",
        help="Skip base generation-count runs and only execute --long-generations runs.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned benchmark/seed/generation runs without launching OMNeT++.",
    )
    p.add_argument("--w-T", type=float, default=1.0, help="Peak temperature weight")
    p.add_argument("--w-sigma", type=float, default=1.0, help="Temperature sigma weight")
    p.add_argument("--w-hot", type=float, default=0.6, help="Hot-PE count weight")
    p.add_argument("--w-makespan", type=float, default=1.2, help="Makespan weight")
    p.add_argument("--w-H", type=float, default=0.4, help="Communication-distance weight")
    p.add_argument("--w-congestion", type=float, default=0.7, help="Static edge-congestion weight")
    p.add_argument("--w-D", type=float, default=0.4, help="DVFS penalty weight")
    p.add_argument("--w-L", type=float, default=0.2, help="Compute-load imbalance weight")
    p.add_argument("--w-E", type=float, default=0.5, help="Total energy weight")
    p.add_argument("--w-peak", type=float, default=0.0)

    # OMNeT++ paths
    p.add_argument("--omnet-bin", default="D:/HNOCS/libhnocs.exe")
    p.add_argument("--omnet-ned-paths", default="/d/HNOCS/src;/d/HNOCS/examples/task_driven")
    p.add_argument("--omnet-workdir", default="/d/HNOCS/examples/task_driven")
    p.add_argument("--omnet-ini", default="/d/HNOCS/examples/task_driven/omnetpp.ini")
    p.add_argument("--omnetpp-root", default="/d/omnetpp/omnetpp-6.3.0")
    p.add_argument("--omnet-timeout", type=float, default=60.0)

    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    if args.seed is not None and args.seeds:
        p.error("Use either --seed or --seeds, not both.")
    if args.long_only and args.long_generations is None and not args.credibility:
        p.error("--long-only requires --long-generations or --credibility.")

    try:
        if args.seeds:
            seeds = _parse_int_list(args.seeds, "--seeds")
        elif args.credibility and args.seed is None:
            seeds = list(DEFAULT_SEEDS)
        else:
            seeds = [args.seed]

        long_generations = args.long_generations
        if args.credibility and long_generations is None:
            long_generations = 60

        long_seeds = _parse_int_list(args.long_seeds, "--long-seeds")
        if long_generations is not None and not long_seeds:
            long_seeds = [seeds[0]]
        long_benchmarks = _parse_benchmark_set(args.long_benchmarks)
    except ValueError as exc:
        p.error(str(exc))

    params = SimParams()

    # Set module-level variables in ga_mapper for parallel workers
    import ga_mapper as ga_mod
    ga_mod._omnet_bin = args.omnet_bin
    ga_mod._omnet_ned_paths = args.omnet_ned_paths
    ga_mod._omnet_work_dir = args.omnet_workdir
    ga_mod._omnet_base_ini = args.omnet_ini
    ga_mod._omnet_base_config = "ONoCGeneral"
    ga_mod._omnetpp_root = args.omnetpp_root
    ga_mod._omnet_timeout_s = args.omnet_timeout

    base_config = GAConfig(
        population_size=args.population,
        num_generations=args.generations,
        crossover_rate=args.crossover_rate,
        mutation_rate=args.mutation_rate,
        elite_count=args.elite,
        tournament_size=args.tournament,
        patience=args.patience,
        n_workers=args.workers,
        seed=args.seed,
        w_T=args.w_T,
        w_sigma=args.w_sigma,
        w_hot=args.w_hot,
        w_makespan=args.w_makespan,
        w_H=args.w_H,
        w_congestion=args.w_congestion,
        w_D=args.w_D,
        w_L=args.w_L,
        w_E=args.w_E,
        w_peak=args.w_peak,
        omnet_bin=args.omnet_bin,
        omnet_ned_paths=args.omnet_ned_paths,
        omnet_work_dir=args.omnet_workdir,
        omnet_base_ini=args.omnet_ini,
        omnet_base_config="ONoCGeneral",
        omnetpp_root=args.omnetpp_root,
        omnet_timeout_s=args.omnet_timeout,
        omnet_verbose=args.verbose,
    )

    if args.all:
        csv_entries = list(BENCHMARKS.items())
    elif args.csv:
        csv_entries = [(_benchmark_key(args.csv), args.csv)]
    else:
        p.print_help()
        return 1

    run_plan: list[tuple[str, str, int | None, int, str]] = []
    if not args.long_only:
        for benchmark, csv_path in csv_entries:
            for seed in seeds:
                run_plan.append(("base", benchmark, seed, args.generations, csv_path))

    if long_generations is not None:
        for benchmark, csv_path in csv_entries:
            if args.all and benchmark.upper() not in long_benchmarks:
                continue
            for seed in long_seeds:
                run_plan.append(("long", benchmark, seed, long_generations, csv_path))

    # De-duplicate accidental overlaps, e.g. --long-generations equal to --generations.
    deduped_plan: list[tuple[str, str, int | None, int, str]] = []
    seen: set[tuple[str, int | None, int]] = set()
    for run_type, benchmark, seed, generations, csv_path in run_plan:
        key = (benchmark.upper(), seed, generations)
        if key in seen:
            continue
        seen.add(key)
        deduped_plan.append((run_type, benchmark, seed, generations, csv_path))

    multi_run_layout = (
        bool(args.seeds)
        or args.credibility
        or long_generations is not None
        or len({seed for _, _, seed, _, _ in deduped_plan}) > 1
        or len({gen for _, _, _, gen, _ in deduped_plan}) > 1
    )

    if args.dry_run:
        print("Planned B-2 runs:")
        for run_type, benchmark, seed, generations, csv_path in deduped_plan:
            if multi_run_layout:
                seed_label = "seed_none" if seed is None else f"seed_{seed}"
                run_output = str(Path(args.output) / seed_label / f"gen_{generations}")
            else:
                run_output = args.output
            print(
                f"  {run_type:4s}  benchmark={benchmark:5s}  "
                f"seed={seed}  generations={generations}  "
                f"csv={csv_path}  output={run_output}"
            )
        return 0

    records: list[dict] = []
    for run_type, benchmark, seed, generations, csv_path in deduped_plan:
        if not Path(csv_path).exists():
            print(f"  SKIP: {csv_path} not found")
            continue
        cfg = replace(base_config, seed=seed, num_generations=generations)
        if multi_run_layout:
            seed_label = "seed_none" if seed is None else f"seed_{seed}"
            run_output = str(Path(args.output) / seed_label / f"gen_{generations}")
        else:
            run_output = args.output
        print(
            f"\n=== {benchmark} | seed={seed} | generations={generations} "
            f"| run={run_type} ==="
        )
        full = run_benchmark(csv_path, run_output, params, cfg, verbose=args.verbose)
        records.append(_result_record(full, seed, generations, run_type))

    if multi_run_layout and records:
        _write_run_summaries(args.output, records)
        print(f"\nWrote multi-run summaries to {Path(args.output).resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
