"""Deterministic CommAware-Heuristic mapper.

This mapper is a platform-adapted, literature-inspired communication-aware
heuristic.  It is not an exact reproduction of Murali, Hu, Tosun, or any other
specific prior implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from mapping.task_graph import TaskGraph

from common import validate_assignment
from comm_proxy import CommProxy, CommProxyConfig, communication_degree


@dataclass(frozen=True)
class CommAwareMapperConfig:
    """Configuration for deterministic greedy construction plus local swaps."""

    proxy: CommProxyConfig = field(default_factory=CommProxyConfig)
    center_candidates: tuple[int, ...] = (5, 6, 9, 10)
    local_swap_passes: int = 5
    enable_local_swap: bool = True


@dataclass
class CommAwareResult:
    """Final assignment and proxy diagnostics."""

    assignment: dict[int, int]
    seed_task: int
    seed_pe: int
    initial_score: dict[str, float]
    final_score: dict[str, float]
    original_score: dict[str, float] | None = None
    comm_degree: dict[int, float] = field(default_factory=dict)
    local_swap_passes: int = 0
    accepted_swaps: int = 0

    def diagnostics(self) -> dict[str, object]:
        return {
            "method": "comm_aware",
            "paper_label": "CommAware-Heuristic",
            "claim_scope": "literature-inspired communication-aware heuristic; not an exact reproduction",
            "seed_task": self.seed_task,
            "seed_pe": self.seed_pe,
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "original_score": self.original_score,
            "comm_degree": {str(k): v for k, v in sorted(self.comm_degree.items())},
            "local_swap_passes": self.local_swap_passes,
            "accepted_swaps": self.accepted_swaps,
            "assignment": {str(k): v for k, v in sorted(self.assignment.items())},
        }


class CommAwareMapper:
    """Build a mapping by minimizing only the communication proxy."""

    def __init__(self, graph: TaskGraph, config: CommAwareMapperConfig | None = None):
        self.graph = graph
        self.config = config or CommAwareMapperConfig()
        self.proxy = CommProxy(graph, self.config.proxy)
        self.degree = communication_degree(graph, self.proxy.edges)
        self.mappable_ids = graph.mappable_task_ids
        if not self.mappable_ids:
            raise ValueError("Task graph has no mappable tasks")

    def run(self, original_assignment: dict[int, int] | None = None) -> CommAwareResult:
        """Return a deterministic CommAware assignment."""
        assignment: dict[int, int] = {}
        seed_task = self._seed_task()
        seed_pe = self._seed_pe(seed_task)
        assignment[seed_task] = seed_pe

        for task_id in self._placement_order(seed_task):
            assignment[task_id] = self._best_pe_for_task(task_id, assignment)

        initial_score = self.proxy.score(assignment).as_dict()
        accepted_swaps = 0
        passes_done = 0
        if self.config.enable_local_swap and self.config.local_swap_passes > 0:
            passes_done, accepted_swaps = self._local_swap(assignment)

        validate_assignment(self.graph, assignment, self.config.proxy.num_pes)
        original_score = (
            self.proxy.score(original_assignment).as_dict()
            if original_assignment is not None
            else None
        )
        return CommAwareResult(
            assignment=assignment,
            seed_task=seed_task,
            seed_pe=seed_pe,
            initial_score=initial_score,
            final_score=self.proxy.score(assignment).as_dict(),
            original_score=original_score,
            comm_degree=dict(self.degree),
            local_swap_passes=passes_done,
            accepted_swaps=accepted_swaps,
        )

    def config_payload(self) -> dict[str, object]:
        return {
            "mapper": {
                "center_candidates": list(self.config.center_candidates),
                "local_swap_passes": self.config.local_swap_passes,
                "enable_local_swap": self.config.enable_local_swap,
            },
            "proxy": asdict(self.config.proxy),
            "objective": "raw_comm_cost + lambda_cong * max_edge_load",
            "tie_breaker": "lower raw_load_imbalance, then lexicographically smaller task->PE assignment",
        }

    def _seed_task(self) -> int:
        return min(self.mappable_ids, key=lambda tid: (-self.degree.get(tid, 0.0), tid))

    def _seed_pe(self, seed_task: int) -> int:
        candidates = [pe for pe in self.config.center_candidates if 0 <= pe < self.config.proxy.num_pes]
        if not candidates:
            candidates = list(range(self.config.proxy.num_pes))
        return min(candidates, key=lambda pe: self._score_key({seed_task: pe}))

    def _placement_order(self, seed_task: int) -> list[int]:
        rest = [tid for tid in self.mappable_ids if tid != seed_task]
        return sorted(rest, key=lambda tid: (-self.degree.get(tid, 0.0), tid))

    def _best_pe_for_task(self, task_id: int, assignment: dict[int, int]) -> int:
        return min(
            range(self.config.proxy.num_pes),
            key=lambda pe: self._score_key({**assignment, task_id: pe}),
        )

    def _local_swap(self, assignment: dict[int, int]) -> tuple[int, int]:
        accepted = 0
        passes_done = 0
        task_ids = list(self.mappable_ids)
        for pass_idx in range(self.config.local_swap_passes):
            improved_this_pass = False
            for i in range(len(task_ids)):
                for j in range(i + 1, len(task_ids)):
                    a = task_ids[i]
                    b = task_ids[j]
                    if assignment[a] == assignment[b]:
                        continue
                    before = self._score_key(assignment)
                    candidate = dict(assignment)
                    candidate[a], candidate[b] = candidate[b], candidate[a]
                    after = self._score_key(candidate)
                    if after < before:
                        assignment[a], assignment[b] = assignment[b], assignment[a]
                        accepted += 1
                        improved_this_pass = True
            passes_done = pass_idx + 1
            if not improved_this_pass:
                break
        return passes_done, accepted

    def _score_key(self, assignment: dict[int, int]) -> tuple[float, float, tuple[tuple[int, int], ...]]:
        score = self.proxy.score(assignment)
        return (
            score.comm_proxy,
            self._load_imbalance(assignment),
            tuple(sorted(assignment.items())),
        )

    def _load_imbalance(self, assignment: dict[int, int]) -> float:
        total = 0.0
        loads = [0.0] * self.config.proxy.num_pes
        for tid in self.mappable_ids:
            weight = max(self.graph.tasks[tid].compute_time_ns, 1.0)
            total += weight
            pe = assignment.get(tid)
            if pe is not None:
                loads[pe] += weight
        ideal = total / self.config.proxy.num_pes if self.config.proxy.num_pes else 0.0
        if ideal <= 0:
            return 0.0
        var = sum((load - ideal) ** 2 for load in loads) / self.config.proxy.num_pes
        return var / (ideal * ideal)

