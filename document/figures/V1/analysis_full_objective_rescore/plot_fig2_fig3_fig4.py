from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "out" / "experimental results" / "analysis_full_objective_rescore"
OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
DATA_DIR = OUT_DIR / "source_data"

FIG2_SRC = SRC_DIR / "figure2_composite_cost_source.csv"
FIG4_SRC = SRC_DIR / "figure4_baseline_and_ablation_source.csv"
FULL_RUNS_SRC = SRC_DIR / "full_objective_rescore_runs.csv"
ABLATION_SUMMARY_SRC = SRC_DIR / "ablation_full_objective_rescore_summary.csv"
BASELINE_SUMMARY_SRC = SRC_DIR / "baseline_full_objective_rescore_summary.csv"
ABLATION_VS_REFERENCE_SUMMARY_SRC = SRC_DIR / "ablation_vs_reference_full_objective_summary.csv"
MAIN_BASELINE_SUMMARY_SRC = SRC_DIR / "main_baseline_full_objective_summary.csv"
RANDOM_ENSEMBLE_SUMMARY_SRC = SRC_DIR / "random_ensemble_full_objective_summary.csv"
FORMULA_VALIDATION_SRC = SRC_DIR / "formula_validation_full_ga.csv"
VALIDITY_AUDIT_SRC = SRC_DIR / "validity_audit.csv"

WORKLOADS = ["GEMM", "MPEG4", "VOPD", "HNN"]

PALETTE = {
    "lavender": "#CDCEF3",
    "gray": "#9D9EA3",
    "sand": "#F3CFA8",
    "blue": "#B7D0EC",
    "coral": "#F6BEC2",
    "neutral_light": "#E7E8EB",
    "neutral_mid": "#777A80",
    "neutral_dark": "#4D4F54",
    "neutral_black": "#272727",
}

METHOD_COLORS = {
    "Original": PALETTE["gray"],
    "ReferenceMapping": PALETTE["gray"],
    "Full-GA": PALETTE["blue"],
    "RandomBest": PALETTE["coral"],
    "CommAware-Heuristic": PALETTE["sand"],
    "Thermal-SA-TAS": PALETTE["lavender"],
    "thermal-only": PALETTE["lavender"],
    "comm-only": PALETTE["gray"],
    "wout-thermal": PALETTE["coral"],
    "wout-comm": PALETTE["sand"],
}

FIG2_METHOD_COLORS = {
    "ReferenceMapping": PALETTE["gray"],
    "Thermal-SA-TAS": PALETTE["lavender"],
    "CommAware-Heuristic": PALETTE["sand"],
    "Full-GA": PALETTE["blue"],
}

METHOD_MARKERS = {
    "Original": "s",
    "ReferenceMapping": "s",
    "Full-GA": "o",
    "RandomBest": "D",
    "CommAware-Heuristic": "X",
    "Thermal-SA-TAS": "o",
    "thermal-only": "^",
    "comm-only": "v",
    "wout-thermal": "P",
    "wout-comm": "h",
}

SINGLE_MAPPING_METHODS = {"Original", "ReferenceMapping", "RandomBest", "CommAware-Heuristic"}

MAIN_COMPARISON_METHODS = [
    ("ReferenceMapping", "Reference\n(anchor)"),
    ("Thermal-SA-TAS", "Thermal-SA-TAS"),
    ("CommAware-Heuristic", "CommAware-Heuristic"),
    ("Full-GA", "Full-GA"),
]

NO_COMMAWARE_METHODS = [
    ("ReferenceMapping", "Reference\n(anchor)"),
    ("Thermal-SA-TAS", "Thermal-SA-TAS"),
    ("Full-GA", "Full-GA"),
]


