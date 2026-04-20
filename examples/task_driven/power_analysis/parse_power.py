#!/usr/bin/env python3
"""
parse_power.py – Parse HNOCS power trace CSV and generate a summary report.

Usage:
    python3 parse_power.py <power_trace.csv> [output_report.md]
"""

import sys
import os

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def parse_power_trace(trace_file):
    """Read power trace CSV into a list of dicts (no pandas dependency)."""
    rows = []
    with open(trace_file) as fh:
        header = None
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if header is None:
                header = parts
                continue
            row = dict(zip(header, parts))
            rows.append(row)
    return rows


def analyze_pe_power(rows):
    """Aggregate per-PE statistics from the parsed rows."""
    pe_stats = {}
    for row in rows:
        if row.get('ComponentType') != 'PE':
            continue
        pe_id = row.get('ComponentID', 'unknown')
        event = row.get('EventType', '')
        try:
            value = float(row.get('Value', 0))
        except ValueError:
            value = 0.0

        if pe_id not in pe_stats:
            pe_stats[pe_id] = {
                'compute_count': 0,
                'send_flit_count': 0,
                'recv_flit_count': 0,
                'power_values': [],
            }

        if event == 'COMPUTE_START':
            pe_stats[pe_id]['compute_count'] += 1
        elif event == 'SEND_FLIT':
            pe_stats[pe_id]['send_flit_count'] += 1
        elif event == 'RECV_FLIT':
            pe_stats[pe_id]['recv_flit_count'] += 1

        pe_stats[pe_id]['power_values'].append(value)

    # Compute averages
    for stats in pe_stats.values():
        vals = stats['power_values']
        stats['avg_power'] = sum(vals) / len(vals) if vals else 0.0
        del stats['power_values']

    return pe_stats


def analyze_router_power(rows):
    """Aggregate router activity counts."""
    router_stats = {}
    for row in rows:
        if row.get('ComponentType') != 'Router':
            continue
        comp_id = row.get('ComponentID', 'unknown')
        try:
            value = float(row.get('Value', 0))
        except ValueError:
            value = 0.0
        router_stats[comp_id] = router_stats.get(comp_id, 0.0) + value
    return router_stats


def generate_report(pe_stats, router_stats, output_file):
    """Write a Markdown power report."""
    with open(output_file, 'w') as f:
        f.write("# HNOCS Power Analysis Report\n\n")

        f.write("## PE Power Statistics\n\n")
        f.write("| PE ID | Compute Events | Sent Flits | Recv Flits | Avg Power (W) |\n")
        f.write("|-------|---------------|------------|------------|---------------|\n")
        for pe_id, stats in sorted(pe_stats.items(), key=lambda x: x[0]):
            f.write(
                f"| {pe_id} | {stats['compute_count']} | "
                f"{stats['send_flit_count']} | {stats['recv_flit_count']} | "
                f"{stats['avg_power']:.3f} |\n"
            )

        f.write("\n## Router Activity\n\n")
        for comp, count in sorted(router_stats.items()):
            f.write(f"- `{comp}`: {count:.0f}\n")

    print(f"Report written to {output_file}")


def plot_power_timeline(trace_file, output_file):
    """Plot per-PE power over time (requires matplotlib)."""
    if not HAS_MATPLOTLIB:
        print("matplotlib not available – skipping plot")
        return

    if HAS_PANDAS:
        df = pd.read_csv(trace_file)
        pe_data = df[df['ComponentType'] == 'PE']
        plt.figure(figsize=(12, 6))
        for pe_id in pe_data['ComponentID'].unique():
            subset = pe_data[pe_data['ComponentID'] == pe_id]
            plt.plot(pd.to_numeric(subset['Time(ns)'], errors='coerce'),
                     pd.to_numeric(subset['Value'], errors='coerce'),
                     label=f'PE{pe_id}', alpha=0.7)
    else:
        rows = parse_power_trace(trace_file)
        from collections import defaultdict
        times_by_pe = defaultdict(list)
        power_by_pe = defaultdict(list)
        for row in rows:
            if row.get('ComponentType') != 'PE':
                continue
            try:
                t = float(row['Time(ns)'])
                v = float(row['Value'])
            except (KeyError, ValueError):
                continue
            pe_id = row.get('ComponentID', '?')
            times_by_pe[pe_id].append(t)
            power_by_pe[pe_id].append(v)

        plt.figure(figsize=(12, 6))
        for pe_id in sorted(times_by_pe.keys()):
            plt.plot(times_by_pe[pe_id], power_by_pe[pe_id],
                     label=f'PE{pe_id}', alpha=0.7)

    plt.xlabel('Time (ns)')
    plt.ylabel('Power (W)')
    plt.title('PE Power Consumption Over Time')
    plt.legend(ncol=4, fontsize='small')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Power timeline plot saved to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 parse_power.py <power_trace.csv> [report.md]")
        sys.exit(1)

    trace_file   = sys.argv[1]
    report_file  = sys.argv[2] if len(sys.argv) > 2 else "power_report.md"

    if not os.path.isfile(trace_file):
        print(f"Error: file not found: {trace_file}")
        sys.exit(1)

    rows        = parse_power_trace(trace_file)
    pe_stats    = analyze_pe_power(rows)
    router_stats = analyze_router_power(rows)

    generate_report(pe_stats, router_stats, report_file)
    plot_power_timeline(trace_file, "power_timeline.png")
