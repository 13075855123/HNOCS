"""
SAOptimizer — Simulated Annealing for thermal-aware task-to-PE mapping.

Algorithm:
  1. Generate initial solution greedily in topological order
  2. Perturb: randomly move one task to a different PE
  3. Accept/reject using Metropolis criterion
  4. Cool geometrically: T *= alpha
  5. Stop when T < T_min or idle_steps >= max_idle

The state is a dict {taskId: peId} for all mappable tasks.
"""

from __future__ import annotations

import math
import random
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

from .task_graph import TaskGraph
from .cost_model import CostModel


@dataclass
class SAResult:
    """Result of a Simulated Annealing run."""
    assignment: dict[int, int]     # {taskId: peId}
    cost: float
    cost_history: list[float]      # best cost after each temperature step
    accepted_uphill: int
    total_iterations: int
    converged: bool                 # True if stopped by idle limit


class SAOptimizer:
    """Simulated Annealing optimizer for thermal-aware task mapping.

    Parameters
    ----------
    graph : TaskGraph
        The task DAG.
    cost_model : CostModel
        Pre-configured cost model.
    T_init : float
        Starting temperature for SA.
    T_min : float
        Stopping temperature.
    alpha : float
        Cooling rate (0 < alpha < 1).
    iterations_per_T : int
        Inner-loop iterations per temperature step.
    max_idle : int
        Early-stop if no improvement for this many temperature steps.
    max_tasks_per_pe : int or None
        Max mappable tasks per PE (hard constraint).  If None,
        auto-computed as ceil(num_mappable / num_PEs) * 2, clamped
        to [1, num_mappable].
    seed : int or None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        graph: TaskGraph,
        cost_model: CostModel,
        T_init: float = 1000.0,
        T_min: float = 0.01,
        alpha: float = 0.95,
        iterations_per_T: int = 100,
        max_idle: int = 30,
        max_tasks_per_pe: Optional[int] = None,
        seed: Optional[int] = 42,
    ):
        self.graph = graph
        self.cost_model = cost_model
        self.T_init = T_init
        self.T_min = T_min
        self.alpha = alpha
        self.iterations_per_T = iterations_per_T
        self.max_idle = max_idle

        # Auto-compute load cap if not given
        self._num_pes = cost_model.num_pes
        n_mappable = graph.num_mappable
        if max_tasks_per_pe is not None:
            self.max_tasks_per_pe = max(1, min(max_tasks_per_pe, n_mappable))
        else:
            self.max_tasks_per_pe = max(1, -(-n_mappable // self._num_pes) * 2)  # ceil div * 2

        self._seed = seed if seed is not None else 42
        self._rng = random.Random(self._seed)
        self._mappable: list[int] = graph.mappable_task_ids

    # ------------------------------------------------------------------
    # PE-load helper
    # ------------------------------------------------------------------
    def _pe_loads(self, assignment: dict[int, int]) -> dict[int, int]:
        loads: dict[int, int] = {pe: 0 for pe in range(self._num_pes)}
        for tid, pe in assignment.items():
            if self.graph.tasks[tid].is_mappable:
                loads[pe] += 1
        return loads

    # ------------------------------------------------------------------
    # Initial solution: greedy topological assignment
    # ------------------------------------------------------------------
    def generate_initial_solution(self) -> dict[int, int]:
        """For each task in topological order, pick the PE that minimizes
        task_cost among candidate PEs.  Respects max_tasks_per_pe.
        """
        assignment: dict[int, int] = {}
        pe_load: dict[int, int] = {pe: 0 for pe in range(self._num_pes)}

        for tid in self.graph.topological_order():
            node = self.graph.tasks[tid]
            if not node.is_mappable:
                continue

            best_pe = -1
            best_cost = float("inf")
            for pe in range(self._num_pes):
                if pe_load[pe] >= self.max_tasks_per_pe:
                    continue
                cost = self.cost_model.task_cost(tid, pe, assignment)
                if cost < best_cost:
                    best_cost = cost
                    best_pe = pe

            if best_pe < 0:
                # All PEs full — pick the one with min cost (relax constraint)
                for pe in range(self._num_pes):
                    cost = self.cost_model.task_cost(tid, pe, assignment)
                    if cost < best_cost:
                        best_cost = cost
                        best_pe = pe

            assignment[tid] = best_pe
            pe_load[best_pe] += 1

        return assignment

    # ------------------------------------------------------------------
    # Neighbor generation: move one random task to a different PE
    # ------------------------------------------------------------------
    def _random_neighbor(self, assignment: dict[int, int]) -> dict[int, int]:
        new_assign = assignment.copy()
        loads = self._pe_loads(new_assign)

        # Pick a random mappable task
        tid = self._rng.choice(self._mappable)
        old_pe = new_assign[tid]

        # Pick a different PE that is not already at capacity
        candidates = [
            pe for pe in range(self._num_pes)
            if pe != old_pe and loads[pe] < self.max_tasks_per_pe
        ]
        if not candidates:
            # All other PEs full — allow any PE (relax constraint)
            candidates = [pe for pe in range(self._num_pes) if pe != old_pe]

        new_pe = self._rng.choice(candidates)
        new_assign[tid] = new_pe
        return new_assign

    # ------------------------------------------------------------------
    # Acceptance probability (Metropolis criterion)
    # ------------------------------------------------------------------
    @staticmethod
    def _acceptance_probability(delta_cost: float, T: float) -> float:
        """Return probability of accepting an uphill move.

        Metropolis: exp(-delta_cost / T).
        delta_cost > 0 means the new state is worse (higher cost).
        """
        if delta_cost <= 0:
            return 1.0
        return math.exp(-delta_cost / T)

    # ------------------------------------------------------------------
    # Main optimization loop
    # ------------------------------------------------------------------
    def optimize(self, verbose: bool = False) -> SAResult:
        """Run Simulated Annealing and return the best assignment found."""

        assignment = self.generate_initial_solution()
        best_assignment = deepcopy(assignment)
        best_cost = self.cost_model.total_cost(best_assignment)

        T = self.T_init
        idle_steps = 0
        total_iters = 0
        accepted_uphill = 0
        cost_history = [best_cost]

        num_t_steps = 0

        while T > self.T_min and idle_steps < self.max_idle:
            improved_this_T = False
            num_t_steps += 1

            for _ in range(self.iterations_per_T):
                total_iters += 1
                neighbor = self._random_neighbor(assignment)
                new_cost = self.cost_model.total_cost(neighbor)
                delta = new_cost - best_cost

                if delta <= 0 or self._rng.random() < self._acceptance_probability(delta, T):
                    assignment = neighbor
                    if delta > 0:
                        accepted_uphill += 1
                    if new_cost < best_cost:
                        best_cost = new_cost
                        best_assignment = deepcopy(neighbor)
                        improved_this_T = True

            cost_history.append(best_cost)

            if improved_this_T:
                idle_steps = 0
            else:
                idle_steps += 1

            T *= self.alpha

        converged = idle_steps >= self.max_idle

        if verbose:
            end_reason = "converged (idle)" if converged else f"T < {self.T_min}"
            print(
                f"[SA] T_steps={num_t_steps} total_iters={total_iters} "
                f"best_cost={best_cost:.4f} "
                f"uphill_accepted={accepted_uphill} "
                f"final_T={T:.4f} "
                f"stop={end_reason}"
            )

        return SAResult(
            assignment=best_assignment,
            cost=best_cost,
            cost_history=cost_history,
            accepted_uphill=accepted_uphill,
            total_iterations=total_iters,
            converged=converged,
        )

    # ------------------------------------------------------------------
    # Multiple restarts: run SA N times, return best result
    # ------------------------------------------------------------------
    def optimize_with_restarts(
        self, num_restarts: int = 5, verbose: bool = False
    ) -> SAResult:
        best_result: Optional[SAResult] = None

        for r in range(num_restarts):
            self._rng = random.Random(self._seed + r * 10007)
            result = self.optimize(verbose=verbose)
            if best_result is None or result.cost < best_result.cost:
                best_result = result

        if verbose and num_restarts > 1:
            print(
                f"[SA] best of {num_restarts} restarts: "
                f"cost={best_result.cost:.4f}"
            )

        return best_result  # type: ignore[return-value]
