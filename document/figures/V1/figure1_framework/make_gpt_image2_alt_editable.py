"""Redraw the GPT-image Figure 1 alternative as editable vector artwork.

The source PNG is a raster design reference. This script rebuilds the same
conceptual layout with matplotlib shapes and text so the SVG can be edited in
PowerPoint, Illustrator, Inkscape, or similar tools.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
plt.rcParams["svg.fonttype"] = "none"

import matplotlib as mpl
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image


mpl.rcParams.update(
    {
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.size": 8,
        "savefig.facecolor": "white",
    }
)

OUT_DIR = Path(__file__).resolve().parent
BASE = OUT_DIR / "figure1_framework_gpt_image2_alt_editable"
DPI = 600

C = {
    "blue": "#0F4D92",
    "blue2": "#2E6DB4",
    "blue3": "#DCEAF8",
    "orange": "#D56D0D",
    "orange2": "#FFF3E7",
    "teal": "#158C8C",
    "teal2": "#E8F6F5",
    "gray0": "#FFFFFF",
    "gray1": "#F6F7F8",
    "gray2": "#E7EAEE",
    "gray3": "#B8BEC6",
    "gray4": "#6D7480",
    "black": "#242424",
}

TEXTS: list[mpl.text.Text] = []


def text(ax, x, y, s, **kwargs):
    defaults = dict(ha="left", va="center", fontsize=7.3, color=C["black"], zorder=10, linespacing=1.08)
    defaults.update(kwargs)
    t = ax.text(x, y, s, **defaults)
    TEXTS.append(t)
    return t


def box(ax, x, y, w, h, fc="white", ec=None, lw=0.8, r=0.006, z=1):
    if ec is None:
        ec = C["gray3"]
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.004,rounding_size={r}",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        zorder=z,
    )
    ax.add_patch(p)
    return p


def arrow(ax, a, b, color=C["gray4"], lw=1.3, scale=12, z=8):
    p = FancyArrowPatch(
        a,
        b,
        arrowstyle="-|>",
        mutation_scale=scale,
        linewidth=lw,
        color=color,
        shrinkA=3,
        shrinkB=3,
        zorder=z,
    )
    ax.add_patch(p)
    return p


def numbered_header(ax, x, y, w, number, title):
    sq = 0.030
    ax.add_patch(Rectangle((x + 0.014, y - sq / 2), sq, sq, facecolor=C["blue"], edgecolor=C["blue"], zorder=4))
    text(ax, x + 0.014 + sq / 2, y, str(number), ha="center", va="center", fontsize=10.5, color="white", fontweight="bold")
    text(ax, x + 0.055, y, title, ha="left", va="center", fontsize=7.7, color=C["blue"], fontweight="bold")
    ax.plot([x, x + w], [y - 0.054, y - 0.054], color=C["gray3"], lw=0.65, zorder=3)


def panel(ax, x, y, w, h, number, title):
    box(ax, x, y, w, h, fc="white", ec=C["gray3"], lw=0.8, r=0.008)
    numbered_header(ax, x, y + h - 0.050, w, number, title)
    return (x, y, w, h)


def draw_workload(ax, p):
    x, y, w, h = p
    text(ax, x + w / 2, y + h - 0.145, "DAG workload", ha="center", fontsize=6.9, fontweight="bold")
    text(ax, x + w / 2, y + h - 0.205, "GEMM / MPEG4 /\nVOPD / HNN", ha="center", fontsize=7.0)

    cx, cy = x + w * 0.50, y + 0.375
    nodes = [
        (cx, cy + 0.115),
        (cx - 0.056, cy + 0.055),
        (cx + 0.056, cy + 0.055),
        (cx - 0.086, cy - 0.026),
        (cx, cy - 0.030),
        (cx + 0.086, cy - 0.026),
        (cx - 0.052, cy - 0.100),
        (cx + 0.052, cy - 0.100),
    ]
    edges = [(0, 1), (0, 2), (1, 3), (1, 4), (2, 4), (2, 5), (3, 6), (4, 6), (4, 7), (5, 7)]
    for a, b in edges:
        arrow(ax, nodes[a], nodes[b], color=C["gray4"], lw=0.6, scale=6, z=3)
    for i, (nx, ny) in enumerate(nodes):
        ax.add_patch(Circle((nx, ny), 0.010, fc=C["blue3"], ec=C["blue"], lw=0.6, zorder=5))
        if i in [1, 2, 4, 5]:
            ax.add_patch(Circle((nx + 0.008, ny + 0.008), 0.006, fc="#EDF4FB", ec=C["gray3"], lw=0.45, zorder=6))

    ax.plot([x + 0.018, x + w - 0.018], [y + 0.242, y + 0.242], color=C["gray3"], lw=0.6, ls=(0, (3, 2)))
    text(ax, x + w / 2, y + 0.205, "Original task-to-PE mapping", ha="center", fontsize=6.1, fontweight="bold")
    sx = x + 0.025
    sy = y + 0.155
    for i, lab in enumerate(["0", "1", "2", "...", "14", "15"]):
        ww = 0.026 if lab != "..." else 0.035
        if lab == "...":
            text(ax, sx, sy + 0.012, lab, ha="center", fontsize=6.5)
        else:
            ax.add_patch(Rectangle((sx - ww / 2, sy), ww, 0.024, fc=C["gray1"], ec=C["gray3"], lw=0.6, zorder=4))
            text(ax, sx, sy + 0.012, lab, ha="center", fontsize=5.8)
        sx += 0.030 if lab != "..." else 0.040
    arrow(ax, (x + w / 2, y + 0.137), (x + w / 2, y + 0.100), color=C["blue"], lw=1.0, scale=9)
    text(ax, x + w / 2, y + 0.065, "Output:\ntask graph + mapping vector", ha="center", fontsize=6.1, color=C["blue"], fontweight="bold")


def genome_row(ax, x, y, nums, highlight=None):
    cell = 0.020
    for i, n in enumerate(nums):
        xx = x + i * cell
        if n == "...":
            text(ax, xx + cell / 2, y + 0.010, "...", ha="center", fontsize=5.4)
            continue
        fc = "#F7F8FA" if highlight != i else "#F4A35D"
        ax.add_patch(Rectangle((xx, y), cell * 0.86, 0.020, fc=fc, ec=C["gray3"], lw=0.5, zorder=4))
        text(ax, xx + cell * 0.43, y + 0.010, str(n), ha="center", fontsize=4.9)


def draw_ga(ax, p):
    x, y, w, h = p
    text(ax, x + w / 2, y + h - 0.125, "population", ha="center", fontsize=6.8, fontweight="bold")
    for yy, row in zip([0.565, 0.525, 0.485], [[3, 7, 1, 12, "...", 9, 4], [0, 5, 2, 15, "...", 6, 11], [14, 10, 8, 3, "...", 1, 13]]):
        genome_row(ax, x + 0.040, y + yy, row)

    ax.plot([x + 0.018, x + w - 0.018], [y + 0.455, y + 0.455], color=C["gray3"], lw=0.6, ls=(0, (3, 2)))
    text(ax, x + w / 2, y + 0.415, "crossover", ha="center", fontsize=6.7, fontweight="bold")
    genome_row(ax, x + 0.047, y + 0.370, [3, 7, 1, 12, 9, 4])
    genome_row(ax, x + 0.047, y + 0.330, [14, 10, 8, 3, 1, 13])
    ax.plot([x + w / 2, x + w / 2], [y + 0.362, y + 0.395], color=C["gray4"], lw=0.7, ls=(0, (2, 2)))
    arrow(ax, (x + w / 2, y + 0.317), (x + w / 2, y + 0.290), color=C["gray4"], lw=0.8, scale=8)
    genome_row(ax, x + 0.047, y + 0.260, [3, 7, 1, 3, 1, 13])

    ax.plot([x + 0.018, x + w - 0.018], [y + 0.225, y + 0.225], color=C["gray3"], lw=0.6, ls=(0, (3, 2)))
    text(ax, x + w / 2, y + 0.190, "mutation", ha="center", fontsize=6.7, fontweight="bold")
    genome_row(ax, x + 0.047, y + 0.150, [3, 7, 1, 3, 6, 13], highlight=4)
    arrow(ax, (x + 0.147, y + 0.136), (x + 0.147, y + 0.158), color=C["black"], lw=0.65, scale=6)
    text(ax, x + w / 2, y + 0.090, "individual = complete\ntask-to-PE assignment", ha="center", fontsize=6.3, fontweight="bold")
    arrow(ax, (x + w / 2, y + 0.054), (x + w / 2, y + 0.030), color=C["blue"], lw=1.0, scale=9)
    text(ax, x + w / 2, y + 0.012, "Output:\ncandidate remapped mapping", ha="center", fontsize=5.8, color=C["blue"], fontweight="bold")


def draw_omnet(ax, p):
    x, y, w, h = p
    inner = (x + 0.014, y + 0.115, w - 0.028, h - 0.215)
    box(ax, *inner, fc="white", ec=C["gray3"], lw=0.75, r=0.006, z=1)
    ix, iy, iw, ih = inner
    text(ax, x + 0.060, y + h - 0.075, "OMNeT++ Full-system Evaluation", fontsize=7.8, color=C["blue"], fontweight="bold")
    text(ax, x + 0.060, y + h - 0.118, "8-wavelength WDM ONoC  |  4x4 / 16 PE", fontsize=6.3)

    # Legend
    lx = ix + 0.020
    ly = iy + ih - 0.045
    ax.add_patch(Rectangle((lx, ly - 0.012), 0.018, 0.024, fc=C["gray1"], ec=C["gray4"], lw=0.5))
    text(ax, lx + 0.026, ly, "PE", fontsize=5.6)
    ax.plot([lx + 0.080, lx + 0.100], [ly, ly], color=C["blue2"], lw=1.2)
    arrow(ax, (lx + 0.080, ly), (lx + 0.100, ly), color=C["blue2"], lw=0.8, scale=5)
    text(ax, lx + 0.108, ly, "optical link\n(WDM)", fontsize=5.1)
    ax.add_patch(Circle((lx + 0.190, ly), 0.010, fc="white", ec=C["orange"], lw=1.0))
    text(ax, lx + 0.205, ly, "MRR", fontsize=5.4)
    ax.add_patch(Rectangle((lx + 0.250, ly - 0.010), 0.020, 0.020, fc="#FBE3AD", ec="#A6762A", lw=0.5))
    text(ax, lx + 0.278, ly, "SOA", fontsize=5.4)
    box(ax, lx + 0.328, ly - 0.012, 0.030, 0.024, fc="#C9E0E6", ec=C["gray4"], lw=0.5, r=0.002, z=4)
    text(ax, lx + 0.343, ly, "laser", ha="center", fontsize=4.7)

    # 4x4 PE fabric
    gx = ix + 0.050
    gy = iy + 0.050
    cw, ch = 0.036, 0.052
    ggap_x, ggap_y = 0.030, 0.040
    centers = []
    for r in range(4):
        for c in range(4):
            px = gx + c * (cw + ggap_x)
            py = gy + (3 - r) * (ch + ggap_y)
            centers.append((px + cw / 2, py + ch / 2))
    for r in range(4):
        for c in range(3):
            a = centers[r * 4 + c]
            b = centers[r * 4 + c + 1]
            ax.plot([a[0], b[0]], [a[1], b[1]], color=C["blue2"], lw=1.2, zorder=2)
            arrow(ax, (a[0] + 0.010, a[1]), (b[0] - 0.010, b[1]), color=C["blue2"], lw=0.75, scale=5, z=3)
            arrow(ax, (b[0] - 0.010, b[1] - 0.006), (a[0] + 0.010, a[1] - 0.006), color=C["blue2"], lw=0.75, scale=5, z=3)
    for c in range(4):
        for r in range(3):
            a = centers[r * 4 + c]
            b = centers[(r + 1) * 4 + c]
            ax.plot([a[0], b[0]], [a[1], b[1]], color=C["blue2"], lw=1.2, zorder=2)
            arrow(ax, (a[0], a[1] - 0.010), (b[0], b[1] + 0.010), color=C["blue2"], lw=0.75, scale=5, z=3)

    idx = 0
    for r in range(4):
        for c in range(4):
            px = gx + c * (cw + ggap_x)
            py = gy + (3 - r) * (ch + ggap_y)
            ax.add_patch(Rectangle((px, py), cw, ch, fc=C["gray1"], ec=C["black"], lw=0.55, zorder=5))
            text(ax, px + cw / 2, py + ch / 2, f"PE\n{idx}", ha="center", fontsize=5.3)
            ax.add_patch(Circle((px + cw + 0.007, py + 0.010), 0.007, fc="white", ec=C["orange"], lw=0.8, zorder=6))
            idx += 1
    grid_right = gx + 4 * cw + 3 * ggap_x
    for yy in [gy + 0.015, gy + 0.145, gy + 0.275]:
        ax.add_patch(Rectangle((gx - 0.040, yy), 0.020, 0.018, fc="#FBE3AD", ec="#A6762A", lw=0.45, zorder=5))
        ax.add_patch(Rectangle((grid_right + 0.020, yy), 0.020, 0.018, fc="#FBE3AD", ec="#A6762A", lw=0.45, zorder=5))
    for xy in [(gx - 0.034, gy + 0.340), (grid_right + 0.018, gy + 0.340), (gx - 0.036, gy - 0.020), (grid_right + 0.016, gy - 0.020)]:
        ax.add_patch(Rectangle(xy, 0.023, 0.020, fc="#C9E0E6", ec=C["gray4"], lw=0.45, zorder=5))

    box(ax, x + 0.020, y + 0.020, w - 0.040, 0.075, fc="white", ec=C["gray3"], lw=0.7, r=0.006)
    text(
        ax,
        x + w / 2,
        y + 0.058,
        "dynamic MRR thermal tuning  |  DVFS feedback  |  power/energy model\ncompact RC thermal network  |  traffic, contention and queues",
        ha="center",
        fontsize=5.3,
    )


def metric_box(ax, x, y, w, h, title, body, color, icon):
    box(ax, x, y, w, h, fc="white", ec=color, lw=0.75, r=0.006, z=2)
    if icon == "therm":
        ax.add_patch(Circle((x + 0.027, y + h / 2 - 0.012), 0.012, fc="white", ec=C["orange"], lw=1.1))
        ax.plot([x + 0.027, x + 0.027], [y + h / 2 - 0.006, y + h / 2 + 0.030], color=C["orange"], lw=2.0)
    elif icon == "speed":
        ax.add_patch(Circle((x + 0.028, y + h / 2), 0.020, fc=C["blue3"], ec=C["blue"], lw=0.9))
        ax.plot([x + 0.028, x + 0.043], [y + h / 2, y + h / 2 + 0.012], color=C["blue"], lw=1.0)
    elif icon == "net":
        pts = [(x + 0.018, y + 0.025), (x + 0.045, y + 0.025), (x + 0.032, y + 0.055), (x + 0.018, y + 0.070), (x + 0.050, y + 0.070)]
        for a, b in [(0, 2), (1, 2), (2, 3), (2, 4)]:
            ax.plot([pts[a][0], pts[b][0]], [pts[a][1], pts[b][1]], color=C["teal"], lw=0.9)
        for px, py in pts:
            ax.add_patch(Circle((px, py), 0.0048, fc="white", ec=C["teal"], lw=0.8))
    elif icon == "balance":
        ax.plot([x + 0.016, x + 0.055], [y + 0.060, y + 0.060], color=C["blue"], lw=1.0)
        ax.plot([x + 0.035, x + 0.035], [y + 0.030, y + 0.080], color=C["blue"], lw=1.0)
        ax.plot([x + 0.024, x + 0.045], [y + 0.030, y + 0.030], color=C["blue"], lw=1.0)
    else:
        ax.add_patch(Rectangle((x + 0.024, y + 0.025), 0.014, 0.050, angle=-8, fc=C["blue"], ec=C["blue"], lw=0.7))
    text(ax, x + 0.070, y + h - 0.028, title, fontsize=5.9, color=color, fontweight="bold", va="top")
    text(ax, x + 0.070, y + 0.028, body, fontsize=5.7, va="bottom")


def draw_metrics(ax, p):
    x, y, w, h = p
    specs = [
        ("thermal safety:", "T_max, sigma_T,\nN_hot", C["orange"], "therm"),
        ("performance:", "makespan,\nDVFS penalty", C["blue"], "speed"),
        ("communication\npressure:", "comm cost,\ncongestion proxy", C["teal"], "net"),
        ("mapping balance:", "load imbalance", C["blue"], "balance"),
        ("energy:", "total PE +\noptical energy", C["blue"], "bolt"),
    ]
    top = y + h - 0.175
    for i, spec in enumerate(specs):
        metric_box(ax, x + 0.016, top - i * 0.112, w - 0.032, 0.090, *spec)


def draw_cost(ax, p):
    x, y, w, h = p
    text(ax, x + w / 2, y + h - 0.175, "baseline-normalized\nobjective", ha="center", fontsize=7.0, fontweight="bold")
    box(ax, x + 0.030, y + 0.360, w - 0.060, 0.120, fc="white", ec=C["orange"], lw=0.9, r=0.006)
    text(ax, x + w / 2, y + 0.420, "F(M)", ha="center", fontsize=17.5, color=C["orange"], fontweight="bold")
    ax.plot([x + 0.024, x + w - 0.024], [y + 0.285, y + 0.285], color=C["gray3"], lw=0.65, ls=(0, (3, 2)))
    # Clipboard icon
    ax.add_patch(Rectangle((x + w / 2 - 0.025, y + 0.150), 0.050, 0.075, fc="white", ec=C["orange"], lw=1.1, zorder=4))
    ax.add_patch(Rectangle((x + w / 2 - 0.014, y + 0.215), 0.028, 0.015, fc=C["orange"], ec=C["orange"], zorder=5))
    for yy in [0.200, 0.180, 0.160]:
        ax.plot([x + w / 2 - 0.010, x + w / 2 + 0.017], [y + yy, y + yy], color=C["orange"], lw=0.8)
        ax.add_patch(Circle((x + w / 2 - 0.016, y + yy), 0.0035, fc="white", ec=C["orange"], lw=0.8))
    text(ax, x + w / 2, y + 0.075, "selection /\nnext generation", ha="center", fontsize=7.0, color=C["orange"], fontweight="bold")


def detect_overlaps(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes = []
    for t in TEXTS:
        if t.get_visible() and t.get_text().strip():
            boxes.append((t.get_text().replace("\n", " / "), t.get_window_extent(renderer=renderer).expanded(1.01, 1.03)))
    overlaps = []
    for (ta, ba), (tb, bb) in combinations(boxes, 2):
        x0, y0 = max(ba.x0, bb.x0), max(ba.y0, bb.y0)
        x1, y1 = min(ba.x1, bb.x1), min(ba.y1, bb.y1)
        if x1 <= x0 or y1 <= y0:
            continue
        area = (x1 - x0) * (y1 - y0)
        frac = area / max(1.0, min(ba.width * ba.height, bb.width * bb.height))
        if area > 15 and frac > 0.12:
            overlaps.append({"text_a": ta, "text_b": tb, "area_px2": round(float(area), 1), "fraction": round(float(frac), 3)})
    return overlaps


def main():
    TEXTS.clear()
    fig = plt.figure(figsize=(16.93, 9.29), dpi=160, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    text(
        ax,
        0.5,
        0.965,
        "Simulation-in-the-loop thermal-aware task remapping framework for ONoC.",
        ha="center",
        fontsize=15.0,
        fontweight="bold",
    )

    y, h = 0.130, 0.780
    panels = [
        panel(ax, 0.014, y, 0.156, h, 1, "Workload and\nInitial Mapping"),
        panel(ax, 0.190, y, 0.154, h, 2, "GA Candidate\nMapping"),
        panel(ax, 0.365, y, 0.310, h, 3, "OMNeT++ Full-system Evaluation"),
        panel(ax, 0.690, y, 0.150, h, 4, "Coupled Feedback\nMetrics"),
        panel(ax, 0.858, y, 0.128, h, 5, "Normalized Composite\nCost and Selection"),
    ]

    draw_workload(ax, panels[0])
    draw_ga(ax, panels[1])
    draw_omnet(ax, panels[2])
    draw_metrics(ax, panels[3])
    draw_cost(ax, panels[4])

    # Data-flow arrows
    for a, b in [
        ((0.170, 0.518), (0.190, 0.518)),
        ((0.344, 0.518), (0.365, 0.518)),
        ((0.675, 0.518), (0.695, 0.518)),
        ((0.840, 0.518), (0.858, 0.518)),
    ]:
        arrow(ax, a, b, color=C["gray4"], lw=1.6, scale=18)

    # Feedback loop
    ax.plot([0.922, 0.922, 0.263, 0.263], [0.130, 0.055, 0.055, 0.105], color=C["orange"], lw=2.2, zorder=2)
    arrow(ax, (0.263, 0.105), (0.263, 0.130), color=C["orange"], lw=2.2, scale=17)
    text(ax, 0.515, 0.078, "selection / next generation", ha="center", fontsize=7.8, color=C["orange"], fontweight="bold")

    # Small legend
    arrow(ax, (0.030, 0.020), (0.060, 0.020), color=C["gray4"], lw=1.8, scale=18)
    text(ax, 0.067, 0.020, "data / candidate flow", fontsize=6.2)
    arrow(ax, (0.205, 0.020), (0.240, 0.020), color=C["orange"], lw=2.1, scale=18)
    text(ax, 0.247, 0.020, "feedback / closed-loop", fontsize=6.2)

    overlaps = detect_overlaps(fig)

    fig.savefig(BASE.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(BASE.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(BASE.with_suffix(".png"), dpi=DPI, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)

    im = Image.open(BASE.with_suffix(".png"))
    qa = {
        "source_reference": str(OUT_DIR / "figure1_framework_gpt_image2_alt.png"),
        "method": "manual structured redraw with Python/matplotlib; not bitmap autotrace",
        "backend": "Python/matplotlib",
        "editable_text": "SVG generated with svg.fonttype=none",
        "outputs": {
            "svg": {"path": str(BASE.with_suffix(".svg")), "bytes": BASE.with_suffix(".svg").stat().st_size},
            "pdf": {"path": str(BASE.with_suffix(".pdf")), "bytes": BASE.with_suffix(".pdf").stat().st_size},
            "png_preview": {
                "path": str(BASE.with_suffix(".png")),
                "bytes": BASE.with_suffix(".png").stat().st_size,
                "width_px": im.width,
                "height_px": im.height,
            },
        },
        "text_overlap_check": {"major_overlap_count": len(overlaps), "major_overlaps": overlaps},
        "notes": [
            "The output is an editable vector reconstruction of the AI raster design.",
            "It preserves the five-module layout, central ONoC hero panel, metric blocks, and feedback loop.",
            "Text and shapes are separately editable in SVG-capable editors, subject to each editor's SVG import behavior.",
        ],
    }
    (OUT_DIR / "figure1_framework_gpt_image2_alt_editable_qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
