from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
WORKLOADS = ["gemm", "hnn", "mpeg4", "vopd"]

WEIGHTS = {
    "f_thermal": 1.0,
    "f_sigma": 1.0,
    "f_hot": 0.6,
    "f_makespan": 1.2,
    "f_comm": 0.4,
    "f_congestion": 0.7,
    "f_dvfs": 0.4,
    "f_load": 0.2,
    "f_energy": 0.5,
}

TERM_LABELS = {
    "f_thermal": "Thermal",
    "f_sigma": "Sigma",
    "f_hot": "Hot PE",
    "f_makespan": "Makespan",
    "f_comm": "Comm",
    "f_congestion": "Congestion",
    "f_dvfs": "DVFS",
    "f_load": "Load",
    "f_energy": "Energy",
}


def load_metrics() -> dict[str, dict]:
    data = {}
    for name in WORKLOADS:
        path = ROOT / name / "metrics.json"
        with path.open("r", encoding="utf-8") as f:
            data[name] = json.load(f)
    return data


def load_history(name: str) -> list[dict]:
    path = ROOT / name / "history.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def metric(d: dict, side: str, section: str, key: str) -> float:
    return float(d[side][section][key])


def pct(before: float, after: float) -> float | None:
    if abs(before) < 1e-15:
        return None
    return (after / before - 1.0) * 100.0


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_tables(data: dict[str, dict]) -> None:
    summary_rows = []
    relative_rows = []
    breakdown_rows = []
    history_rows = []

    for name in WORKLOADS:
        d = data[name]
        baseline_cost = metric(d, "baseline", "tradeoff", "TR2_composite_cost")
        b2_cost = metric(d, "b2", "tradeoff", "TR2_composite_cost")
        baseline_t = metric(d, "baseline", "thermal", "T1_pe_peak_temp_K") - 273.15
        b2_t = metric(d, "b2", "thermal", "T1_pe_peak_temp_K") - 273.15
        baseline_sigma = metric(d, "baseline", "thermal", "T3_temp_std_K")
        b2_sigma = metric(d, "b2", "thermal", "T3_temp_std_K")
        baseline_hot = metric(d, "baseline", "thermal", "T5_over_throttle_count")
        b2_hot = metric(d, "b2", "thermal", "T5_over_throttle_count")
        baseline_makespan = metric(d, "baseline", "performance", "P1_makespan_s") * 1e6
        b2_makespan = metric(d, "b2", "performance", "P1_makespan_s") * 1e6
        baseline_dvfs = metric(d, "baseline", "performance", "P3_dvfs_penalty_pct")
        b2_dvfs = metric(d, "b2", "performance", "P3_dvfs_penalty_pct")
        baseline_comm = metric(d, "baseline", "communication", "C1_total_comm_cost")
        b2_comm = metric(d, "b2", "communication", "C1_total_comm_cost")
        baseline_energy = metric(d, "baseline", "energy", "E7_total_energy_J") * 1e3
        b2_energy = metric(d, "b2", "energy", "E7_total_energy_J") * 1e3

        summary_rows.append({
            "workload": name.upper(),
            "configured_generations": d["config"]["num_generations"],
            "actual_generations": d["b2_generations"],
            "converged": d["b2_converged"],
            "baseline_cost": baseline_cost,
            "b2_cost": b2_cost,
            "baseline_tmax_C": baseline_t,
            "b2_tmax_C": b2_t,
            "baseline_sigma_K": baseline_sigma,
            "b2_sigma_K": b2_sigma,
            "baseline_hot_pe": baseline_hot,
            "b2_hot_pe": b2_hot,
            "baseline_makespan_us": baseline_makespan,
            "b2_makespan_us": b2_makespan,
            "baseline_dvfs_pct": baseline_dvfs,
            "b2_dvfs_pct": b2_dvfs,
            "baseline_comm_cost": baseline_comm,
            "b2_comm_cost": b2_comm,
            "baseline_energy_mJ": baseline_energy,
            "b2_energy_mJ": b2_energy,
        })
        relative_rows.append({
            "workload": name.upper(),
            "cost_delta_pct": pct(baseline_cost, b2_cost),
            "tmax_delta_C": b2_t - baseline_t,
            "sigma_delta_pct": pct(baseline_sigma, b2_sigma),
            "hot_pe_delta": b2_hot - baseline_hot,
            "makespan_delta_pct": pct(baseline_makespan, b2_makespan),
            "dvfs_delta_pct_points": b2_dvfs - baseline_dvfs,
            "comm_delta_pct": pct(baseline_comm, b2_comm),
            "energy_delta_pct": pct(baseline_energy, b2_energy),
        })

        terms = d["b2"]["tradeoff"]["cost_terms"]
        row = {"workload": name.upper()}
        for term, weight in WEIGHTS.items():
            row[f"{term}_normalized"] = terms[term]
            row[f"{term}_weighted"] = terms[term] * weight
        row["total_cost"] = terms["total_cost"]
        breakdown_rows.append(row)

        for item in load_history(name):
            info = item.get("best_info") or {}
            history_rows.append({
                "workload": name.upper(),
                "generation": item["generation"],
                "best_fitness": item["best_fitness"],
                "avg_fitness": item["avg_fitness"],
                "worst_fitness": item["worst_fitness"],
                "best_tmax_C": info.get("T_max_K", math.nan) - 273.15
                if info.get("T_max_K") is not None else math.nan,
                "best_sigma_K": info.get("sigma_T_K", math.nan),
                "best_hot_pe": info.get("N_hot", math.nan),
                "best_makespan_us": info.get("makespan_s", math.nan) * 1e6
                if info.get("makespan_s") is not None else math.nan,
                "best_energy_mJ": info.get("total_energy_J", math.nan) * 1e3
                if info.get("total_energy_J") is not None else math.nan,
            })

    write_csv(ROOT / "metrics_summary_table.csv", summary_rows)
    write_csv(ROOT / "metrics_relative_changes.csv", relative_rows)
    write_csv(ROOT / "cost_breakdown_weighted.csv", breakdown_rows)
    write_csv(ROOT / "convergence_history_flat.csv", history_rows)


