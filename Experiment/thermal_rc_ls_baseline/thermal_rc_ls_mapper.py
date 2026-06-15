"""Local-search mapper for the ThermalRC-LS baseline."""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from mapping.task_graph import TaskGraph

from thermal_rc_proxy import (
    RCObjectiveWeights,
    RCProxyConfig,
    aggregate_power,
    communication_proxy,
    proxy_score,
    score_from_temp_and_comm,
    temperature_proxy,
)


@dataclass(frozen=True)
class ThermalRCLSSearchConfig:
    """Search controls for ThermalRC-LS."""

    seed: int = 42
    init_mode: str = "original"
    max_iter: int = 300
    no_improve_patience: int = 50
    time_limit_s: float = 0.0
    hot_pe_count: int = 4
    cool_pe_count: int = 4
    candidate_task_limit: int = 4
    random_swap_rate: float = 0.10
    random_candidate_count: int = 8
    enable_sa: bool = False
    sa_initial_temp: float = 0.05
    sa_cooling: float = 0.98

    def validate(self) -> None:
        if self.init_mode not in ("original", "thermal_greedy", "random_spread"):
            raise ValueError(f"unsupported init_mode: {self.init_mode}")
        if self.max_iter <= 0:
            raise ValueError("max_iter must be positive")
        if self.no_improve_patience <= 0:
            raise ValueError("no_improve_patience must be positive")
        if self.hot_pe_count <= 0 or self.cool_pe_count <= 0:
            raise ValueError("hot_pe_count and cool_pe_count must be positive")
        if self.candidate_task_limit <= 0:
            raise ValueError("candidate_task_limit must be positive")
        if not 0.0 <= self.random_swap_rate <= 1.0:
            raise ValueError("random_swap_rate must be in [0, 1]")
        if self.random_candidate_count < 0:
            raise ValueError("random_candidate_count must be non-negative")
        if self.sa_initial_temp <= 0.0:
            raise ValueError("sa_initial_temp must be positive")
        if not 0.0 < self.sa_cooling <= 1.0:
            raise ValueError("sa_cooling must be in (0, 1]")


@dataclass
class ThermalRCLSResult:
    assignment: dict[int, int]
    proxy: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    elapsed_s: float = 0.0
    converged: bool = False
    iterations: int = 0


