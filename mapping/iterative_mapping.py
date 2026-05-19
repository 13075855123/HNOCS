#!/usr/bin/env python3
"""
Direction B — Multi-Round Iterative Thermal-Aware Task Mapping.

Repeatedly alternates between Python thermal simulation and SA
optimisation until the mapping converges or temperatures stabilise.

Usage:
    python -m mapping.iterative_mapping \
        --input tasks_gemm.csv --output tasks_gemm_final.csv \
        --rows 4 --cols 4 --wT 1.0 --wH 0.5 \
        --max-rounds 20 --seed 42 --verbose
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .task_graph import TaskGraph
from .cost_model import CostModel
from .sa_optimizer import SAOptimizer
from .thermal_simulator import simulate_thermal, SimParams
from .csv_writer import write_static_csv


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # 1. Load task graph
    # ------------------------------------------------------------------
    print(f"Loading: {args.input}")
    graph = TaskGraph.from_csv(args.input)
    n_mappable = graph.num_mappable
    if n_mappable == 0:
        print("No mappable tasks (peId=-2). Nothing to optimise.")
        return 1
    print(f"  {graph.num_tasks} tasks, {n_mappable} mappable")

    # ------------------------------------------------------------------
    # 2. Simulation parameters
    # ------------------------------------------------------------------
    sim_params = SimParams(
        rows=args.rows, cols=args.cols,
        RconvPE=args.RconvPE, RconvRouter=args.RconvRouter,
        RlateralPE=args.RlateralPE, RlateralRouter=args.RlateralRouter,
        Rpe2router=args.Rpe2router, Cpe=args.Cpe, Crouter=args.Crouter,
        Tambient=args.Tambient,
        powerIdle=args.powerIdle, powerCompute=args.powerCompute,
        Tthrottle=args.Tthrottle, throttleBeta=args.throttleBeta,
        dt=args.dt, commDelayPerHop=args.commDelayPerHop,
    )

    # ------------------------------------------------------------------
    # 3. Round 0: SA with uniform temperature (comm-only)
    # ------------------------------------------------------------------
    print("\n=== Round 0: initial SA (uniform temperature) ===")
    t0 = time.perf_counter()

    uniform_temps = [args.Tambient] * (args.rows * args.cols)
    cm = CostModel(
        graph, uniform_temps, w_T=args.wT, w_H=args.wH,
        Tambient=args.Tambient, rows=args.rows, cols=args.cols,
    )
    opt = SAOptimizer(graph, cm, seed=args.seed)
    result = opt.optimize()
    best_assignment = result.assignment
    best_cost = result.cost

    print(f"  Cost: {best_cost:.4f}  (comm-only, no thermal data)")

    # ------------------------------------------------------------------
    # 4. Iterative rounds
    # ------------------------------------------------------------------
    prev_temps = list(uniform_temps)
    prev_assignment: dict[int, int] = {}
    round_history: list[dict] = []

    # Temperature smoothing (EMA) to damp oscillation
    ema_alpha = args.ema_alpha

    # Cycle detection: hash assignment → round number
    seen_assignments: dict[int, int] = {}
    # Track best result across all rounds
    best_overall_assignment = dict(best_assignment)
    best_overall_max_temp = max(uniform_temps)

    for rnd in range(1, args.max_rounds + 1):
        print(f"\n=== Round {rnd}: thermal simulation ===")

        # 4a. Simulate thermal with current mapping
        sim_result = simulate_thermal(
            graph, best_assignment, sim_params, verbose=args.verbose
        )

        # Use max temperature per PE (more conservative about hotspots)
        raw_temps = list(sim_result.pe_max_temp)

        # Temperature smoothing: EMA with previous temps
        if ema_alpha < 1.0:
            new_temps = [
                ema_alpha * raw_temps[i] + (1 - ema_alpha) * prev_temps[i]
                for i in range(len(raw_temps))
            ]
        else:
            new_temps = raw_temps

        max_t = max(new_temps)
        min_t = min(new_temps)
        print(
            f"  PE temps: min={min_t:.2f} K ({min_t-273.15:.1f}C) "
            f"max={max_t:.2f} K ({max_t-273.15:.1f}C) "
            f"end={sim_result.sim_end_time*1e6:.1f} us"
        )

        if args.verbose:
            print("  Raw temps:")
            _print_temp_grid(raw_temps, sim_params.rows, sim_params.cols)
            if ema_alpha < 1.0:
                print("  Smoothed temps:")
                _print_temp_grid(new_temps, sim_params.rows, sim_params.cols)

        # Track best overall (lowest max temperature)
        if max(raw_temps) < best_overall_max_temp:
            best_overall_max_temp = max(raw_temps)
            best_overall_assignment = dict(best_assignment)

        # 4b. Check convergence — assignment cycle detection
        assign_hash = _hash_assignment(best_assignment)
        if assign_hash in seen_assignments:
            cycle_start = seen_assignments[assign_hash]
            print(f"  Assignment cycle detected (seen at round {cycle_start}) — CONVERGED")
            break
        seen_assignments[assign_hash] = rnd

        # 4c. Check convergence — temperature
        temp_deltas = [abs(new_temps[i] - prev_temps[i])
                       for i in range(len(new_temps))]
        max_delta = max(temp_deltas)

        # 4d. Check convergence — mapping unchanged
        if prev_assignment and best_assignment == prev_assignment:
            print(f"  Mapping unchanged — CONVERGED at round {rnd}")
            break

        # 4e. Temperature convergence
        print(f"  Max dT vs previous round: {max_delta:.2f} K")
        if max_delta < args.temp_convergence and rnd > 1:
            print(f"  Temperature converged (d < {args.temp_convergence} K) at round {rnd}")
            break

        # 4f. Re-optimise with per-task start-time temperatures
        print(f"  Re-optimising...")
        cm2 = CostModel(
            graph, new_temps, w_T=args.wT, w_H=args.wH,
            Tambient=args.Tambient, rows=args.rows, cols=args.cols,
        )
        # Use per-task start-time temps from simulation (replaces static per-PE max)
        if sim_result.task_start_temps:
            cm2.set_task_start_temps(sim_result.task_start_temps)
        opt2 = SAOptimizer(graph, cm2, seed=args.seed + rnd)
        result2 = opt2.optimize()

        prev_assignment = dict(best_assignment)
        best_assignment = result2.assignment
        prev_temps = list(new_temps)

        breakdown = cm2.cost_breakdown(best_assignment)
        print(
            f"  New cost: {breakdown['total_cost']:.4f} "
            f"(thermal={breakdown['thermal_cost']:.4f} "
            f"comm={breakdown['comm_cost']:.4f})"
        )

        round_history.append({
            "round": rnd, "max_temp_K": max_t,
            "cost": result2.cost, "mapping_changed": (best_assignment != prev_assignment),
        })

    elapsed = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # 5. Final simulation & report
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"Iterative mapping complete ({elapsed:.2f}s, {rnd} rounds)")

    final_sim = simulate_thermal(graph, best_assignment, sim_params)
    final_temps = final_sim.pe_max_temp

    final_cm = CostModel(
        graph, final_temps, w_T=args.wT, w_H=args.wH,
        Tambient=args.Tambient, rows=args.rows, cols=args.cols,
    )
    final_breakdown = final_cm.cost_breakdown(best_assignment)

    print(f"  Final cost: {final_breakdown['total_cost']:.4f}")
    print(f"    Thermal:  {final_breakdown['thermal_cost']:.4f}")
    print(f"    Comm:     {final_breakdown['comm_cost']:.4f}")
    print(f"    Load pen: {final_breakdown.get('load_penalty', 0):.4f}")
    print(f"  Max PE temp: {max(final_temps):.2f} K ({max(final_temps)-273.15:.1f}C)")

    if args.verbose:
        print(f"\n  Final temperature grid:")
        _print_temp_grid(final_temps, sim_params.rows, sim_params.cols)
        print(f"\n  Round history:")
        for h in round_history:
            print(f"    R{h['round']}: cost={h['cost']:.4f} "
                  f"maxT={h['max_temp_K']:.2f}K changed={h['mapping_changed']}")

    # ------------------------------------------------------------------
    # 6. Write output
    # ------------------------------------------------------------------
    comment = (
        f"Direction B iterative SA-optimized mapping\n"
        f"  input: {args.input}\n"
        f"  rounds: {rnd}\n"
        f"  cost: {final_breakdown['total_cost']:.4f} "
        f"thermal={final_breakdown['thermal_cost']:.4f} "
        f"comm={final_breakdown['comm_cost']:.4f}\n"
        f"  max PE temp: {max(final_temps):.2f} K"
    )
    write_static_csv(graph, best_assignment, args.output, comment=comment)
    print(f"  Output: {args.output}")
    print(f"{'='*60}")
    return 0


# ------------------------------------------------------------------
def _hash_assignment(assignment: dict[int, int]) -> int:
    """Hash an assignment dict for cycle detection (order-independent)."""
    return hash(tuple(sorted(assignment.items())))

def _print_temp_grid(temps: list[float], rows: int, cols: int):
    """Pretty-print temperature grid in C."""
    for r in range(rows):
        line = "    "
        for c in range(cols):
            pe = r * cols + c
            tc = temps[pe] - 273.15
            line += f"PE{pe:2d}={tc:5.1f}C  "
        print(line)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="HNOCS Direction B: Multi-Round Iterative Thermal-Aware Mapping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument("--input", "-i", required=True, help="Input task CSV (dynamic format)")
    p.add_argument("--output", "-o", required=True, help="Output static CSV")

    # Mesh
    p.add_argument("--rows", type=int, default=4)
    p.add_argument("--cols", type=int, default=4)

    # Weights
    p.add_argument("--wT", type=float, default=1.0, help="Temperature weight")
    p.add_argument("--wH", type=float, default=0.5, help="Hop-count weight")

    # Convergence
    p.add_argument("--max-rounds", type=int, default=20)
    p.add_argument("--temp-convergence", type=float, default=1.0,
                   help="Temperature convergence threshold (K)")
    p.add_argument("--ema-alpha", type=float, default=0.5,
                   help="Temperature EMA smoothing (1.0=no smoothing, 0.5=half old+half new)")

    # Thermal
    p.add_argument("--Tambient", type=float, default=318.15)
    p.add_argument("--RconvPE", type=float, default=8.0)
    p.add_argument("--RconvRouter", type=float, default=10.0)
    p.add_argument("--RlateralPE", type=float, default=15.0)
    p.add_argument("--RlateralRouter", type=float, default=15.0)
    p.add_argument("--Rpe2router", type=float, default=3.0)
    p.add_argument("--Cpe", type=float, default=1e-6)
    p.add_argument("--Crouter", type=float, default=2e-7)

    # Power
    p.add_argument("--powerIdle", type=float, default=0.5)
    p.add_argument("--powerCompute", type=float, default=2.0)

    # DVFS
    p.add_argument("--Tthrottle", type=float, default=320.0)
    p.add_argument("--throttleBeta", type=float, default=0.05)

    # Time
    p.add_argument("--dt", type=float, default=100e-9, help="Thermal time step (s)")
    p.add_argument("--commDelayPerHop", type=float, default=1e-9,
                   help="Communication delay per hop (s)")

    # SA
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--verbose", "-v", action="store_true")

    return p


if __name__ == "__main__":
    sys.exit(main())