def style_axes(ax) -> None:
    ax.grid(True, axis="y", color="#d0d0d0", linewidth=0.7, alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def plot_convergence() -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.0), dpi=180)
    for name in WORKLOADS:
        hist = load_history(name)
        x = [h["generation"] for h in hist]
        y = [h["best_fitness"] for h in hist]
        ax.plot(x, y, marker="o", markersize=2.8, linewidth=1.7, label=name.upper())
    ax.set_title("B-2 GA Convergence: Best Fitness")
    ax.set_xlabel("Generation")
    ax.set_ylabel("Best fitness (TR2 composite cost)")
    ax.legend(frameon=False, ncols=2)
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(ROOT / "convergence_best_fitness.png")
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(10.0, 7.2), dpi=180, sharex=False)
    for ax, name in zip(axes.ravel(), WORKLOADS):
        hist = load_history(name)
        x = [h["generation"] for h in hist]
        ax.plot(x, [h["best_fitness"] for h in hist], label="Best", linewidth=1.7)
        ax.plot(x, [h["avg_fitness"] for h in hist], label="Avg", linewidth=1.4)
        ax.plot(x, [h["worst_fitness"] for h in hist], label="Worst", linewidth=1.1)
        ax.set_title(name.upper())
        ax.set_xlabel("Generation")
        ax.set_ylabel("Fitness")
        style_axes(ax)
    axes[0, 0].legend(frameon=False, ncols=3, loc="upper right")
    fig.suptitle("B-2 GA Population Fitness by Generation", y=0.995)
    fig.tight_layout()
    fig.savefig(ROOT / "convergence_population_fitness.png")
    plt.close(fig)


