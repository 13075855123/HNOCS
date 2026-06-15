"""Create Figure 1: simulation-in-the-loop ONoC remapping framework.

This is a conceptual schematic. It uses no experimental numerical data.
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
        "font.size": 8.0,
        "axes.linewidth": 0.8,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "legend.frameon": False,
        "savefig.facecolor": "white",
    }
)


OUT_DIR = Path(__file__).resolve().parent
BASE = OUT_DIR / "figure1_framework"
DPI = 600

PALETTE = {
    "blue_main": "#0F4D92",
    "blue_mid": "#3775BA",
    "blue_soft": "#EAF2FB",
    "blue_pale": "#F5F9FE",
    "orange": "#C86F1A",
    "orange_soft": "#FFF2E4",
    "teal": "#42949E",
    "teal_soft": "#E9F5F6",
    "neutral_0": "#FFFFFF",
    "neutral_1": "#F7F7F7",
    "neutral_2": "#E5E7EB",
    "neutral_3": "#A9AFB7",
    "neutral_4": "#69717A",
    "neutral_5": "#272727",
}

TEXT_ARTISTS = []


def add_text(ax, x, y, text, **kwargs):
    defaults = {
        "ha": "left",
        "va": "center",
        "color": PALETTE["neutral_5"],
        "fontsize": 7.2,
        "linespacing": 1.12,
        "zorder": 8,
    }
    defaults.update(kwargs)
    artist = ax.text(x, y, text, **defaults)
    TEXT_ARTISTS.append(artist)
    return artist


def add_box(
    ax,
    x,
    y,
    w,
    h,
    facecolor,
    edgecolor=PALETTE["neutral_3"],
    lw=0.8,
    radius=0.012,
    zorder=1,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        linewidth=lw,
        edgecolor=edgecolor,
        facecolor=facecolor,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def add_arrow(
    ax,
    start,
    end,
    color=PALETTE["blue_main"],
    lw=1.4,
    rad=0.0,
    mutation_scale=12,
    zorder=5,
):
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=mutation_scale,
        linewidth=lw,
        color=color,
        shrinkA=4,
        shrinkB=4,
        connectionstyle=f"arc3,rad={rad}",
        zorder=zorder,
    )
    ax.add_patch(arrow)
    return arrow


def draw_genome(ax, x, y, w, h, colors, n=16, zorder=6):
    gap = w * 0.012
    cell_w = (w - gap * (n - 1)) / n
    for i in range(n):
        ax.add_patch(
            Rectangle(
                (x + i * (cell_w + gap), y),
                cell_w,
                h,
                facecolor=colors[i % len(colors)],
                edgecolor="white",
                linewidth=0.25,
                zorder=zorder,
            )
        )


def draw_workload_panel(ax):
    x, y, w, h = 0.035, 0.285, 0.158, 0.485
    add_box(ax, x, y, w, h, PALETTE["neutral_0"], PALETTE["neutral_3"], lw=0.9)
    add_text(
        ax,
        x + 0.012,
        y + h - 0.044,
        "Workload and\ninitial mapping",
        fontsize=7.8,
        fontweight="bold",
        color=PALETTE["blue_main"],
        va="top",
    )

    # Compact DAG icon.
    nodes = [
        (x + 0.044, y + 0.300),
        (x + 0.025, y + 0.235),
        (x + 0.064, y + 0.235),
        (x + 0.044, y + 0.170),
        (x + 0.090, y + 0.170),
    ]
    edges = [(0, 1), (0, 2), (1, 3), (2, 3), (2, 4)]
    for a, b in edges:
        ax.plot(
            [nodes[a][0], nodes[b][0]],
            [nodes[a][1], nodes[b][1]],
            color=PALETTE["neutral_4"],
            linewidth=0.8,
            zorder=3,
        )
    for idx, (nx, ny) in enumerate(nodes):
        ax.add_patch(
            Circle(
                (nx, ny),
                0.010,
                facecolor=PALETTE["blue_soft"],
                edgecolor=PALETTE["blue_main"],
                linewidth=0.8,
                zorder=4,
            )
        )
        add_text(
            ax,
            nx,
            ny,
            str(idx + 1),
            fontsize=5.0,
            ha="center",
            va="center",
            color=PALETTE["blue_main"],
        )

    add_text(
        ax,
        x + 0.096,
        y + 0.285,
        "DAG workload\nGEMM / MPEG4\nVOPD / HNN",
        fontsize=6.6,
        va="top",
    )

    # Original mapping icon as a 4x4 PE assignment grid.
    gx, gy, cell = x + 0.025, y + 0.080, 0.014
    grid_colors = ["#E6EEF8", "#D5E3F3", "#FBE4CA", "#E8EEF1"]
    for r in range(4):
        for c in range(4):
            ax.add_patch(
                Rectangle(
                    (gx + c * cell, gy + (3 - r) * cell),
                    cell * 0.86,
                    cell * 0.86,
                    facecolor=grid_colors[(r + c) % len(grid_colors)],
                    edgecolor=PALETTE["neutral_3"],
                    linewidth=0.35,
                    zorder=4,
                )
            )
    add_text(
        ax,
        x + 0.096,
        y + 0.125,
        "Original\ntask-to-PE\nmapping",
        fontsize=6.3,
        va="center",
    )

    add_box(
        ax,
        x + 0.016,
        y + 0.020,
        w - 0.032,
        0.045,
        PALETTE["blue_pale"],
        PALETTE["blue_mid"],
        lw=0.6,
        radius=0.007,
        zorder=3,
    )
    add_text(
        ax,
        x + w / 2,
        y + 0.042,
        "task graph + mapping vector",
        fontsize=5.5,
        ha="center",
        color=PALETTE["blue_main"],
    )
    return x, y, w, h


def draw_ga_panel(ax):
    x, y, w, h = 0.225, 0.285, 0.138, 0.485
    add_box(ax, x, y, w, h, PALETTE["blue_pale"], PALETTE["blue_mid"], lw=1.0)
    add_text(
        ax,
        x + 0.014,
        y + h - 0.044,
        "GA candidate\nmapping",
        fontsize=7.8,
        fontweight="bold",
        color=PALETTE["blue_main"],
        va="top",
    )
    add_text(ax, x + 0.014, y + 0.338, "population", fontsize=6.4, color=PALETTE["neutral_4"])
    genome_colors = ["#0F4D92", "#3775BA", "#8DAED4", "#C86F1A"]
    for i, yy in enumerate([0.300, 0.272, 0.244]):
        draw_genome(ax, x + 0.018, y + yy, w - 0.036, 0.014, genome_colors[i:] + genome_colors[:i])

    add_box(
        ax,
        x + 0.018,
        y + 0.165,
        w - 0.036,
        0.056,
        PALETTE["neutral_0"],
        PALETTE["neutral_3"],
        lw=0.6,
        radius=0.006,
        zorder=3,
    )
    add_text(
        ax,
        x + w / 2,
        y + 0.193,
        "crossover + mutation",
        fontsize=6.4,
        ha="center",
        color=PALETTE["neutral_5"],
    )
    add_text(
        ax,
        x + w / 2,
        y + 0.120,
        "individual = complete\ntask-to-PE assignment",
        fontsize=5.9,
        ha="center",
        va="center",
    )
    add_box(
        ax,
        x + 0.016,
        y + 0.020,
        w - 0.032,
        0.045,
        PALETTE["neutral_0"],
        PALETTE["blue_mid"],
        lw=0.6,
        radius=0.007,
        zorder=3,
    )
    add_text(
        ax,
        x + w / 2,
        y + 0.042,
        "candidate remapped mapping",
        fontsize=5.4,
        ha="center",
        color=PALETTE["blue_main"],
    )
    return x, y, w, h


def draw_omnet_panel(ax):
    x, y, w, h = 0.392, 0.190, 0.290, 0.645
    add_box(ax, x, y, w, h, PALETTE["neutral_0"], PALETTE["blue_main"], lw=1.2, radius=0.014)
    add_text(
        ax,
        x + 0.016,
        y + h - 0.045,
        "OMNeT++ full-system evaluation",
        fontsize=8.2,
        fontweight="bold",
        color=PALETTE["blue_main"],
        va="top",
    )
    add_text(
        ax,
        x + 0.016,
        y + h - 0.092,
        "8-wavelength WDM ONoC | 4x4 / 16 PE",
        fontsize=6.7,
        color=PALETTE["neutral_4"],
        va="top",
    )

    # PE array and optical fabric.
    grid_x, grid_y = x + 0.085, y + 0.168
    cell, gap = 0.034, 0.011
    bus_color = PALETTE["blue_mid"]
    for r in range(4):
        yy = grid_y + r * (cell + gap) + cell / 2
        ax.plot(
            [grid_x - 0.022, grid_x + 4 * cell + 3 * gap + 0.022],
            [yy, yy],
            color=bus_color,
            linewidth=1.0,
            alpha=0.75,
            zorder=2,
        )
    for c in range(4):
        xx = grid_x + c * (cell + gap) + cell / 2
        ax.plot(
            [xx, xx],
            [grid_y - 0.022, grid_y + 4 * cell + 3 * gap + 0.022],
            color=bus_color,
            linewidth=1.0,
            alpha=0.75,
            zorder=2,
        )
    for r in range(4):
        for c in range(4):
            xx = grid_x + c * (cell + gap)
            yy = grid_y + r * (cell + gap)
            ax.add_patch(
                Rectangle(
                    (xx, yy),
                    cell,
                    cell,
                    facecolor=PALETTE["blue_soft"],
                    edgecolor=PALETTE["blue_main"],
                    linewidth=0.65,
                    zorder=4,
                )
            )
            if r in (0, 3) and c in (0, 3):
                add_text(ax, xx + cell / 2, yy + cell / 2, "PE", fontsize=4.8, ha="center", va="center")

    # MRR rings along the optical fabric.
    ring_points = [
        (grid_x - 0.018, grid_y + 0.5 * cell),
        (grid_x - 0.018, grid_y + 2.5 * (cell + gap)),
        (grid_x + 4 * cell + 3 * gap + 0.018, grid_y + 1.5 * (cell + gap)),
        (grid_x + 4 * cell + 3 * gap + 0.018, grid_y + 3.1 * (cell + gap)),
        (grid_x + 1.5 * (cell + gap), grid_y - 0.018),
        (grid_x + 2.7 * (cell + gap), grid_y + 4 * cell + 3 * gap + 0.018),
    ]
    for rx, ry in ring_points:
        ax.add_patch(
            Circle(
                (rx, ry),
                0.0075,
                facecolor="white",
                edgecolor=PALETTE["orange"],
                linewidth=1.0,
                zorder=5,
            )
        )

    # Laser and SOA blocks.
    add_box(ax, x + 0.021, y + 0.345, 0.046, 0.042, PALETTE["orange_soft"], PALETTE["orange"], lw=0.7, radius=0.006)
    add_text(ax, x + 0.044, y + 0.366, "laser", fontsize=5.8, ha="center", color=PALETTE["orange"])
    add_box(ax, x + 0.021, y + 0.286, 0.046, 0.042, PALETTE["orange_soft"], PALETTE["orange"], lw=0.7, radius=0.006)
    add_text(ax, x + 0.044, y + 0.307, "SOA", fontsize=5.8, ha="center", color=PALETTE["orange"])
    add_arrow(ax, (x + 0.069, y + 0.366), (grid_x - 0.024, y + 0.366), color=PALETTE["orange"], lw=0.9, mutation_scale=8)
    add_arrow(ax, (x + 0.069, y + 0.307), (grid_x - 0.024, y + 0.307), color=PALETTE["orange"], lw=0.9, mutation_scale=8)

    add_text(ax, x + 0.196, y + 0.399, "MRR tuning", fontsize=5.9, color=PALETTE["orange"])
    add_text(ax, x + 0.165, y + 0.099, "PE array + optical links", fontsize=6.2, ha="center", color=PALETTE["blue_main"])

    add_box(ax, x + 0.029, y + 0.036, 0.088, 0.042, PALETTE["neutral_1"], PALETTE["neutral_3"], lw=0.55, radius=0.006)
    add_text(ax, x + 0.073, y + 0.057, "thermal RC", fontsize=5.8, ha="center", color=PALETTE["neutral_4"])
    add_box(ax, x + 0.178, y + 0.036, 0.088, 0.042, PALETTE["neutral_1"], PALETTE["neutral_3"], lw=0.55, radius=0.006)
    add_text(ax, x + 0.222, y + 0.057, "DVFS feedback", fontsize=5.6, ha="center", color=PALETTE["neutral_4"])

    return x, y, w, h


def draw_metrics_panel(ax):
    x, y, w, h = 0.714, 0.190, 0.142, 0.645
    add_box(ax, x, y, w, h, PALETTE["neutral_0"], PALETTE["neutral_3"], lw=0.9)
    add_text(
        ax,
        x + 0.012,
        y + h - 0.043,
        "Coupled feedback\nmetrics",
        fontsize=7.8,
        fontweight="bold",
        color=PALETTE["blue_main"],
        va="top",
    )
    blocks = [
        ("thermal safety", "T_max, sigma_T,\nN_hot", PALETTE["orange_soft"], PALETTE["orange"]),
        ("performance", "makespan,\nDVFS penalty", PALETTE["blue_pale"], PALETTE["blue_mid"]),
        ("communication", "comm cost,\ncongestion proxy", PALETTE["teal_soft"], PALETTE["teal"]),
        ("mapping balance", "load imbalance", PALETTE["neutral_1"], PALETTE["neutral_4"]),
        ("energy", "total PE +\noptical energy", PALETTE["blue_soft"], PALETTE["blue_main"]),
    ]
    block_h = 0.083
    top = y + h - 0.175
    for i, (label, value, fc, ec) in enumerate(blocks):
        yy = top - i * 0.092
        add_box(ax, x + 0.014, yy, w - 0.028, block_h, fc, ec, lw=0.55, radius=0.006, zorder=3)
        add_text(ax, x + 0.023, yy + block_h - 0.014, label, fontsize=5.35, fontweight="bold", color=ec, va="top")
        add_text(ax, x + 0.023, yy + 0.024, value, fontsize=5.15, color=PALETTE["neutral_5"], va="center")
    return x, y, w, h


def draw_cost_panel(ax):
    x, y, w, h = 0.881, 0.285, 0.104, 0.485
    add_box(ax, x, y, w, h, PALETTE["orange_soft"], PALETTE["orange"], lw=1.0)
    add_text(
        ax,
        x + w / 2,
        y + h - 0.050,
        "Normalized\ncomposite cost",
        fontsize=7.4,
        fontweight="bold",
        color=PALETTE["orange"],
        ha="center",
        va="top",
    )
    add_box(ax, x + 0.022, y + 0.260, w - 0.044, 0.075, "white", PALETTE["orange"], lw=0.7, radius=0.008, zorder=3)
    add_text(ax, x + w / 2, y + 0.298, "F(M)", fontsize=12.2, fontweight="bold", ha="center", color=PALETTE["neutral_5"])
    add_text(
        ax,
        x + w / 2,
        y + 0.198,
        "baseline-normalized\nobjective",
        fontsize=5.9,
        ha="center",
        va="center",
    )
    add_box(ax, x + 0.018, y + 0.070, w - 0.036, 0.060, "white", PALETTE["orange"], lw=0.65, radius=0.007, zorder=3)
    add_text(ax, x + w / 2, y + 0.100, "selection", fontsize=6.5, fontweight="bold", ha="center", color=PALETTE["orange"])
    return x, y, w, h


def detect_text_overlaps(fig, artists, min_area_px=12, min_fraction=0.10):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bboxes = []
    for i, artist in enumerate(artists):
        if not artist.get_visible() or not artist.get_text().strip():
            continue
        bbox = artist.get_window_extent(renderer=renderer).expanded(1.01, 1.04)
        bboxes.append((i, artist.get_text(), bbox))

    overlaps = []
    for (i, text_i, box_i), (j, text_j, box_j) in combinations(bboxes, 2):
        x0 = max(box_i.x0, box_j.x0)
        y0 = max(box_i.y0, box_j.y0)
        x1 = min(box_i.x1, box_j.x1)
        y1 = min(box_i.y1, box_j.y1)
        if x1 <= x0 or y1 <= y0:
            continue
        area = (x1 - x0) * (y1 - y0)
        smallest = min(box_i.width * box_i.height, box_j.width * box_j.height)
        if area >= min_area_px and area / max(smallest, 1.0) >= min_fraction:
            overlaps.append(
                {
                    "text_a": text_i.replace("\n", " / "),
                    "text_b": text_j.replace("\n", " / "),
                    "area_px2": round(float(area), 1),
                    "fraction_of_smaller": round(float(area / max(smallest, 1.0)), 3),
                }
            )
    return overlaps


def image_stats(path):
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im)
    nonwhite = np.mean(np.any(arr < 248, axis=2))
    return {
        "width_px": int(im.width),
        "height_px": int(im.height),
        "nonwhite_pixel_fraction": round(float(nonwhite), 4),
    }


def make_single_column_preview(png_path, out_path, width_mm=89.0, dpi=600):
    im = Image.open(png_path).convert("RGB")
    target_w = int(round(width_mm / 25.4 * dpi))
    target_h = int(round(target_w * im.height / im.width))
    resized = im.resize((target_w, target_h), Image.Resampling.LANCZOS)
    resized.save(out_path, dpi=(dpi, dpi))
    return image_stats(out_path)


def main():
    TEXT_ARTISTS.clear()
    fig = plt.figure(figsize=(8.2, 4.55), dpi=DPI, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    add_text(
        ax,
        0.5,
        0.952,
        "Simulation-in-the-loop thermal-aware task remapping framework for ONoC.",
        fontsize=11.2,
        fontweight="bold",
        ha="center",
        color=PALETTE["neutral_5"],
    )
    add_text(
        ax,
        0.5,
        0.890,
        "Simulation-in-the-loop optimization cycle",
        fontsize=7.2,
        fontweight="bold",
        ha="center",
        color=PALETTE["orange"],
    )

    workload = draw_workload_panel(ax)
    ga = draw_ga_panel(ax)
    omnet = draw_omnet_panel(ax)
    metrics = draw_metrics_panel(ax)
    cost = draw_cost_panel(ax)

    # Forward dataflow.
    add_arrow(ax, (workload[0] + workload[2], 0.528), (ga[0], 0.528), color=PALETTE["blue_main"])
    add_arrow(ax, (ga[0] + ga[2], 0.528), (omnet[0], 0.528), color=PALETTE["blue_main"])
    add_arrow(ax, (omnet[0] + omnet[2], 0.528), (metrics[0], 0.528), color=PALETTE["blue_main"])
    add_arrow(ax, (metrics[0] + metrics[2], 0.528), (cost[0], 0.528), color=PALETTE["blue_main"])

    label_box = {"facecolor": "white", "edgecolor": "none", "pad": 0.8}
    add_text(
        ax,
        0.381,
        0.565,
        "simulate each\ncandidate",
        fontsize=5.7,
        ha="center",
        color=PALETTE["neutral_4"],
        bbox=label_box,
    )
    add_text(
        ax,
        0.698,
        0.565,
        "parse\noutputs",
        fontsize=5.7,
        ha="center",
        color=PALETTE["neutral_4"],
        bbox=label_box,
    )
    add_text(
        ax,
        0.864,
        0.565,
        "aggregate",
        fontsize=5.7,
        ha="center",
        color=PALETTE["neutral_4"],
        bbox=label_box,
    )

    # Feedback loop from objective value back to GA selection.
    loop_start = (cost[0] + cost[2] * 0.50, cost[1] - 0.002)
    loop_mid_y = 0.115
    loop_end_x = ga[0] + ga[2] * 0.50
    ax.plot(
        [loop_start[0], loop_start[0], loop_end_x],
        [loop_start[1], loop_mid_y, loop_mid_y],
        color=PALETTE["orange"],
        linewidth=1.45,
        solid_capstyle="round",
        zorder=4,
    )
    add_arrow(
        ax,
        (loop_end_x, loop_mid_y),
        (loop_end_x, ga[1] - 0.006),
        color=PALETTE["orange"],
        lw=1.45,
        rad=0.0,
        mutation_scale=13,
        zorder=4,
    )
    add_text(
        ax,
        0.610,
        loop_mid_y + 0.022,
        "selection / next generation",
        fontsize=6.4,
        fontweight="bold",
        ha="center",
        color=PALETTE["orange"],
        bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.6},
    )

    overlaps = detect_text_overlaps(fig, TEXT_ARTISTS)

    export_paths = {
        "svg": str(BASE.with_suffix(".svg")),
        "pdf": str(BASE.with_suffix(".pdf")),
        "png": str(BASE.with_suffix(".png")),
        "tiff": str(BASE.with_suffix(".tiff")),
    }
    fig.savefig(export_paths["svg"], bbox_inches="tight", pad_inches=0.035)
    fig.savefig(export_paths["pdf"], bbox_inches="tight", pad_inches=0.035)
    fig.savefig(export_paths["png"], dpi=DPI, bbox_inches="tight", pad_inches=0.035)
    fig.savefig(export_paths["tiff"], dpi=DPI, bbox_inches="tight", pad_inches=0.035)
    plt.close(fig)

    single_preview = OUT_DIR / "figure1_framework_single_column_preview.png"
    preview_stats = make_single_column_preview(BASE.with_suffix(".png"), single_preview)

    file_checks = {}
    for fmt, path_str in export_paths.items():
        path = Path(path_str)
        file_checks[fmt] = {
            "path": str(path),
            "bytes": path.stat().st_size if path.exists() else 0,
            "nonempty": path.exists() and path.stat().st_size > 0,
        }
        if fmt in {"png", "tiff"} and path.exists():
            file_checks[fmt].update(image_stats(path))

    qa = {
        "backend": "Python/matplotlib",
        "dpi": DPI,
        "figure_archetype": "schematic-led composite",
        "designed_width_in": 8.2,
        "designed_height_in": 4.55,
        "single_column_preview": {
            "path": str(single_preview),
            "target_width_mm": 89.0,
            **preview_stats,
        },
        "file_checks": file_checks,
        "text_overlap_check": {
            "major_overlap_count": len(overlaps),
            "major_overlaps": overlaps,
        },
        "notes": [
            "Conceptual pipeline schematic; no experimental numerical values are plotted.",
            "SVG uses svg.fonttype='none' so labels remain editable text.",
            "PDF uses TrueType font embedding via pdf.fonttype=42.",
        ],
    }

    qa_path = OUT_DIR / "figure1_framework_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
