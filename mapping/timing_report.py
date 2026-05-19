"""
Timing validation — compare Python thermal simulator task scheduling
against OMNeT++ scalar output.

Usage:
    python -m mapping.timing_report --csv tasks_gemm_static.csv --mapping static
    python -m mapping.timing_report --csv tasks_gemm.csv --mapping 0,8,9,12,4,9,12,5,5,13

The second form takes a comma-separated list of PE assignments
(task IDs in order: T1→PE0, T2→PE8, T3→PE9, ...).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .task_graph import TaskGraph
from .thermal_simulator import TaskScheduler, SimParams, simulate_thermal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task timing report")
    parser.add_argument("--csv", required=True, help="Task CSV file")
    parser.add_argument("--mapping", required=True,
                        help="PE assignments: 'static' (use CSV peIds) or "
                             "'0,1,2,...' (comma-separated PE list)")
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=4)
    args = parser.parse_args(argv)

    graph = TaskGraph.from_csv(args.csv)

    # Build assignment
    if args.mapping == "static":
        assignment = {
            tid: node.assigned_pe
            for tid, node in graph.tasks.items()
            if node.assigned_pe >= 0
        }
    else:
        pe_list = [int(x.strip()) for x in args.mapping.split(",")]
        mappable = graph.mappable_task_ids
        if len(pe_list) != len(mappable):
            print(f"Error: {len(pe_list)} PEs given but {len(mappable)} mappable tasks")
            return 1
        assignment = dict(zip(mappable, pe_list))

    params = SimParams(rows=args.rows, cols=args.cols)

    # Run full thermal simulation (schedule + power + thermal)
    result = simulate_thermal(graph, assignment, params)

    # Print report
    hdr = f"{'Task':>6} {'PE':>4} {'Start(ns)':>12} {'Compute(ns)':>12} {'Finish(ns)':>12} {'CommFromPred':>20}"
    print(hdr)
    print("-" * len(hdr))

    total_time = 0.0
    for slot in sorted(result.schedule, key=lambda s: s.start_time):
        node = graph.tasks[slot.task_id]
        # Compute communication delay from predecessors
        comm_parts = []
        for pred_id in node.predecessor_set:
            pred_node = graph.tasks.get(pred_id)
            if pred_node is None or pred_node.is_gb_task:
                comm_parts.append(f"GB")
                continue
            src_pe = assignment.get(pred_id, 0)
            hops = abs(src_pe // params.cols - slot.pe_id // params.cols) + \
                   abs(src_pe % params.cols - slot.pe_id % params.cols)
            comm_parts.append(f"T{pred_id}(PE{src_pe}) h={hops}")

        comm_str = ", ".join(comm_parts) if comm_parts else "none"
        print(f"T{slot.task_id:>5} {slot.pe_id:>4} "
              f"{slot.start_time*1e9:>11.1f} "
              f"{slot.compute_time*1e9:>11.1f} "
              f"{slot.finish_time*1e9:>11.1f} "
              f"{comm_str:>20}")
        total_time = max(total_time, slot.finish_time)

    print("-" * len(hdr))
    print(f"Total simulation time: {total_time*1e6:.2f} us")
    print(f"PE temperatures at end: max={max(result.pe_max_temp)-273.15:.1f}C "
          f"min={min(result.pe_max_temp)-273.15:.1f}C")

    return 0


if __name__ == "__main__":
    sys.exit(main())
