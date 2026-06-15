"""Simulated annealing mapper for Thermal-SA-TAS-Mapping."""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from mapping.task_graph import TaskGraph
from thermal_rc_ls_baseline.thermal_rc_proxy import (
    RCProxyConfig,
    aggregate_power,
    communication_proxy,
    temperature_proxy,
)

try:
    from .thermal_sa_tas_proxy import (
        TASScheduleConfig,
        TASObjectiveWeights,
        critical_path_priority_ns,
        proxy_payload,
        tas_proxy_score,
    )
except ImportError:  # pragma: no cover - direct script-style imports
    from thermal_sa_tas_proxy import (
        TASScheduleConfig,
        TASObjectiveWeights,
        critical_path_priority_ns,
        proxy_payload,
        tas_proxy_score,
    )


@dataclass(frozen=True)
class ThermalSATASearchConfig:
    seed: int = 42
    init_mode: str = "original"
    init_temperature: float = 0.10
    final_temperature: float = 1e-4
    alpha: float = 0.95
    iterations_per_temperature: int = 0
    max_total_iter: int = 2000
    restarts: int = 3
    no_improve_patience: int = 300
    time_limit_s: float = 0.0
    hot_pe_count: int = 4
    cool_pe_count: int = 4
    dependency_aware_rate: float = 0.15
    selection_mode: str = "pareto_safe_thermal"
    comm_guard_ratio: float = 1.10
    comm_guard_weight: float = 0.25
    makespan_guard_ratio: float = 1.10
    makespan_guard_weight: float = 0.20
    max_load_guard_ratio: float = 1.10
    max_load_guard_weight: float = 0.10
    load_imbalance_guard_ratio: float = 1.25
    load_imbalance_guard_weight: float = 0.05
    tmax_guard_delta_K: float = 0.0
    tmax_guard_weight: float = 0.10
    sigma_guard_ratio: float = 1.0
    sigma_guard_weight: float = 0.10

    def validate(self) -> None:
        if self.init_mode not in ("original", "thermal_greedy", "comm_aware", "random_balanced", "multi"):
            raise ValueError(f"unsupported init_mode: {self.init_mode}")
        if self.init_temperature <= 0.0:
            raise ValueError("init_temperature must be positive")
        if self.final_temperature <= 0.0:
            raise ValueError("final_temperature must be positive")
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        if self.iterations_per_temperature < 0:
            raise ValueError("iterations_per_temperature must be non-negative")
        if self.max_total_iter <= 0:
            raise ValueError("max_total_iter must be positive")
        if self.restarts <= 0:
            raise ValueError("restarts must be positive")
        if self.no_improve_patience <= 0:
            raise ValueError("no_improve_patience must be positive")
        if self.hot_pe_count <= 0 or self.cool_pe_count <= 0:
            raise ValueError("hot_pe_count and cool_pe_count must be positive")
        if not 0.0 <= self.dependency_aware_rate <= 1.0:
            raise ValueError("dependency_aware_rate must be in [0, 1]")
        if self.selection_mode not in ("score", "thermal_lexicographic", "pareto_safe_thermal"):
            raise ValueError("selection_mode must be 'score', 'thermal_lexicographic', or 'pareto_safe_thermal'")
        guarded_ratios = {
            "comm_guard_ratio": self.comm_guard_ratio,
            "makespan_guard_ratio": self.makespan_guard_ratio,
            "max_load_guard_ratio": self.max_load_guard_ratio,
            "load_imbalance_guard_ratio": self.load_imbalance_guard_ratio,
            "sigma_guard_ratio": self.sigma_guard_ratio,
        }
        for name, value in guarded_ratios.items():
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative; set 0 to disable")
        guarded_weights = {
            "comm_guard_weight": self.comm_guard_weight,
            "makespan_guard_weight": self.makespan_guard_weight,
            "max_load_guard_weight": self.max_load_guard_weight,
            "load_imbalance_guard_weight": self.load_imbalance_guard_weight,
            "tmax_guard_weight": self.tmax_guard_weight,
            "sigma_guard_weight": self.sigma_guard_weight,
        }
        for name, value in guarded_weights.items():
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")


