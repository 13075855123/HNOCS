"""
CSV writer — output an optimized task-to-PE mapping as a static CSV.

The generated CSV is compatible with the existing static-mode code path:
- Tasks have peId >= 0 (optimized assignment)
- successorPE filled with the PE of each successor task
- GB injection tasks (peId == -1) preserved unchanged
- succId == -1 (send to GB) → succPE == -1 preserved
"""

from __future__ import annotations

from pathlib import Path

from .task_graph import TaskGraph


def write_static_csv(
    graph: TaskGraph,
    assignment: dict[int, int],
    output_path: str | Path,
    comment: str = "",
) -> None:
    """Write the optimized mapping as a static CSV file.

    Parameters
    ----------
    graph : TaskGraph
        The parsed task graph (with original peId=-2 for dynamic tasks).
    assignment : dict[int, int]
        {taskId: peId} for all mappable tasks.
    output_path : str or Path
        Where to write the CSV file.
    comment : str
        Optional comment line(s) to prepend (without '#' prefix).
    """
    output_path = Path(output_path)
    _validate_assignment(graph, assignment)
    lines: list[str] = []

    # Header comments
    if comment:
        for cline in comment.strip().split("\n"):
            lines.append(f"# {cline.strip()}")
    lines.append(
        f"# Optimized static mapping — {graph.num_mappable} mappable tasks"
    )

    # Preserve source row order so a remap changes placement, not ready-queue ties.
    write_order = graph.input_order or graph.topological_order()
    for tid in write_order:
        node = graph.tasks[tid]
        pe = node.assigned_pe if node.is_gb_task else assignment.get(tid, node.assigned_pe)

        fields = [
            str(tid),
            str(pe),
            str(int(node.compute_time_ns)),
            str(node.output_data_size),
        ]

        for succ_id in node.successors:
            if succ_id == -1:
                succ_pe = -1
            elif succ_id in graph.tasks and graph.tasks[succ_id].is_gb_task:
                succ_pe = -1
            elif succ_id in assignment:
                succ_pe = assignment[succ_id]
            elif succ_id in graph.tasks:
                succ_pe = graph.tasks[succ_id].assigned_pe  # static task
            else:
                raise ValueError(f"Task {tid} references unknown successor {succ_id}")
            fields.append(f"{succ_id}:{succ_pe}")

        lines.append(", ".join(fields))

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _validate_assignment(graph: TaskGraph, assignment: dict[int, int]) -> None:
    """Validate a mapping before writing a simulator-facing CSV."""
    missing = [tid for tid in graph.mappable_task_ids if tid not in assignment]
    if missing:
        raise ValueError(f"Missing PE assignment for mappable tasks: {missing}")

    for tid, pe in assignment.items():
        if tid not in graph.tasks:
            raise ValueError(f"Assignment contains unknown task {tid}")
        if graph.tasks[tid].is_gb_task:
            raise ValueError(f"GB task {tid} must not be assigned to a PE")
        if not isinstance(pe, int) or pe < 0:
            raise ValueError(f"Task {tid} has invalid assigned PE {pe}")

    for tid, node in graph.tasks.items():
        if not node.is_gb_task and not node.is_dynamic and node.assigned_pe < 0:
            raise ValueError(f"Task {tid} has invalid static PE {node.assigned_pe}")
        if node.compute_time_ns < 0:
            raise ValueError(f"Task {tid} has negative compute time {node.compute_time_ns}")
        if node.output_data_size < 0:
            raise ValueError(f"Task {tid} has negative output size {node.output_data_size}")
        for succ_id in node.successors:
            if succ_id == -1:
                continue
            if succ_id not in graph.tasks:
                raise ValueError(f"Task {tid} references unknown successor {succ_id}")
