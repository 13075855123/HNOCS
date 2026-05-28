"""Tests for cost_model.py — Manhattan distance and cost calculations."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mapping.task_graph import TaskGraph
from mapping.cost_model import CostModel


def _make_graph():
    """Simple graph: 0=GB, 1→2, 1→3, 2→4, 3→4."""
    import tempfile
    csv = """\
0, -1, 0, 0
1, -2, 15000, 512, 2:-2, 3:-2
2, -2, 50000, 128, 4:-2
3, -2, 50000, 128, 4:-2
4, -2, 20000, 256, -1:-1
"""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="\n"
    )
    f.write(csv)
    f.close()
    p = Path(f.name)
    g = TaskGraph.from_csv(p)
    p.unlink()
    return g


def test_hops():
    g = _make_graph()
    cm = CostModel(g, [318.15] * 16, rows=4, cols=4)

    assert cm.hops(0, 0) == 0
    assert cm.hops(0, 1) == 1
    assert cm.hops(0, 5) == 2   # (0,0)→(1,1)
    assert cm.hops(0, 15) == 6  # (0,0)→(3,3)
    assert cm.hops(5, 0) == 2   # symmetric


def test_thermal_term():
    g = _make_graph()
    # PE 0 at 320K, PE 2 at Tambient
    temps = [318.15] * 16
    temps[0] = 320.0
    cm = CostModel(g, temps, w_T=1.0, w_H=0.0, Tambient=318.15)

    # Task 1 thermal cost on PE 0 with leakage-corrected temp:
    #   leakageFactor = exp((320 - 318.15) / 15.0) ≈ 1.1313
    #   eff_excess = 1.85 * 1.1313 ≈ 2.093
    #   thermal = 1.0 * 2.093 ≈ 2.093
    cost = cm.task_cost(1, 0, {})
    expected = 1.85 * math.exp(1.85 / 15.0)
    assert abs(cost - expected) < 0.01

    # Task 1 on PE 2 (at Tambient): cost = 0
    cost = cm.task_cost(1, 2, {})
    assert abs(cost) < 0.01


def test_comm_term():
    g = _make_graph()
    temps = [318.15] * 16
    cm = CostModel(g, temps, w_T=0.0, w_H=1.0, Tambient=318.15)

    # Assign T1 to PE 0 → then T2 to PE 5 (hops=2), dataSize=512
    assignment = {1: 0}
    cost = cm.task_cost(2, 5, assignment)
    # comm = hops(0,5) * 512 = 2 * 512 = 1024
    assert abs(cost - 1024.0) < 0.1


def test_total_cost_consistent():
    g = _make_graph()
    temps = [318.15] * 16
    cm = CostModel(g, temps, w_T=0.5, w_H=0.5)

    # Manual assignment
    assignment = {1: 0, 2: 4, 3: 8, 4: 12}
    total = cm.total_cost(assignment)

    # Manually compute comm cost
    expected_comm = 0.0
    # T2 on PE4: pred T1(PE0) hops=1, dataSize=512
    expected_comm += 0.5 * (1 * 512)  # = 256
    # T3 on PE8: pred T1(PE0) hops=2, dataSize=512
    expected_comm += 0.5 * (2 * 512)  # = 512
    # T4 on PE12: pred T2(PE4) hops=2*128 + pred T3(PE8) hops=1*128
    expected_comm += 0.5 * (2 * 128 + 1 * 128)  # = 192
    # Load penalty: 4 tasks on 4 distinct PEs → variance=0.1875 * 500
    expected_load = 500.0 * 0.1875  # = 93.75
    expected = expected_comm + expected_load  # = 960 + 93.75

    assert abs(total - expected) < 0.1, f"total={total} expected={expected}"


def test_cost_breakdown():
    g = _make_graph()
    temps = [318.15] * 16
    temps[0] = 320.0
    cm = CostModel(g, temps, w_T=1.0, w_H=0.5, Tambient=318.15)

    assignment = {1: 0, 2: 1, 3: 2, 4: 3}
    bd = cm.cost_breakdown(assignment)

    assert "thermal_cost" in bd
    assert "comm_cost" in bd
    assert "total_cost" in bd
    assert "max_temp_K" in bd
    assert abs(bd["total_cost"] - (bd["thermal_cost"] + bd["comm_cost"] + bd.get("load_penalty", 0))) < 1e-9


def test_normalized_costs():
    g = _make_graph()
    temps = [318.15] * 16
    cm = CostModel(g, temps, w_T=1.0, w_H=0.5)

    assignment = {1: 0, 2: 1, 3: 2, 4: 3}
    nc = cm.normalized_costs(assignment)

    assert "thermal_fraction" in nc
    assert "comm_fraction" in nc
    assert nc["thermal_fraction"] + nc["comm_fraction"] <= 1.0 + 1e-9


if __name__ == "__main__":
    test_hops()
    test_thermal_term()
    test_comm_term()
    test_total_cost_consistent()
    test_cost_breakdown()
    test_normalized_costs()
    print("All cost_model tests passed!")
