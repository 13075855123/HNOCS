"""Merge VOPD top-up random samples into random-mapping-ensemble-v2."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EXP = _HERE.parent
_PROJ = _EXP.parent

for _d in (_HERE, _EXP, _PROJ):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from mapping.csv_writer import write_static_csv
from mapping.omnet_cost_model import CostReference, SimParams
from mapping.task_graph import TaskGraph

from b2_baseline_reference import (
    CostWeights,
    OmnetRunConfig,
    build_cost_model,
    build_omnet_evaluator,
)
from b2_metrics_schema import grouped_metrics


BENCHMARK = "vopd"
CSV_PATH = _PROJ / "examples/task_driven/static/tasks_vopd_static.csv"
LABELS = {
    "RandomBest": "random_best",
    "RandomMedian": "random_median",
    "RandomP10": "random_p10",
    "RandomP90": "random_p90",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge VOPD top-up samples")
    parser.add_argument("--root", default="out/random-mapping-ensemble-v2")
    parser.add_argument("--target-valid", type=int, default=3000)
    parser.add_argument(
        "--topup-dir",
        action="append",
        required=True,
        help="Top-up output root, e.g. out/random-mapping-ensemble-v2/_topup_batches/vopd_seed3000_n240",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    random_dir = root / BENCHMARK / "random"
    samples_path = random_dir / "samples.csv"
    payload_path = random_dir / "metrics.json"
    payload = _read_json(payload_path)
    existing_rows = _read_csv(samples_path)
    existing_valid = sum(1 for row in existing_rows if _truthy(row.get("valid_for_cost")))
    needed_valid = args.target_valid - existing_valid
    if needed_valid <= 0:
        print(f"{BENCHMARK}: already has {existing_valid} valid samples; nothing to merge")
        return 0

    included_rows, executed_elapsed_s, executed_batches = _collect_topup_rows(
        root=root,
        topup_dirs=[Path(item) for item in args.topup_dir],
        needed_valid=needed_valid,
    )
    added_valid = sum(1 for row in included_rows if _truthy(row.get("valid_for_cost")))
    if added_valid < needed_valid:
        raise RuntimeError(f"only found {added_valid} valid top-up rows; need {needed_valid}")

    merged_rows = sorted(
        existing_rows + included_rows,
        key=lambda row: int(row["sample_id"]),
    )
    n_valid = sum(1 for row in merged_rows if _truthy(row.get("valid_for_cost")))
    n_invalid = len(merged_rows) - n_valid
    if n_valid != args.target_valid:
        raise RuntimeError(f"merged valid count is {n_valid}, expected {args.target_valid}")

    _write_rows(merged_rows, random_dir / "samples.csv", random_dir / "samples.json")
    invalid_rows = [row for row in merged_rows if not _truthy(row.get("valid_for_cost"))]
    _write_rows(invalid_rows, random_dir / "invalid_samples.csv", random_dir / "invalid_samples.json")

    selected_rows = _select_rows(merged_rows)
    selected_metrics = _reevaluate_selected(root, payload, selected_rows)

    payload["random_best"] = selected_metrics["RandomBest"]
    payload["random_median"] = selected_metrics["RandomMedian"]
    payload["random_p10"] = selected_metrics["RandomP10"]
    payload["random_p90"] = selected_metrics["RandomP90"]
    payload["selection"] = {
        label: {
            "sample_id": int(row["sample_id"]),
            "sample_seed": int(row["sample_seed"]),
            "mapping_csv": row["mapping_csv"],
            "TR2_composite_cost": _cost(selected_metrics[label]),
        }
        for label, row in selected_rows.items()
    }
    payload["run_status"] = {
        **payload.get("run_status", {}),
        "n_requested": len(merged_rows),
        "n_valid": n_valid,
        "n_invalid": n_invalid,
        "elapsed_s": _float(payload.get("run_status", {}).get("elapsed_s")) + executed_elapsed_s,
    }
    config = payload.setdefault("config", {})
    config["random_n"] = len(merged_rows)
    config["sample_seeds"] = [int(row["sample_seed"]) for row in merged_rows]
    config["topup_policy"] = (
        f"append VOPD samples in seed order until {args.target_valid} valid samples are reached"
    )
    config["topup_batches"] = executed_batches

    payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (random_dir / "summary.txt").write_text(_summary(payload) + "\n", encoding="utf-8")

    print(
        f"{BENCHMARK}: merged {len(included_rows)} top-up attempts, "
        f"added_valid={added_valid}, total_valid={n_valid}, total_invalid={n_invalid}"
    )
    return 0


def _collect_topup_rows(
    root: Path,
    topup_dirs: list[Path],
    needed_valid: int,
) -> tuple[list[dict[str, str]], float, list[dict[str, object]]]:
    random_dir = root / BENCHMARK / "random"
    mappings_dir = random_dir / "mappings"
    included: list[dict[str, str]] = []
    added_valid = 0
    executed_elapsed_s = 0.0
    executed_batches: list[dict[str, object]] = []

    for topup_dir in topup_dirs:
        topup_random = topup_dir / BENCHMARK / "random"
        topup_payload = _read_json(topup_random / "metrics.json")
        topup_rows = sorted(
            _read_csv(topup_random / "samples.csv"),
            key=lambda row: int(row["sample_seed"]),
        )
        executed_elapsed_s += _float(topup_payload.get("run_status", {}).get("elapsed_s"))
        batch_record = {
            "path": str(topup_dir),
            "executed_requested": topup_payload.get("run_status", {}).get("n_requested", ""),
            "executed_valid": topup_payload.get("run_status", {}).get("n_valid", ""),
            "executed_invalid": topup_payload.get("run_status", {}).get("n_invalid", ""),
            "merged_rows": 0,
            "merged_valid": 0,
            "merged_invalid": 0,
        }
        for row in topup_rows:
            if added_valid >= needed_valid:
                break
            seed = int(row["sample_seed"])
            sample_id = seed
            src_mapping = topup_dir / Path(row["mapping_csv"].replace("\\", "/"))
            dst_rel = Path(BENCHMARK) / "random" / "mappings" / f"sample_{sample_id:03d}_seed_{seed}.csv"
            dst_mapping = root / dst_rel
            if dst_mapping.exists():
                raise RuntimeError(f"refusing to overwrite existing mapping: {dst_mapping}")
            dst_mapping.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_mapping, dst_mapping)

            merged = dict(row)
            merged["sample_id"] = str(sample_id)
            merged["mapping_csv"] = str(dst_rel).replace("/", "\\")
            included.append(merged)
            batch_record["merged_rows"] += 1
            if _truthy(row.get("valid_for_cost")):
                added_valid += 1
                batch_record["merged_valid"] += 1
            else:
                batch_record["merged_invalid"] += 1
        executed_batches.append(batch_record)
        if added_valid >= needed_valid:
            break

    return included, executed_elapsed_s, executed_batches


def _select_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    valid = sorted(
        [
            row for row in rows
            if _truthy(row.get("valid_for_cost")) and math.isfinite(_float(row.get("TR2_composite_cost")))
        ],
        key=lambda row: (_float(row["TR2_composite_cost"]), int(row["sample_id"])),
    )
    if not valid:
        raise RuntimeError("no valid rows after merge")
    return {
        "RandomBest": valid[0],
        "RandomMedian": _nearest_rank(valid, 0.50),
        "RandomP10": _nearest_rank(valid, 0.10),
        "RandomP90": _nearest_rank(valid, 0.90),
    }


def _reevaluate_selected(
    root: Path,
    payload: dict,
    selected_rows: dict[str, dict[str, str]],
) -> dict[str, dict[str, object]]:
    graph = TaskGraph.from_csv(CSV_PATH)
    for node in graph.tasks.values():
        if not node.is_gb_task and node.assigned_pe >= 0:
            node.assigned_pe = -2
    graph._topo_order = None

    params = SimParams()
    weights = CostWeights(**payload["config"]["weights"])
    reference = CostReference(**payload["config"]["cost_reference"])
    cost_model = build_cost_model(graph, params, weights, reference=reference)
    evaluator = build_omnet_evaluator(OmnetRunConfig(verbose=False))
    baseline_makespan_s = _metric(payload["original"], "performance", "P1_makespan_s")
    selected_dir = root / BENCHMARK / "random" / "selected"
    metrics_by_label: dict[str, dict[str, object]] = {}

    for label, row in selected_rows.items():
        assignment = {int(k): int(v) for k, v in json.loads(row["assignment"]).items()}
        scalars = evaluator.evaluate(graph, assignment)
        if not scalars.valid_for_cost:
            raise RuntimeError(f"selected {label} sample {row['sample_id']} became invalid")
        metrics = grouped_metrics(
            graph,
            assignment,
            scalars,
            cost_model,
            params,
            baseline_makespan_s=baseline_makespan_s,
        )
        metrics_by_label[label] = metrics

        write_static_csv(
            graph,
            assignment,
            selected_dir / f"{label}.csv",
            comment=f"{label} selected from Random Mapping Ensemble after VOPD top-up",
        )
        slug = LABELS[label]
        artifact_dir = selected_dir / slug
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("mapping.csv", "remapped.csv"):
            write_static_csv(
                graph,
                assignment,
                artifact_dir / filename,
                comment=f"{slug} selected from Random Mapping Ensemble after VOPD top-up",
            )
        (artifact_dir / "metrics.json").write_text(
            json.dumps({
                "name": BENCHMARK,
                "kind": slug,
                "sample_id": int(row["sample_id"]),
                "sample_seed": int(row["sample_seed"]),
                "mapping_csv": row["mapping_csv"],
                "metrics": metrics,
                "assignment": assignment,
            }, indent=2),
            encoding="utf-8",
        )

    return metrics_by_label


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_rows(rows: list[dict[str, str]], csv_path: Path, json_path: Path) -> None:
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _summary(payload: dict) -> str:
    selection = payload["selection"]
    status = payload["run_status"]
    original_cost = _cost(payload["original"])
    return "\n".join([
        f"[{BENCHMARK}] Random Mapping Ensemble",
        f"  samples: requested={status['n_requested']} valid={status['n_valid']} invalid={status['n_invalid']}",
        f"  Original cost:     {original_cost:.4f}",
        f"  RandomBest cost:   {selection['RandomBest']['TR2_composite_cost']:.4f} "
        f"(sample={selection['RandomBest']['sample_id']}, seed={selection['RandomBest']['sample_seed']})",
        f"  RandomMedian cost: {selection['RandomMedian']['TR2_composite_cost']:.4f} "
        f"(sample={selection['RandomMedian']['sample_id']}, seed={selection['RandomMedian']['sample_seed']})",
        f"  RandomP10/P90:     {selection['RandomP10']['TR2_composite_cost']:.4f} / "
        f"{selection['RandomP90']['TR2_composite_cost']:.4f}",
    ])


def _nearest_rank(sorted_rows: list[dict[str, str]], percentile: float) -> dict[str, str]:
    n = len(sorted_rows)
    rank = max(1, math.ceil(percentile * n))
    return sorted_rows[min(rank - 1, n - 1)]


def _cost(metrics: object) -> float:
    if not isinstance(metrics, dict):
        return math.nan
    return _float(metrics.get("tradeoff", {}).get("TR2_composite_cost"))


def _metric(metrics: dict, section: str, key: str) -> float:
    return _float(metrics.get(section, {}).get(key))


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


if __name__ == "__main__":
    raise SystemExit(main())
