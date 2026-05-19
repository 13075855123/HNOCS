#!/usr/bin/env python3
"""
Direction B — Offline Static Thermal-Aware Task Mapping CLI.

Usage:
    python -m mapping.run_mapping --input tasks_gemm.csv --output out.csv
    python -m mapping.run_mapping --input tasks_gemm.csv --output out.csv \\
        --temperature thermal_snapshot.json --wT 1.0 --wH 0.5
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .task_graph import TaskGraph
from .cost_model import CostModel
from .temperature_reader import read_temperatures
from .sa_optimizer import SAOptimizer
from .csv_writer import write_static_csv


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # 1. Load task graph
    # ------------------------------------------------------------------
    if args.verbose:
        print(f"Loading task graph from: {args.input}")
    graph = TaskGraph.from_csv(args.input)

    if args.verbose:
        print(
            f"  {graph.num_tasks} tasks total, "
            f"{graph.num_mappable} mappable (peId=-2), "
            f"{len(graph.gb_task_ids)} GB-injection (peId=-1)"
        )

    if graph.num_mappable == 0:
        print("Warning: No mappable tasks (peId=-2) in input CSV. Nothing to do.")
        write_static_csv(graph, {}, args.output, comment="Pass-through (no mappable tasks)")
        return 0

    # ------------------------------------------------------------------
    # 2. Load temperatures
    # ------------------------------------------------------------------
    pe_temps = read_temperatures(
        filepath=args.temperature,
        num_pes=args.rows * args.cols,
        Tambient=args.Tambient,
    )

    if args.verbose:
        min_t = min(pe_temps)
        max_t = max(pe_temps)
        print(
            f"  PE temperatures: min={min_t:.2f} K ({min_t - 273.15:.1f}°C), "
            f"max={max_t:.2f} K ({max_t - 273.15:.1f}°C), "
            f"Tambient={args.Tambient:.2f} K"
        )

    # ------------------------------------------------------------------
    # 3. Build cost model
    # ------------------------------------------------------------------
    cost_model = CostModel(
        graph=graph,
        pe_temperatures=pe_temps,
        w_T=args.wT,
        w_H=args.wH,
        Tambient=args.Tambient,
        rows=args.rows,
        cols=args.cols,
    )

    # ------------------------------------------------------------------
    # 4. Run optimizer
    # ------------------------------------------------------------------
    algorithm = args.algorithm.lower()
    t0 = time.perf_counter()

    if algorithm == "sa":
        opt = SAOptimizer(
            graph=graph,
            cost_model=cost_model,
            T_init=args.T_init,
            T_min=args.T_min,
            alpha=args.alpha,
            iterations_per_T=args.iters_per_T,
            max_idle=args.max_idle,
            seed=args.seed,
        )
        if args.restarts > 1:
            result = opt.optimize_with_restarts(
                num_restarts=args.restarts, verbose=args.verbose
            )
        else:
            result = opt.optimize(verbose=args.verbose)
    else:
        print(f"Error: unknown algorithm '{args.algorithm}'. Supported: sa", file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # 5. Report results
    # ------------------------------------------------------------------
    breakdown = cost_model.cost_breakdown(result.assignment)
    print(f"\n{'='*60}")
    print(f"Optimization complete ({elapsed:.3f}s, {result.total_iterations} iters)")
    print(f"  Total cost:    {breakdown['total_cost']:.4f}")
    print(f"  Thermal term:  {breakdown['thermal_cost']:.4f}")
    print(f"  Comm term:     {breakdown['comm_cost']:.4f}")
    print(f"  Max PE temp:   {breakdown['max_temp_K']:.2f} K ({breakdown['max_temp_K'] - 273.15:.1f}°C)")
    print(f"  Accepted uphill moves: {result.accepted_uphill}")
    print(f"  SA converged:  {result.converged}")

    # PE load distribution
    pe_loads = {pe: 0 for pe in range(args.rows * args.cols)}
    for tid, pe in result.assignment.items():
        pe_loads[pe] += 1
    max_load = max(pe_loads.values())
    print(f"  PE load:       1-{max_load} tasks/PE")

    # ------------------------------------------------------------------
    # 6. Write output CSV
    # ------------------------------------------------------------------
    comment = (
        f"Direction B SA-optimized mapping\n"
        f"  input: {args.input}\n"
        f"  algorithm: {algorithm}\n"
        f"  w_T={args.wT} w_H={args.wH}\n"
        f"  total_cost={breakdown['total_cost']:.4f} "
        f"thermal={breakdown['thermal_cost']:.4f} "
        f"comm={breakdown['comm_cost']:.4f}"
    )
    write_static_csv(graph, result.assignment, args.output, comment=comment)

    if args.verbose:
        cost_curve = ", ".join(f"{c:.4f}" for c in result.cost_history[:10])
        print(f"\n  Cost history (first 10 steps): [{cost_curve}...]")

    print(f"  Output: {args.output}")
    print(f"{'='*60}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="HNOCS Direction B: Offline Static Thermal-Aware Task Mapping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m mapping.run_mapping --input tasks_gemm.csv --output tasks_gemm_opt.csv
  python -m mapping.run_mapping --input tasks_vopd.csv --output out.csv \\
      --temperature thermal_snapshot.json --wT 1.0 --wH 0.5 --verbose
        """,
    )

    # Required
    p.add_argument("--input", "-i", required=True, help="Input task CSV (dynamic format)")
    p.add_argument("--output", "-o", required=True, help="Output static CSV")

    # Mesh geometry
    p.add_argument("--rows", type=int, default=4, help="Mesh rows (default: 4)")
    p.add_argument("--cols", "--columns", type=int, default=4, help="Mesh columns (default: 4)")

    # Cost function weights
    p.add_argument("--wT", type=float, default=1.0, help="Temperature weight (default: 1.0)")
    p.add_argument("--wH", type=float, default=0.5, help="Hop-count weight (default: 0.5)")

    # Thermal
    p.add_argument("--Tambient", type=float, default=318.15, help="Ambient temperature K (default: 318.15 = 45°C)")
    p.add_argument("--temperature", "-t", default=None, help="Thermal snapshot JSON or .sca file")

    # Algorithm
    p.add_argument("--algorithm", "-a", default="sa", choices=["sa"], help="Optimization algorithm (default: sa)")

    # SA hyperparameters
    p.add_argument("--T-init", type=float, default=1000.0, help="SA initial temperature (default: 1000)")
    p.add_argument("--T-min", type=float, default=0.01, help="SA min temperature (default: 0.01)")
    p.add_argument("--alpha", type=float, default=0.95, help="SA cooling rate (default: 0.95)")
    p.add_argument("--iters-per-T", type=int, default=100, help="SA iterations per temperature step (default: 100)")
    p.add_argument("--max-idle", type=int, default=30, help="SA idle steps before early stop (default: 30)")

    # Multiple restarts
    p.add_argument("--restarts", type=int, default=1, help="Number of SA restarts (default: 1)")

    # Misc
    p.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    return p


if __name__ == "__main__":
    sys.exit(main())