def apply_style() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
    plt.rcParams["svg.fonttype"] = "none"
    mpl.rcParams.update(
        {
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "font.size": 7,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 0.8,
            "legend.frameon": False,
            "xtick.major.width": 0.7,
            "ytick.major.width": 0.7,
            "xtick.major.size": 2.5,
            "ytick.major.size": 2.5,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def ensure_dirs() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def is_true_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def ci95(values: pd.Series | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size <= 1:
        return 0.0
    return float(1.96 * np.std(arr, ddof=1) / np.sqrt(arr.size))


def save_figure(fig: plt.Figure, stem: str, dpi: int = 600, formats: tuple[str, ...] = ("png",)) -> list[str]:
    base = FIG_DIR / stem
    paths = []
    for ext in formats:
        path = base.with_suffix(f".{ext}")
        save_kwargs = {"bbox_inches": "tight"}
        if ext in {"tiff", "png"}:
            save_kwargs["dpi"] = dpi
        fig.savefig(path, **save_kwargs)
        paths.append(str(path))
    plt.close(fig)
    return paths


def assert_inputs_valid() -> dict[str, object]:
    formula = pd.read_csv(FORMULA_VALIDATION_SRC)
    validity = pd.read_csv(VALIDITY_AUDIT_SRC)
    source_checks = {}
    for path in [FIG2_SRC, FIG4_SRC, FULL_RUNS_SRC]:
        df = pd.read_csv(path)
        source_checks[path.name] = {
            "rows": int(len(df)),
            "valid_rows": int(is_true_series(df["valid"]).sum()),
        }
        if "valid" in df.columns and not is_true_series(df["valid"]).all():
            raise ValueError(f"{path.name} contains invalid rows")

    if not is_true_series(formula["matches_stored"]).all():
        raise ValueError("Full-GA formula validation has mismatches")
    if not is_true_series(validity["valid"]).all():
        raise ValueError("Validity audit contains invalid rows")

    return {
        "source_checks": source_checks,
        "formula_validation_rows": int(len(formula)),
        "formula_mismatches": int((~is_true_series(formula["matches_stored"])).sum()),
        "validity_rows": int(len(validity)),
        "invalid_rows": int((~is_true_series(validity["valid"])).sum()),
    }


def copy_source_data() -> list[str]:
    copied = []
    for src in [
        FIG2_SRC,
        FIG4_SRC,
        FULL_RUNS_SRC,
        ABLATION_SUMMARY_SRC,
        BASELINE_SUMMARY_SRC,
        ABLATION_VS_REFERENCE_SUMMARY_SRC,
        MAIN_BASELINE_SUMMARY_SRC,
        RANDOM_ENSEMBLE_SUMMARY_SRC,
        FORMULA_VALIDATION_SRC,
        VALIDITY_AUDIT_SRC,
    ]:
        if not src.exists():
            continue
        dst = DATA_DIR / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def luminance_rgba(color) -> float:
    rgba = mpl.colors.to_rgba(color)
    r, g, b = rgba[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def plot_fig2(
    methods: list[tuple[str, str]] = MAIN_COMPARISON_METHODS,
    stem: str = "fig2_full_ga_composite_score",
    summary_name: str = "fig2_plotted_summary.csv",
    y_upper: float | None = None,
    y_ticks: list[float] | None = None,
) -> tuple[list[str], pd.DataFrame]:
    reference_df = pd.read_csv(FIG2_SRC)
    method_df = pd.read_csv(FIG4_SRC)
    rows = []
    for workload in WORKLOADS:
        reference = reference_df[
            (reference_df["workload"] == workload) & (reference_df["method"] == "ReferenceMapping")
        ]
        if reference.empty:
            raise ValueError(f"Missing Fig. 2 ReferenceMapping rows for {workload}")
        reference_score = float(pd.to_numeric(reference["full_objective_comparable_score"]).mean())
        for method, label in methods:
            if method == "ReferenceMapping":
                scores = pd.Series([reference_score], dtype=float)
                seed_type = "reference"
            else:
                subset = method_df[(method_df["workload"] == workload) & (method_df["method"] == method)]
                if subset.empty:
                    raise ValueError(f"Missing Fig. 2 method rows for {workload} {method}")
                scores = pd.to_numeric(subset["full_objective_comparable_score"], errors="raise")
                seed_type = str(subset["seed_type"].iloc[0])
            mean_score = float(scores.mean())
            has_ci = method not in SINGLE_MAPPING_METHODS and len(scores) > 1
            rel = (mean_score - reference_score) / reference_score * 100.0
            rows.append(
                {
                    "workload": workload,
                    "method": method,
                    "display_label": label.replace("\n", " "),
                    "seed_type": seed_type,
                    "n": int(len(scores)),
                    "reference_score": reference_score,
                    "score_mean": mean_score,
                    "score_ci95": ci95(scores) if has_ci else 0.0,
                    "score_min": float(scores.min()),
                    "score_max": float(scores.max()),
                    "relative_change_pct_vs_reference": rel,
                    "display_as": "single/reference" if method in SINGLE_MAPPING_METHODS else "mean +/- 95% CI",
                }
            )
    summary = pd.DataFrame(rows)
    summary.to_csv(DATA_DIR / summary_name, index=False)

    fig, ax = plt.subplots(figsize=(7.15, 2.85))
    x = np.arange(len(WORKLOADS))
    group_width = 0.78
    width = group_width / len(methods)
    max_y = 0.0
    for m_idx, (method, label) in enumerate(methods):
        method_summary = summary[summary["method"] == method].set_index("workload").loc[WORKLOADS]
        means = method_summary["score_mean"].to_numpy(dtype=float)
        cis = method_summary["score_ci95"].to_numpy(dtype=float)
        positions = x + (m_idx - (len(methods) - 1) / 2) * width
        max_y = max(max_y, float(np.max(means + cis)))
        bars = ax.bar(
            positions,
            means,
            width=width * 0.92,
            color=FIG2_METHOD_COLORS[method],
            edgecolor=PALETTE["neutral_black"],
            linewidth=0.55,
            yerr=cis if np.any(cis > 0) else None,
            capsize=2.2,
            error_kw={"elinewidth": 0.72, "capthick": 0.72},
            label=label,
        )
        if method == "ReferenceMapping":
            for bar in bars:
                bar.set_hatch("//")
        if method != "ReferenceMapping":
            for pos, mean, ci in zip(
                positions,
                means,
                cis,
            ):
                ax.text(
                    pos,
                    mean + ci + 0.13,
                    f"{mean:.2f}",
                    ha="center",
                    va="bottom",
                    color=PALETTE["neutral_black"],
                    fontsize=5.8,
                    rotation=0,
                )
        else:
            for pos, mean, ci in zip(positions, means, cis):
                ax.text(
                    pos,
                    mean + ci + 0.13,
                    f"{mean:.2f}",
                    ha="center",
                    va="bottom",
                    color=PALETTE["neutral_black"],
                    fontsize=5.8,
                    rotation=0,
                )

    ax.set_ylabel("Full-objective comparable score")
    ax.set_xticks(x)
    ax.set_xticklabels(WORKLOADS)
    ax.set_ylim(0, y_upper if y_upper is not None else max_y + 0.95)
    ax.set_yticks(y_ticks if y_ticks is not None else np.arange(0, 11, 2))
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.24),
        ncol=4,
        fontsize=6.2,
        handlelength=1.1,
        columnspacing=1.0,
    )
    ax.text(
        0.0,
        -0.28,
        "ReferenceMapping is the normalization anchor, not a baseline method.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=6.2,
        color=PALETTE["neutral_mid"],
    )
    fig.subplots_adjust(left=0.08, right=0.995, top=0.78, bottom=0.26)

    return save_figure(fig, stem), summary


TERM_SPECS = [
    ("thermal_safety", "f_thermal", "Tmax"),
    ("thermal_safety", "f_sigma", "sigmaT"),
    ("thermal_safety", "f_hot", "Nhot"),
    ("performance", "f_makespan", "makespan"),
    ("performance", "f_dvfs", "DVFS"),
    ("communication_pressure", "f_comm", "comm"),
    ("communication_pressure", "f_congestion", "congestion"),
    ("mapping_balance", "f_load", "load"),
    ("energy", "f_energy", "energy"),
]

TERM_GROUP_LABELS = {
    "thermal_safety": "thermal safety",
    "performance": "performance",
    "communication_pressure": "communication pressure",
    "mapping_balance": "mapping balance",
    "energy": "energy",
}


def plot_fig3(
    methods: list[tuple[str, str]] = MAIN_COMPARISON_METHODS,
    stem_suffix: str = "normalized_terms",
    summary_name: str = "fig3_normalized_terms_summary.csv",
    draw_ci: bool = False,
    y_cap: float = 3.0,
    y_ticks: list[float] | None = None,
) -> tuple[list[str], pd.DataFrame]:
    df = pd.read_csv(FULL_RUNS_SRC)
    term_cols = [term for _, term, _ in TERM_SPECS]
    plot_rows = []
    for workload in WORKLOADS:
        for method, label in methods:
            subset = df[(df["workload"] == workload) & (df["method"] == method)]
            if subset.empty:
                raise ValueError(f"Missing normalized-term rows for {workload} {method}")
            for group, term, term_label in TERM_SPECS:
                values = pd.to_numeric(subset[term], errors="raise")
                has_ci = method not in SINGLE_MAPPING_METHODS and len(values) > 1
                plot_rows.append(
                    {
                        "workload": workload,
                        "method": method,
                        "display_label": label.replace("\n", " "),
                        "metric_group": group,
                        "term": term,
                        "term_label": term_label,
                        "n": int(len(values)),
                        "term_mean": float(values.mean()),
                        "term_ci95": ci95(values) if has_ci else 0.0,
                        "term_min": float(values.min()),
                        "term_max": float(values.max()),
                        "display_as": (
                            "single/reference"
                            if method in SINGLE_MAPPING_METHODS
                            else ("mean +/- 95% CI" if draw_ci else "mean only; CI not drawn")
                        ),
                    }
                )
    summary = pd.DataFrame(plot_rows)
    summary.to_csv(DATA_DIR / summary_name, index=False)

    outputs: list[str] = []
    y_arrow = y_cap - 0.10
    x = np.arange(len(TERM_SPECS))
    group_width = 0.78
    width = group_width / len(methods)
    for workload in WORKLOADS:
        fig, ax = plt.subplots(figsize=(7.15, 3.15))
        workload_summary = summary[summary["workload"] == workload]
        for m_idx, (method, label) in enumerate(methods):
            method_summary = workload_summary[workload_summary["method"] == method].set_index("term").loc[term_cols]
            means = method_summary["term_mean"].to_numpy(dtype=float)
            cis = method_summary["term_ci95"].to_numpy(dtype=float)
            plot_heights = np.minimum(means, y_cap)
            positions = x + (m_idx - (len(methods) - 1) / 2) * width
            yerr = np.minimum(cis, np.maximum(0.0, y_cap - plot_heights))
            bars = ax.bar(
                positions,
                plot_heights,
                width=width * 0.92,
                color=FIG2_METHOD_COLORS[method],
                edgecolor=PALETTE["neutral_black"],
                linewidth=0.55,
                yerr=yerr if draw_ci and np.any(yerr > 0) else None,
                capsize=2.0 if draw_ci else 0,
                error_kw={"elinewidth": 0.68, "capthick": 0.68},
                label=label,
                zorder=3,
            )
            if method == "ReferenceMapping":
                for bar in bars:
                    bar.set_hatch("//")
            for pos, mean, ci, shown in zip(positions, means, cis, plot_heights):
                if mean > y_cap:
                    ax.annotate(
                        "",
                        xy=(pos, y_cap + 0.01),
                        xytext=(pos, y_arrow - 0.24),
                        arrowprops=dict(arrowstyle="-|>", lw=0.75, color=PALETTE["neutral_black"]),
                        clip_on=False,
                    )
                    label_y = y_cap + 0.10
                else:
                    label_y = shown + (min(ci, 0.22) if draw_ci else 0.0) + 0.07
                ax.text(
                    pos,
                    label_y,
                    f"{mean:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=5.0,
                    color=PALETTE["neutral_black"],
                    clip_on=False,
                )

        ax.axhline(1.0, color=PALETTE["neutral_mid"], linestyle="--", lw=0.75, alpha=0.8, zorder=1)
        ax.set_title(workload, fontsize=8.2, loc="left", pad=7)
        ax.set_ylabel("Normalized cost term")
        ax.set_xticks(x)
        ax.set_xticklabels([label for _, _, label in TERM_SPECS], rotation=25, ha="right", fontsize=6.4)
        ax.set_ylim(0, y_cap if draw_ci else y_cap + 0.38)
        ax.set_yticks(y_ticks if y_ticks is not None else [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
        ax.grid(axis="y", color="#D8D8D8", lw=0.45, alpha=0.55, zorder=0)

        start = 0
        current_group = TERM_SPECS[0][0]
        for idx, spec in enumerate(TERM_SPECS + [(None, None, None)]):
            group = spec[0]
            if group != current_group:
                ax.text(
                    (start + idx - 1) / 2,
                    -0.33,
                    TERM_GROUP_LABELS[current_group],
                    ha="center",
                    va="top",
                    transform=ax.get_xaxis_transform(),
                    fontsize=5.7,
                    color=PALETTE["neutral_mid"],
                    clip_on=False,
                )
                if start > 0:
                    ax.axvline(start - 0.5, color=PALETTE["neutral_mid"], lw=0.65, alpha=0.65)
                start = idx
                current_group = group

        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, 1.23),
            ncol=len(methods),
            fontsize=6.2,
            handlelength=1.1,
            columnspacing=1.0,
        )
        ax.text(
            0.0,
            -0.47,
            (
                "Lower is better. Error bars show 95% CI for n=10 methods; dashed line marks the reference-normalized value of 1.0."
                if draw_ci
                else "Lower is better. Dashed line marks the reference-normalized value of 1.0; arrows show bars clipped above 3.0."
            ),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=6.1,
            color=PALETTE["neutral_mid"],
        )
        fig.subplots_adjust(left=0.08, right=0.995, top=0.78, bottom=0.31)
        outputs.extend(save_figure(fig, f"fig3_{workload.lower()}_{stem_suffix}"))

    return outputs, summary


def fig4_summary(df: pd.DataFrame, methods: list[str]) -> pd.DataFrame:
    rows = []
    for workload in WORKLOADS:
        for method in methods:
            subset = df[(df["workload"] == workload) & (df["method"] == method)]
            if subset.empty:
                raise ValueError(f"Missing Fig. 4 rows for {workload} {method}")
            values = subset["relative_change_pct_vs_reference"].astype(float)
            scores = subset["full_objective_comparable_score"].astype(float)
            has_ci = method not in SINGLE_MAPPING_METHODS and len(values) > 1
            rows.append(
                {
                    "workload": workload,
                    "method": method,
                    "n_source_rows": int(len(subset)),
                    "display_as": "single mapping" if method in SINGLE_MAPPING_METHODS else "mean +/- 95% CI",
                    "relative_change_pct_mean": float(values.mean()),
                    "relative_change_pct_ci95": ci95(values) if has_ci else 0.0,
                    "score_mean": float(scores.mean()),
                    "score_ci95": ci95(scores) if has_ci else 0.0,
                }
            )
    return pd.DataFrame(rows)


def plot_forest_panel(ax: plt.Axes, summary: pd.DataFrame, methods: list[tuple[str, str]], workload: str) -> None:
    ypos = np.arange(len(methods))[::-1]
    ax.axvline(0, color=PALETTE["neutral_mid"], linestyle="--", lw=0.8, zorder=1)
    ax.axvspan(-45, 0, color="#E9F1FA", alpha=0.28, zorder=0)
    ax.axvspan(0, 85, color="#F8E9E6", alpha=0.18, zorder=0)
    for y, (method, label) in zip(ypos, methods):
        row = summary[(summary["workload"] == workload) & (summary["method"] == method)].iloc[0]
        mean = float(row["relative_change_pct_mean"])
        ci = float(row["relative_change_pct_ci95"])
        color = METHOD_COLORS[method]
        marker = METHOD_MARKERS[method]
        if method not in SINGLE_MAPPING_METHODS and ci > 0:
            ax.plot([mean - ci, mean + ci], [y, y], color=color, lw=1.2, solid_capstyle="round", zorder=3)
        marker_size = 4.6 if method != "CommAware-Heuristic" else 5.0
        ax.plot(
            mean,
            y,
            marker=marker,
            ms=marker_size,
            color=color,
            markeredgecolor=PALETTE["neutral_black"],
            markeredgewidth=0.35,
            zorder=4,
        )
    ax.set_xlim(-45, 85)
    ax.set_xticks([-40, -20, 0, 20, 40, 60, 80])
    ax.set_ylim(-0.6, len(methods) - 0.4)
    ax.grid(axis="x", color="#D8D8D8", lw=0.45, alpha=0.55)
    ax.set_yticks(ypos)
    ax.set_yticklabels([label for _, label in methods], fontsize=6.1)
    ax.tick_params(axis="x", labelsize=6.1)
    ax.tick_params(axis="y", length=0)
    ax.set_title(workload, fontsize=7.2, pad=3)


def plot_fig4() -> tuple[list[str], pd.DataFrame]:
    df = pd.read_csv(FIG4_SRC)
    external_methods = [
        ("Full-GA", "Full-GA"),
        ("Thermal-SA-TAS", "Thermal-SA-TAS"),
        ("CommAware-Heuristic", "CommAware-\nHeuristic"),
    ]
    ablation_methods = [
        ("Full-GA", "Full-GA"),
        ("thermal-only", "thermal-only"),
        ("comm-only", "comm-only"),
        ("wout-thermal", "w/o thermal"),
        ("wout-comm", "w/o comm"),
    ]
    keep_methods = sorted({m for m, _ in external_methods + ablation_methods})
    summary = fig4_summary(df[df["method"].isin(keep_methods)], keep_methods)
    summary.to_csv(DATA_DIR / "fig4_plotted_summary.csv", index=False)

    fig, axes = plt.subplots(
        2,
        4,
        figsize=(7.2, 5.05),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.16], "hspace": 0.34, "wspace": 0.18},
    )

    for col, workload in enumerate(WORKLOADS):
        plot_forest_panel(axes[0, col], summary, external_methods, workload)
        plot_forest_panel(axes[1, col], summary, ablation_methods, workload)
        if col != 0:
            axes[0, col].set_yticklabels([])
            axes[1, col].set_yticklabels([])
        axes[0, col].tick_params(axis="x", labelbottom=False)
        axes[1, col].set_xlabel("Relative change vs reference (%)", fontsize=6.4)

    axes[0, 0].text(
        -0.2,
        1.12,
        "a  Main baseline methods",
        transform=axes[0, 0].transAxes,
        ha="left",
        va="bottom",
        fontsize=7.4,
        fontweight="bold",
    )
    axes[1, 0].text(
        -0.2,
        1.12,
        "b  Objective ablations",
        transform=axes[1, 0].transAxes,
        ha="left",
        va="bottom",
        fontsize=7.4,
        fontweight="bold",
    )

    legend_items = [
        Line2D([0], [0], marker="o", color=PALETTE["blue"], lw=1.2, label="mean +/- 95% CI (n=10)"),
        Line2D([0], [0], marker="D", color=PALETTE["neutral_dark"], lw=0, label="single representative mapping"),
        Line2D([0], [0], color=PALETTE["neutral_mid"], linestyle="--", lw=0.8, label="ReferenceMapping"),
    ]
    fig.legend(
        handles=legend_items,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.005),
        ncol=3,
        fontsize=6.2,
        frameon=False,
        handlelength=1.7,
    )
    fig.subplots_adjust(left=0.13, right=0.985, top=0.93, bottom=0.12)

    return save_figure(fig, "fig4_baseline_ablation_full_objective_rescore"), summary


