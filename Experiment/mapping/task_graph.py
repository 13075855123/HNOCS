"""
TaskGraph — DAG representation for task-driven NoC simulation.

Mirrors the C++ TaskGraphParser logic (src/utils/TaskGraphParser.cc) and
the TaskDescriptor data model (src/cores/task/TaskDescriptor.h).

CSV format:
    taskId, peId, compTime_ns, outSize_B, [succId:succPE, ...]

    peId = -1  → GB injection task (not mappable, preserved as-is)
    peId = -2  → dynamic task (target for optimization)
    peId >= 0  → static PE assignment
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TaskNode:
    """A single node in the task DAG."""
    task_id: int
    assigned_pe: int                # -1=GB, -2=dynamic, >=0=static PE
    compute_time_ns: float          # nanoseconds
    output_data_size: int           # bytes
    successors: list[int] = field(default_factory=list)
    # {successor_task_id: pe_id}  — read from CSV, rewritten by optimizer
    successor_pe: dict[int, int] = field(default_factory=dict)
    predecessor_set: set[int] = field(default_factory=set)

    @property
    def is_gb_task(self) -> bool:
        return self.assigned_pe == -1

    @property
    def is_dynamic(self) -> bool:
        return self.assigned_pe == -2

    @property
    def is_mappable(self) -> bool:
        """True if this task should be assigned a PE by the optimizer."""
        return self.assigned_pe == -2


class TaskGraph:
    """Directed Acyclic Graph of all tasks, with topological-order utilities."""

    def __init__(self):
        self.tasks: dict[int, TaskNode] = {}
        self._topo_order: Optional[list[int]] = None
        self._input_order: list[int] = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_csv(cls, filepath: str | Path) -> "TaskGraph":
        """Parse a task CSV into a TaskGraph.

        Mirrors TaskGraphParser::parse() logic exactly.
        """
        graph = cls()
        filepath = Path(filepath)

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line_num, raw in enumerate(f, 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue

                tokens = _split_csv(line)
                if len(tokens) < 4:
                    raise ValueError(
                        f"{filepath}:{line_num} — need at least 4 columns "
                        f"(taskId,peId,compTime_ns,outSize_B), got {len(tokens)}"
                    )

                task_id       = int(tokens[0])
                pe_id         = int(tokens[1])
                comp_time_ns  = float(tokens[2])
                out_size_b    = int(tokens[3])

                if task_id in graph.tasks:
                    raise ValueError(
                        f"{filepath}:{line_num} — duplicate taskId {task_id}"
                    )

                node = TaskNode(
                    task_id=task_id,
                    assigned_pe=pe_id,
                    compute_time_ns=comp_time_ns,
                    output_data_size=out_size_b,
                )

                # Parse successor pairs: succTaskId:succPE
                for i in range(4, len(tokens)):
                    token = tokens[i]
                    if not token:
                        continue
                    if ":" not in token:
                        raise ValueError(
                            f"{filepath}:{line_num} — bad successor format "
                            f"'{token}' (need taskId:peId)"
                        )
                    succ_str, pe_str = token.split(":", 1)
                    succ_id = int(succ_str)
                    succ_pe = int(pe_str)
                    node.successors.append(succ_id)
                    node.successor_pe[succ_id] = succ_pe

                graph.tasks[task_id] = node
                graph._input_order.append(task_id)

        # Pass 2: compute predecessor sets from successor lists
        for node in graph.tasks.values():
            for succ_id in node.successors:
                succ_node = graph.tasks.get(succ_id)
                if succ_node is not None:
                    succ_node.predecessor_set.add(node.task_id)

        return graph

    # ------------------------------------------------------------------
    # Topological ordering
    # ------------------------------------------------------------------
    def topological_order(self) -> list[int]:
        """Return task IDs in topological order (Kahn's algorithm).

        Guarantees: every task appears after all of its predecessors.
        """
        if self._topo_order is not None:
            return self._topo_order

        in_degree: dict[int, int] = {
            tid: len(node.predecessor_set)
            for tid, node in self.tasks.items()
        }
        queue: deque[int] = deque(
            tid for tid, deg in in_degree.items() if deg == 0
        )
        order: list[int] = []

        while queue:
            tid = queue.popleft()
            order.append(tid)
            node = self.tasks[tid]
            for succ_id in node.successors:
                if succ_id in in_degree:
                    in_degree[succ_id] -= 1
                    if in_degree[succ_id] == 0:
                        queue.append(succ_id)

        if len(order) != len(self.tasks):
            remaining = set(self.tasks.keys()) - set(order)
            raise ValueError(
                f"Task graph contains a cycle involving tasks: {remaining}"
            )

        self._topo_order = order
        return order

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def mappable_task_ids(self) -> list[int]:
        """Return task IDs with peId == -2, in topological order."""
        topo = self.topological_order()
        return [
            tid for tid in topo
            if self.tasks[tid].is_mappable
        ]

    @property
    def gb_task_ids(self) -> list[int]:
        """Return task IDs with peId == -1 (GB injection tasks)."""
        return [
            tid for tid, node in self.tasks.items()
            if node.is_gb_task
        ]

    @property
    def num_mappable(self) -> int:
        return sum(1 for n in self.tasks.values() if n.is_mappable)

    @property
    def num_tasks(self) -> int:
        return len(self.tasks)

    @property
    def input_order(self) -> list[int]:
        """Return task IDs in the order they appeared in the source CSV."""
        return list(self._input_order)

    def predecessors_of(self, task_id: int) -> set[int]:
        node = self.tasks.get(task_id)
        return node.predecessor_set if node else set()

    def get_assignment(self) -> dict[int, int]:
        """Return {taskId: assignedPE} for all mappable tasks."""
        return {
            tid: node.assigned_pe
            for tid, node in self.tasks.items()
            if node.is_mappable
        }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------
def _split_csv(line: str) -> list[str]:
    """Split a CSV line, stripping whitespace from each field."""
    return [tok.strip() for tok in line.split(",")]
