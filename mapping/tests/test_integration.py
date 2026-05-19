"""End-to-end integration test — CSV → optimize → CSV → re-parse."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mapping.task_graph import TaskGraph
from mapping.cost_model import CostModel
from mapping.sa_optimizer import SAOptimizer
from mapping.csv_writer import write_static_csv


def test_integration():
    # Create a task graph
    csv_content = """\
0, -1, 0, 0
1, -2, 15000, 512, 2:-2, 3:-2, 4:-2, 5:-2
2, -2, 50000, 128, 6:-2
3, -2, 50000, 128, 7:-2
4, -2, 50000, 128, 8:-2
5, -2, 50000, 128, 9:-2
6, -2, 30000, 64, 10:-2
7, -2, 30000, 64, 10:-2
8, -2, 30000, 64, 10:-2
9, -2, 30000, 64, 10:-2
10, -2, 20000, 256, -1:-1
"""
    # Write input CSV
    in_f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="\n"
    )
    in_f.write(csv_content)
    in_f.close()
    in_path = Path(in_f.name)

    # Write output CSV
    out_f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="\n"
    )
    out_f.close()
    out_path = Path(out_f.name)

    try:
        # 1. Parse
        graph = TaskGraph.from_csv(in_path)
        assert graph.num_mappable == 10

        # 2. Optimize
        temps = [318.15] * 16
        temps[0] = 320.0
        cm = CostModel(graph, temps, w_T=1.0, w_H=0.5, rows=4, cols=4)
        opt = SAOptimizer(graph, cm, seed=42)
        result = opt.optimize()

        # 3. Write static CSV
        write_static_csv(graph, result.assignment, out_path)

        # 4. Re-parse the output
        graph2 = TaskGraph.from_csv(out_path)

        # 5. Verify
        # All tasks should have peId >= 0 (except GB task 0)
        for tid, node in graph2.tasks.items():
            if tid == 0:
                assert node.assigned_pe == -1, f"T{tid} should remain GB task"
            else:
                assert node.assigned_pe >= 0, f"T{tid} peId={node.assigned_pe} should be >= 0"

        # Successor PE entries should reference valid PEs
        for tid, node in graph2.tasks.items():
            for succ_id, succ_pe in node.successor_pe.items():
                if succ_id == -1:
                    assert succ_pe == -1, f"GB successor should have succPE=-1"
                else:
                    assert 0 <= succ_pe < 16, (
                        f"T{tid}→T{succ_id} succPE={succ_pe} invalid"
                    )
                    # succ_pe should match successor's actual PE
                    assert succ_pe == graph2.tasks[succ_id].assigned_pe, (
                        f"T{tid}→T{succ_id} succPE={succ_pe} ≠ "
                        f"actual PE={graph2.tasks[succ_id].assigned_pe}"
                    )

        print(f"Integration test passed! Output CSV at {out_path}")

    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)


def test_integration_real_csv():
    """End-to-end test with real GEMM CSV."""
    gemm_path = Path(__file__).resolve().parent.parent.parent / "examples" / "task_driven" / "tasks_gemm.csv"
    if not gemm_path.exists():
        print("SKIP: tasks_gemm.csv not found")
        return

    graph = TaskGraph.from_csv(gemm_path)
    assert graph.num_mappable >= 1

    temps = [318.15] * 16
    cm = CostModel(graph, temps, w_T=1.0, w_H=0.5, rows=4, cols=4)
    opt = SAOptimizer(graph, cm, seed=42)
    result = opt.optimize()

    out_f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="\n"
    )
    out_f.close()
    out_path = Path(out_f.name)

    try:
        write_static_csv(graph, result.assignment, out_path)
        graph2 = TaskGraph.from_csv(out_path)

        # All mappable tasks should have valid PE assignments
        for tid in graph2.mappable_task_ids:
            assert graph2.tasks[tid].assigned_pe >= 0

        # Verify successor PE consistency
        for tid, node in graph2.tasks.items():
            for succ_id, succ_pe in node.successor_pe.items():
                if succ_id == -1:
                    continue
                assert succ_pe >= 0
                assert graph2.tasks[succ_id].assigned_pe == succ_pe

        print(f"Real CSV integration test passed! Output at {out_path}")

    finally:
        out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    test_integration()
    test_integration_real_csv()
    print("All integration tests passed!")
