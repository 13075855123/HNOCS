"""CLI for the CommAware-Heuristic baseline.

The runner evaluates Original plus CommAware-Heuristic under the same
OMNeT++/B-2 metrics schema.  With --proxy-only, it performs only static proxy
construction and CSV validation; it does not start OMNeT++.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EXP = _HERE.parent
_PROJ = _EXP.parent

for _d in (_HERE, _EXP, _PROJ):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from mapping.csv_writer import write_static_csv
from mapping.omnet_cost_model import SimParams
from mapping.task_graph import TaskGraph

from comm_aware_mapper import CommAwareMapper, CommAwareMapperConfig
from comm_proxy import CommProxyConfig
from common import (
    BENCHMARKS,
    CostWeights,
    OmnetRunConfig,
    build_cost_model,
    build_omnet_evaluator,
    config_payload,
    evaluate_original_reference,
    extract_original_assignment,
    grouped_metrics,
    make_original_static_tasks_mappable,
    metric_value,
    require_valid_scalars,
    validate_assignment,
    write_json,
    write_run_summaries,
)


PROTECTED_OUTPUT_DIRS = (
    (_PROJ / "out" / "B-2-v3-g60-seed42").resolve(),
    (_PROJ / "out" / "B-2-v3-g60-seed43").resolve(),
    (_PROJ / "out" / "B-2-v3" / "B-2-v3-g60-seed42").resolve(),
    (_PROJ / "out" / "B-2-v3" / "B-2-v3-g60-seed43").resolve(),
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        benchmarks = _selected_benchmarks(args)
        params = SimParams(rows=args.rows, cols=args.cols)
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
            w_peak=args.w_peak,
        )
        proxy_config = CommProxyConfig(
            rows=args.rows,
            cols=args.cols,
            lambda_cong=args.lambda_cong,
        )
        mapper_config = CommAwareMapperConfig(
            proxy=proxy_config,
            center_candidates=tuple(_parse_int_list(args.center_candidates)),
            local_swap_passes=args.local_swap_passes,
            enable_local_swap=not args.no_local_swap,
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
            _dry_run(benchmarks, output_dir, params, mapper_config, omnet_config, args)
            return 0

        _guard_output_path(output_dir, benchmarks, args.force, proxy_only=args.proxy_only)

        records: list[dict[str, object]] = []
        for benchmark in benchmarks:
            csv_path = _PROJ / BENCHMARKS[benchmark]
            if args.proxy_only:
                record = run_proxy_only(
                    benchmark=benchmark,
                    csv_path=csv_path,
                    output_dir=output_dir,
                    params=params,
                    weights=weights,
                    mapper_config=mapper_config,
                    write_outputs=not args.no_write_proxy_outputs,
                )
            else:
                record = run_workload(
                    benchmark=benchmark,
                    csv_path=csv_path,
                    output_dir=output_dir,
                    params=params,
                    weights=weights,
                    mapper_config=mapper_config,
                    omnet_config=omnet_config,
                    verbose=args.verbose,
                )
            records.append(record)

        wrote_outputs = not args.proxy_only or not args.no_write_proxy_outputs
        if wrote_outputs:
            write_run_summaries(output_dir, records)
            print(f"\nWrote CommAware-Heuristic results to {output_dir.resolve()}")
        else:
            print("\nProxy-only validation completed without persistent output.")
        return 0
    except Exception as exc:
        parser.exit(1, f"ERROR: {exc}\n")


def run_proxy_only(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    weights: CostWeights,
    mapper_config: CommAwareMapperConfig,
    write_outputs: bool = True,
) -> dict[str, object]:
    """Run static proxy construction and validation without OMNeT++."""
    start = time.perf_counter()
    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    validate_assignment(graph, original_assignment, params.num_pes)

    mapper = CommAwareMapper(graph, mapper_config)
    result = mapper.run(original_assignment=original_assignment)
    validate_assignment(graph, result.assignment, params.num_pes)
    _validate_csv_successors(graph, result.assignment)

    proxy_payload = {
        "name": benchmark,
        "kind": "CommAwareProxyOnly",
        "config": {
            **config_payload(csv_path, params, weights),
            **mapper.config_payload(),
        },
        "diagnostics": result.diagnostics(),
        "validation": {
            "omnet_executed": False,
            "assignment_covers_mappable_tasks": True,
            "pe_range": f"0..{params.num_pes - 1}",
            "gb_tasks_assigned": [],
            "csv_successor_pe_validated": True,
        },
    }

    if write_outputs:
        workload_dir = output_dir / benchmark
        original_dir = workload_dir / "original"
        comm_dir = workload_dir / "comm_aware"
        original_dir.mkdir(parents=True, exist_ok=True)
        comm_dir.mkdir(parents=True, exist_ok=True)
        write_static_csv(
            graph,
            original_assignment,
            original_dir / "mapping.csv",
            comment="Original static mapping for CommAware-Heuristic reference",
        )
        write_static_csv(
            graph,
            result.assignment,
            comm_dir / "mapping.csv",
            comment="CommAware-Heuristic mapping; communication proxy only",
        )
        write_json(comm_dir / "proxy.json", proxy_payload)
        (comm_dir / "summary.txt").write_text(_proxy_summary(benchmark, proxy_payload) + "\n", encoding="utf-8")
        (original_dir / "summary.txt").write_text(
            f"[{benchmark}] Original mapping written for CommAware proxy reference\n",
            encoding="utf-8",
        )

    elapsed_s = time.perf_counter() - start
    final_score = result.final_score
    original_score = result.original_score or {}
    record = {
        "benchmark": benchmark,
        "mode": "proxy_only",
        "original_raw_comm_cost": original_score.get("raw_comm_cost", 0.0),
        "comm_aware_raw_comm_cost": final_score["raw_comm_cost"],
        "original_max_edge_load": original_score.get("max_edge_load", 0.0),
        "comm_aware_max_edge_load": final_score["max_edge_load"],
        "original_comm_proxy": original_score.get("comm_proxy", 0.0),
        "comm_aware_comm_proxy": final_score["comm_proxy"],
        "accepted_swaps": result.accepted_swaps,
        "elapsed_s": elapsed_s,
    }
    print(_proxy_summary(benchmark, proxy_payload))
    return record


def run_workload(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    weights: CostWeights,
    mapper_config: CommAwareMapperConfig,
    omnet_config: OmnetRunConfig,
    verbose: bool = False,
) -> dict[str, object]:
    """Run Original plus CommAware-Heuristic through OMNeT++."""
    start = time.perf_counter()
    workload_dir = output_dir / benchmark
    original_dir = workload_dir / "original"
    comm_dir = workload_dir / "comm_aware"
    original_dir.mkdir(parents=True, exist_ok=True)
    comm_dir.mkdir(parents=True, exist_ok=True)

    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    validate_assignment(graph, original_assignment, params.num_pes)

    mapper = CommAwareMapper(graph, mapper_config)
    comm_result = mapper.run(original_assignment=original_assignment)
    validate_assignment(graph, comm_result.assignment, params.num_pes)

    evaluator = build_omnet_evaluator(omnet_config)
    cost_model = build_cost_model(graph, params, weights)

    if verbose:
        print(f"\n[{benchmark}] Original OMNeT++ simulation...")
    original_ref = evaluate_original_reference(
        graph, original_assignment, evaluator, cost_model, params, benchmark,
    )
    write_static_csv(
        graph,
        original_assignment,
        original_dir / "mapping.csv",
        comment="Original static mapping for CommAware-Heuristic reference",
    )
    write_json(
        original_dir / "metrics.json",
        {
            "name": benchmark,
            "method": "original",
            **original_ref.metrics,
            "config": config_payload(csv_path, params, weights, original_ref.cost_reference),
        },
    )
    (original_dir / "summary.txt").write_text(
        _metrics_summary(benchmark, "Original", original_ref.metrics) + "\n",
        encoding="utf-8",
    )

    if verbose:
        print(f"[{benchmark}] CommAware-Heuristic OMNeT++ simulation...")
    scalars = evaluator.evaluate(graph, comm_result.assignment)
    require_valid_scalars(benchmark, "CommAware-Heuristic", scalars)
    comm_metrics = grouped_metrics(
        graph,
        comm_result.assignment,
        scalars,
        cost_model,
        params,
        baseline_makespan_s=original_ref.scalars.makespan_s,
    )
    write_static_csv(
        graph,
        comm_result.assignment,
        comm_dir / "mapping.csv",
        comment="CommAware-Heuristic mapping; literature-inspired communication proxy baseline",
    )
    write_json(
        comm_dir / "proxy.json",
        {
            "name": benchmark,
            "kind": "CommAware-Heuristic",
            "config": {
                **config_payload(csv_path, params, weights, original_ref.cost_reference),
                **mapper.config_payload(),
            },
            "diagnostics": comm_result.diagnostics(),
        },
    )
    write_json(
        comm_dir / "metrics.json",
        {
            "name": benchmark,
            "method": "comm_aware",
            "paper_label": "CommAware-Heuristic",
            **comm_metrics,
            "config": {
                **config_payload(csv_path, params, weights, original_ref.cost_reference),
                **mapper.config_payload(),
            },
        },
    )
    (comm_dir / "summary.txt").write_text(
        _metrics_summary(benchmark, "CommAware-Heuristic", comm_metrics) + "\n",
        encoding="utf-8",
    )

    elapsed_s = time.perf_counter() - start
    record = {
        "benchmark": benchmark,
        "mode": "omnet",
        "original_cost": _composite_cost(original_ref.metrics),
        "comm_aware_cost": _composite_cost(comm_metrics),
        "original_raw_comm_cost": original_ref.metrics["tradeoff"]["cost_terms"]["raw_comm_cost"],
        "comm_aware_raw_comm_cost": comm_metrics["tradeoff"]["cost_terms"]["raw_comm_cost"],
        "original_raw_congestion_cost": original_ref.metrics["tradeoff"]["cost_terms"]["raw_congestion_cost"],
        "comm_aware_raw_congestion_cost": comm_metrics["tradeoff"]["cost_terms"]["raw_congestion_cost"],
        "elapsed_s": elapsed_s,
    }
    print(_metrics_summary(benchmark, "CommAware-Heuristic", comm_metrics))
    return record


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run CommAware-Heuristic with B-2-compatible OMNeT++ evaluation"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="Path to one static task CSV")
    source.add_argument("--all", action="store_true", help="Run gemm,mpeg4,vopd,hnn")
    parser.add_argument("--benchmarks", default="gemm,mpeg4,vopd,hnn")
    parser.add_argument("--out", default="out/comm-aware-baseline-v1")
    parser.add_argument("--proxy-only", action="store_true", help="Do not run OMNeT++; write mapping/proxy diagnostics only")
    parser.add_argument("--no-write-proxy-outputs", action="store_true", help="With --proxy-only, validate in memory only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")

    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--lambda-cong", type=float, default=0.25)
    parser.add_argument("--center-candidates", default="5,6,9,10")
    parser.add_argument("--local-swap-passes", type=int, default=5)
    parser.add_argument("--no-local-swap", action="store_true")

    parser.add_argument("--w-T", type=float, default=1.0)
    parser.add_argument("--w-sigma", type=float, default=1.0)
    parser.add_argument("--w-hot", type=float, default=0.6)
    parser.add_argument("--w-makespan", type=float, default=1.2)
    parser.add_argument("--w-H", type=float, default=0.4)
    parser.add_argument("--w-congestion", type=float, default=0.7)
    parser.add_argument("--w-D", type=float, default=0.4)
    parser.add_argument("--w-L", type=float, default=0.2)
    parser.add_argument("--w-E", type=float, default=0.5)
    parser.add_argument("--w-peak", type=float, default=0.0)

    parser.add_argument("--omnet-bin", default="D:/HNOCS/libhnocs.exe")
    parser.add_argument("--omnet-ned-paths", default="D:/HNOCS/src;D:/HNOCS/examples/task_driven")
    parser.add_argument("--omnet-workdir", default="D:/HNOCS/examples/task_driven")
    parser.add_argument("--omnet-ini", default="D:/HNOCS/examples/task_driven/omnetpp.ini")
    parser.add_argument("--omnet-base-config", default="ONoCGeneral")
    parser.add_argument("--omnetpp-root", default="D:/omnetpp/omnetpp-6.3.0")
    parser.add_argument("--omnet-timeout", type=float, default=60.0)
    return parser


def _selected_benchmarks(args: argparse.Namespace) -> list[str]:
    if args.csv:
        csv_path = Path(args.csv)
        name = csv_path.stem.replace("tasks_", "").replace("_static", "").lower()
        if name not in BENCHMARKS:
            BENCHMARKS[name] = str(csv_path)
        return [name]
    names = [part.strip().lower() for part in args.benchmarks.split(",") if part.strip()]
    if not names:
        raise ValueError("no benchmarks selected")
    unknown = [name for name in names if name not in BENCHMARKS]
    if unknown:
        raise ValueError(f"unknown benchmarks: {unknown}")
    return names


def _parse_int_list(value: str) -> list[int]:
    out: list[int] = []
    for part in value.split(","):
        item = part.strip()
        if item:
            out.append(int(item))
    if not out:
        raise ValueError("integer list must not be empty")
    return out


def _dry_run(
    benchmarks: list[str],
    output_dir: Path,
    params: SimParams,
    mapper_config: CommAwareMapperConfig,
    omnet_config: OmnetRunConfig,
    args: argparse.Namespace,
) -> None:
    print("Planned CommAware-Heuristic runs:")
    print(f"  mode={'proxy_only' if args.proxy_only else 'omnet'}")
    print(f"  output={output_dir.resolve()}")
    print(f"  rows={params.rows} cols={params.cols} num_pes={params.num_pes}")
    print(f"  lambda_cong={mapper_config.proxy.lambda_cong}")
    print(f"  center_candidates={list(mapper_config.center_candidates)}")
    print(f"  local_swap_passes={mapper_config.local_swap_passes} enabled={mapper_config.enable_local_swap}")
    if not args.proxy_only:
        print("  path checks:")
        for label, path in [
            ("omnet_bin", omnet_config.omnet_bin),
            ("omnet_workdir", omnet_config.omnet_workdir),
            ("omnet_ini", omnet_config.omnet_ini),
            ("omnetpp_root", omnet_config.omnetpp_root),
        ]:
            print(f"    {label}: {Path(path).exists()}  {path}")
    for benchmark in benchmarks:
        csv_path = _PROJ / BENCHMARKS[benchmark] if not Path(BENCHMARKS[benchmark]).is_absolute() else Path(BENCHMARKS[benchmark])
        graph = TaskGraph.from_csv(csv_path)
        original_assignment = extract_original_assignment(graph)
        make_original_static_tasks_mappable(graph)
        print(
            f"  {benchmark}: csv={csv_path} tasks={graph.num_tasks} "
            f"gb={len(graph.gb_task_ids)} mappable={len(graph.mappable_task_ids)} "
            f"original_tasks={len(original_assignment)}"
        )


def _guard_output_path(
    output_dir: Path,
    benchmarks: list[str],
    force: bool,
    proxy_only: bool,
) -> None:
    resolved = output_dir.resolve()
    for protected in PROTECTED_OUTPUT_DIRS:
        if resolved == protected or _is_under(resolved, protected):
            raise RuntimeError(f"refusing to write into protected paper result directory: {protected}")

    try:
        rel_parts = resolved.relative_to((_PROJ / "out").resolve()).parts
    except ValueError:
        rel_parts = resolved.parts
    if any(part.startswith("B-2") for part in rel_parts):
        raise RuntimeError("refusing to write CommAware output into a B-2 output path")

    if force:
        return

    collisions: list[Path] = []
    for benchmark in benchmarks:
        files = [
            output_dir / benchmark / "original" / "mapping.csv",
            output_dir / benchmark / "original" / "summary.txt",
            output_dir / benchmark / "comm_aware" / "mapping.csv",
            output_dir / benchmark / "comm_aware" / "proxy.json",
            output_dir / benchmark / "comm_aware" / "summary.txt",
        ]
        if not proxy_only:
            files.extend([
                output_dir / benchmark / "original" / "metrics.json",
                output_dir / benchmark / "comm_aware" / "metrics.json",
            ])
        for path in files:
            if path.exists():
                collisions.append(path)

    for path in [output_dir / "runs_summary.csv", output_dir / "aggregate_summary.json"]:
        if path.exists():
            collisions.append(path)

    if collisions:
        details = "\n".join(f"  {path.resolve()}" for path in collisions[:20])
        raise RuntimeError(
            "refusing to overwrite existing CommAware outputs. "
            "Choose a new --out directory or pass --force:\n"
            f"{details}"
        )


def _validate_csv_successors(graph: TaskGraph, assignment: dict[int, int]) -> None:
    """Exercise csv_writer validation and successorPE rewriting in a temp file."""
    with tempfile.TemporaryDirectory(prefix="commaware_proxy_validate_") as tmp:
        path = Path(tmp) / "mapping.csv"
        write_static_csv(graph, assignment, path, comment="CommAware proxy validation")
        parsed = TaskGraph.from_csv(path)
        for tid, node in parsed.tasks.items():
            if node.is_gb_task:
                continue
            expected_pe = assignment.get(tid, node.assigned_pe)
            if node.assigned_pe != expected_pe:
                raise RuntimeError(f"task {tid} CSV PE mismatch: got {node.assigned_pe}, expected {expected_pe}")
            for succ_id in node.successors:
                succ_pe = node.successor_pe[succ_id]
                if succ_id == -1 or parsed.tasks.get(succ_id, None) and parsed.tasks[succ_id].is_gb_task:
                    if succ_pe != -1:
                        raise RuntimeError(f"task {tid} successor {succ_id} should preserve succPE=-1")
                elif succ_id in assignment and succ_pe != assignment[succ_id]:
                    raise RuntimeError(
                        f"task {tid} successor {succ_id} has successorPE={succ_pe}, "
                        f"expected {assignment[succ_id]}"
                    )


def _proxy_summary(benchmark: str, payload: dict[str, object]) -> str:
    diag = payload["diagnostics"]
    original = diag.get("original_score") or {}
    final = diag["final_score"]
    return "\n".join([
        f"[{benchmark}] CommAware-Heuristic proxy-only",
        f"  seed: task={diag['seed_task']} pe={diag['seed_pe']}",
        f"  raw_comm: {original.get('raw_comm_cost', 0.0):.0f} -> {final['raw_comm_cost']:.0f}",
        f"  max_edge_load: {original.get('max_edge_load', 0.0):.0f} -> {final['max_edge_load']:.0f}",
        f"  comm_proxy: {original.get('comm_proxy', 0.0):.2f} -> {final['comm_proxy']:.2f}",
        f"  local_swaps: passes={diag['local_swap_passes']} accepted={diag['accepted_swaps']}",
    ])


def _metrics_summary(benchmark: str, label: str, metrics: dict[str, object]) -> str:
    cost = _composite_cost(metrics)
    comm = metrics["tradeoff"]["cost_terms"]["raw_comm_cost"]
    congestion = metrics["tradeoff"]["cost_terms"]["raw_congestion_cost"]
    makespan_us = metric_value(metrics, "performance", "P1_makespan_s") * 1e6
    return "\n".join([
        f"[{benchmark}] {label}",
        f"  TR2_composite_cost: {cost:.4f}",
        f"  raw_comm_cost:      {comm:.0f}",
        f"  raw_congestion:     {congestion:.0f}",
        f"  makespan:           {makespan_us:.2f} us",
    ])


def _composite_cost(metrics: dict[str, object]) -> float:
    value = metrics.get("tradeoff", {}).get("TR2_composite_cost", float("nan"))
    return float(value) if isinstance(value, (int, float)) else float("nan")


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())
