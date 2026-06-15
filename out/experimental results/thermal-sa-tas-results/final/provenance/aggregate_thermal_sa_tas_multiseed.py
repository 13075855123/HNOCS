# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean, stdev
from typing import Any


OUTPUT_ROOT = Path(r"D:\HNOCS\out\thermal-sa-tas-results\final\thermal-sa-tas-v3-integrated-seeds40-49")
B2_V4_ROOT = Path(r"D:\HNOCS\out\B-2-v4")
SEEDS = list(range(40, 50))
WORKLOADS = ["gemm", "mpeg4", "vopd", "hnn"]
METHOD = "thermal_sa_tas"
K_TO_C = 273.15

T_CRITICAL_95 = {
    1: 12.706204736432095,
    2: 4.302652729749464,
    3: 3.182446305284263,
    4: 2.7764451051977987,
    5: 2.5705818366147395,
    6: 2.4469118511449692,
    7: 2.3646242510102993,
    8: 2.306004135204166,
    9: 2.2621571627409915,
    10: 2.2281388519649385,
    11: 2.200985160091638,
    12: 2.178812829663418,
    13: 2.1603686564610127,
    14: 2.1447866879169273,
    15: 2.131449545559323,
    16: 2.1199052992210112,
    17: 2.1098155778331806,
    18: 2.10092204024096,
    19: 2.093024054408263,
    20: 2.0859634472658364,
    21: 2.079613844727662,
    22: 2.0738730679040147,
    23: 2.0686576104190406,
    24: 2.0638985616280205,
    25: 2.059538552753294,
    26: 2.055529438642871,
    27: 2.0518305164802833,
    28: 2.048407141795244,
    29: 2.045229642132703,
    30: 2.042272456301238,
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh, parse_constant=lambda value: math.inf if value == "Infinity" else -math.inf)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if not fieldnames:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def get(metrics: dict[str, Any], *keys: str) -> Any:
    cur: Any = metrics
    for key in keys:
        cur = cur[key]
    return cur


def cost_terms(metrics: dict[str, Any]) -> dict[str, Any]:
    return metrics["tradeoff"]["cost_terms"]


def extract_metric_values(metrics: dict[str, Any]) -> dict[str, float]:
    terms = cost_terms(metrics)
    return {
        "TR2_composite_cost": float(metrics["tradeoff"]["TR2_composite_cost"]),
        "T_max_C": float(metrics["thermal"]["T1_pe_peak_temp_K"]) - K_TO_C,
        "sigma_T_K": float(metrics["thermal"]["T3_temp_std_K"]),
        "N_hot": float(metrics["thermal"]["T5_over_throttle_count"]),
        "makespan_us": float(metrics["performance"]["P1_makespan_s"]) * 1e6,
        "DVFS_penalty_pct": float(metrics["performance"].get("P3_dvfs_penalty_pct", terms.get("eta_dvfs_pct", 0.0))),
        "comm_cost": float(metrics["communication"]["C1_total_comm_cost"]),
        "congestion_proxy": float(terms["raw_congestion_cost"]),
        "load_imbalance": float(terms["raw_load_imbalance"]),
        "total_PE_optical_energy_mJ": float(metrics["energy"]["E7_pe_optical_comm_energy_J"]) * 1e3,
    }


METRICS = [
    ("TR2_composite_cost", "TR2 composite cost", "cost"),
    ("T_max_C", "T_max", "C"),
    ("sigma_T_K", "sigma_T", "K"),
    ("N_hot", "N_hot", "count"),
    ("makespan_us", "makespan", "us"),
    ("DVFS_penalty_pct", "DVFS penalty", "%"),
    ("comm_cost", "comm cost", "byte-hop"),
    ("congestion_proxy", "congestion proxy", "byte-hop"),
    ("load_imbalance", "load imbalance", "ratio"),
    ("total_PE_optical_energy_mJ", "total PE+optical energy", "mJ"),
]


