from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
FIG_DIR = Path(__file__).resolve().parent
AGG_PATH = ROOT / "aggregate_summary.csv"
RUNS_PATH = ROOT / "runs_summary.csv"

WORKLOAD_ORDER = ["GEMM", "MPEG4", "VOPD", "HNN"]


mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 7,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.8,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "legend.frameon": False,
    }
)


def main() -> None:
    agg = pd.read_csv(AGG_PATH)
    runs = pd.read_csv(RUNS_PATH)

    agg = agg[agg["benchmark"].isin(WORKLOAD_ORDER)].copy()
    runs = runs[(runs["benchmark"].isin(WORKLOAD_ORDER)) & (runs["valid"])].copy()

    agg["benchmark"] = pd.Categorical(agg["benchmark"], WORKLOAD_ORDER, ordered=True)
    runs["benchmark"] = pd.Categorical(runs["benchmark"], WORKLOAD_ORDER, ordered=True)
    agg = agg.sort_values("benchmark")
    runs = runs.sort_values(["benchmark", "seed"])

    agg["improvement_mean_pct"] = -agg["cost_delta_pct_mean"]
    agg["improvement_ci95_half_pct"] = agg["cost_delta_pct_ci95_half"]
    agg["improvement_std_pct"] = agg["cost_delta_pct_std"]
    runs["improvement_pct"] = -runs["cost_delta_pct"]

    source = runs[["benchmark", "seed", "improvement_pct", "cost_delta_pct"]].merge(
        agg[
            [
                "benchmark",
                "n",
                "valid_count",
                "improvement_mean_pct",
                "improvement_std_pct",
                "improvement_ci95_half_pct",
            ]
        ],
        on="benchmark",
        how="left",
    )
    source.to_csv(FIG_DIR / "composite_cost_improvement_source_data.csv", index=False)

    x = np.arange(len(WORKLOAD_ORDER))
    means = agg["improvement_mean_pct"].to_numpy()
    ci = agg["improvement_ci95_half_pct"].to_numpy()

    fig, ax = plt.subplots(figsize=(3.55, 2.45))

    bar_color = "#5C8FA8"
    edge_color = "#2F5364"
    dot_color = "#263238"

    ax.bar(
        x,
        means,
        width=0.58,
        color=bar_color,
        edgecolor=edge_color,
        linewidth=0.8,
        zorder=2,
    )
    ax.errorbar(
        x,
        means,
        yerr=ci,
        fmt="none",
        ecolor="#263238",
        elinewidth=0.9,
        capsize=2.5,
        capthick=0.9,
        zorder=4,
    )

    rng = np.random.default_rng(20260614)
    for i, workload in enumerate(WORKLOAD_ORDER):
        vals = runs.loc[runs["benchmark"] == workload, "improvement_pct"].to_numpy()
        jitter = rng.uniform(-0.13, 0.13, size=len(vals))
        ax.scatter(
            np.full_like(vals, i, dtype=float) + jitter,
            vals,
            s=14,
            facecolor=dot_color,
            edgecolor="white",
            linewidth=0.35,
            alpha=0.72,
            zorder=5,
        )

    for i, mean in enumerate(means):
        ax.text(
            i,
            mean + ci[i] + 1.0,
            f"{mean:.1f}%",
            ha="center",
            va="bottom",
            fontsize=7,
            color="#263238",
        )

    ax.axhline(0, color="#7A7A7A", linewidth=0.8, zorder=1)
    ax.set_xticks(x, WORKLOAD_ORDER)
    ax.set_ylabel("Composite cost improvement over Original (%)")
    ax.set_xlabel("")
    ax.set_ylim(0, max(means + ci) + 5.2)
    ax.set_title("B-2-v4 composite cost improvement", loc="left", pad=6, fontsize=8.5)
    fig.text(
        0.12,
        0.02,
        "Bars: mean; error bars: 95% CI; dots: individual seeds (n = 10)",
        ha="left",
        va="bottom",
        fontsize=6.5,
        color="#4D4D4D",
    )
    ax.grid(axis="y", color="#E8E8E8", linewidth=0.6, zorder=0)
    ax.tick_params(axis="x", length=0)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.88, bottom=0.2)

    out_base = FIG_DIR / "composite_cost_improvement_b2v4"
    fig.savefig(out_base.with_suffix(".png"), dpi=600, bbox_inches="tight")
    fig.savefig(out_base.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(out_base.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(out_base.with_suffix(".tiff"), dpi=600, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