def write_readme(qa: dict[str, object], outputs: dict[str, list[str]]) -> None:
    fig2_files = chr(10).join("- " + p for p in outputs.get("fig2", []))
    fig3_files = chr(10).join("- " + p for p in outputs.get("fig3", []))
    fig2_no_commaware_files = chr(10).join("- " + p for p in outputs.get("fig2_no_commaware", []))
    fig3_no_commaware_files = chr(10).join("- " + p for p in outputs.get("fig3_no_commaware", []))
    fig4_section = ""
    if "fig4" in outputs:
        fig4_files = chr(10).join("- " + p for p in outputs["fig4"])
        fig4_section = f"""
### Fig. 4

Core claim: under the same full-objective rescore, Full-GA outperforms the main baseline methods and objective ablations clarify why the full objective is needed.

Files:
{fig4_files}
"""
    fig4_caption = ""
    if "fig4" in outputs:
        fig4_caption = (
            "- Fig. 4: Full-GA, Thermal-SA-TAS, thermal-only, comm-only, wout-thermal, and wout-comm are n=10 "
            "and have mean +/- 95% CI. CommAware-Heuristic is a single representative mapping and has no CI. "
            "ReferenceMapping is shown only as the 0% reference line."
        )
    text = f"""# Paper Figures From Full-Objective Rescore

This folder was generated by `plot_fig2_fig3_fig4.py` using Python/matplotlib only.

## Scope

- Figures are based on existing source CSV files in `analysis_full_objective_rescore`.
- The script does not rerun OMNeT++ and does not modify original experiment result folders.
- Cross-method comparisons use `full_objective_comparable_score` or `relative_change_pct_vs_reference`.
- Ablation native objective values are not used for horizontal comparison.
- `ReferenceMapping` is the initial/reference mapping and normalization anchor, not a baseline method.
- Main baseline methods are `Thermal-SA-TAS` and `CommAware-Heuristic`.
- `ReferenceMapping` and `CommAware-Heuristic` are plotted without CI because they are not 10-seed method distributions in Fig. 2.

## Palette

- `Thermal-SA-TAS`: `#CDCEF3`, RGB `(205, 206, 243)`.
- `CommAware-Heuristic`: `#F3CFA8`, RGB `(243, 207, 168)`.
- `Full-GA`: `#B7D0EC`, RGB `(183, 208, 236)`.
- Backup/accent color: `#F6BEC2`, RGB `(246, 190, 194)`.
- `ReferenceMapping`: gray `#9D9EA3`; it is the normalization anchor, not a baseline method.

## Outputs

### Fig. 2

Core claim: Full-GA reduces the full-objective composite score relative to ReferenceMapping and outperforms the main baseline methods under the same full-objective rescore.

Files:
{fig2_files}

### Fig. 3

Core claim: each workload's nine normalized objective terms show how Full-GA differs from the reference mapping and the two main baseline methods.

Files:
{fig3_files}

### Fig. 2 Candidate Without CommAware-Heuristic

Purpose: exploratory candidate for deciding whether `CommAware-Heuristic` should remain a main-text baseline. This version keeps `ReferenceMapping`, `Thermal-SA-TAS`, and `Full-GA` only.
The y-axis is tightened to 0-7 because the visually dominant CommAware-Heuristic bars are omitted.

Files:
{fig2_no_commaware_files}

### Fig. 3 Candidate Without CommAware-Heuristic

Purpose: exploratory candidate for reading the nine normalized objective terms without the visually dominant `CommAware-Heuristic` series.
This version restores 95% CI error bars for the n=10 methods and uses a tightened 0-2.8 y-axis.

Files:
{fig3_no_commaware_files}
{fig4_section}

## QA Summary

```json
{json.dumps(qa, indent=2)}
```

## Caption Notes

- Fig. 2: ReferenceMapping is the normalization anchor, not a baseline method. Full-GA is placed as the rightmost bar in each workload group. Full-GA and Thermal-SA-TAS are n=10 and use mean +/- 95% CI; CommAware-Heuristic is a single representative mapping and has no CI. Bar-top labels are full-objective comparable score values, not percentages; individual seed dots are intentionally hidden.
- Fig. 3: four workload-specific grouped bar charts use the nine normalized cost terms (`f_thermal`, `f_sigma`, `f_hot`, `f_makespan`, `f_dvfs`, `f_comm`, `f_congestion`, `f_load`, `f_energy`) on a shared y-axis. Lower is better; ReferenceMapping is the normalization anchor; bars above 3.0 are clipped with arrows and true values printed above the bar. No 95% CI error bars are drawn in Fig. 3.
- Candidate no-CommAware versions are exploratory comparison figures only; they do not change the source data or the full-objective rescore. In the no-CommAware Fig. 3 panels, error bars show 95% CI for the n=10 methods.
{fig4_caption}
"""
    (OUT_DIR / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    apply_style()
    ensure_dirs()
    qa = assert_inputs_valid()
    copied = copy_source_data()
    fig2_paths, fig2_summary = plot_fig2()
    fig3_paths, fig3_summary = plot_fig3()
    fig2_no_commaware_paths, fig2_no_commaware_summary = plot_fig2(
        methods=NO_COMMAWARE_METHODS,
        stem="fig2_full_ga_composite_score_no_commaware",
        summary_name="fig2_plotted_summary_no_commaware.csv",
        y_upper=7.0,
        y_ticks=[0, 1, 2, 3, 4, 5, 6, 7],
    )
    fig3_no_commaware_paths, fig3_no_commaware_summary = plot_fig3(
        methods=NO_COMMAWARE_METHODS,
        stem_suffix="normalized_terms_no_commaware",
        summary_name="fig3_normalized_terms_summary_no_commaware.csv",
        draw_ci=True,
        y_cap=2.8,
        y_ticks=[0, 0.5, 1.0, 1.5, 2.0, 2.5],
    )

    outputs = {
        "fig2": fig2_paths,
        "fig3": fig3_paths,
        "fig2_no_commaware": fig2_no_commaware_paths,
        "fig3_no_commaware": fig3_no_commaware_paths,
    }
    qa.update(
        {
            "copied_source_files": copied,
            "output_files": outputs,
            "fig2_rows_plotted": int(len(fig2_summary)),
            "fig3_term_bars_plotted": int(len(fig3_summary)),
            "fig2_no_commaware_rows_plotted": int(len(fig2_no_commaware_summary)),
            "fig3_no_commaware_term_bars_plotted": int(len(fig3_no_commaware_summary)),
        }
    )
    (OUT_DIR / "qa_summary.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    write_readme(qa, outputs)
    print(json.dumps({"out_dir": str(OUT_DIR), "outputs": outputs}, indent=2))


if __name__ == "__main__":
    main()
