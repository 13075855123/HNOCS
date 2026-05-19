"""Tests for task_graph.py — CSV parsing, DAG structure, topological order."""

import sys
import tempfile
from pathlib import Path

# Add project root for imports from mapping/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mapping.task_graph import TaskGraph, TaskNode


def _write_csv(content: str) -> Path:
    """Write a temporary CSV and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="\n"
    )
    f.write(content)
    f.close()
    return Path(f.name)


# ------------------------------------------------------------------


def test_parse_simple():
    csv = """\
0, -1, 0, 0
1, -2, 15000, 512, 2:-2, 3:-2
2, -2, 50000, 128, -1:-1
3, -2, 50000, 128, -1:-1
"""
    path = _write_csv(csv)
    g = TaskGraph.from_csv(path)
    path.unlink()

    assert g.num_tasks == 4
    assert g.num_mappable == 3
    assert len(g.gb_task_ids) == 1

    # Check GB task
    assert g.tasks[0].is_gb_task
    assert g.tasks[0].assigned_pe == -1

    # Check dynamic tasks
    assert g.tasks[1].is_mappable
    assert g.tasks[2].is_mappable
    assert g.tasks[3].is_mappable

    # Check predecessors
    assert set(g.tasks[2].predecessor_set) == {1}
    assert set(g.tasks[3].predecessor_set) == {1}


def test_topological_order():
    csv = """\
0, -1, 0, 0
1, -2, 15000, 512, 2:-2
2, -2, 30000, 256, 3:-2, 4:-2
3, -2, 20000, 128, -1:-1
4, -2, 20000, 128, -1:-1
"""
    path = _write_csv(csv)
    g = TaskGraph.from_csv(path)
    path.unlink()

    order = g.topological_order()
    # Check all predecessors appear before their dependents
    pos = {tid: i for i, tid in enumerate(order)}
    for tid, node in g.tasks.items():
        for pred in node.predecessor_set:
            assert pos[pred] < pos[tid], f"Task {pred} must precede {tid}"


def test_duplicate_task_id():
    csv = """\
1, -2, 100, 10, 2:-2
2, -2, 200, 20
1, -2, 300, 30
"""
    path = _write_csv(csv)
    try:
        TaskGraph.from_csv(path)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    finally:
        path.unlink()


def test_parse_gemm_csv():
    """Parse the real GEMM CSV file."""
    gemm_path = Path(__file__).resolve().parent.parent.parent / "examples" / "task_driven" / "tasks_gemm.csv"
    if not gemm_path.exists():
        print(f"SKIP: {gemm_path} not found")
        return

    g = TaskGraph.from_csv(gemm_path)
    assert g.num_tasks == 11  # T0 (GB) + T1-T10
    assert g.num_mappable == 10
    assert len(g.gb_task_ids) == 1

    # Check DAG structure: T1 → T2,T3,T4,T5
    t1 = g.tasks[1]
    assert set(t1.successors) == {2, 3, 4, 5}
    assert len(t1.predecessor_set) == 0

    # T2 → T6
    assert g.tasks[2].successors == [6]
    assert g.tasks[6].predecessor_set == {2}

    # T10 is the final gather (leaf)
    assert g.tasks[10].successors == [-1]


def test_parse_mpeg4_csv():
    mpeg4_path = Path(__file__).resolve().parent.parent.parent / "examples" / "task_driven" / "tasks_mpeg4.csv"
    if not mpeg4_path.exists():
        print(f"SKIP: {mpeg4_path} not found")
        return

    g = TaskGraph.from_csv(mpeg4_path)
    assert g.num_mappable > 0
    order = g.topological_order()
    assert len(order) == g.num_tasks


def test_parse_vopd_csv():
    vopd_path = Path(__file__).resolve().parent.parent.parent / "examples" / "task_driven" / "tasks_vopd.csv"
    if not vopd_path.exists():
        print(f"SKIP: {vopd_path} not found")
        return

    g = TaskGraph.from_csv(vopd_path)
    # VOPD has a long pipeline: T1→T2→T3→T4→T5→T6→T7
    # Verify pipeline chain
    for tid in range(1, 7):
        assert tid + 1 in g.tasks[tid].successors, f"T{tid} should have successor T{tid+1}"


def test_parse_optic_calib_csv():
    optic_path = Path(__file__).resolve().parent.parent.parent / "examples" / "task_driven" / "tasks_optic_calib.csv"
    if not optic_path.exists():
        print(f"SKIP: {optic_path} not found")
        return

    g = TaskGraph.from_csv(optic_path)
    # Optic Calib: T0 (GB) injects to T1-T16; each sends result back to GB.
    for tid in range(1, 17):
        node = g.tasks[tid]
        assert node.successors == [-1], f"T{tid} should only have GB successor"
        assert node.predecessor_set == {0}, f"T{tid} should have GB as predecessor"


def test_mappable_task_ids():
    csv = """\
0, -1, 0, 0
1, -2, 100, 10, 2:-2
2, -2, 200, 20, -1:-1
3, 5, 300, 30
"""
    path = _write_csv(csv)
    g = TaskGraph.from_csv(path)
    path.unlink()

    mappable = g.mappable_task_ids
    assert set(mappable) == {1, 2}
    # Task 3 has peId=5 (static), not mappable


def test_comments_and_empty_lines():
    csv = """\
# This is a comment
0, -1, 0, 0

1, -2, 100, 10, 2:-2
# Another comment
2, -2, 200, 20, -1:-1
"""
    path = _write_csv(csv)
    g = TaskGraph.from_csv(path)
    path.unlink()

    assert g.num_tasks == 3


if __name__ == "__main__":
    test_parse_simple()
    test_topological_order()
    test_duplicate_task_id()
    test_parse_gemm_csv()
    test_parse_mpeg4_csv()
    test_parse_vopd_csv()
    test_parse_optic_calib_csv()
    test_mappable_task_ids()
    test_comments_and_empty_lines()
    print("All task_graph tests passed!")
