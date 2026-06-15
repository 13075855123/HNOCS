"""Selection and compact summary helpers for Random Mapping Ensemble."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RandomSampleRecord:
    """One random sample evaluation record."""

    sample_id: int
    sample_seed: int
    assignment: dict[int, int]
    mapping_csv: str
    metrics: dict[str, object] | None
    valid_for_cost: bool
    failure_reason: str

    @property
    def cost(self) -> float:
        if not self.metrics:
            return math.inf
        value = (
            self.metrics.get("tradeoff", {})
            .get("TR2_composite_cost", math.inf)
        )
        return float(value) if isinstance(value, (int, float)) else math.inf


def select_distribution_records(
    samples: list[RandomSampleRecord],
) -> dict[str, RandomSampleRecord]:
    """Select RandomBest/Median/P10/P90 from valid samples by composite cost."""
    valid = sorted(
        [sample for sample in samples if sample.valid_for_cost and math.isfinite(sample.cost)],
        key=lambda sample: (sample.cost, sample.sample_id),
    )
    if not valid:
        raise RuntimeError("no valid random samples available for distribution selection")

    return {
        "RandomBest": valid[0],
        "RandomMedian": _nearest_rank(valid, 0.50),
        "RandomP10": _nearest_rank(valid, 0.10),
        "RandomP90": _nearest_rank(valid, 0.90),
    }


def compact_sample_rows(samples: list[RandomSampleRecord]) -> list[dict[str, object]]:
    """Flatten sample results for compact CSV/JSON output."""
    rows: list[dict[str, object]] = []
    for sample in samples:
        metrics = sample.metrics or {}
        run_status = metrics.get("run_status", {}) if isinstance(metrics, dict) else {}
        thermal = metrics.get("thermal", {}) if isinstance(metrics, dict) else {}
        performance = metrics.get("performance", {}) if isinstance(metrics, dict) else {}
        communication = metrics.get("communication", {}) if isinstance(metrics, dict) else {}
        energy = metrics.get("energy", {}) if isinstance(metrics, dict) else {}
        tradeoff = metrics.get("tradeoff", {}) if isinstance(metrics, dict) else {}
        cost_terms = tradeoff.get("cost_terms", {}) if isinstance(tradeoff, dict) else {}

        rows.append({
            "sample_id": sample.sample_id,
            "sample_seed": sample.sample_seed,
            "valid_for_cost": sample.valid_for_cost,
            "failure_reason": sample.failure_reason,
            "mapping_csv": sample.mapping_csv,
            "TR2_composite_cost": sample.cost if math.isfinite(sample.cost) else "",
            "T1_pe_peak_temp_K": _num(thermal, "T1_pe_peak_temp_K"),
            "T3_temp_std_K": _num(thermal, "T3_temp_std_K"),
            "T5_over_throttle_count": _num(thermal, "T5_over_throttle_count"),
            "P1_makespan_s": _num(performance, "P1_makespan_s"),
            "P3_dvfs_penalty_pct": _num(performance, "P3_dvfs_penalty_pct"),
            "C1_total_comm_cost": _num(communication, "C1_total_comm_cost"),
            "raw_congestion_cost": _num(cost_terms, "raw_congestion_cost"),
            "raw_load_imbalance": _num(cost_terms, "raw_load_imbalance"),
            "E7_pe_optical_comm_energy_J": _num(energy, "E7_pe_optical_comm_energy_J"),
            "run_ok": run_status.get("run_ok", ""),
            "temperature_source": run_status.get("temperature_source", ""),
            "parsed_pe_count": run_status.get("parsed_pe_count", ""),
            "assignment": json.dumps(sample.assignment, sort_keys=True),
        })
    return rows


def write_compact_outputs(
    rows: list[dict[str, object]],
    csv_path: Path,
    json_path: Path,
) -> None:
    """Write compact sample summaries in CSV and JSON form."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _nearest_rank(
    sorted_valid: list[RandomSampleRecord],
    percentile: float,
) -> RandomSampleRecord:
    n = len(sorted_valid)
    rank = max(1, math.ceil(percentile * n))
    return sorted_valid[min(rank - 1, n - 1)]


def _num(section: object, key: str) -> object:
    if not isinstance(section, dict):
        return ""
    value = section.get(key, "")
    return value if isinstance(value, (int, float, bool)) else ""

