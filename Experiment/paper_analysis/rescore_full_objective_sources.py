"""Re-score HNOCS mappings under the full GA objective and emit source CSVs.

This script is intentionally read-only with respect to existing experiment
results. It reads metrics/history/summary artifacts and writes derived CSVs to
an output analysis directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


WORKLOADS = ("gemm", "mpeg4", "vopd", "hnn")
ABLATIONS = ("thermal-only", "comm-only", "wout-thermal", "wout-comm")
RANDOM_SELECTIONS = (
    ("RandomBest", "random_best"),
    ("RandomMedian", "random_median"),
    ("RandomP10", "random_p10"),
    ("RandomP90", "random_p90"),
)
REFERENCE_METHOD = "ReferenceMapping"
MAIN_BASELINE_METHODS = {"Thermal-SA-TAS", "CommAware-Heuristic"}
RANDOM_BASELINE_METHODS = {"RandomBest", "RandomMedian", "RandomP10", "RandomP90"}
SUMMARY_CSV_NAMES = {
    "runs_summary.csv",
    "aggregate_summary.csv",
    "validity_report.csv",
    "convergence_report.csv",
    "ga_vs_random_summary.csv",
}

FULL_WEIGHTS = {
    "w_T": 1.0,
    "w_sigma": 1.0,
    "w_hot": 0.6,
    "w_makespan": 1.2,
    "w_H": 0.4,
    "w_congestion": 0.7,
    "w_D": 0.4,
    "w_L": 0.2,
    "w_E": 0.5,
}

REFERENCE_KEYS = (
    "peak_excess_K",
    "sigma_T_K",
    "N_hot",
    "makespan_s",
    "pe_optical_comm_energy_J",
    "eta_dvfs_pct",
    "comm_cost",
    "congestion_cost",
    "load_imbalance",
)

RAW_KEYS = (
    "T_max_K",
    "sigma_T_K",
    "N_hot",
    "makespan_s",
    "eta_dvfs_pct",
    "raw_comm_cost",
    "raw_congestion_cost",
    "raw_load_imbalance",
    "pe_optical_comm_energy_J",
)

TERM_KEYS = (
    "f_thermal",
    "f_sigma",
    "f_hot",
    "f_makespan",
    "f_comm",
    "f_congestion",
    "f_dvfs",
    "f_load",
    "f_energy",
)

METRIC_DEFS = (
    ("thermal_safety", "T_max_C", "T_max", "C", "T_max_C"),
    ("thermal_safety", "sigma_T_K", "sigma_T", "K", "sigma_T_K"),
    ("thermal_safety", "N_hot", "N_hot", "count", "N_hot"),
    ("performance", "makespan_us", "makespan", "us", "makespan_us"),
    ("performance", "DVFS_penalty_pct", "DVFS", "%", "DVFS_penalty_pct"),
    ("communication_pressure", "comm_cost", "comm", "byte-hop", "comm_cost"),
    ("communication_pressure", "congestion_proxy", "congestion proxy", "byte", "congestion_proxy"),
    ("mapping_balance", "load_imbalance", "load imbalance", "ratio", "load_imbalance"),
    ("energy", "total_PE_optical_energy_mJ", "total energy", "mJ", "total_PE_optical_energy_mJ"),
)

GA_SOURCE_ROOT = "B-2-v4"
ABLATION_SOURCE_ROOT = "B-2-v4-ablation"
RANDOM_SOURCE_ROOT = "random-mapping-ensemble-v2"
COMMAWARE_SOURCE_ROOT = "comm-aware-baseline-v1"
TAS_SOURCE_ROOT = "thermal-sa-tas-results"

DEFAULT_AMBIENT_K = 318.15
FLOAT_TOL = 1e-9


@dataclass
class CanonicalRun:
    workload: str
    method: str
    method_family: str
    source_root: str
    metrics_path: Path
    history_path: Path | None
    reference_source_path: Path | None
    seed: str
    seed_type: str
    ablation: str
    selection_policy: str
    source_objective_name: str
    source_objective_weights: str
    stored_TR2_composite_cost: float
    raw: dict[str, float]
    terms: dict[str, float]
    score: float
    run_status: dict[str, Any]
    history_status: dict[str, Any]
    valid: bool
    validity_notes: str
    extra: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-score existing HNOCS mappings under the full objective"
    )
    parser.add_argument(
        "--results-root",
        default=str(Path("out") / "experimental results"),
        help="Root containing B-2-v4, ablation, and baseline result folders",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output directory for derived analysis CSV files",
    )
    parser.add_argument(
        "--workloads",
        default=",".join(WORKLOADS),
        help="Comma-separated workload names",
    )
    parser.add_argument(
        "--seeds",
        default="40-49",
        help="Seed list/range, for example 40-49 or 40,41,42",
    )
    args = parser.parse_args()

    results_root = Path(args.results_root)
    out_dir = Path(args.out) if args.out else results_root / "analysis_full_objective_rescore"
    workloads = tuple(item.strip().lower() for item in args.workloads.split(",") if item.strip())
    seeds = parse_seeds(args.seeds)

    if not results_root.exists():
        raise FileNotFoundError(f"results root does not exist: {results_root}")

    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = build_manifest(results_root, out_dir)
    write_csv(out_dir / "manifest.csv", manifest_rows)
    schema_rows = build_schema_rows()
    write_csv(out_dir / "canonical_parser_schema.csv", schema_rows)

    canonical_refs, ambient_by_workload = load_canonical_references(results_root, workloads, seeds)
    reference_rows: list[dict[str, Any]] = []
    formula_rows: list[dict[str, Any]] = []
    validity_rows: list[dict[str, Any]] = []
    all_runs: list[CanonicalRun] = []
    reference_index: dict[tuple[str, str, str], CanonicalRun] = {}
    workload_reference_index: dict[str, CanonicalRun] = {}

    for run in load_full_ga_runs(
        results_root, workloads, seeds, canonical_refs, ambient_by_workload, reference_rows, formula_rows
    ):
        all_runs.append(run)
        if run.method == REFERENCE_METHOD:
            reference_index[(run.source_root, run.workload, run.seed)] = run
            reference_index[(run.source_root, run.workload.lower(), run.seed)] = run
            workload_reference_index.setdefault(run.workload, run)

    ablation_runs = list(load_ablation_runs(
        results_root, workloads, seeds, canonical_refs, ambient_by_workload, reference_rows
    ))
    all_runs.extend(ablation_runs)

    external_runs = list(load_external_method_runs(
        results_root, workloads, seeds, canonical_refs, ambient_by_workload, reference_rows
    ))
    all_runs.extend(external_runs)

    for run in all_runs:
        validity_rows.append(validity_row(run))

    write_csv(out_dir / "cost_reference_audit.csv", reference_rows)
    write_csv(out_dir / "formula_validation_full_ga.csv", formula_rows)
    write_csv(out_dir / "validity_audit.csv", validity_rows)
    write_csv(out_dir / "full_objective_rescore_runs.csv", [run_to_row(run) for run in all_runs])

    ablation_comparisons = build_ablation_comparisons(ablation_runs, reference_index)
    external_comparisons = build_external_comparisons(external_runs, workload_reference_index, reference_index)
    main_baseline_comparisons = [
        row for row in external_comparisons if row.get("method") in MAIN_BASELINE_METHODS
    ]
    random_comparisons = [
        row for row in external_comparisons if row.get("method") in RANDOM_BASELINE_METHODS
    ]
    write_csv(out_dir / "ablation_vs_reference_full_objective_runs.csv", ablation_comparisons)
    write_csv(out_dir / "ablation_vs_reference_full_objective_summary.csv", summarize_comparisons(ablation_comparisons))
    write_csv(out_dir / "main_baseline_full_objective_runs.csv", main_baseline_comparisons)
    write_csv(out_dir / "main_baseline_full_objective_summary.csv", summarize_comparisons(main_baseline_comparisons))
    write_csv(out_dir / "random_ensemble_full_objective_source.csv", random_comparisons)
    write_csv(out_dir / "random_ensemble_full_objective_summary.csv", summarize_comparisons(random_comparisons))

    figure2_rows = build_figure2_source(all_runs, reference_index)
    figure3_rows = build_figure3_source(all_runs, reference_index)
    figure4_rows = build_figure4_source(all_runs, reference_index, workload_reference_index)
    write_csv(out_dir / "figure2_composite_cost_source.csv", figure2_rows)
    write_csv(out_dir / "figure3_nine_metric_grouped_source.csv", figure3_rows)
    write_csv(out_dir / "figure4_baseline_and_ablation_source.csv", figure4_rows)

    spot_checks = build_spot_checks(all_runs, reference_index)
    write_csv(out_dir / "spot_check_samples.csv", spot_checks)

    print(f"Wrote {len(manifest_rows)} manifest rows")
    print(f"Wrote {len(all_runs)} canonical run rows")
    print(f"Wrote {len(ablation_comparisons)} ablation-vs-reference comparison rows")
    print(f"Wrote {len(main_baseline_comparisons)} main-baseline comparison rows")
    print(f"Wrote {len(random_comparisons)} random-ensemble comparison rows")
    print(f"Output directory: {out_dir.resolve()}")
    return 0


def parse_seeds(text: str) -> tuple[int, ...]:
    seeds: list[int] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            step = 1 if end >= start else -1
            seeds.extend(range(start, end + step, step))
        else:
            seeds.append(int(item))
    return tuple(dict.fromkeys(seeds))


def build_manifest(results_root: Path, out_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results_root.rglob("*")):
        if not path.is_file():
            continue
        if out_dir == path or out_dir in path.parents:
            continue
        file_type = ""
        if path.name == "metrics.json":
            file_type = "metrics_json"
        elif path.name == "history.json":
            file_type = "history_json"
        elif path.name in SUMMARY_CSV_NAMES:
            file_type = "summary_csv"
        if not file_type:
            continue
        rel = path.relative_to(results_root)
        rows.append({
            "file_type": file_type,
            "source_root": rel.parts[0] if rel.parts else "",
            "relative_path": str(rel),
            "absolute_path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "last_write_time": path.stat().st_mtime,
        })
    return rows


def build_schema_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source, node in (
        ("B-2-v4", "baseline or b2"),
        ("B-2-v4-ablation", "baseline or b2"),
        ("random-mapping-ensemble-v2", "metrics wrapper or selected metrics"),
        ("comm-aware-baseline-v1", "top-level metrics"),
        ("thermal-sa-tas-results", "metrics wrapper"),
    ):
        for canonical, candidates in (
            ("T_max_K", "cost_terms.T_max_K; thermal.T1_pe_peak_temp_K"),
            ("sigma_T_K", "cost_terms.sigma_T_K; thermal.T3_temp_std_K"),
            ("N_hot", "cost_terms.N_hot; thermal.T5_over_throttle_count"),
            ("makespan_s", "cost_terms.makespan_s; performance.P1_makespan_s"),
            ("eta_dvfs_pct", "cost_terms.eta_dvfs_pct; performance.P3_dvfs_penalty_pct"),
            ("raw_comm_cost", "cost_terms.raw_comm_cost; communication.C1_total_comm_cost"),
            ("raw_congestion_cost", "cost_terms.raw_congestion_cost"),
            ("raw_load_imbalance", "cost_terms.raw_load_imbalance"),
            ("pe_optical_comm_energy_J", "cost_terms.pe_optical_comm_energy_J; energy.E7_pe_optical_comm_energy_J"),
        ):
            rows.append({
                "source_root": source,
                "metrics_node": node,
                "canonical_field": canonical,
                "candidate_paths": candidates,
                "notes": "raw field used for full-objective rescore",
            })
    return rows


def load_canonical_references(
    results_root: Path,
    workloads: Iterable[str],
    seeds: Iterable[int],
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    refs: dict[str, dict[str, float]] = {}
    ambient: dict[str, float] = {}
    for workload in workloads:
        for seed in seeds:
            path = results_root / GA_SOURCE_ROOT / f"seed_{seed}" / "gen_60" / workload / "metrics.json"
            if not path.exists():
                continue
            payload = read_json(path)
            ref = reference_from_config(payload.get("config", {}))
            baseline = payload.get("baseline", {})
            raw = extract_raw_metrics(baseline)
            if ref:
                refs[workload] = ref
                tmax = raw.get("T_max_K", math.nan)
                peak_excess = ref.get("peak_excess_K", math.nan)
                if finite(tmax) and finite(peak_excess):
                    ambient[workload] = tmax - peak_excess
                else:
                    ambient[workload] = DEFAULT_AMBIENT_K
                break
        if workload not in refs:
            raise FileNotFoundError(f"no canonical B-2-v4 reference found for {workload}")
    return refs, ambient


def load_full_ga_runs(
    results_root: Path,
    workloads: Iterable[str],
    seeds: Iterable[int],
    canonical_refs: dict[str, dict[str, float]],
    ambient_by_workload: dict[str, float],
    reference_rows: list[dict[str, Any]],
    formula_rows: list[dict[str, Any]],
) -> Iterable[CanonicalRun]:
    for seed in seeds:
        for workload in workloads:
            path = results_root / GA_SOURCE_ROOT / f"seed_{seed}" / "gen_60" / workload / "metrics.json"
            history_path = path.with_name("history.json")
            if not path.exists():
                continue
            payload = read_json(path)
            config = payload.get("config", {})
            ref = reference_from_config(config)
            audit_reference(reference_rows, workload, "Full-GA", GA_SOURCE_ROOT, path, ref, canonical_refs[workload])
            source_weights = weights_from_config(config)

            for method, node_name, family in (
                (REFERENCE_METHOD, "baseline", "reference_mapping"),
                ("Full-GA", "b2", "proposed"),
            ):
                metrics = payload.get(node_name, {})
                run = make_run(
                    workload=workload,
                    method=method,
                    method_family=family,
                    source_root=GA_SOURCE_ROOT,
                    metrics_path=path,
                    history_path=history_path,
                    reference_source_path=path,
                    seed=str(seed),
                    seed_type="ga_seed",
                    ablation="",
                    selection_policy="",
                    source_objective_name=str(config.get("fitness", "baseline_normalized_v2")),
                    source_objective_weights=source_weights,
                    metrics=metrics,
                    reference=ref,
                    ambient_k=ambient_by_workload[workload],
                    stored_TR2_composite_cost=to_float(
                        get_nested(metrics, ("tradeoff", "TR2_composite_cost"))
                    ),
                    extra={
                        "configured_generations": payload.get("config", {}).get("num_generations", ""),
                        "actual_generations": payload.get("b2_generations", ""),
                        "converged": payload.get("b2_converged", ""),
                        "elapsed_s": payload.get("b2_elapsed_s", ""),
                    },
                )
                formula_rows.append(formula_validation_row(run))
                yield run


def load_ablation_runs(
    results_root: Path,
    workloads: Iterable[str],
    seeds: Iterable[int],
    canonical_refs: dict[str, dict[str, float]],
    ambient_by_workload: dict[str, float],
    reference_rows: list[dict[str, Any]],
) -> Iterable[CanonicalRun]:
    for ablation in ABLATIONS:
        for seed in seeds:
            for workload in workloads:
                path = (
                    results_root
                    / ABLATION_SOURCE_ROOT
                    / ablation
                    / f"seed_{seed}"
                    / "gen_60"
                    / workload
                    / "metrics.json"
                )
                history_path = path.with_name("history.json")
                if not path.exists():
                    continue
                payload = read_json(path)
                config = payload.get("config", {})
                ref = reference_from_config(config)
                audit_reference(reference_rows, workload, ablation, ABLATION_SOURCE_ROOT, path, ref, canonical_refs[workload])
                metrics = payload.get("b2", {})
                yield make_run(
                    workload=workload,
                    method=ablation,
                    method_family="ablation",
                    source_root=ABLATION_SOURCE_ROOT,
                    metrics_path=path,
                    history_path=history_path,
                    reference_source_path=path,
                    seed=str(seed),
                    seed_type="ga_seed",
                    ablation=ablation,
                    selection_policy="",
                    source_objective_name=str(config.get("fitness", "baseline_normalized_v2")),
                    source_objective_weights=weights_from_config(config),
                    metrics=metrics,
                    reference=ref,
                    ambient_k=ambient_by_workload[workload],
                    stored_TR2_composite_cost=to_float(
                        get_nested(metrics, ("tradeoff", "TR2_composite_cost"))
                    ),
                    extra={
                        "configured_generations": config.get("num_generations", ""),
                        "actual_generations": payload.get("b2_generations", ""),
                        "converged": payload.get("b2_converged", ""),
                        "elapsed_s": payload.get("b2_elapsed_s", ""),
                    },
                )


def load_external_method_runs(
    results_root: Path,
    workloads: Iterable[str],
    seeds: Iterable[int],
    canonical_refs: dict[str, dict[str, float]],
    ambient_by_workload: dict[str, float],
    reference_rows: list[dict[str, Any]],
) -> Iterable[CanonicalRun]:
    yield from load_random_runs(results_root, workloads, canonical_refs, ambient_by_workload, reference_rows)
    yield from load_comm_aware_runs(results_root, workloads, canonical_refs, ambient_by_workload, reference_rows)
    yield from load_tas_runs(results_root, workloads, seeds, canonical_refs, ambient_by_workload, reference_rows)


def load_random_runs(
    results_root: Path,
    workloads: Iterable[str],
    canonical_refs: dict[str, dict[str, float]],
    ambient_by_workload: dict[str, float],
    reference_rows: list[dict[str, Any]],
) -> Iterable[CanonicalRun]:
    root = results_root / RANDOM_SOURCE_ROOT
    for workload in workloads:
        parent_path = root / workload / "random" / "metrics.json"
        original_path = root / workload / "original" / "metrics.json"
        if not original_path.exists():
            continue
        ref_payload_path = parent_path if parent_path.exists() else original_path
        ref_payload = read_json(ref_payload_path)
        ref = reference_from_config(ref_payload.get("config", {}))
        audit_reference(reference_rows, workload, "RandomReference", RANDOM_SOURCE_ROOT, ref_payload_path, ref, canonical_refs[workload])

        original_payload = read_json(original_path)
        original_metrics = unwrap_metrics(original_payload)
        yield make_run(
            workload=workload,
            method="RandomReferenceMapping",
            method_family="reference_mapping",
            source_root=RANDOM_SOURCE_ROOT,
            metrics_path=original_path,
            history_path=None,
            reference_source_path=ref_payload_path,
            seed="",
            seed_type="none",
            ablation="",
            selection_policy="ReferenceMapping",
            source_objective_name="full_objective_reference",
            source_objective_weights=weights_from_config(original_payload.get("config", {})),
            metrics=original_metrics,
            reference=ref,
            ambient_k=ambient_by_workload[workload],
            stored_TR2_composite_cost=to_float(
                get_nested(original_metrics, ("tradeoff", "TR2_composite_cost"))
            ),
            extra={"requested_samples": get_nested(ref_payload, ("config", "random_n"))},
        )

        for label, dirname in RANDOM_SELECTIONS:
            path = root / workload / "random" / "selected" / dirname / "metrics.json"
            if not path.exists():
                continue
            payload = read_json(path)
            metrics = unwrap_metrics(payload)
            sample_seed = payload.get("sample_seed", "")
            yield make_run(
                workload=workload,
                method=label,
                method_family="supplement_random_baseline",
                source_root=RANDOM_SOURCE_ROOT,
                metrics_path=path,
                history_path=None,
                reference_source_path=ref_payload_path,
                seed=str(sample_seed) if sample_seed != "" else "",
                seed_type="random_sample_seed",
                ablation="",
                selection_policy=label,
                source_objective_name="full_objective_reference",
                source_objective_weights=weights_from_config(ref_payload.get("config", {})),
                metrics=metrics,
                reference=ref,
                ambient_k=ambient_by_workload[workload],
                stored_TR2_composite_cost=to_float(
                    get_nested(metrics, ("tradeoff", "TR2_composite_cost"))
                ),
                extra={
                    "sample_id": payload.get("sample_id", ""),
                    "sample_seed": sample_seed,
                    "mapping_csv": payload.get("mapping_csv", ""),
                    "requested_samples": get_nested(ref_payload, ("config", "random_n")),
                },
            )


def load_comm_aware_runs(
    results_root: Path,
    workloads: Iterable[str],
    canonical_refs: dict[str, dict[str, float]],
    ambient_by_workload: dict[str, float],
    reference_rows: list[dict[str, Any]],
) -> Iterable[CanonicalRun]:
    root = results_root / COMMAWARE_SOURCE_ROOT
    for workload in workloads:
        for method, subdir, family in (
            ("CommAwareReferenceMapping", "original", "reference_mapping"),
            ("CommAware-Heuristic", "comm_aware", "main_baseline"),
        ):
            path = root / workload / subdir / "metrics.json"
            if not path.exists():
                continue
            payload = read_json(path)
            ref = reference_from_config(payload.get("config", {}))
            audit_reference(reference_rows, workload, method, COMMAWARE_SOURCE_ROOT, path, ref, canonical_refs[workload])
            metrics = unwrap_metrics(payload)
            yield make_run(
                workload=workload,
                method=method,
                method_family=family,
                source_root=COMMAWARE_SOURCE_ROOT,
                metrics_path=path,
                history_path=None,
                reference_source_path=path,
                seed="",
                seed_type="none",
                ablation="",
                selection_policy=method,
                source_objective_name=str(get_nested(payload, ("config", "objective")) or "comm_aware_proxy"),
                source_objective_weights=weights_from_config(payload.get("config", {})),
                metrics=metrics,
                reference=ref,
                ambient_k=ambient_by_workload[workload],
                stored_TR2_composite_cost=to_float(
                    get_nested(metrics, ("tradeoff", "TR2_composite_cost"))
                ),
                extra={},
            )


def load_tas_runs(
    results_root: Path,
    workloads: Iterable[str],
    seeds: Iterable[int],
    canonical_refs: dict[str, dict[str, float]],
    ambient_by_workload: dict[str, float],
    reference_rows: list[dict[str, Any]],
) -> Iterable[CanonicalRun]:
    root = results_root / TAS_SOURCE_ROOT / "final"
    for seed in seeds:
        for workload in workloads:
            for method, subdir, family in (
                ("Thermal-SA-TAS-ReferenceMapping", "original", "reference_mapping"),
                ("Thermal-SA-TAS", "thermal_sa_tas", "main_baseline"),
            ):
                path = root / f"seed_{seed}" / workload / subdir / "metrics.json"
                history_path = path.with_name("history.json") if subdir == "thermal_sa_tas" else None
                if not path.exists():
                    continue
                payload = read_json(path)
                ref = reference_from_config(payload.get("config", {}))
                audit_reference(reference_rows, workload, method, TAS_SOURCE_ROOT, path, ref, canonical_refs[workload])
                metrics = unwrap_metrics(payload)
                yield make_run(
                    workload=workload,
                    method=method,
                    method_family=family,
                    source_root=TAS_SOURCE_ROOT,
                    metrics_path=path,
                    history_path=history_path if history_path and history_path.exists() else None,
                    reference_source_path=path,
                    seed=str(seed),
                    seed_type="tas_seed",
                    ablation="",
                    selection_policy=method,
                    source_objective_name="thermal_sa_tas_proxy_then_full_eval",
                    source_objective_weights=weights_from_config(payload.get("config", {})),
                    metrics=metrics,
                    reference=ref,
                    ambient_k=ambient_by_workload[workload],
                    stored_TR2_composite_cost=to_float(
                        get_nested(metrics, ("tradeoff", "TR2_composite_cost"))
                    ),
                    extra={},
                )


def make_run(
    *,
    workload: str,
    method: str,
    method_family: str,
    source_root: str,
    metrics_path: Path,
    history_path: Path | None,
    reference_source_path: Path | None,
    seed: str,
    seed_type: str,
    ablation: str,
    selection_policy: str,
    source_objective_name: str,
    source_objective_weights: str,
    metrics: dict[str, Any],
    reference: dict[str, float],
    ambient_k: float,
    stored_TR2_composite_cost: float,
    extra: dict[str, Any],
) -> CanonicalRun:
    raw = extract_raw_metrics(metrics)
    terms, score = rescore_full_objective(raw, reference, ambient_k, num_pes=16)
    run_status = run_status_from_metrics(metrics)
    history_status = inspect_history(history_path)
    valid, notes = determine_validity(raw, run_status, history_status, score)
    return CanonicalRun(
        workload=workload.upper(),
        method=method,
        method_family=method_family,
        source_root=source_root,
        metrics_path=metrics_path,
        history_path=history_path,
        reference_source_path=reference_source_path,
        seed=seed,
        seed_type=seed_type,
        ablation=ablation,
        selection_policy=selection_policy,
        source_objective_name=source_objective_name,
        source_objective_weights=source_objective_weights,
        stored_TR2_composite_cost=stored_TR2_composite_cost,
        raw=raw,
        terms=terms,
        score=score,
        run_status=run_status,
        history_status=history_status,
        valid=valid,
        validity_notes=notes,
        extra=extra,
    )


def extract_raw_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    cost_terms = get_nested(metrics, ("tradeoff", "cost_terms"))
    if not isinstance(cost_terms, dict):
        cost_terms = {}
    raw = {
        "T_max_K": first_float(
            cost_terms.get("T_max_K"),
            get_nested(metrics, ("thermal", "T1_pe_peak_temp_K")),
        ),
        "sigma_T_K": first_float(
            cost_terms.get("sigma_T_K"),
            get_nested(metrics, ("thermal", "T3_temp_std_K")),
        ),
        "N_hot": first_float(
            cost_terms.get("N_hot"),
            get_nested(metrics, ("thermal", "T5_over_throttle_count")),
        ),
        "makespan_s": first_float(
            cost_terms.get("makespan_s"),
            get_nested(metrics, ("performance", "P1_makespan_s")),
        ),
        "eta_dvfs_pct": first_float(
            cost_terms.get("eta_dvfs_pct"),
            get_nested(metrics, ("performance", "P3_dvfs_penalty_pct")),
        ),
        "raw_comm_cost": first_float(
            cost_terms.get("raw_comm_cost"),
            get_nested(metrics, ("communication", "C1_total_comm_cost")),
        ),
        "raw_congestion_cost": first_float(cost_terms.get("raw_congestion_cost")),
        "raw_load_imbalance": first_float(cost_terms.get("raw_load_imbalance")),
        "pe_optical_comm_energy_J": first_float(
            cost_terms.get("pe_optical_comm_energy_J"),
            get_nested(metrics, ("energy", "E7_pe_optical_comm_energy_J")),
            get_nested(metrics, ("energy", "E7_total_energy_J")),
        ),
    }
    return raw


def rescore_full_objective(
    raw: dict[str, float],
    reference: dict[str, float],
    ambient_k: float,
    num_pes: int,
) -> tuple[dict[str, float], float]:
    tmax = raw.get("T_max_K", math.nan)
    terms = {
        "f_thermal": max(0.0, tmax - ambient_k) / positive(reference.get("peak_excess_K", math.nan))
        if finite(tmax) else math.nan,
        "f_sigma": divide(raw.get("sigma_T_K", math.nan), positive(reference.get("sigma_T_K", math.nan))),
        "f_hot": f_hot(raw.get("N_hot", math.nan), reference.get("N_hot", math.nan), num_pes),
        "f_makespan": divide(raw.get("makespan_s", math.nan), positive(reference.get("makespan_s", math.nan))),
        "f_comm": divide(raw.get("raw_comm_cost", math.nan), positive(reference.get("comm_cost", math.nan))),
        "f_congestion": divide(raw.get("raw_congestion_cost", math.nan), positive(reference.get("congestion_cost", math.nan))),
        "f_dvfs": f_dvfs(raw.get("eta_dvfs_pct", math.nan), reference.get("eta_dvfs_pct", math.nan)),
        "f_load": divide(raw.get("raw_load_imbalance", math.nan), positive(reference.get("load_imbalance", math.nan))),
        "f_energy": divide(raw.get("pe_optical_comm_energy_J", math.nan), positive(reference.get("pe_optical_comm_energy_J", math.nan))),
    }
    score = (
        FULL_WEIGHTS["w_T"] * terms["f_thermal"]
        + FULL_WEIGHTS["w_sigma"] * terms["f_sigma"]
        + FULL_WEIGHTS["w_hot"] * terms["f_hot"]
        + FULL_WEIGHTS["w_makespan"] * terms["f_makespan"]
        + FULL_WEIGHTS["w_H"] * terms["f_comm"]
        + FULL_WEIGHTS["w_congestion"] * terms["f_congestion"]
        + FULL_WEIGHTS["w_D"] * terms["f_dvfs"]
        + FULL_WEIGHTS["w_L"] * terms["f_load"]
        + FULL_WEIGHTS["w_E"] * terms["f_energy"]
    )
    return terms, score


def f_hot(value: float, ref: float, num_pes: int) -> float:
    if not finite(value) or value <= 0:
        return 0.0
    if finite(ref) and ref > 1e-12:
        return value / ref
    return value / max(num_pes, 1)


def f_dvfs(value: float, ref: float) -> float:
    if not finite(value):
        return math.nan
    if finite(ref) and ref > 1e-12:
        return value / ref
    return value / 100.0


def positive(value: float) -> float:
    return value if finite(value) and value > 1e-12 else 1.0


def divide(value: float, denom: float) -> float:
    if not finite(value) or not finite(denom):
        return math.nan
    return value / denom


def determine_validity(
    raw: dict[str, float],
    run_status: dict[str, Any],
    history_status: dict[str, Any],
    score: float,
) -> tuple[bool, str]:
    notes: list[str] = []
    if run_status.get("run_ok") is False:
        notes.append("run_ok_false")
    if run_status.get("valid_for_cost") is False:
        notes.append("valid_for_cost_false")
    tmax_k = raw.get("T_max_K", math.nan)
    if not finite(tmax_k) or tmax_k <= 0.0 or abs((tmax_k - 273.15) - (-273.1)) <= 0.2:
        notes.append("invalid_T_max")
    if not finite(raw.get("makespan_s", math.nan)) or raw.get("makespan_s", 0.0) <= 0.0:
        notes.append("invalid_makespan")
    if not finite(raw.get("pe_optical_comm_energy_J", math.nan)) or raw.get("pe_optical_comm_energy_J", 0.0) <= 0.0:
        notes.append("invalid_energy")
    if history_status.get("history_all_best_fitness_infinite") is True:
        notes.append("history_all_best_fitness_infinite")
    if not finite(score):
        notes.append("nonfinite_full_score")
    return not notes, ";".join(notes)


def inspect_history(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "history_path": "",
            "history_rows": "",
            "history_schema": "not_available",
            "history_all_best_fitness_infinite": "",
            "history_best_inf_gens": "",
            "history_avg_inf_gens": "",
            "history_worst_inf_gens": "",
        }
    payload = read_json(path)
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return {
            "history_path": str(path),
            "history_rows": 0,
            "history_schema": "empty_or_unknown",
            "history_all_best_fitness_infinite": "",
            "history_best_inf_gens": "",
            "history_avg_inf_gens": "",
            "history_worst_inf_gens": "",
        }
    first = rows[0] if isinstance(rows[0], dict) else {}
    if "best_fitness" not in first:
        return {
            "history_path": str(path),
            "history_rows": len(rows),
            "history_schema": "non_ga",
            "history_all_best_fitness_infinite": "",
            "history_best_inf_gens": "",
            "history_avg_inf_gens": "",
            "history_worst_inf_gens": "",
        }
    best_values = [to_float(row.get("best_fitness")) for row in rows if isinstance(row, dict)]
    avg_values = [to_float(row.get("avg_fitness")) for row in rows if isinstance(row, dict)]
    worst_values = [to_float(row.get("worst_fitness")) for row in rows if isinstance(row, dict)]
    best_inf = sum(not finite(value) for value in best_values)
    return {
        "history_path": str(path),
        "history_rows": len(rows),
        "history_schema": "ga",
        "history_all_best_fitness_infinite": bool(best_values) and best_inf == len(best_values),
        "history_best_inf_gens": best_inf,
        "history_avg_inf_gens": sum(not finite(value) for value in avg_values),
        "history_worst_inf_gens": sum(not finite(value) for value in worst_values),
    }


def audit_reference(
    rows: list[dict[str, Any]],
    workload: str,
    method: str,
    source_root: str,
    path: Path,
    ref: dict[str, float],
    canonical: dict[str, float],
) -> None:
    diffs = []
    row: dict[str, Any] = {
        "workload": workload.upper(),
        "method": method,
        "source_root": source_root,
        "reference_path": str(path),
    }
    for key in REFERENCE_KEYS:
        value = ref.get(key, math.nan)
        canonical_value = canonical.get(key, math.nan)
        diff = value - canonical_value if finite(value) and finite(canonical_value) else math.nan
        diffs.append(abs(diff) if finite(diff) else math.inf)
        row[f"{key}"] = value
        row[f"canonical_{key}"] = canonical_value
        row[f"{key}_diff"] = diff
    max_diff = max(diffs) if diffs else math.inf
    row["max_abs_diff"] = max_diff
    row["matches_canonical"] = max_diff <= FLOAT_TOL
    rows.append(row)


def formula_validation_row(run: CanonicalRun) -> dict[str, Any]:
    diff = run.score - run.stored_TR2_composite_cost
    return {
        "workload": run.workload,
        "method": run.method,
        "seed": run.seed,
        "stored_TR2_composite_cost": run.stored_TR2_composite_cost,
        "recomputed_full_objective_score": run.score,
        "absolute_error": abs(diff) if finite(diff) else math.inf,
        "matches_stored": abs(diff) <= 1e-8 if finite(diff) else False,
        "metrics_path": str(run.metrics_path),
    }


def build_ablation_comparisons(
    ablation_runs: list[CanonicalRun],
    reference_index: dict[tuple[str, str, str], CanonicalRun],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in ablation_runs:
        reference = find_reference(reference_index, run.workload, run.seed)
        if reference is None:
            continue
        rows.append(comparison_row(reference, run, "ablation_vs_reference"))
    return rows


def build_external_comparisons(
    external_runs: list[CanonicalRun],
    workload_reference_index: dict[str, CanonicalRun],
    reference_index: dict[tuple[str, str, str], CanonicalRun],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in external_runs:
        if run.method_family == "reference_mapping":
            continue
        reference = None
        if run.seed:
            reference = find_reference(reference_index, run.workload, run.seed)
        if reference is None:
            reference = workload_reference_index.get(run.workload.upper()) or workload_reference_index.get(run.workload.lower())
        if reference is None:
            continue
        rows.append(comparison_row(reference, run, "method_vs_reference"))
    return rows


def comparison_row(reference: CanonicalRun, method_run: CanonicalRun, comparison_type: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "comparison_type": comparison_type,
        "workload": method_run.workload,
        "method": method_run.method,
        "method_family": method_run.method_family,
        "ablation": method_run.ablation,
        "seed": method_run.seed,
        "seed_type": method_run.seed_type,
        "selection_policy": method_run.selection_policy,
        "source_root": method_run.source_root,
        "metrics_path": str(method_run.metrics_path),
        "reference_metrics_path": str(reference.metrics_path),
        "source_objective_name": method_run.source_objective_name,
        "source_objective_weights": method_run.source_objective_weights,
        "stored_TR2_composite_cost": method_run.stored_TR2_composite_cost,
        "reference_full_objective_comparable_score": reference.score,
        "method_full_objective_comparable_score": method_run.score,
        "full_score_delta_vs_reference": method_run.score - reference.score,
        "full_score_relative_change_pct_vs_reference": pct_change(method_run.score, reference.score),
        "run_ok": method_run.run_status.get("run_ok", ""),
        "valid_for_cost": method_run.run_status.get("valid_for_cost", ""),
        "valid": method_run.valid,
        "validity_notes": method_run.validity_notes,
    }
    for key in RAW_KEYS:
        row[f"reference_{key}"] = reference.raw.get(key, math.nan)
        row[f"method_{key}"] = method_run.raw.get(key, math.nan)
        row[f"{key}_delta_vs_reference"] = method_run.raw.get(key, math.nan) - reference.raw.get(key, math.nan)
        row[f"{key}_relative_change_pct"] = pct_change(
            method_run.raw.get(key, math.nan), reference.raw.get(key, math.nan)
        )
    add_display_metric_columns(row, reference, method_run)
    for key in TERM_KEYS:
        row[f"reference_{key}"] = reference.terms.get(key, math.nan)
        row[f"method_{key}"] = method_run.terms.get(key, math.nan)
        row[f"{key}_delta_vs_reference"] = method_run.terms.get(key, math.nan) - reference.terms.get(key, math.nan)
    return row


def add_display_metric_columns(row: dict[str, Any], reference: CanonicalRun, method_run: CanonicalRun) -> None:
    reference_display = display_metrics(reference)
    method_display = display_metrics(method_run)
    for _, metric_name, _, _, column in METRIC_DEFS:
        row[f"reference_{column}"] = reference_display[column]
        row[f"method_{column}"] = method_display[column]
        row[f"{column}_delta_vs_reference"] = method_display[column] - reference_display[column]
        row[f"{column}_relative_change_pct"] = pct_change(method_display[column], reference_display[column])


def summarize_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("valid", "")).lower() != "true":
            continue
        key = (
            str(row.get("comparison_type", "")),
            str(row.get("workload", "")),
            str(row.get("method", "")),
            str(row.get("ablation", "")),
        )
        grouped[key].append(row)
    output: list[dict[str, Any]] = []
    for (comparison_type, workload, method, ablation), items in sorted(grouped.items()):
        scores = [to_float(row.get("method_full_objective_comparable_score")) for row in items]
        deltas = [to_float(row.get("full_score_delta_vs_reference")) for row in items]
        rels = [to_float(row.get("full_score_relative_change_pct_vs_reference")) for row in items]
        score_stats = stats(scores)
        delta_stats = stats(deltas)
        rel_stats = stats(rels)
        output.append({
            "comparison_type": comparison_type,
            "workload": workload,
            "method": method,
            "ablation": ablation,
            "n": len(items),
            "valid_count": len(items),
            "seeds": ",".join(str(row.get("seed", "")) for row in items if str(row.get("seed", ""))),
            "full_score_mean": score_stats["mean"],
            "full_score_std": score_stats["std"],
            "full_score_ci95_half": score_stats["ci95_half"],
            "full_score_min": score_stats["min"],
            "full_score_max": score_stats["max"],
            "full_score_delta_vs_reference_mean": delta_stats["mean"],
            "full_score_delta_vs_reference_std": delta_stats["std"],
            "full_score_delta_vs_reference_ci95_half": delta_stats["ci95_half"],
            "full_score_delta_vs_reference_min": delta_stats["min"],
            "full_score_delta_vs_reference_max": delta_stats["max"],
            "full_score_relative_change_pct_vs_reference_mean": rel_stats["mean"],
            "full_score_relative_change_pct_vs_reference_std": rel_stats["std"],
            "full_score_relative_change_pct_vs_reference_ci95_half": rel_stats["ci95_half"],
            "full_score_relative_change_pct_vs_reference_min": rel_stats["min"],
            "full_score_relative_change_pct_vs_reference_max": rel_stats["max"],
        })
    return output


def build_figure2_source(
    all_runs: list[CanonicalRun],
    reference_index: dict[tuple[str, str, str], CanonicalRun],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in all_runs:
        if run.source_root != GA_SOURCE_ROOT or run.method not in {REFERENCE_METHOD, "Full-GA"}:
            continue
        reference = find_reference(reference_index, run.workload, run.seed)
        delta = run.score - reference.score if reference else math.nan
        rows.append({
            "figure": "figure2",
            "workload": run.workload,
            "method": run.method,
            "role": "reference_mapping" if run.method == REFERENCE_METHOD else "proposed_method",
            "seed": run.seed,
            "seed_type": run.seed_type,
            "full_objective_comparable_score": run.score,
            "reference_full_objective_comparable_score": reference.score if reference else math.nan,
            "delta_vs_reference": delta,
            "relative_change_pct_vs_reference": pct_change(run.score, reference.score) if reference else math.nan,
            "valid": run.valid,
            "validity_notes": run.validity_notes,
            "metrics_path": str(run.metrics_path),
        })
    return rows


def build_figure3_source(
    all_runs: list[CanonicalRun],
    reference_index: dict[tuple[str, str, str], CanonicalRun],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in all_runs:
        if run.source_root != GA_SOURCE_ROOT or run.method != "Full-GA":
            continue
        reference = find_reference(reference_index, run.workload, run.seed)
        if not reference:
            continue
        reference_display = display_metrics(reference)
        method_display = display_metrics(run)
        for metric_group, metric_name, metric_label, unit, column in METRIC_DEFS:
            before = reference_display[column]
            after = method_display[column]
            rows.append({
                "figure": "figure3",
                "workload": run.workload,
                "method": run.method,
                "reference_method": REFERENCE_METHOD,
                "seed": run.seed,
                "metric_group": metric_group,
                "metric_name": metric_name,
                "metric_label": metric_label,
                "unit": unit,
                "reference_metric": before,
                "method_metric": after,
                "delta_vs_reference": after - before,
                "relative_change_pct_vs_reference": pct_change(after, before),
                "full_objective_comparable_score": run.score,
                "valid": run.valid,
                "validity_notes": run.validity_notes,
                "metrics_path": str(run.metrics_path),
            })
    return rows


def build_figure4_source(
    all_runs: list[CanonicalRun],
    reference_index: dict[tuple[str, str, str], CanonicalRun],
    workload_reference_index: dict[str, CanonicalRun],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed_families = {"proposed", "ablation", "main_baseline"}
    for run in all_runs:
        if run.method_family not in allowed_families:
            continue
        reference = None
        if run.seed:
            reference = find_reference(reference_index, run.workload, run.seed)
        if reference is None:
            reference = workload_reference_index.get(run.workload)
        reference_score = reference.score if reference else math.nan
        rows.append({
            "figure": "figure4",
            "workload": run.workload,
            "method": run.method,
            "method_family": run.method_family,
            "ablation": run.ablation,
            "seed": run.seed,
            "seed_type": run.seed_type,
            "selection_policy": run.selection_policy,
            "source_root": run.source_root,
            "source_objective_name": run.source_objective_name,
            "stored_TR2_composite_cost": run.stored_TR2_composite_cost,
            "full_objective_comparable_score": run.score,
            "reference_full_objective_comparable_score": reference_score,
            "delta_vs_reference": run.score - reference_score,
            "relative_change_pct_vs_reference": pct_change(run.score, reference_score),
            "valid": run.valid,
            "validity_notes": run.validity_notes,
            "metrics_path": str(run.metrics_path),
        })
    return rows


def build_spot_checks(
    all_runs: list[CanonicalRun],
    reference_index: dict[tuple[str, str, str], CanonicalRun],
) -> list[dict[str, Any]]:
    desired = [
        ("GEMM", "Full-GA", "42"),
        ("GEMM", "thermal-only", "42"),
        ("VOPD", "wout-thermal", "40"),
        ("HNN", "Full-GA", "49"),
        ("GEMM", "RandomBest", ""),
        ("VOPD", "CommAware-Heuristic", ""),
        ("HNN", "Thermal-SA-TAS", "49"),
    ]
    rows: list[dict[str, Any]] = []
    for workload, method, seed in desired:
        matches = [
            run for run in all_runs
            if run.workload == workload and run.method == method and (not seed or run.seed == seed)
        ]
        if not matches:
            continue
        run = matches[0]
        reference = find_reference(reference_index, run.workload, run.seed)
        score_from_terms = (
            FULL_WEIGHTS["w_T"] * run.terms["f_thermal"]
            + FULL_WEIGHTS["w_sigma"] * run.terms["f_sigma"]
            + FULL_WEIGHTS["w_hot"] * run.terms["f_hot"]
            + FULL_WEIGHTS["w_makespan"] * run.terms["f_makespan"]
            + FULL_WEIGHTS["w_H"] * run.terms["f_comm"]
            + FULL_WEIGHTS["w_congestion"] * run.terms["f_congestion"]
            + FULL_WEIGHTS["w_D"] * run.terms["f_dvfs"]
            + FULL_WEIGHTS["w_L"] * run.terms["f_load"]
            + FULL_WEIGHTS["w_E"] * run.terms["f_energy"]
        )
        rows.append({
            "workload": run.workload,
            "method": run.method,
            "seed": run.seed,
            "stored_TR2_composite_cost": run.stored_TR2_composite_cost,
            "recomputed_full_objective_score": run.score,
            "score_from_terms": score_from_terms,
            "score_term_difference": run.score - score_from_terms,
            "delta_vs_reference_full_score": run.score - reference.score if reference else "",
            "valid": run.valid,
            "validity_notes": run.validity_notes,
            "metrics_path": str(run.metrics_path),
        })
    return rows


def find_reference(
    reference_index: dict[tuple[str, str, str], CanonicalRun],
    workload: str,
    seed: str,
) -> CanonicalRun | None:
    for key_workload in (workload, workload.lower(), workload.upper()):
        found = reference_index.get((GA_SOURCE_ROOT, key_workload, seed))
        if found is not None:
            return found
    return None


def run_to_row(run: CanonicalRun) -> dict[str, Any]:
    row: dict[str, Any] = {
        "workload": run.workload,
        "method": run.method,
        "method_family": run.method_family,
        "source_root": run.source_root,
        "metrics_path": str(run.metrics_path),
        "history_path": str(run.history_path) if run.history_path else "",
        "reference_source_path": str(run.reference_source_path) if run.reference_source_path else "",
        "seed": run.seed,
        "seed_type": run.seed_type,
        "ablation": run.ablation,
        "selection_policy": run.selection_policy,
        "source_objective_name": run.source_objective_name,
        "source_objective_weights": run.source_objective_weights,
        "stored_TR2_composite_cost": run.stored_TR2_composite_cost,
        "full_objective_comparable_score": run.score,
        "run_ok": run.run_status.get("run_ok", ""),
        "valid_for_cost": run.run_status.get("valid_for_cost", ""),
        "failure_reason": run.run_status.get("failure_reason", ""),
        "temperature_source": run.run_status.get("temperature_source", ""),
        "parsed_pe_count": run.run_status.get("parsed_pe_count", ""),
        "valid": run.valid,
        "validity_notes": run.validity_notes,
    }
    row.update(display_metrics(run))
    row.update(run.raw)
    row.update(run.terms)
    row.update(run.history_status)
    row.update(run.extra)
    return row


def validity_row(run: CanonicalRun) -> dict[str, Any]:
    tmax_k = run.raw.get("T_max_K", math.nan)
    return {
        "workload": run.workload,
        "method": run.method,
        "method_family": run.method_family,
        "source_root": run.source_root,
        "seed": run.seed,
        "ablation": run.ablation,
        "selection_policy": run.selection_policy,
        "run_ok": run.run_status.get("run_ok", ""),
        "valid_for_cost": run.run_status.get("valid_for_cost", ""),
        "T_max_valid": finite(tmax_k) and tmax_k > 0.0 and abs((tmax_k - 273.15) - (-273.1)) > 0.2,
        "makespan_valid": finite(run.raw.get("makespan_s", math.nan)) and run.raw.get("makespan_s", 0.0) > 0.0,
        "energy_valid": finite(run.raw.get("pe_optical_comm_energy_J", math.nan)) and run.raw.get("pe_optical_comm_energy_J", 0.0) > 0.0,
        "history_rows": run.history_status.get("history_rows", ""),
        "history_schema": run.history_status.get("history_schema", ""),
        "history_all_best_fitness_infinite": run.history_status.get("history_all_best_fitness_infinite", ""),
        "history_best_inf_gens": run.history_status.get("history_best_inf_gens", ""),
        "history_avg_inf_gens": run.history_status.get("history_avg_inf_gens", ""),
        "history_worst_inf_gens": run.history_status.get("history_worst_inf_gens", ""),
        "valid": run.valid,
        "validity_notes": run.validity_notes,
        "metrics_path": str(run.metrics_path),
        "history_path": str(run.history_path) if run.history_path else "",
    }


def display_metrics(run: CanonicalRun) -> dict[str, float]:
    return {
        "T_max_C": run.raw.get("T_max_K", math.nan) - 273.15,
        "sigma_T_K": run.raw.get("sigma_T_K", math.nan),
        "N_hot": run.raw.get("N_hot", math.nan),
        "makespan_us": run.raw.get("makespan_s", math.nan) * 1e6,
        "DVFS_penalty_pct": run.raw.get("eta_dvfs_pct", math.nan),
        "comm_cost": run.raw.get("raw_comm_cost", math.nan),
        "congestion_proxy": run.raw.get("raw_congestion_cost", math.nan),
        "load_imbalance": run.raw.get("raw_load_imbalance", math.nan),
        "total_PE_optical_energy_mJ": run.raw.get("pe_optical_comm_energy_J", math.nan) * 1e3,
    }


def unwrap_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return payload


def run_status_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    status = metrics.get("run_status")
    if not isinstance(status, dict):
        return {
            "run_ok": "",
            "valid_for_cost": "",
            "failure_reason": "",
            "temperature_source": "",
            "parsed_pe_count": "",
        }
    return dict(status)


def reference_from_config(config: Any) -> dict[str, float]:
    if not isinstance(config, dict):
        return {}
    ref = config.get("cost_reference")
    if not isinstance(ref, dict):
        return {}
    return {key: to_float(ref.get(key)) for key in REFERENCE_KEYS}


def weights_from_config(config: Any) -> str:
    if not isinstance(config, dict):
        return ""
    weights = config.get("weights")
    if not isinstance(weights, dict):
        weights = config.get("final_evaluation_weights")
    if not isinstance(weights, dict):
        weights = {key: config.get(key) for key in FULL_WEIGHTS if key in config}
    parts = []
    for key in ("w_T", "w_sigma", "w_hot", "w_makespan", "w_H", "w_congestion", "w_D", "w_L", "w_E", "w_peak"):
        if key in weights:
            parts.append(f"{key}={weights.get(key)}")
    return ";".join(parts)


def stats(values: Iterable[float]) -> dict[str, float]:
    clean = [value for value in values if finite(value)]
    if not clean:
        return {"mean": math.nan, "std": math.nan, "ci95_half": math.nan, "min": math.nan, "max": math.nan}
    mean = statistics.fmean(clean)
    std = statistics.stdev(clean) if len(clean) > 1 else 0.0
    ci95 = 1.96 * std / math.sqrt(len(clean)) if len(clean) > 1 else 0.0
    return {
        "mean": mean,
        "std": std,
        "ci95_half": ci95,
        "min": min(clean),
        "max": max(clean),
    }


def pct_change(after: float, before: float) -> float:
    if not finite(after) or not finite(before) or abs(before) <= 1e-15:
        return math.nan
    return (after / before - 1.0) * 100.0


def first_float(*values: Any) -> float:
    for value in values:
        result = to_float(value)
        if finite(result):
            return result
    return math.nan


def to_float(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return math.nan
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


def finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def get_nested(payload: Any, keys: tuple[str, ...]) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = union_fieldnames(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key, "")) for key in fieldnames})


def union_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    preferred = [
        "figure",
        "comparison_type",
        "file_type",
        "workload",
        "method",
        "method_family",
        "source_root",
        "ablation",
        "seed",
        "seed_type",
        "selection_policy",
        "metric_group",
        "metric_name",
        "metric_label",
        "unit",
    ]
    for key in preferred:
        for row in rows:
            if key in row and key not in seen:
                ordered.append(key)
                seen.add(key)
                break
    for row in rows:
        for key in row:
            if key not in seen:
                ordered.append(key)
                seen.add(key)
    return ordered


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, float) and math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, Path):
        return str(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