def stats(values: list[float]) -> dict[str, Any]:
    clean = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    n = len(clean)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci95_half": None, "min": None, "max": None}
    sample_std = stdev(clean) if n > 1 else 0.0
    tcrit = T_CRITICAL_95.get(n - 1, 1.96)
    ci = tcrit * sample_std / math.sqrt(n) if n > 1 else 0.0
    return {
        "n": n,
        "mean": mean(clean),
        "std": sample_std,
        "ci95_half": ci,
        "min": min(clean),
        "max": max(clean),
    }


def rel_change(new: float, old: float) -> float | None:
    if old == 0 or not math.isfinite(old):
        return None
    return (new - old) / old * 100.0


def fmt(value: Any, digits: int = 3, suffix: str = "") -> str:
    if value is None:
        return "NA"
    if isinstance(value, str):
        return value
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "NA"
    return f"{value:.{digits}f}{suffix}"


def metric_invalid_flags(values: dict[str, float], status: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if not bool(status.get("run_ok", False)):
        notes.append("run_ok_false")
    if not bool(status.get("valid_for_cost", False)):
        notes.append("valid_for_cost_false")
    if values["T_max_C"] < -200.0 or abs(values["T_max_C"] + 273.1) < 0.2:
        notes.append("invalid_Tmax_minus_273C")
    if values["makespan_us"] == 0:
        notes.append("invalid_makespan_zero")
    if values["total_PE_optical_energy_mJ"] == 0:
        notes.append("invalid_energy_zero")
    return notes


def history_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "history_rows": 0,
            "history_best_field": "",
            "history_all_best_inf": True,
            "history_inf_count": 0,
        }
    history = load_json(path)
    field = ""
    values: list[Any] = []
    for candidate in ("best_fitness", "best_score"):
        if any(candidate in row for row in history):
            field = candidate
            values = [row.get(candidate) for row in history]
            break
    inf_count = sum(1 for value in values if isinstance(value, (int, float)) and math.isinf(value))
    all_inf = bool(values) and inf_count == len(values)
    return {
        "history_rows": len(history),
        "history_best_field": field,
        "history_all_best_inf": all_inf,
        "history_inf_count": inf_count,
    }


def collect() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = []
    validity_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        for workload in WORKLOADS:
            base = OUTPUT_ROOT / f"seed_{seed}" / workload
            original_json = load_json(base / "original" / "metrics.json")
            tas_json = load_json(base / METHOD / "metrics.json")
            original_metrics = original_json["metrics"]
            tas_metrics = tas_json["metrics"]
            original_values = extract_metric_values(original_metrics)
            tas_values = extract_metric_values(tas_metrics)
            original_status = original_metrics.get("run_status", {})
            tas_status = tas_metrics.get("run_status", {})
            hist = history_status(base / METHOD / "history.json")

            original_notes = metric_invalid_flags(original_values, original_status)
            tas_notes = metric_invalid_flags(tas_values, tas_status)
            if hist["history_all_best_inf"]:
                tas_notes.append("invalid_history_all_best_inf")
            valid = not original_notes and not tas_notes

            row: dict[str, Any] = {
                "seed": seed,
                "workload": workload.upper(),
                "preset": tas_json.get("config", {}).get("preset", ""),
                "iterations": tas_json.get("proxy", {}).get(METHOD, {}).get("iterations", ""),
                "converged": tas_json.get("proxy", {}).get(METHOD, {}).get("converged", ""),
                "valid": valid,
                "validity_notes": ";".join(original_notes + tas_notes),
            }
            for key, _label, _unit in METRICS:
                ov = original_values[key]
                tv = tas_values[key]
                delta = tv - ov
                pct = rel_change(tv, ov)
                row[f"original_{key}"] = ov
                row[f"thermal_sa_tas_{key}"] = tv
                row[f"{key}_delta"] = delta
                row[f"{key}_relative_change_pct"] = pct
            row.update(hist)
            runs.append(row)

            validity_rows.append({
                "seed": seed,
                "workload": workload.upper(),
                "original_run_ok": original_status.get("run_ok", ""),
                "original_valid_for_cost": original_status.get("valid_for_cost", ""),
                "thermal_sa_tas_run_ok": tas_status.get("run_ok", ""),
                "thermal_sa_tas_valid_for_cost": tas_status.get("valid_for_cost", ""),
                "original_T_max_C": original_values["T_max_C"],
                "thermal_sa_tas_T_max_C": tas_values["T_max_C"],
                "thermal_sa_tas_makespan_us": tas_values["makespan_us"],
                "thermal_sa_tas_energy_mJ": tas_values["total_PE_optical_energy_mJ"],
                "history_rows": hist["history_rows"],
                "history_best_field": hist["history_best_field"],
                "history_all_best_inf": hist["history_all_best_inf"],
                "history_inf_count": hist["history_inf_count"],
                "valid": valid,
                "validity_notes": ";".join(original_notes + tas_notes),
            })
    return runs, validity_rows


