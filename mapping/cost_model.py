"""
CostModel — thermal-aware joint cost function for task-to-PE mapping.

Cost for assigning task_i to PE_j (evaluated in topological order):

    cost(PE_j, task_i) = w_T * (T_j - Tambient)
                       + w_H * sum over predecessors p of i:
                           hops(assignment[p], PE_j) * dataSize(p, i)

Communication cost is computed per-edge: each predecessor → task pair
contributes its data size weighted by Manhattan distance.
GB predecessors (peId == -1) contribute zero communication cost.
"""

from __future__ import annotations

import math
from typing import Optional

from .task_graph import TaskGraph


class CostModel:
    """Computes thermal-aware mapping cost for a given assignment."""

    # Load-imbalance penalty.  Scaled to be comparable to communication
    # cost (~50-500 per edge) so that pathological all-on-one-PE solutions
    # are penalised even when temperature gradient is absent.
    LOAD_PENALTY = 500.0

    def __init__(
        self,
        graph: TaskGraph,
        pe_temperatures: list[float],
        w_T: float = 1.0,
        w_H: float = 0.5,
        Tambient: float = 318.15,
        rows: int = 4,
        cols: int = 4,
    ):
        self.graph = graph
        self.T = list(pe_temperatures)   # K, indexed by PE id
        self.w_T = w_T
        self.w_H = w_H
        self.Tamb = float(Tambient)
        self.rows = rows
        self.cols = cols
        self.num_pes = rows * cols

        self._hops_cache: dict[tuple[int, int], int] = {}

    # ------------------------------------------------------------------
    # Manhattan distance on 2-D mesh
    # ------------------------------------------------------------------
    def hops(self, pe_a: int, pe_b: int) -> int:
        if pe_a == pe_b:
            return 0
        key = (pe_a, pe_b) if pe_a < pe_b else (pe_b, pe_a)
        cached = self._hops_cache.get(key)
        if cached is not None:
            return cached
        r1, c1 = divmod(pe_a, self.cols)
        r2, c2 = divmod(pe_b, self.cols)
        d = abs(r1 - r2) + abs(c1 - c2)
        self._hops_cache[key] = d
        return d

    # ------------------------------------------------------------------
    # Per-task cost (used during greedy topological assignment)
    # ------------------------------------------------------------------
    def task_cost(
        self,
        task_id: int,
        candidate_pe: int,
        assignment: dict[int, int],
    ) -> float:
        """Cost of assigning *task_id* to *candidate_pe* given prior
        assignments of its predecessors.
        """
        node = self.graph.tasks[task_id]

        # Thermal term
        thermal = self.w_T * max(0.0, self.T[candidate_pe] - self.Tamb)

        # Communication term: sum over predecessors already assigned
        comm = 0.0
        for pred_id in node.predecessor_set:
            pred_node = self.graph.tasks.get(pred_id)
            if pred_node is None:
                continue
            # GB tasks have no PE; skip them
            if pred_node.is_gb_task:
                continue
            pred_pe = assignment.get(pred_id)
            if pred_pe is None:
                # Predecessor not yet assigned — shouldn't happen in topo order
                continue
            d = self.hops(pred_pe, candidate_pe)
            comm += d * pred_node.output_data_size

        comm *= self.w_H
        return thermal + comm

    # ------------------------------------------------------------------
    # Total cost of a full assignment
    # ------------------------------------------------------------------
    def _load_penalty(self, assignment: dict[int, int]) -> float:
        """Penalty for uneven task distribution across PEs.

        Returns penalty proportional to variance of PE loads, scaled
        so the penalty is small relative to communication/thermal cost
        but large enough to prevent pathological all-on-one-PE solutions.
        """
        loads = [0.0] * self.num_pes
        for tid, pe in assignment.items():
            node = self.graph.tasks.get(tid)
            if node is not None and node.is_mappable:
                loads[pe] += 1.0
        avg = sum(loads) / self.num_pes
        variance = sum((l - avg) ** 2 for l in loads) / self.num_pes
        return self.LOAD_PENALTY * variance

    def total_cost(self, assignment: dict[int, int]) -> float:
        """Sum of task_cost over all mappable tasks, evaluated in
        topological order, plus a small load-imbalance penalty.
        """
        total = 0.0
        topo = self.graph.topological_order()
        for tid in topo:
            node = self.graph.tasks[tid]
            if not node.is_mappable:
                continue
            pe = assignment.get(tid)
            if pe is None:
                continue
            total += self.task_cost(tid, pe, assignment)
        total += self._load_penalty(assignment)
        return total

    # ------------------------------------------------------------------
    # Cost breakdown (for reporting)
    # ------------------------------------------------------------------
    def cost_breakdown(
        self, assignment: dict[int, int]
    ) -> dict[str, float]:
        """Return {thermal_cost, comm_cost, total_cost, max_temp_K}."""
        thermal = 0.0
        comm = 0.0
        max_t = self.Tamb
        topo = self.graph.topological_order()

        for tid in topo:
            node = self.graph.tasks[tid]
            if not node.is_mappable:
                continue
            pe = assignment.get(tid)
            if pe is None:
                continue
            thermal += self.w_T * max(0.0, self.T[pe] - self.Tamb)
            if pe < len(self.T):
                max_t = max(max_t, self.T[pe])

            for pred_id in node.predecessor_set:
                pred_node = self.graph.tasks.get(pred_id)
                if pred_node is None or pred_node.is_gb_task:
                    continue
                pred_pe = assignment.get(pred_id)
                if pred_pe is None:
                    continue
                d = self.hops(pred_pe, pe)
                comm += self.w_H * d * pred_node.output_data_size

        load_pen = self._load_penalty(assignment)
        return {
            "thermal_cost": thermal,
            "comm_cost": comm,
            "load_penalty": load_pen,
            "total_cost": thermal + comm + load_pen,
            "max_temp_K": max_t,
        }

    # ------------------------------------------------------------------
    # Normalized costs (thermal / comm as fractions)
    # ------------------------------------------------------------------
    def normalized_costs(
        self, assignment: dict[int, int]
    ) -> dict[str, float]:
        bd = self.cost_breakdown(assignment)
        total = bd["total_cost"]
        if total > 0:
            bd["thermal_fraction"] = bd["thermal_cost"] / total
            bd["comm_fraction"] = bd["comm_cost"] / total
        else:
            bd["thermal_fraction"] = 0.0
            bd["comm_fraction"] = 0.0
        return bd