@dataclass
class ThermalSATAResult:
    assignment: dict[int, int]
    proxy: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    schedule: list[dict[str, float | int]] = field(default_factory=list)
    elapsed_s: float = 0.0
    iterations: int = 0
    converged: bool = False


class ThermalSATASMapper:
    """TAS-inspired simulated annealing over static task-to-PE mappings."""

    def __init__(
        self,
        graph: TaskGraph,
        original_assignment: dict[int, int],
        task_power: dict[int, float],
        resistance_matrix: list[list[float]],
        proxy_config: RCProxyConfig,
        schedule_config: TASScheduleConfig,
        objective_weights: TASObjectiveWeights,
        search_config: ThermalSATASearchConfig,
        denominators: dict[str, float],
        baseline_hotspot_risk: list[float] | None = None,
    ):
        self.graph = graph
        self.original_assignment = dict(original_assignment)
        self.task_power = dict(task_power)
        self.R = resistance_matrix
        self.proxy_config = proxy_config
        self.schedule_config = schedule_config
        self.objective_weights = objective_weights
        self.search_config = search_config
        self.denominators = dict(denominators)
        self.baseline_hotspot_risk = list(baseline_hotspot_risk) if baseline_hotspot_risk is not None else None
        self._rng = random.Random(search_config.seed)
        self._tasks = list(graph.mappable_task_ids)
        self._eps = 1e-12

        self.proxy_config.validate()
        self.schedule_config.validate()
        self.objective_weights.validate()
        self.search_config.validate()
        expected = set(self._tasks)
        actual = set(self.original_assignment)
        if expected != actual:
            raise ValueError(
                "original assignment must cover exactly mappable tasks: "
                f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )

    def run(self) -> ThermalSATAResult:
        t0 = time.perf_counter()
        global_best_assignment: dict[int, int] | None = None
        global_best_score: dict[str, Any] | None = None
        archive: dict[tuple[tuple[int, int], ...], dict[str, Any]] = {}
        history: list[dict[str, Any]] = []
        total_iter = 0
        converged = False

        for restart in range(self.search_config.restarts):
            if total_iter >= self.search_config.max_total_iter or self._timed_out(t0):
                break

            current_assignment = self._initial_assignment(restart)
            current_score = self._score(current_assignment)
            self._archive_candidate(archive, current_assignment, current_score, "initial")
            if global_best_score is None or self._is_better(current_score, global_best_score):
                global_best_assignment = dict(current_assignment)
                global_best_score = dict(current_score)

            local_best_score = dict(current_score)
            no_improve = 0
            temperature = self.search_config.init_temperature
            iters_per_temp = self._iterations_per_temperature()

            while (
                temperature >= self.search_config.final_temperature
                and total_iter < self.search_config.max_total_iter
                and not self._timed_out(t0)
            ):
                for _ in range(iters_per_temp):
                    if total_iter >= self.search_config.max_total_iter or self._timed_out(t0):
                        break
                    total_iter += 1
                    op = self._neighbor_op(current_assignment, current_score)
                    candidate = self._apply_op(current_assignment, op)
                    candidate_score = self._score(candidate)
                    self._archive_candidate(archive, candidate, candidate_score, "candidate")
                    delta = float(candidate_score["score"]) - float(current_score["score"])
                    accept_prob = 1.0 if delta <= 0.0 else math.exp(-delta / max(temperature, 1e-12))
                    accepted = delta <= 0.0 or self._rng.random() < accept_prob

                    improved = False
                    if accepted:
                        current_assignment = candidate
                        current_score = candidate_score
                        if self._is_better(current_score, local_best_score):
                            local_best_score = dict(current_score)
                            no_improve = 0
                        else:
                            no_improve += 1

                        if (
                            global_best_score is None
                            or self._is_better(current_score, global_best_score)
                        ):
                            global_best_assignment = dict(current_assignment)
                            global_best_score = dict(current_score)
                            improved = True
                    else:
                        no_improve += 1

                    history.append(
                        self._history_row(
                            total_iter,
                            restart,
                            temperature,
                            current_score,
                            global_best_score or current_score,
                            op,
                            accepted,
                            improved,
                            delta,
                            accept_prob,
                            no_improve,
                        )
                    )

                    if no_improve >= self.search_config.no_improve_patience:
                        converged = True
                        break
                if no_improve >= self.search_config.no_improve_patience:
                    break
                temperature *= self.search_config.alpha

        if global_best_assignment is None or global_best_score is None:
            raise RuntimeError("Thermal-SA-TAS failed to evaluate any mapping")

        final_assignment, final_score, final_selection = self._select_final_assignment(
            archive,
            global_best_assignment,
            global_best_score,
        )
        final_proxy = proxy_payload(
            self.graph,
            self.original_assignment,
            final_assignment,
            self.task_power,
            self.R,
            self.proxy_config,
            self.schedule_config,
            self.objective_weights,
            self.denominators,
            baseline_hotspot_risk=self.baseline_hotspot_risk,
        )
        final_schedule = final_score["schedule"]
        final_proxy["config"]["search"] = asdict(self.search_config)
        final_proxy["config"]["guard_reference"] = dict(self.denominators)
        final_proxy["thermal_sa_tas"]["iterations"] = total_iter
        final_proxy["thermal_sa_tas"]["converged"] = converged
        final_proxy["thermal_sa_tas"]["search_score_without_guard"] = final_score.get("score_without_guard", final_score["score"])
        final_proxy["thermal_sa_tas"]["search_score"] = final_score["score"]
        final_proxy["thermal_sa_tas"]["guard_penalty"] = final_score.get("guard_penalty", 0.0)
        final_proxy["thermal_sa_tas"]["guard_violations"] = final_score.get("guard_violations", {})
        final_proxy["thermal_sa_tas"]["final_selection"] = final_selection

        return ThermalSATAResult(
            assignment=final_assignment,
            proxy=final_proxy,
            history=history,
            schedule=final_schedule,
            elapsed_s=time.perf_counter() - t0,
            iterations=total_iter,
            converged=converged,
        )

    def _score(self, assignment: dict[int, int]) -> dict[str, Any]:
        score = tas_proxy_score(
            self.graph,
            assignment,
            self.task_power,
            self.R,
            self.proxy_config,
            self.schedule_config,
            self.objective_weights,
            denominators=self.denominators,
            baseline_hotspot_risk=self.baseline_hotspot_risk,
        )
        self._apply_guard_penalty(score)
        return score

    def _initial_assignment(self, restart: int) -> dict[int, int]:
        if self.search_config.init_mode == "multi":
            mode = ("original", "comm_aware", "thermal_greedy", "random_balanced")[restart % 4]
            if mode == "original":
                return dict(self.original_assignment)
            if mode == "comm_aware":
                return self._comm_aware_assignment()
            if mode == "thermal_greedy":
                return self._thermal_greedy_assignment()
            return self._random_balanced_assignment()
        if restart == 0 and self.search_config.init_mode == "original":
            return dict(self.original_assignment)
        if restart == 0 and self.search_config.init_mode == "thermal_greedy":
            return self._thermal_greedy_assignment()
        if restart == 0 and self.search_config.init_mode == "comm_aware":
            return self._comm_aware_assignment()
        return self._random_balanced_assignment()

    def _random_balanced_assignment(self) -> dict[int, int]:
        pes = list(range(self.proxy_config.num_pes))
        self._rng.shuffle(pes)
        loads = [0.0 for _ in range(self.proxy_config.num_pes)]
        assignment: dict[int, int] = {}
        pe_rank = {pe: idx for idx, pe in enumerate(pes)}
        for tid in sorted(self._tasks, key=lambda item: (-self.task_power.get(item, 0.0), item)):
            pe = min(pes, key=lambda candidate: (loads[candidate], pe_rank[candidate]))
            assignment[tid] = pe
            loads[pe] += self.task_power.get(tid, 0.0)
        return assignment

    def _thermal_greedy_assignment(self) -> dict[int, int]:
        assignment: dict[int, int] = {}
        power = [0.0 for _ in range(self.proxy_config.num_pes)]
        for tid in sorted(self._tasks, key=lambda item: (-self.task_power.get(item, 0.0), -self._comm_degree(item), item)):
            best_pe = 0
            best_key: tuple[float, float, int] | None = None
            for pe in range(self.proxy_config.num_pes):
                trial_power = list(power)
                trial_power[pe] += self.task_power.get(tid, 0.0)
                trial_temp = temperature_proxy(self.R, trial_power, self.proxy_config.Tambient)
                key = (max(trial_temp), trial_power[pe], pe)
                if best_key is None or key < best_key:
                    best_key = key
                    best_pe = pe
            assignment[tid] = best_pe
            power[best_pe] += self.task_power.get(tid, 0.0)
        return assignment

    def _comm_aware_assignment(self) -> dict[int, int]:
        assignment: dict[int, int] = {}
        seed = min(self._tasks, key=lambda tid: (-self._comm_degree(tid), tid))
        centers = [pe for pe in (5, 6, 9, 10) if pe < self.proxy_config.num_pes]
        assignment[seed] = min(centers or list(range(self.proxy_config.num_pes)),
                               key=lambda pe: self._comm_load_key({seed: pe}))
        for tid in sorted(
            [task for task in self._tasks if task != seed],
            key=lambda item: (-self._comm_degree(item), item),
        ):
            assignment[tid] = min(
                range(self.proxy_config.num_pes),
                key=lambda pe: self._comm_load_key({**assignment, tid: pe}),
            )
        return assignment

    def _comm_load_key(self, assignment: dict[int, int]) -> tuple[float, float, float, tuple[tuple[int, int], ...]]:
        comm = self._partial_comm_cost(assignment)
        max_load, imbalance = self._partial_load_terms(assignment)
        return (comm, max_load, imbalance, tuple(sorted(assignment.items())))

    def _partial_comm_cost(self, assignment: dict[int, int]) -> float:
        total = 0.0
        for src_id in self._tasks:
            src = self.graph.tasks[src_id]
            src_pe = assignment.get(src_id)
            if src_pe is None:
                continue
            for dst_id in src.successors:
                if dst_id not in assignment:
                    continue
                total += self._hops(src_pe, assignment[dst_id]) * src.output_data_size
        return total

    def _partial_load_terms(self, assignment: dict[int, int]) -> tuple[float, float]:
        loads = [0.0 for _ in range(self.proxy_config.num_pes)]
        total = 0.0
        for tid, pe in assignment.items():
            weight = max(float(self.graph.tasks[tid].compute_time_ns), 0.0)
            loads[pe] += weight
            total += weight
        ideal = total / self.proxy_config.num_pes if total > 0.0 else 1.0
        imbalance = sum((load - ideal) ** 2 for load in loads) / self.proxy_config.num_pes / (ideal * ideal)
        return max(loads), imbalance

    def _hops(self, pe_a: int, pe_b: int) -> int:
        r1, c1 = divmod(pe_a, self.proxy_config.cols)
        r2, c2 = divmod(pe_b, self.proxy_config.cols)
        return abs(r1 - r2) + abs(c1 - c2)

    def _neighbor_op(self, assignment: dict[int, int], score: dict[str, Any]) -> dict[str, Any]:
        if self._rng.random() < self.search_config.dependency_aware_rate:
            return self._critical_path_move(assignment)
        choice = self._rng.random()
        if choice < 0.35:
            return self._random_swap(assignment)
        if choice < 0.70:
            return self._random_move(assignment)
        return self._hot_cool_op(assignment, score)

    def _random_swap(self, assignment: dict[int, int]) -> dict[str, Any]:
        if len(self._tasks) < 2:
            return self._random_move(assignment)
        a, b = self._rng.sample(self._tasks, 2)
        if assignment[a] == assignment[b]:
            return self._random_move(assignment)
        lo, hi = sorted((a, b))
        return {"kind": "swap", "task_a": lo, "task_b": hi, "target_pe": None}

    def _random_move(self, assignment: dict[int, int]) -> dict[str, Any]:
        task = self._rng.choice(self._tasks)
        current = assignment[task]
        choices = [pe for pe in range(self.proxy_config.num_pes) if pe != current]
        target = self._rng.choice(choices)
        return {"kind": "move", "task_a": task, "task_b": None, "target_pe": target}

    def _hot_cool_op(self, assignment: dict[int, int], score: dict[str, Any]) -> dict[str, Any]:
        temps = [float(v) for v in score["temperatures_K"]]
        by_pe = self._tasks_by_pe(assignment)
        hot_pes = sorted(range(self.proxy_config.num_pes), key=lambda pe: (-temps[pe], pe))[
            : self.search_config.hot_pe_count
        ]
        cool_pes = sorted(range(self.proxy_config.num_pes), key=lambda pe: (temps[pe], pe))[
            : self.search_config.cool_pe_count
        ]
        hot_tasks = [
            tid
            for pe in hot_pes
            for tid in sorted(by_pe.get(pe, []), key=lambda item: (-self.task_power.get(item, 0.0), item))
        ]
        if not hot_tasks:
            return self._random_move(assignment)
        task_a = self._rng.choice(hot_tasks[: max(1, min(4, len(hot_tasks)))])
        target_pe = self._rng.choice([pe for pe in cool_pes if pe != assignment[task_a]] or list(range(self.proxy_config.num_pes)))
        cool_tasks = by_pe.get(target_pe, [])
        if cool_tasks and self._rng.random() < 0.5:
            task_b = self._rng.choice(cool_tasks)
            if task_a != task_b:
                lo, hi = sorted((task_a, task_b))
                return {"kind": "swap", "task_a": lo, "task_b": hi, "target_pe": None}
        return {"kind": "move", "task_a": task_a, "task_b": None, "target_pe": target_pe}

    def _critical_path_move(self, assignment: dict[int, int]) -> dict[str, Any]:
        priorities = critical_path_priority_ns(
            self.graph,
            assignment,
            self.proxy_config.cols,
            self.schedule_config,
        )
        top = sorted(self._tasks, key=lambda tid: (-priorities.get(tid, 0.0), tid))
        task = self._rng.choice(top[: max(1, min(5, len(top)))])
        current = assignment[task]
        current_comm = communication_proxy(self.graph, assignment, self.proxy_config.cols)
        candidates: list[tuple[float, int]] = []
        for pe in range(self.proxy_config.num_pes):
            if pe == current:
                continue
            trial = dict(assignment)
            trial[task] = pe
            candidates.append((communication_proxy(self.graph, trial, self.proxy_config.cols), pe))
        best_comm = min(candidates, key=lambda item: (item[0], item[1])) if candidates else (current_comm, current)
        if best_comm[0] <= current_comm or self._rng.random() < 0.5:
            return {"kind": "move", "task_a": task, "task_b": None, "target_pe": best_comm[1]}
        return self._random_move(assignment)

    def _apply_op(self, assignment: dict[int, int], op: dict[str, Any]) -> dict[int, int]:
        out = dict(assignment)
        task_a = int(op["task_a"])
        if op["kind"] == "move":
            out[task_a] = int(op["target_pe"])
            return out
        if op["kind"] == "swap":
            task_b = int(op["task_b"])
            out[task_a], out[task_b] = out[task_b], out[task_a]
            return out
        raise ValueError(f"unsupported op kind: {op['kind']}")

    def _tasks_by_pe(self, assignment: dict[int, int]) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {pe: [] for pe in range(self.proxy_config.num_pes)}
        for tid, pe in assignment.items():
            out.setdefault(pe, []).append(tid)
        return out

    def _comm_degree(self, task_id: int) -> float:
        node = self.graph.tasks[task_id]
        total = 0.0
        for pred_id in node.predecessor_set:
            pred = self.graph.tasks.get(pred_id)
            if pred is not None and not pred.is_gb_task:
                total += pred.output_data_size
        for succ_id in node.successors:
            if succ_id == -1:
                continue
            succ = self.graph.tasks.get(succ_id)
            if succ is not None and not succ.is_gb_task:
                total += node.output_data_size
        return total

    def _iterations_per_temperature(self) -> int:
        if self.search_config.iterations_per_temperature > 0:
            return self.search_config.iterations_per_temperature
        return max(50, 10 * len(self._tasks))

    def _is_better(self, candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
        if self.search_config.selection_mode == "score":
            return float(candidate["score"]) + self._eps < float(incumbent["score"])
        if self.search_config.selection_mode == "pareto_safe_thermal":
            return self._pareto_rank(candidate) < self._pareto_rank(incumbent)
        return self._thermal_rank(candidate) < self._thermal_rank(incumbent)

    def _thermal_rank(self, score: dict[str, Any]) -> tuple[float, ...]:
        return (
            round(float(score["Tmax_proxy"]), 9),
            round(float(score["SigmaT_proxy"]), 9),
            round(float(score["HotCount_proxy"]), 9),
            round(float(score.get("PeakWindowEnergyProxy", 0.0)), 9),
            round(float(score.get("NeighborPeakWindowEnergyProxy", 0.0)), 9),
            round(float(score.get("PeakWindowSigmaProxy", 0.0)), 9),
            round(float(score.get("MaxLoadProxy_ns", 0.0)), 9),
            round(float(score.get("LoadImbalanceProxy", 0.0)), 9),
            round(float(score["MakespanProxy_ns"]), 9),
            round(float(score["CommProxy"]), 9),
            round(float(score["score"]), 12),
        )

    def _pareto_rank(self, score: dict[str, Any]) -> tuple[float, ...]:
        violations = self._guard_violations(score)
        violation_sum = sum(float(value) for value in violations.values())
        feasible_flag = 0.0 if violation_sum <= self._eps else 1.0
        return (
            feasible_flag,
            round(violation_sum, 12),
            *self._thermal_rank(score),
        )

    def _archive_candidate(
        self,
        archive: dict[tuple[tuple[int, int], ...], dict[str, Any]],
        assignment: dict[int, int],
        score: dict[str, Any],
        source: str,
    ) -> None:
        key = tuple(sorted((int(tid), int(pe)) for tid, pe in assignment.items()))
        entry = archive.get(key)
        if entry is None or self._pareto_rank(score) < self._pareto_rank(entry["score"]):
            archive[key] = {
                "assignment": dict(assignment),
                "score": dict(score),
                "source": source,
            }

    def _select_final_assignment(
        self,
        archive: dict[tuple[tuple[int, int], ...], dict[str, Any]],
        fallback_assignment: dict[int, int],
        fallback_score: dict[str, Any],
    ) -> tuple[dict[int, int], dict[str, Any], dict[str, Any]]:
        if self.search_config.selection_mode != "pareto_safe_thermal" or not archive:
            return (
                dict(fallback_assignment),
                dict(fallback_score),
                {
                    "mode": self.search_config.selection_mode,
                    "selected_from": "global_best",
                    "archive_size": len(archive),
                    "feasible_count": None,
                    "relaxation": None,
                },
            )

        entries = list(archive.values())
        selected_entries: list[dict[str, Any]] = []
        selected_relaxation: float | str = 1.0
        for relaxation in (1.0, 1.05, 1.10, 1.25, 1.50, math.inf):
            feasible = [
                entry for entry in entries
                if self._is_guard_feasible(entry["score"], relaxation=relaxation)
            ]
            if feasible:
                selected_entries = feasible
                selected_relaxation = "inf" if math.isinf(relaxation) else relaxation
                break

        if not selected_entries:
            selected_entries = entries
            selected_relaxation = "none"

        selected = min(selected_entries, key=lambda entry: self._thermal_rank(entry["score"]))
        score = dict(selected["score"])
        return (
            dict(selected["assignment"]),
            score,
            {
                "mode": "pareto_safe_thermal",
                "selected_from": selected.get("source", "archive"),
                "archive_size": len(archive),
                "feasible_count": len(selected_entries),
                "relaxation": selected_relaxation,
                "guard_violations": score.get("guard_violations", {}),
                "guard_penalty": score.get("guard_penalty", 0.0),
            },
        )

    def _apply_guard_penalty(self, score: dict[str, Any]) -> None:
        violations = self._guard_violations(score)
        penalty = (
            self.search_config.comm_guard_weight * violations.get("CommProxy", 0.0)
            + self.search_config.makespan_guard_weight * violations.get("MakespanProxy_ns", 0.0)
            + self.search_config.max_load_guard_weight * violations.get("MaxLoadProxy_ns", 0.0)
            + self.search_config.load_imbalance_guard_weight * violations.get("LoadImbalanceProxy", 0.0)
            + self.search_config.tmax_guard_weight * violations.get("Tmax_proxy", 0.0)
            + self.search_config.sigma_guard_weight * violations.get("SigmaT_proxy", 0.0)
        )
        score["score_without_guard"] = score["score"]
        score["guard_violations"] = violations
        score["guard_penalty"] = penalty
        score["score"] = float(score["score"]) + penalty

    def _guard_violations(self, score: dict[str, Any], relaxation: float = 1.0) -> dict[str, float]:
        if math.isinf(relaxation):
            return {}
        out: dict[str, float] = {}
        self._add_ratio_violation(out, score, "CommProxy", self.search_config.comm_guard_ratio, relaxation)
        self._add_ratio_violation(out, score, "MakespanProxy_ns", self.search_config.makespan_guard_ratio, relaxation)
        self._add_ratio_violation(out, score, "MaxLoadProxy_ns", self.search_config.max_load_guard_ratio, relaxation)
        self._add_ratio_violation(out, score, "LoadImbalanceProxy", self.search_config.load_imbalance_guard_ratio, relaxation)
        self._add_ratio_violation(out, score, "SigmaT_proxy", self.search_config.sigma_guard_ratio, relaxation)
        if self.search_config.tmax_guard_delta_K >= 0.0:
            ref = float(self.denominators.get("Tmax_proxy", 0.0))
            if ref > self._eps:
                limit = ref + self.search_config.tmax_guard_delta_K
                excess = max(0.0, float(score.get("Tmax_proxy", 0.0)) - limit)
                out["Tmax_proxy"] = excess / ref
        return {key: value for key, value in out.items() if value > self._eps}

    def _add_ratio_violation(
        self,
        out: dict[str, float],
        score: dict[str, Any],
        term: str,
        ratio: float,
        relaxation: float,
    ) -> None:
        if ratio <= 0.0:
            return
        ref = float(self.denominators.get(term, 0.0))
        if ref <= self._eps:
            return
        limit = ref * ratio * relaxation
        if limit <= self._eps:
            return
        out[term] = max(0.0, float(score.get(term, 0.0)) / limit - 1.0)

    def _is_guard_feasible(self, score: dict[str, Any], relaxation: float = 1.0) -> bool:
        return not self._guard_violations(score, relaxation=relaxation)

    def _history_row(
        self,
        iteration: int,
        restart: int,
        temperature: float,
        current: dict[str, Any],
        best: dict[str, Any],
        op: dict[str, Any],
        accepted: bool,
        improved: bool,
        delta: float,
        accept_prob: float,
        no_improve: int,
    ) -> dict[str, Any]:
        return {
            "iteration": iteration,
            "restart": restart,
            "temperature": temperature,
            "current_score": current["score"],
            "best_score": best["score"],
            "current_Tmax_proxy": current["Tmax_proxy"],
            "best_Tmax_proxy": best["Tmax_proxy"],
            "current_SigmaT_proxy": current["SigmaT_proxy"],
            "best_SigmaT_proxy": best["SigmaT_proxy"],
            "current_HotCount_proxy": current["HotCount_proxy"],
            "best_HotCount_proxy": best["HotCount_proxy"],
            "current_PeakWindowEnergyProxy": current.get("PeakWindowEnergyProxy", 0.0),
            "best_PeakWindowEnergyProxy": best.get("PeakWindowEnergyProxy", 0.0),
            "current_NeighborPeakWindowEnergyProxy": current.get("NeighborPeakWindowEnergyProxy", 0.0),
            "best_NeighborPeakWindowEnergyProxy": best.get("NeighborPeakWindowEnergyProxy", 0.0),
            "current_MakespanProxy_ns": current["MakespanProxy_ns"],
            "best_MakespanProxy_ns": best["MakespanProxy_ns"],
            "current_CommProxy": current["CommProxy"],
            "best_CommProxy": best["CommProxy"],
            "current_guard_penalty": current.get("guard_penalty", 0.0),
            "best_guard_penalty": best.get("guard_penalty", 0.0),
            "accepted": accepted,
            "improved_best": improved,
            "delta_score": delta,
            "acceptance_probability": accept_prob,
            "accepted_op": op,
            "no_improve": no_improve,
        }

    def _timed_out(self, start: float) -> bool:
        return (
            self.search_config.time_limit_s > 0.0
            and time.perf_counter() - start >= self.search_config.time_limit_s
        )