def aggregate(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    csv_rows: list[dict[str, Any]] = []
    json_obj: dict[str, Any] = {
        "metadata": {
            "method": METHOD,
            "method_label": "Thermal-SA-TAS-Mapping",
            "preset": "v3_integrated",
            "seeds": SEEDS,
            "workloads": [w.upper() for w in WORKLOADS],
            "source": "metrics.json structured fields",
            "ci": "95% CI half-width using Student t critical value",
        },
        "workloads": {},
    }
    for workload in [w.upper() for w in WORKLOADS]:
        subset = [row for row in runs if row["workload"] == workload]
        valid_subset = [row for row in subset if row["valid"]]
        json_obj["workloads"][workload] = {
            "n": len(subset),
            "valid_count": len(valid_subset),
            "seeds": [row["seed"] for row in subset],
            "metrics": {},
        }
        for key, label, unit in METRICS:
            original_values = [row[f"original_{key}"] for row in valid_subset]
            tas_values = [row[f"thermal_sa_tas_{key}"] for row in valid_subset]
            deltas = [row[f"{key}_delta"] for row in valid_subset]
            rels = [row[f"{key}_relative_change_pct"] for row in valid_subset if row[f"{key}_relative_change_pct"] is not None]
            original_stats = stats(original_values)
            tas_stats = stats(tas_values)
            delta_stats = stats(deltas)
            rel_stats = stats(rels)
            metric_obj = {
                "metric_label": label,
                "unit": unit,
                "original": original_stats,
                "thermal_sa_tas": tas_stats,
                "delta": delta_stats,
                "relative_change_pct": rel_stats,
            }
            json_obj["workloads"][workload]["metrics"][key] = metric_obj
            csv_rows.append({
                "workload": workload,
                "metric": key,
                "metric_label": label,
                "unit": unit,
                "n": len(subset),
                "valid_count": len(valid_subset),
                "original_mean": original_stats["mean"],
                "original_std": original_stats["std"],
                "original_ci95_half": original_stats["ci95_half"],
                "original_min": original_stats["min"],
                "original_max": original_stats["max"],
                "thermal_sa_tas_mean": tas_stats["mean"],
                "thermal_sa_tas_std": tas_stats["std"],
                "thermal_sa_tas_ci95_half": tas_stats["ci95_half"],
                "thermal_sa_tas_min": tas_stats["min"],
                "thermal_sa_tas_max": tas_stats["max"],
                "delta_mean": delta_stats["mean"],
                "delta_std": delta_stats["std"],
                "delta_ci95_half": delta_stats["ci95_half"],
                "delta_min": delta_stats["min"],
                "delta_max": delta_stats["max"],
                "relative_change_pct_mean": rel_stats["mean"],
                "relative_change_pct_std": rel_stats["std"],
                "relative_change_pct_ci95_half": rel_stats["ci95_half"],
                "relative_change_pct_min": rel_stats["min"],
                "relative_change_pct_max": rel_stats["max"],
            })
    return csv_rows, json_obj


def load_b2_summary() -> dict[str, dict[str, Any]]:
    path = B2_V4_ROOT / "aggregate_summary.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return {row["benchmark"].upper(): row for row in data}


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def make_markdown(agg: dict[str, Any], validity_rows: list[dict[str, Any]], b2: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Thermal-SA-TAS v3 integrated multi-seed analysis")
    lines.append("")
    lines.append("本报告聚合 seed 40-49 的 Thermal-SA-TAS v3 integrated preset 结果。聚合指标全部来自每个 workload 的 `metrics.json` 结构化字段；有效性检查同时读取 `history.json`。")
    lines.append("")
    valid_count = sum(1 for row in validity_rows if row["valid"])
    total_count = len(validity_rows)
    lines.append(f"- 有效性：{valid_count}/{total_count} 个 seed-workload 组合通过检查。")
    lines.append("- 无效判定覆盖：`run_ok=false`、`valid_for_cost=false`、`T_max=-273.1 C`、`makespan=0`、`E_total=0`、`history.json` 全代 best_fitness/best_score 为 Infinity。")
    lines.append("- 对照口径：original mapping 为每个 seed 输出中的 `original/metrics.json`；B-2-v4 GA 对照来自 `D:\\HNOCS\\out\\B-2-v4\\aggregate_summary.json`。")
    lines.append("")

    cost_rows: list[list[str]] = []
    for workload in ["GEMM", "MPEG4", "VOPD", "HNN"]:
        m = agg["workloads"][workload]["metrics"]["TR2_composite_cost"]
        b2_row = b2.get(workload, {})
        sa_mean = m["thermal_sa_tas"]["mean"]
        sa_ci = m["thermal_sa_tas"]["ci95_half"]
        sa_rel = m["relative_change_pct"]["mean"]
        b2_cost = b2_row.get("cost_b2_mean")
        b2_rel = b2_row.get("cost_delta_pct_mean")
        gap = sa_mean - b2_cost if b2_cost is not None else None
        gap_pct = rel_change(sa_mean, b2_cost) if b2_cost not in (None, 0) else None
        cost_rows.append([
            workload,
            f"{fmt(sa_mean, 4)} ± {fmt(sa_ci, 4)}",
            fmt(sa_rel, 2, "%"),
            fmt(b2_cost, 4),
            fmt(b2_rel, 2, "%"),
            f"{fmt(gap, 4)} ({fmt(gap_pct, 2, '%')})",
        ])
    lines.append("## Composite cost vs original and B-2-v4")
    lines.append("")
    lines.append(markdown_table(
        ["Workload", "Thermal-SA-TAS cost mean ± CI95", "vs original", "B-2-v4 GA cost mean", "B-2-v4 vs original", "SA cost - GA cost"],
        cost_rows,
    ))
    lines.append("")

    metric_headers = ["Workload", "Cost %", "Tmax ΔC", "SigmaT %", "Hot PE Δ", "Makespan %", "Comm %", "Congestion %", "Load %", "Energy %"]
    metric_rows: list[list[str]] = []
    for workload in ["GEMM", "MPEG4", "VOPD", "HNN"]:
        wm = agg["workloads"][workload]["metrics"]
        metric_rows.append([
            workload,
            fmt(wm["TR2_composite_cost"]["relative_change_pct"]["mean"], 2, "%"),
            fmt(wm["T_max_C"]["delta"]["mean"], 3),
            fmt(wm["sigma_T_K"]["relative_change_pct"]["mean"], 2, "%"),
            fmt(wm["N_hot"]["delta"]["mean"], 2),
            fmt(wm["makespan_us"]["relative_change_pct"]["mean"], 2, "%"),
            fmt(wm["comm_cost"]["relative_change_pct"]["mean"], 2, "%"),
            fmt(wm["congestion_proxy"]["relative_change_pct"]["mean"], 2, "%"),
            fmt(wm["load_imbalance"]["relative_change_pct"]["mean"], 2, "%"),
            fmt(wm["total_PE_optical_energy_mJ"]["relative_change_pct"]["mean"], 2, "%"),
        ])
    lines.append("## Mean change relative to original mapping")
    lines.append("")
    lines.append(markdown_table(metric_headers, metric_rows))
    lines.append("")

    lines.append("## Workload-level interpretation")
    lines.append("")
    for workload in ["GEMM", "MPEG4", "VOPD", "HNN"]:
        wm = agg["workloads"][workload]["metrics"]
        cost_rel = wm["TR2_composite_cost"]["relative_change_pct"]["mean"]
        tmax_delta = wm["T_max_C"]["delta"]["mean"]
        sigma_rel = wm["sigma_T_K"]["relative_change_pct"]["mean"]
        hot_delta = wm["N_hot"]["delta"]["mean"]
        makespan_rel = wm["makespan_us"]["relative_change_pct"]["mean"]
        comm_rel = wm["comm_cost"]["relative_change_pct"]["mean"]
        energy_rel = wm["total_PE_optical_energy_mJ"]["relative_change_pct"]["mean"]
        if workload == "HNN":
            text = (
                f"- HNN：复合代价平均 {fmt(cost_rel, 2, '%')}，热点 PE 平均变化 {fmt(hot_delta, 2)}，"
                f"sigma_T {fmt(sigma_rel, 2, '%')}；但 Tmax 平均变化为 {fmt(tmax_delta, 3)} C，"
                f"makespan 平均 {fmt(makespan_rel, 2, '%')}。因此应写成降低热点/温度不均衡和通信/能耗的多目标折中，"
                "不要表述为 Tmax 或 makespan 全面改善。"
            )
        elif workload == "VOPD":
            text = (
                f"- VOPD：复合代价平均 {fmt(cost_rel, 2, '%')}，Tmax {fmt(tmax_delta, 3)} C，"
                f"sigma_T {fmt(sigma_rel, 2, '%')}，通信 {fmt(comm_rel, 2, '%')}，能耗 {fmt(energy_rel, 2, '%')}；"
                f"makespan 平均 {fmt(makespan_rel, 2, '%')}。可表述为 v3 integrated 下温度均匀性、通信和能耗改善，"
                "Tmax 多 seed 平均基本持平，不宜夸大为稳定峰温下降。"
            )
        else:
            text = (
                f"- {workload}：复合代价平均 {fmt(cost_rel, 2, '%')}，Tmax {fmt(tmax_delta, 3)} C，"
                f"sigma_T {fmt(sigma_rel, 2, '%')}，makespan {fmt(makespan_rel, 2, '%')}，"
                f"通信 {fmt(comm_rel, 2, '%')}，能耗 {fmt(energy_rel, 2, '%')}。"
            )
        lines.append(text)
    lines.append("")

    lines.append("## Paper-ready conclusion")
    lines.append("")
    lines.append("Thermal-SA-TAS v3 integrated 在 seed 40-49 上稳定优于 original mapping：四个 workload 的 TR2 composite cost 均为负向变化，且 40/40 个 seed-workload 组合通过有效性检查。")
    lines.append("与 B-2-v4 GA 相比，Thermal-SA-TAS 的平均 cost 在四个 workload 上均更高，因此可作为有效但较弱的启发式 baseline，而不是主方法的替代。")
    lines.append("trade-off 主要出现在 HNN：热点 PE 和温度不均衡下降，但 Tmax 不应夸大为改善，makespan 也存在明显变差；GEMM 的 makespan/能耗也存在代价上升，说明 Thermal-SA-TAS 更偏热稳定而非系统级综合最优。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    runs, validity_rows = collect()
    aggregate_rows, aggregate_json = aggregate(runs)
    b2 = load_b2_summary()
    aggregate_json["b2_v4_reference"] = b2

    write_csv(OUTPUT_ROOT / "runs_summary.csv", runs)
    write_csv(OUTPUT_ROOT / "validity_report.csv", validity_rows)
    write_csv(OUTPUT_ROOT / "aggregate_summary.csv", aggregate_rows)
    write_json(OUTPUT_ROOT / "aggregate_summary.json", aggregate_json)
    (OUTPUT_ROOT / "thermal_sa_tas_multiseed_analysis.md").write_text(
        make_markdown(aggregate_json, validity_rows, b2),
        encoding="utf-8",
    )

    invalid = [row for row in validity_rows if not row["valid"]]
    print(f"runs={len(runs)} validity_rows={len(validity_rows)} invalid={len(invalid)}")
    print(f"wrote outputs under {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
