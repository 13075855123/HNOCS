"""Compare Original, ThermalGreedy, ThermalOnly-RC-LS, ThermalRC-LS, and proposed GA metrics."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


WORKLOADS = ("gemm", "mpeg4", "vopd", "hnn")
ENERGY_KEYS = ("E7_pe_optical_comm_energy_J", "E7_total_energy_J")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a CSV comparison for ThermalRC-LS baseline results"
    )
    parser.add_argument("--thermal-rc-ls", required=True, help="ThermalRC-LS result root")
    parser.add_argument("--thermal-only-rc-ls", help="ThermalOnly-RC-LS result root")
    parser.add_argument("--thermal-greedy", help="ThermalGreedy result root")
    parser.add_argument("--proposed", help="Proposed GA result root, e.g. out/B-2-v4/seed_42/gen_60")
    parser.add_argument("--out", required=True, help="Output comparison CSV")
    parser.add_argument("--json-out", help="Optional output JSON")
    parser.add_argument("--workloads", default="gemm,mpeg4,vopd,hnn")
    args = parser.parse_args()

    workloads = [item.strip().lower() for item in args.workloads.split(",") if item.strip()]
    rows: list[dict[str, Any]] = []
    thermal_root = Path(args.thermal_rc_ls)
    thermal_only_root = Path(args.thermal_only_rc_ls) if args.thermal_only_rc_ls else None
    greedy_root = Path(args.thermal_greedy) if args.thermal_greedy else None
    proposed_root = Path(args.proposed) if args.proposed else None

    for workload in workloads:
        original_metrics = load_method_metrics(
            thermal_root / workload / "original" / "metrics.json",
            preferred_section="metrics",
        )
        original_row = metric_row(workload, "Original", "thermal_rc_ls/original", original_metrics)
        rows.append(original_row)

        if greedy_root:
            greedy_path = greedy_root / workload / "thermal_greedy" / "metrics.json"
            if greedy_path.exists():
                rows.append(metric_row(
                    workload,
                    "ThermalGreedy",
                    str(greedy_path),
                    load_method_metrics(greedy_path, preferred_section="metrics"),
                    baseline=original_row,
                ))

        rc_path = thermal_root / workload / "thermal_rc_ls" / "metrics.json"
        rows.append(metric_row(
            workload,
            "ThermalRC-LS",
            str(rc_path),
            load_method_metrics(rc_path, preferred_section="metrics"),
            baseline=original_row,
        ))

        if thermal_only_root:
            thermal_only_path = thermal_only_root / workload / "thermal_only_rc_ls" / "metrics.json"
            if thermal_only_path.exists():
                rows.append(metric_row(
                    workload,
                    "ThermalOnly-RC-LS",
                    str(thermal_only_path),
                    load_method_metrics(thermal_only_path, preferred_section="metrics"),
                    baseline=original_row,
                ))

        if proposed_root:
            proposed_path = proposed_root / workload / "metrics.json"
            if proposed_path.exists():
                proposed_payload = read_json(proposed_path)
                rows.append(metric_row(
                    workload,
                    "Proposed-GA",
                    str(proposed_path),
                    proposed_payload["b2"],
                    baseline=original_row,
                ))

    write_csv(Path(args.out), rows)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote comparison CSV to {Path(args.out).resolve()}")
    return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_method_metrics(path: Path, preferred_section: str) -> dict[str, Any]:
    payload = read_json(path)
    if preferred_section in payload and isinstance(payload[preferred_section], dict):
        return payload[preferred_section]
    return payload


def metric_row(
    workload: str,
    method: str,
    source: str,
    metrics: dict[str, Any],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cost = value(metrics, "tradeoff", "TR2_composite_cost")
    tmax_K = value(metrics, "thermal", "T1_pe_peak_temp_K")
    sigma_K = value(metrics, "thermal", "T3_temp_std_K")
    hot = value(metrics, "thermal", "T5_over_throttle_count")
    makespan_s = value(metrics, "performance", "P1_makespan_s")
    comm = value(metrics, "communication", "C1_total_comm_cost")
    energy_J = energy(metrics)

    row: dict[str, Any] = {
        "workload": workload,
        "method": method,
        "source": source,
        "TR2_composite_cost": cost,
        "Tmax_K": tmax_K,
        "Tmax_C": tmax_K - 273.15 if tmax_K else 0.0,
        "SigmaT_K": sigma_K,
        "Hot_PE": hot,
        "makespan_s": makespan_s,
        "makespan_us": makespan_s * 1e6,
        "comm_cost": comm,
        "energy_J": energy_J,
        "energy_mJ": energy_J * 1e3,
    }
    if baseline:
        row.update({
            "cost_delta_pct": pct(cost, baseline["TR2_composite_cost"]),
            "Tmax_delta_C": row["Tmax_C"] - baseline["Tmax_C"],
            "SigmaT_delta_pct": pct(sigma_K, baseline["SigmaT_K"]),
            "Hot_PE_delta": hot - baseline["Hot_PE"],
            "makespan_delta_pct": pct(makespan_s, baseline["makespan_s"]),
            "comm_delta_pct": pct(comm, baseline["comm_cost"]),
            "energy_delta_pct": pct(energy_J, baseline["energy_J"]),
        })
    else:
        row.update({
            "cost_delta_pct": 0.0,
            "Tmax_delta_C": 0.0,
            "SigmaT_delta_pct": 0.0,
            "Hot_PE_delta": 0.0,
            "makespan_delta_pct": 0.0,
            "comm_delta_pct": 0.0,
            "energy_delta_pct": 0.0,
        })
    return row


def value(metrics: dict[str, Any], section: str, key: str) -> float:
    section_value = metrics.get(section, {})
    if not isinstance(section_value, dict):
        return 0.0
    leaf = section_value.get(key, 0.0)
    return float(leaf) if isinstance(leaf, (int, float)) else 0.0


def energy(metrics: dict[str, Any]) -> float:
    energy_section = metrics.get("energy", {})
    if not isinstance(energy_section, dict):
        return 0.0
    for key in ENERGY_KEYS:
        leaf = energy_section.get(key, 0.0)
        if isinstance(leaf, (int, float)) and float(leaf) > 0.0:
            return float(leaf)
    return 0.0


def pct(after: float, before: float) -> float:
    if abs(before) <= 1e-15:
        return 0.0
    return (after / before - 1.0) * 100.0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