class ThermalRCLSMapper:
    """Thermal-resistance-aware local search over task-to-PE mappings."""

    def __init__(
        self,
        graph: TaskGraph,
        original_assignment: dict[int, int],
        task_power: dict[int, float],
        resistance_matrix: list[list[float]],
        proxy_config: RCProxyConfig,
        objective_weights: RCObjectiveWeights,
        search_config: ThermalRCLSSearchConfig,
        initial_assignment: dict[int, int] | None = None,
    ):
        self.graph = graph
        self.original_assignment = dict(original_assignment)
        self.task_power = dict(task_power)
        self.R = resistance_matrix
        self.proxy_config = proxy_config
        self.objective_weights = objective_weights
        self.search_config = search_config
        self.initial_assignment = dict(initial_assignment) if initial_assignment else None
        self._rng = random.Random(search_config.seed)
        self._tasks = list(graph.mappable_task_ids)
        self._eps = 1e-12

        self.proxy_config.validate()
        self.objective_weights.validate()
        self.search_config.validate()
        if set(self.original_assignment) != set(self._tasks):
            missing = sorted(set(self._tasks) - set(self.original_assignment))
            extra = sorted(set(self.original_assignment) - set(self._tasks))
            raise ValueError(f"bad original assignment: missing={missing}, extra={extra}")

    def run(self) -> ThermalRCLSResult:
        t0 = time.perf_counter()
        original = proxy_score(
            self.graph,
            self.original_assignment,
            self.task_power,
            self.R,
            self.proxy_config,
            self.objective_weights,
        )
        denominators = {
            "Tmax_proxy": float(original["Tmax_proxy"]),
            "SigmaT_proxy": float(original["SigmaT_proxy"]),
            "HotCount_proxy": float(original["HotCount_proxy"]),
        }
        if self.objective_weights.objective != "thermal_only":
            denominators["CommProxy"] = float(original["CommProxy"])

        current_assignment = self._initial_assignment(denominators)
        current_power = aggregate_power(current_assignment, self.task_power, self.proxy_config)
        current_temp = temperature_proxy(self.R, current_power, self.proxy_config.Tambient)
        current_comm = self._comm_for_score(current_assignment)
        current = score_from_temp_and_comm(
            current_temp, current_comm, self.proxy_config, self.objective_weights, denominators,
        )
        initial = dict(current)
        initial["power_W"] = list(current_power)

        best_assignment = dict(current_assignment)
        best_power = list(current_power)
        best_temp = list(current_temp)
        best_comm = current_comm
        best = dict(current)
        history: list[dict[str, Any]] = [
            self._history_row(0, current, best, accepted=False, op=None, no_improve=0)
        ]

        no_improve = 0
        converged = False
        last_iteration = 0
        for iteration in range(1, self.search_config.max_iter + 1):
            last_iteration = iteration
            if self._timed_out(t0):
                converged = True
                break

            candidates = self._candidate_ops(current_assignment, current_temp)
            accepted_payload = self._choose_candidate(
                candidates,
                current_assignment,
                current_power,
                current_temp,
                current_comm,
                current,
                denominators,
                iteration,
            )

            accepted = False
            accepted_op = None
            best_improved = False
            if accepted_payload is not None:
                accepted = True
                accepted_op = accepted_payload["op"]
                current_assignment = self._apply_op(current_assignment, accepted_op)
                current_power = accepted_payload["power"]
                current_temp = accepted_payload["temp"]
                current_comm = accepted_payload["comm"]
                current = accepted_payload["score"]

                if float(current["score"]) + self._eps < float(best["score"]):
                    best_assignment = dict(current_assignment)
                    best_power = list(current_power)
                    best_temp = list(current_temp)
                    best_comm = current_comm
                    best = dict(current)
                    best_improved = True

            no_improve = 0 if best_improved else no_improve + 1
            history.append(
                self._history_row(
                    iteration,
                    current,
                    best,
                    accepted=accepted,
                    op=accepted_op,
                    no_improve=no_improve,
                )
            )
            if no_improve >= self.search_config.no_improve_patience:
                converged = True
                break

        final = score_from_temp_and_comm(
            best_temp, best_comm, self.proxy_config, self.objective_weights, denominators,
        )
        final["power_W"] = best_power
        method_key = self._method_key()
        proxy_payload = {
            "method": method_key,
            "method_label": self._method_label(),
            "not_exact_reproduction": True,
            "search_objective": self._search_objective_text(),
            "forbidden_search_inputs": self._forbidden_search_inputs(),
            "config": {
                "proxy": asdict(self.proxy_config),
                "objective_weights": asdict(self.objective_weights),
                "search": asdict(self.search_config),
            },
            "denominators": denominators,
            "original": original,
            "initial": initial,
            method_key: final,
            "assignment": {str(tid): pe for tid, pe in sorted(best_assignment.items())},
        }
        return ThermalRCLSResult(
            assignment=best_assignment,
            proxy=proxy_payload,
            history=history,
            elapsed_s=time.perf_counter() - t0,
            converged=converged,
            iterations=last_iteration,
        )

    def _initial_assignment(self, denominators: dict[str, float]) -> dict[int, int]:
        if self.initial_assignment is not None:
            return dict(self.initial_assignment)
        if self.search_config.init_mode == "original":
            return dict(self.original_assignment)
        if self.search_config.init_mode == "random_spread":
            return self._random_spread_assignment()
        return self._greedy_proxy_assignment(denominators)

    def _random_spread_assignment(self) -> dict[int, int]:
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

    def _greedy_proxy_assignment(self, denominators: dict[str, float]) -> dict[int, int]:
        assignment: dict[int, int] = {}
        if self.objective_weights.objective == "thermal_only":
            task_order = sorted(
                self._tasks,
                key=lambda tid: (-self.task_power.get(tid, 0.0), tid),
            )
        else:
            task_order = sorted(
                self._tasks,
                key=lambda tid: (-self.task_power.get(tid, 0.0), -self._comm_degree(tid), tid),
            )
        for tid in task_order:
            best_pe = 0
            best_key: tuple[float, float, float, int] | None = None
            for pe in range(self.proxy_config.num_pes):
                candidate = dict(assignment)
                candidate[tid] = pe
                score = proxy_score(
                    self.graph,
                    candidate,
                    self.task_power,
                    self.R,
                    self.proxy_config,
                    self.objective_weights,
                    denominators=denominators,
                )
                key = (
                    float(score["score"]),
                    float(score["Tmax_proxy"]),
                    float(score["SigmaT_proxy"]),
                    pe,
                )
                if best_key is None or key < best_key:
                    best_key = key
                    best_pe = pe
            assignment[tid] = best_pe
        return assignment

    def _candidate_ops(
        self,
        assignment: dict[int, int],
        temps: list[float],
    ) -> list[dict[str, int | str | None]]:
        tasks_by_pe = self._tasks_by_pe(assignment)
        hot_pes = sorted(
            range(self.proxy_config.num_pes),
            key=lambda pe: (-temps[pe], pe),
        )[: self.search_config.hot_pe_count]
        if self.objective_weights.objective == "thermal_only":
            cool_pes = sorted(
                range(self.proxy_config.num_pes),
                key=lambda pe: (temps[pe], 0 if not tasks_by_pe.get(pe) else 1, pe),
            )[: self.search_config.cool_pe_count]
        else:
            cool_pes = sorted(
                range(self.proxy_config.num_pes),
                key=lambda pe: (temps[pe], pe),
            )[: self.search_config.cool_pe_count]

        ops: list[dict[str, int | str | None]] = []
        seen: set[tuple[Any, ...]] = set()

        def add(op: dict[str, int | str | None]) -> None:
            key = (op.get("kind"), op.get("task_a"), op.get("task_b"), op.get("target_pe"))
            if key not in seen:
                seen.add(key)
                ops.append(op)

        for hot_pe in hot_pes:
            hot_tasks = sorted(
                tasks_by_pe.get(hot_pe, []),
                key=lambda tid: (-self.task_power.get(tid, 0.0), tid),
            )[: self.search_config.candidate_task_limit]
            for task_a in hot_tasks:
                for cool_pe in cool_pes:
                    if cool_pe == hot_pe:
                        continue
                    add({"kind": "move", "task_a": task_a, "task_b": None, "target_pe": cool_pe})
                    for task_b in tasks_by_pe.get(cool_pe, []):
                        if task_a == task_b:
                            continue
                        lo, hi = sorted((task_a, task_b))
                        add({"kind": "swap", "task_a": lo, "task_b": hi, "target_pe": None})

        if self._rng.random() < self.search_config.random_swap_rate:
            for _ in range(self.search_config.random_candidate_count):
                if len(self._tasks) >= 2 and self._rng.random() < 0.5:
                    a, b = self._rng.sample(self._tasks, 2)
                    if assignment[a] != assignment[b]:
                        lo, hi = sorted((a, b))
                        add({"kind": "swap", "task_a": lo, "task_b": hi, "target_pe": None})
                else:
                    task = self._rng.choice(self._tasks)
                    pe = self._rng.randrange(self.proxy_config.num_pes)
                    if pe != assignment[task]:
                        add({"kind": "move", "task_a": task, "task_b": None, "target_pe": pe})
        return ops

    def _choose_candidate(
        self,
        candidates: list[dict[str, int | str | None]],
        assignment: dict[int, int],
        power: list[float],
        temps: list[float],
        comm: float | None,
        current_score: dict[str, Any],
        denominators: dict[str, float],
        iteration: int,
    ) -> dict[str, Any] | None:
        del comm
        evaluated: list[dict[str, Any]] = []
        for op in candidates:
            payload = self._evaluate_op(assignment, power, temps, op, denominators)
            evaluated.append(payload)

        if not evaluated:
            return None

        current_value = float(current_score["score"])
        best = min(evaluated, key=self._candidate_rank_key)
        if float(best["score"]["score"]) + self._eps < current_value:
            return best

        if not self.search_config.enable_sa:
            return None

        temperature = self.search_config.sa_initial_temp * (
            self.search_config.sa_cooling ** max(0, iteration - 1)
        )
        self._rng.shuffle(evaluated)
        for payload in evaluated:
            delta = float(payload["score"]["score"]) - current_value
            if delta <= 0.0:
                return payload
            accept_prob = math.exp(-delta / max(temperature, 1e-12))
            if self._rng.random() < accept_prob:
                return payload
        return None

    def _evaluate_op(
        self,
        assignment: dict[int, int],
        power: list[float],
        temps: list[float],
        op: dict[str, int | str | None],
        denominators: dict[str, float],
    ) -> dict[str, Any]:
        new_assignment = self._apply_op(assignment, op)
        new_power = list(power)
        deltas = self._power_deltas(assignment, op)
        for pe, delta in deltas.items():
            new_power[pe] += delta
        new_temp = self._apply_temperature_delta(temps, deltas)
        new_comm = self._comm_for_score(new_assignment)
        score = score_from_temp_and_comm(
            new_temp,
            new_comm,
            self.proxy_config,
            self.objective_weights,
            denominators,
        )
        return {
            "op": op,
            "assignment": new_assignment,
            "power": new_power,
            "temp": new_temp,
            "comm": new_comm,
            "score": score,
        }

    def _comm_for_score(self, assignment: dict[int, int]) -> float | None:
        if self.objective_weights.objective == "thermal_only":
            return None
        return communication_proxy(self.graph, assignment, self.proxy_config.cols)

    def _candidate_rank_key(self, item: dict[str, Any]) -> tuple[Any, ...]:
        op = item["op"]
        if self.objective_weights.objective == "thermal_only":
            return (
                float(item["score"]["score"]),
                int(op.get("task_a") or -1),
                int(op.get("task_b") or -1),
                int(op.get("target_pe") or -1),
            )
        return (
            float(item["score"]["score"]),
            str(op.get("kind")),
            int(op.get("task_a") or -1),
            int(op.get("task_b") or -1),
            int(op.get("target_pe") or -1),
        )

    def _apply_op(
        self,
        assignment: dict[int, int],
        op: dict[str, int | str | None],
    ) -> dict[int, int]:
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

    def _power_deltas(
        self,
        assignment: dict[int, int],
        op: dict[str, int | str | None],
    ) -> dict[int, float]:
        task_a = int(op["task_a"])
        pe_a = assignment[task_a]
        p_a = self.task_power.get(task_a, 0.0)
        deltas: dict[int, float] = {}

        def add(pe: int, delta: float) -> None:
            deltas[pe] = deltas.get(pe, 0.0) + delta

        if op["kind"] == "move":
            target = int(op["target_pe"])
            add(pe_a, -p_a)
            add(target, p_a)
            return deltas

        task_b = int(op["task_b"])
        pe_b = assignment[task_b]
        p_b = self.task_power.get(task_b, 0.0)
        add(pe_a, p_b - p_a)
        add(pe_b, p_a - p_b)
        return deltas

    def _apply_temperature_delta(
        self,
        temps: list[float],
        deltas: dict[int, float],
    ) -> list[float]:
        new_temp = list(temps)
        for target_pe in range(self.proxy_config.num_pes):
            delta_t = 0.0
            for source_pe, delta_power in deltas.items():
                delta_t += self.R[target_pe][source_pe] * delta_power
            new_temp[target_pe] += delta_t
        return new_temp

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

    def _history_row(
        self,
        iteration: int,
        current: dict[str, Any],
        best: dict[str, Any],
        accepted: bool,
        op: dict[str, int | str | None] | None,
        no_improve: int,
    ) -> dict[str, Any]:
        row = {
            "iteration": iteration,
            "current_score": current["score"],
            "best_score": best["score"],
            "current_Tmax_proxy": current["Tmax_proxy"],
            "best_Tmax_proxy": best["Tmax_proxy"],
            "current_SigmaT_proxy": current["SigmaT_proxy"],
            "best_SigmaT_proxy": best["SigmaT_proxy"],
            "current_HotCount_proxy": current["HotCount_proxy"],
            "best_HotCount_proxy": best["HotCount_proxy"],
            "accepted": accepted,
            "accepted_op": op,
            "no_improve": no_improve,
        }
        if self.objective_weights.objective != "thermal_only":
            row["current_CommProxy"] = current["CommProxy"]
            row["best_CommProxy"] = best["CommProxy"]
        return row

    def _timed_out(self, start: float) -> bool:
        return (
            self.search_config.time_limit_s > 0.0
            and time.perf_counter() - start >= self.search_config.time_limit_s
        )

    def _method_key(self) -> str:
        if self.objective_weights.objective == "thermal_only":
            return "thermal_only_rc_ls"
        return "thermal_rc_ls"

    def _method_label(self) -> str:
        if self.objective_weights.objective == "thermal_only":
            return "ThermalOnly-RC-LS"
        return "ThermalRC-LS / Thermal-Resistance-Aware Local Search"

    def _search_objective_text(self) -> str:
        if self.objective_weights.objective == "thermal_only":
            return "thermal-only RC proxy over Tmax, SigmaT, and HotCount; no communication tie-breaker"
        return "lightweight RC thermal proxy plus weak Manhattan communication tie-breaker"

    def _forbidden_search_inputs(self) -> list[str]:
        if self.objective_weights.objective == "thermal_only":
            return [
                "OMNeT++ candidate simulation",
                "communication",
                "makespan",
                "congestion",
                "DVFS penalty",
                "energy",
                "load balance",
                "full composite cost",
            ]
        return [
            "OMNeT++ candidate full simulation",
            "B-2 full composite cost",
            "makespan",
            "congestion",
            "DVFS penalty",
            "PE plus optical communication energy",
        ]
