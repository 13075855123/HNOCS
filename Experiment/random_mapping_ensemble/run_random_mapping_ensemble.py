"""CLI for the Random Mapping Ensemble baseline experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
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

from b2_baseline_reference import (
    CostWeights,
    OmnetRunConfig,
    build_cost_model,
    build_omnet_evaluator,
    evaluate_original_reference,
    extract_original_assignment,
    make_original_static_tasks_mappable,
)
from b2_metrics_schema import grouped_metrics
from random_assignment_generator import generate_random_assignment
from random_ensemble_summary import (
    RandomSampleRecord,
    compact_sample_rows,
    select_distribution_records,
    write_compact_outputs,
)


BENCHMARKS = {
    "gemm": "examples/task_driven/static/tasks_gemm_static.csv",
    "mpeg4": "examples/task_driven/static/tasks_mpeg4_static.csv",
    "vopd": "examples/task_driven/static/tasks_vopd_static.csv",
    "hnn": "examples/task_driven/static/tasks_hnn_static.csv",
}

PROTECTED_OUTPUT_DIRS = (
    (_PROJ / "out" / "B-2-v3-g60-seed42").resolve(),
    (_PROJ / "out" / "B-2-v3-g60-seed43").resolve(),
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        benchmarks = _parse_benchmarks(args.benchmarks)
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

        if args.random_n <= 0:
            parser.error("--random-n must be positive")
        if args.workers <= 0:
            parser.error("--workers must be positive")

        output_dir = Path(args.out)
        _guard_output_path(output_dir, benchmarks, args.force)

        if args.dry_run:
            _dry_run(benchmarks, params, args, omnet_config, output_dir)
            return 0

        run_records: list[dict[str, object]] = []
        for benchmark in benchmarks:
            record = run_workload(
                benchmark=benchmark,
                csv_path=_PROJ / BENCHMARKS[benchmark],
                output_dir=output_dir,
                params=params,
                weights=weights,
                omnet_config=omnet_config,
                random_n=args.random_n,
                seed_base=args.seed,
                workers=args.workers,
                force=args.force,
                verbose=args.verbose,
            )
            run_records.append(record)

        _write_run_summary(output_dir, run_records)
        print(f"\nWrote Random Mapping Ensemble results to {output_dir.resolve()}")
        return 0
    except Exception as exc:
        parser.exit(1, f"ERROR: {exc}\n")


def run_workload(
    benchmark: str,
    csv_path: Path,
    output_dir: Path,
    params: SimParams,
    weights: CostWeights,
    omnet_config: OmnetRunConfig,
    random_n: int,
    seed_base: int,
    workers: int,
    force: bool,
    verbose: bool = False,
) -> dict[str, object]:
    """Run Original reference plus N random samples for one workload."""
    del force
    start = time.perf_counter()
    workload_dir = output_dir / benchmark
    original_dir = workload_dir / "original"
    random_dir = workload_dir / "random"
    mappings_dir = random_dir / "mappings"
    selected_dir = random_dir / "selected"

    for directory in (original_dir, mappings_dir, selected_dir):
        directory.mkdir(parents=True, exist_ok=True)

    graph = TaskGraph.from_csv(csv_path)
    original_assignment = extract_original_assignment(graph)
    make_original_static_tasks_mappable(graph)
    mappable_ids = graph.mappable_task_ids

    if set(original_assignment) != set(mappable_ids):
        missing = sorted(set(mappable_ids) - set(original_assignment))
        extra = sorted(set(original_assignment) - set(mappable_ids))
        raise RuntimeError(
            f"{benchmark} Original assignment does not match mappable tasks; "
            f"missing={missing}, extra={extra}"
        )

    if verbose:
        print(f"\n[{benchmark}] Original OMNeT++ simulation...")
    evaluator = build_omnet_evaluator(omnet_config)
    cost_model = build_cost_model(graph, params, weights)
    original_ref = evaluate_original_reference(
        graph, original_assignment, evaluator, cost_model, benchmark,
    )
    original_metrics = grouped_metrics(
        graph, original_assignment, original_ref.scalars, cost_model, params,
    )
    write_static_csv(
        graph,
        original_assignment,
        original_dir / "mapping.csv",
        comment="Original static mapping for Random Mapping Ensemble reference",
    )
    (original_dir / "metrics.json").write_text(
        json.dumps({
            "name": benchmark,
            "kind": "Original",
            "metrics": original_metrics,
            "config": {
                "source_csv": str(csv_path),
                "cost_reference": asdict(original_ref.cost_reference),
                "weights": asdict(weights),
            },
        }, indent=2),
        encoding="utf-8",
    )

    sample_jobs: list[dict[str, object]] = []
    for sample_id in range(random_n):
        sample_seed = seed_base + sample_id
        assignment = generate_random_assignment(
            mappable_task_ids=mappable_ids,
            num_pes=params.num_pes,
            sample_seed=sample_seed,
        )
        mapping_path = mappings_dir / f"sample_{sample_id:03d}_seed_{sample_seed}.csv"
        write_static_csv(
            graph,
            assignment,
            mapping_path,
            comment=(
                "Random Mapping Ensemble sample "
                f"{sample_id} seed={sample_seed}"
            ),
        )

        if verbose:
            print(f"[{benchmark}] queued random sample {sample_id + 1}/{random_n} seed={sample_seed}")

        sample_jobs.append({
            "sample_id": sample_id,
            "sample_seed": sample_seed,
            "assignment": assignment,
            "mapping_csv": str(mapping_path.relative_to(output_dir)),
        })

    samples = _evaluate_random_jobs(
        benchmark=benchmark,
        graph=graph,
        params=params,
        weights=weights,
        omnet_config=omnet_config,
        cost_reference=original_ref.cost_reference,
        baseline_makespan_s=original_ref.scalars.makespan_s,
        jobs=sample_jobs,
        workers=workers,
        verbose=verbose,
    )

    selected = select_distribution_records(samples)
    for label, sample in selected.items():
        write_static_csv(
            graph,
            sample.assignment,
            selected_dir / f"{label}.csv",
            comment=f"{label} selected from Random Mapping Ensemble",
        )
        _write_selected_artifact(
            benchmark=benchmark,
            output_dir=output_dir,
            selected_dir=selected_dir,
            label=label,
            sample=sample,
            graph=graph,
        )

    rows = compact_sample_rows(samples)
    write_compact_outputs(
        rows,
        random_dir / "samples.csv",
        random_dir / "samples.json",
    )
    invalid_rows = [row for row in rows if not _truthy(row.get("valid_for_cost"))]
    _write_rows(invalid_rows, random_dir / "invalid_samples.csv", random_dir / "invalid_samples.json")

    elapsed_s = time.perf_counter() - start
    full_metrics = {
        "name": benchmark,
        "kind": "RandomMappingEnsemble",
        "original": original_metrics,
        "random_best": selected["RandomBest"].metrics,
        "random_median": selected["RandomMedian"].metrics,
        "random_p10": selected["RandomP10"].metrics,
        "random_p90": selected["RandomP90"].metrics,
        "selection": {
            label: {
                "sample_id": sample.sample_id,
                "sample_seed": sample.sample_seed,
                "mapping_csv": sample.mapping_csv,
                "TR2_composite_cost": sample.cost,
            }
            for label, sample in selected.items()
        },
        "run_status": {
            "n_requested": random_n,
            "n_valid": sum(1 for sample in samples if sample.valid_for_cost),
            "n_invalid": sum(1 for sample in samples if not sample.valid_for_cost),
            "elapsed_s": elapsed_s,
        },
        "config": {
            "source_csv": str(csv_path),
            "random_n": random_n,
            "seed_base": seed_base,
            "sample_seeds": [seed_base + i for i in range(random_n)],
            "pe_list": list(range(params.num_pes)),
            "rows": params.rows,
            "cols": params.cols,
            "num_pes": params.num_pes,
            "workers": workers,
            "weights": asdict(weights),
            "cost_reference": asdict(original_ref.cost_reference),
            "random_generator_rule": (
                "assignment[tid] = random.Random(sample_seed).randrange(num_pes) "
                "for each tid in graph.mappable_task_ids"
            ),
        },
    }

    (random_dir / "metrics.json").write_text(
        json.dumps(full_metrics, indent=2),
        encoding="utf-8",
    )
    summary = _summary_text(benchmark, full_metrics)
    (random_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    (original_dir / "summary.txt").write_text(
        _original_summary_text(benchmark, original_metrics) + "\n",
        encoding="utf-8",
    )

    print(summary)
    return {
        "benchmark": benchmark,
        "random_n": random_n,
        "seed_base": seed_base,
        "workers": workers,
        "n_valid": full_metrics["run_status"]["n_valid"],
        "n_invalid": full_metrics["run_status"]["n_invalid"],
        "original_cost": _cost(original_metrics),
        "random_best_cost": selected["RandomBest"].cost,
        "random_median_cost": selected["RandomMedian"].cost,
        "random_p10_cost": selected["RandomP10"].cost,
        "random_p90_cost": selected["RandomP90"].cost,
        "elapsed_s": elapsed_s,
    }


def _evaluate_random_jobs(
    benchmark: str,
    graph: TaskGraph,
    params: SimParams,
    weights: CostWeights,
    omnet_config: OmnetRunConfig,
    cost_reference,
    baseline_makespan_s: float,
    jobs: list[dict[str, object]],
    workers: int,
    verbose: bool,
) -> list[RandomSampleRecord]:
    if workers <= 1:
        samples: list[RandomSampleRecord] = []
        for idx, job in enumerate(jobs, start=1):
            if verbose:
                print(
                    f"[{benchmark}] random sample {idx}/{len(jobs)} "
                    f"seed={job['sample_seed']}"
                )
            samples.append(_evaluate_random_sample_worker(
                benchmark=benchmark,
                graph=graph,
                params=params,
                weights=weights,
                omnet_config=omnet_config,
                cost_reference=cost_reference,
                baseline_makespan_s=baseline_makespan_s,
                job=job,
            ))
        return samples

    samples_by_id: dict[int, RandomSampleRecord] = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for job in jobs:
            fut = ex.submit(
                _evaluate_random_sample_worker,
                benchmark,
                graph,
                params,
                weights,
                omnet_config,
                cost_reference,
                baseline_makespan_s,
                job,
            )
            futures[fut] = job
        for fut in as_completed(futures):
            job = futures[fut]
            completed += 1
            try:
                sample = fut.result()
            except Exception as exc:  # defensive: keep one bad worker from losing the run
                sample = RandomSampleRecord(
                    sample_id=int(job["sample_id"]),
                    sample_seed=int(job["sample_seed"]),
                    assignment={int(k): int(v) for k, v in dict(job["assignment"]).items()},
                    mapping_csv=str(job["mapping_csv"]),
                    metrics={"run_status": {
                        "run_ok": False,
                        "valid_for_cost": False,
                        "failure_reason": f"worker exception: {exc}",
                    }},
                    valid_for_cost=False,
                    failure_reason=f"worker exception: {exc}",
                )
            samples_by_id[sample.sample_id] = sample
            if verbose or completed == len(jobs) or completed % max(1, len(jobs) // 20) == 0:
                valid = sum(1 for item in samples_by_id.values() if item.valid_for_cost)
                invalid = sum(1 for item in samples_by_id.values() if not item.valid_for_cost)
                print(
                    f"[{benchmark}] completed {completed}/{len(jobs)} "
                    f"valid={valid} invalid={invalid}"
                )
    return [samples_by_id[i] for i in sorted(samples_by_id)]


def _evaluate_random_sample_worker(
    benchmark: str,
    graph: TaskGraph,
    params: SimParams,
    weights: CostWeights,
    omnet_config: OmnetRunConfig,
    cost_reference,
    baseline_makespan_s: float,
    job: dict[str, object],
) -> RandomSampleRecord:
    assignment = {int(k): int(v) for k, v in dict(job["assignment"]).items()}
    evaluator = build_omnet_evaluator(omnet_config)
    cost_model = build_cost_model(graph, params, weights, reference=cost_reference)
    scalars = evaluator.evaluate(graph, assignment)
    if scalars.valid_for_cost:
        metrics = grouped_metrics(
            graph,
            assignment,
            scalars,
            cost_model,
            params,
            baseline_makespan_s=baseline_makespan_s,
        )
        failure_reason = ""
        valid_for_cost = True
    else:
        metrics = {
            "run_status": {
                "run_ok": scalars.run_ok,
                "valid_for_cost": scalars.valid_for_cost,
                "failure_reason": scalars.failure_reason,
                "temperature_source": scalars.temperature_source,
                "temperature_complete": scalars.temperature_complete,
                "parsed_pe_count": scalars.parsed_pe_count,
                "parsed_temp_timepoints": scalars.parsed_temp_timepoints,
            }
        }
        failure_reason = scalars.failure_reason
        valid_for_cost = False

    return RandomSampleRecord(
        sample_id=int(job["sample_id"]),
        sample_seed=int(job["sample_seed"]),
        assignment=assignment,
        mapping_csv=str(job["mapping_csv"]),
        metrics=metrics,
        valid_for_cost=valid_for_cost,
        failure_reason=failure_reason,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Random Mapping Ensemble with B-2-compatible OMNeT++ evaluation"
    )
    parser.add_argument(
        "--benchmarks",
        default="gemm,mpeg4,vopd,hnn",
        help="Comma-separated benchmark names: gemm,mpeg4,vopd,hnn",
    )
    parser.add_argument("--random-n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0, help="Base seed; samples use seed+i")
    parser.add_argument("--out", default="out/random-mapping-ensemble-v1")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")

    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--cols", type=int, default=4)

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


def _parse_benchmarks(value: str) -> list[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise ValueError("no benchmarks selected")
    unknown = [name for name in names if name not in BENCHMARKS]
    if unknown:
        raise ValueError(f"unknown benchmarks: {unknown}")
    return names


def _dry_run(
    benchmarks: list[str],
    params: SimParams,
    args: argparse.Namespace,
    omnet_config: OmnetRunConfig,
    output_dir: Path,
) -> None:
    print("Planned Random Mapping Ensemble runs:")
    print(f"  output={output_dir.resolve()}")
    print(f"  random_n={args.random_n} seed_base={args.seed}")
    print(f"  sample_seeds={args.seed}..{args.seed + args.random_n - 1}")
    print(f"  pe_list=0..{params.num_pes - 1} rows={params.rows} cols={params.cols}")
    print(f"  estimated_omnet_runs={len(benchmarks) * (1 + args.random_n)}")
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


def _guard_output_path(output_dir: Path, benchmarks: list[str], force: bool) -> None:
    resolved = output_dir.resolve()
    for protected in PROTECTED_OUTPUT_DIRS:
        if resolved == protected or _is_under(resolved, protected):
            raise RuntimeError(
                f"refusing to write into protected paper result directory: {protected}"
            )

    try:
        rel_parts = resolved.relative_to((_PROJ / "out").resolve()).parts
    except ValueError:
        rel_parts = resolved.parts
    if any(part.startswith("B-2") for part in rel_parts):
        raise RuntimeError(
            "refusing to write Random Mapping Ensemble output into a B-2 output path"
        )

    if force:
        return

    collisions: list[Path] = []
    for benchmark in benchmarks:
        for path in [
            output_dir / benchmark / "original" / "metrics.json",
            output_dir / benchmark / "original" / "mapping.csv",
            output_dir / benchmark / "random" / "metrics.json",
            output_dir / benchmark / "random" / "samples.csv",
            output_dir / benchmark / "random" / "samples.json",
            output_dir / benchmark / "random" / "summary.txt",
        ]:
            if path.exists():
                collisions.append(path)

    if collisions:
        details = "\n".join(f"  {path.resolve()}" for path in collisions[:20])
        raise RuntimeError(
            "refusing to overwrite existing Random Mapping Ensemble outputs. "
            "Choose a new --out directory or pass --force:\n"
            f"{details}"
        )


def _write_run_summary(output_dir: Path, records: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "runs_summary.json").write_text(
        json.dumps(records, indent=2),
        encoding="utf-8",
    )
    if not records:
        (output_dir / "runs_summary.csv").write_text("", encoding="utf-8")
        return
    import csv

    with (output_dir / "runs_summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def _write_selected_artifact(
    benchmark: str,
    output_dir: Path,
    selected_dir: Path,
    label: str,
    sample: RandomSampleRecord,
    graph: TaskGraph,
) -> None:
    label_slug = {
        "RandomBest": "random_best",
        "RandomMedian": "random_median",
        "RandomP10": "random_p10",
        "RandomP90": "random_p90",
    }.get(label, label.lower())
    artifact_dir = selected_dir / label_slug
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("mapping.csv", "remapped.csv"):
        write_static_csv(
            graph,
            sample.assignment,
            artifact_dir / filename,
            comment=f"{label_slug} selected from Random Mapping Ensemble",
        )
    payload = {
        "name": benchmark,
        "kind": label_slug,
        "sample_id": sample.sample_id,
        "sample_seed": sample.sample_seed,
        "mapping_csv": sample.mapping_csv,
        "metrics": sample.metrics,
        "assignment": sample.assignment,
    }
    (artifact_dir / "metrics.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _write_rows(rows: list[dict[str, object]], csv_path: Path, json_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _summary_text(benchmark: str, full: dict[str, object]) -> str:
    selection = full["selection"]
    status = full["run_status"]
    return "\n".join([
        f"[{benchmark}] Random Mapping Ensemble",
        f"  samples: requested={status['n_requested']} valid={status['n_valid']} invalid={status['n_invalid']}",
        f"  Original cost:     {_cost(full['original']):.4f}",
        f"  RandomBest cost:   {selection['RandomBest']['TR2_composite_cost']:.4f} "
        f"(sample={selection['RandomBest']['sample_id']}, seed={selection['RandomBest']['sample_seed']})",
        f"  RandomMedian cost: {selection['RandomMedian']['TR2_composite_cost']:.4f} "
        f"(sample={selection['RandomMedian']['sample_id']}, seed={selection['RandomMedian']['sample_seed']})",
        f"  RandomP10/P90:     {selection['RandomP10']['TR2_composite_cost']:.4f} / "
        f"{selection['RandomP90']['TR2_composite_cost']:.4f}",
    ])


def _original_summary_text(benchmark: str, metrics: dict[str, object]) -> str:
    return f"[{benchmark}] Original cost={_cost(metrics):.4f}"


def _cost(metrics: object) -> float:
    if not isinstance(metrics, dict):
        return float("nan")
    value = metrics.get("tradeoff", {}).get("TR2_composite_cost", float("nan"))
    return float(value) if isinstance(value, (int, float)) else float("nan")


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


if __name__ == "__main__":
    sys.exit(main())