def plot_main_metrics(data: dict[str, dict]) -> None:
    labels = [w.upper() for w in WORKLOADS]
    metrics = [
        ("TR2 cost", lambda d: metric(d, "baseline", "tradeoff", "TR2_composite_cost"),
         lambda d: metric(d, "b2", "tradeoff", "TR2_composite_cost")),
        ("Tmax (C)", lambda d: metric(d, "baseline", "thermal", "T1_pe_peak_temp_K") - 273.15,
         lambda d: metric(d, "b2", "thermal", "T1_pe_peak_temp_K") - 273.15),
        ("Sigma T (K)", lambda d: metric(d, "baseline", "thermal", "T3_temp_std_K"),
         lambda d: metric(d, "b2", "thermal", "T3_temp_std_K")),
        ("Hot PE count", lambda d: metric(d, "baseline", "thermal", "T5_over_throttle_count"),
         lambda d: metric(d, "b2", "thermal", "T5_over_throttle_count")),
        ("Makespan (us)", lambda d: metric(d, "baseline", "performance", "P1_makespan_s") * 1e6,
         lambda d: metric(d, "b2", "performance", "P1_makespan_s") * 1e6),
        ("DVFS penalty (%)", lambda d: metric(d, "baseline", "performance", "P3_dvfs_penalty_pct"),
         lambda d: metric(d, "b2", "performance", "P3_dvfs_penalty_pct")),
        ("Comm cost", lambda d: metric(d, "baseline", "communication", "C1_total_comm_cost"),
         lambda d: metric(d, "b2", "communication", "C1_total_comm_cost")),
        ("Energy (mJ)", lambda d: metric(d, "baseline", "energy", "E7_total_energy_J") * 1e3,
         lambda d: metric(d, "b2", "energy", "E7_total_energy_J") * 1e3),
    ]

    fig, axes = plt.subplots(2, 4, figsize=(14.0, 7.0), dpi=180)
    x = np.arange(len(labels))
    width = 0.36
    for ax, (title, baseline_fn, b2_fn) in zip(axes.ravel(), metrics):
        baseline = [baseline_fn(data[w]) for w in WORKLOADS]
        b2 = [b2_fn(data[w]) for w in WORKLOADS]
        ax.bar(x - width / 2, baseline, width, label="Baseline", color="#8a8f98")
        ax.bar(x + width / 2, b2, width, label="B-2", color="#2563eb")
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=25, ha="right")
        if title == "Comm cost":
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
        style_axes(ax)
    axes[0, 0].legend(frameon=False)
    fig.suptitle("B-2-v3-g60: Baseline vs Optimized Mapping", y=0.995)
    fig.tight_layout()
    fig.savefig(ROOT / "main_metrics_baseline_vs_b2.png")
    plt.close(fig)


def plot_cost_breakdown(data: dict[str, dict]) -> None:
    labels = [w.upper() for w in WORKLOADS]
    x = np.arange(len(labels))
    bottom = np.zeros(len(labels))
    colors = [
        "#1f77b4", "#ff7f0e", "#d62728", "#2ca02c", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#17becf",
    ]
    fig, ax = plt.subplots(figsize=(9.2, 5.2), dpi=180)
    for color, term in zip(colors, WEIGHTS):
        values = [
            data[w]["b2"]["tradeoff"]["cost_terms"][term] * WEIGHTS[term]
            for w in WORKLOADS
        ]
        ax.bar(x, values, bottom=bottom, label=TERM_LABELS[term], color=color)
        bottom += np.array(values)
    ax.set_title("Final B-2 Cost Breakdown")
    ax.set_ylabel("Weighted contribution")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(frameon=False, ncols=3, fontsize=8)
    style_axes(ax)
    fig.tight_layout()
    fig.savefig(ROOT / "cost_breakdown.png")
    plt.close(fig)


def main() -> None:
    data = load_metrics()
    build_tables(data)
    plot_convergence()
    plot_main_metrics(data)
    plot_cost_breakdown(data)


if __name__ == "__main__":
    main()
