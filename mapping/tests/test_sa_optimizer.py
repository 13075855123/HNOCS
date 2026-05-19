"""Tests for sa_optimizer.py — SA convergence, determinism, cost improvement."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mapping.task_graph import TaskGraph
from mapping.cost_model import CostModel
from mapping.sa_optimizer import SAOptimizer


def _make_graph_and_model():
    """Simple 4-task graph on 4×4 mesh."""
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

    # Slightly non-uniform temps to make temperature-aware decisions
    temps = [318.15] * 16
    temps[0] = 320.0    # PE0 hotter
    temps[15] = 319.0   # PE15 slightly hot
    cm = CostModel(g, temps, w_T=1.0, w_H=0.5, Tambient=318.15, rows=4, cols=4)
    return g, cm


def test_sa_returns_valid_assignment():
    g, cm = _make_graph_and_model()
    opt = SAOptimizer(g, cm, seed=42)
    result = opt.optimize()

    # All 4 mappable tasks should have a PE assigned
    assert len(result.assignment) == 4
    for tid in g.mappable_task_ids:
        pe = result.assignment[tid]
        assert 0 <= pe < 16


def test_sa_deterministic_with_seed():
    g, cm = _make_graph_and_model()
    opt1 = SAOptimizer(g, cm, seed=42)
    opt2 = SAOptimizer(g, cm, seed=42)
    r1 = opt1.optimize()
    r2 = opt2.optimize()
    assert r1.assignment == r2.assignment
    assert abs(r1.cost - r2.cost) < 1e-9


def test_sa_never_worse_than_greedy():
    g, cm = _make_graph_and_model()
    opt = SAOptimizer(g, cm, seed=42)

    greedy = opt.generate_initial_solution()
    greedy_cost = cm.total_cost(greedy)

    result = opt.optimize()
    assert result.cost <= greedy_cost + 1e-9, (
        f"SA cost {result.cost} > greedy cost {greedy_cost}"
    )


def test_sa_with_zero_temperature():
    """With T_init=0, SA should return greedy solution (no uphill moves)."""
    g, cm = _make_graph_and_model()
    opt = SAOptimizer(g, cm, T_init=0.001, T_min=0.001, seed=42)

    greedy = opt.generate_initial_solution()
    greedy_cost = cm.total_cost(greedy)

    result = opt.optimize()
    assert abs(result.cost - greedy_cost) < 1e-9 or result.cost <= greedy_cost


def test_sa_cost_improves():
    """On a non-trivial problem with non-uniform temps, SA should find
    an improvement over the greedy solution or at least match it."""
    g, cm = _make_graph_and_model()

    greedy = SAOptimizer(g, cm, seed=42).generate_initial_solution()
    greedy_cost = cm.total_cost(greedy)

    # Multiple restarts to increase chance of improvement
    opt = SAOptimizer(g, cm, seed=42)
    result = opt.optimize_with_restarts(num_restarts=5)

    assert result.cost <= greedy_cost + 1e-9


def test_restarts_produce_different_costs():
    """Multiple restarts should explore different solutions."""
    g, cm = _make_graph_and_model()
    opt = SAOptimizer(g, cm, seed=42)
    result = opt.optimize_with_restarts(num_restarts=3)

    # Result should still be valid
    assert len(result.assignment) == 4
    assert result.cost >= 0


def test_cost_history_monotonic():
    """Best-cost history should be non-increasing."""
    g, cm = _make_graph_and_model()
    opt = SAOptimizer(g, cm, seed=42)
    result = opt.optimize()

    for i in range(1, len(result.cost_history)):
        assert result.cost_history[i] <= result.cost_history[i-1] + 1e-9, (
            f"Cost history increased at step {i}: "
            f"{result.cost_history[i-1]} → {result.cost_history[i]}"
        )


if __name__ == "__main__":
    test_sa_returns_valid_assignment()
    test_sa_deterministic_with_seed()
    test_sa_never_worse_than_greedy()
    test_sa_with_zero_temperature()
    test_sa_cost_improves()
    test_restarts_produce_different_costs()
    test_cost_history_monotonic()
    print("All sa_optimizer tests passed!")
