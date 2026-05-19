"""
ThermalSimulator — Python replica of the OMNeT++ RC thermal model.

Mirrors ThermalModel::updateTemperature() (ThermalTrace.cc:237-290)
and the TaskPE power/DVFS model.

Provides:
  TaskScheduler  — event-driven DAG scheduling with PE serialization
  PowerModel     — compute/idle power + DVFS thermal throttling
  ThermalSimulator — explicit-Euler RC thermal network solver
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from .task_graph import TaskGraph


# ============================================================================
# Simulation parameters (defaults from omnetpp.ini [General] / [Dynamic])
# ============================================================================
@dataclass
class SimParams:
    """Thermal / power / scheduling parameters matching omnetpp.ini."""
    # Mesh
    rows: int = 4
    cols: int = 4

    # Thermal (K/W, J/K, K)
    RconvPE:        float = 8.0
    RconvRouter:    float = 10.0
    RlateralPE:     float = 15.0
    RlateralRouter: float = 15.0
    Rpe2router:     float = 3.0
    Cpe:            float = 1e-6
    Crouter:        float = 2e-7
    Tambient:       float = 318.15

    # Power (W)
    powerIdle:      float = 0.5
    powerCompute:   float = 2.0

    # DVFS throttling
    Tthrottle:      float = 320.0    # K  (46.85 C)
    throttleBeta:   float = 0.05     # 5 % slowdown per C above threshold

    # Time discretisation
    dt:             float = 100e-9   # 100 ns

    # Communication
    flitSize:       int = 16         # bytes
    commDelayPerHop: float = 1e-9    # 1 ns per hop (router pipeline)

    @property
    def num_pes(self) -> int:
        return self.rows * self.cols

    @property
    def num_routers(self) -> int:
        return self.rows * self.cols


# ============================================================================
# Schedule entry
# ============================================================================
@dataclass
class TaskSlot:
    """One scheduled task on a PE."""
    task_id: int
    pe_id: int
    start_time: float       # seconds
    compute_time: float     # effective compute time after DVFS (seconds)
    finish_time: float      # seconds
    dvfs_factor: float = 1.0


@dataclass
class ThermalResult:
    """Output of one thermal simulation run."""
    schedule: list[TaskSlot]              # per-task timing
    pe_max_temp: list[float]              # K, index = PE id
    pe_avg_temp: list[float]              # K, averaged over active period
    pe_temp_trace: Optional[list[list[float]]] = None  # [pe_id][time_step]
    # Per-task start-time temperatures: {task_id: {pe_id: T_K}}
    # "At the moment task_i started, PE_j was at this temperature"
    task_start_temps: Optional[dict[int, dict[int, float]]] = None
    sim_end_time: float = 0.0


# ============================================================================
# TaskScheduler — event-driven DAG schedule
# ============================================================================
class TaskScheduler:
    """Given a TaskGraph and a PE assignment, produce a time-ordered
    schedule respecting DAG dependencies and PE serialization."""

    def __init__(self, graph: TaskGraph, assignment: dict[int, int],
                 params: SimParams):
        self.graph = graph
        self.assignment = dict(assignment)
        self.params = params
        self._hops_cache: dict[tuple[int, int], int] = {}

    def _hops(self, pe_a: int, pe_b: int) -> int:
        key = (pe_a, pe_b) if pe_a < pe_b else (pe_b, pe_a)
        if key not in self._hops_cache:
            r1, c1 = divmod(pe_a, self.params.cols)
            r2, c2 = divmod(pe_b, self.params.cols)
            self._hops_cache[key] = abs(r1 - r2) + abs(c1 - c2)
        return self._hops_cache[key]

    def _comm_delay(self, pred_id: int, dst_pe: int,
                    finish_time: dict[int, float]) -> float:
        """Communication delay for predecessor *pred_id* sending data
        to PE *dst_pe*."""
        pred_node = self.graph.tasks.get(pred_id)
        if pred_node is None or pred_node.is_gb_task:
            return 0.0
        src_pe = self.assignment.get(pred_id)
        if src_pe is None:
            return 0.0
        hops = self._hops(src_pe, dst_pe)
        n_flits = max(2, (pred_node.output_data_size +
                          self.params.flitSize - 1) // self.params.flitSize)
        return hops * self.params.commDelayPerHop * n_flits

    def _data_ready(self, tid: int, finish_time: dict[int, float]) -> float:
        """Earliest time task *tid* can start (all predecessor data arrived)."""
        node = self.graph.tasks[tid]
        dst_pe = self.assignment[tid]
        t = 0.0
        for pred_id in node.predecessor_set:
            pred_finish = finish_time.get(pred_id, 0.0)
            delay = self._comm_delay(pred_id, dst_pe, finish_time)
            t = max(t, pred_finish + delay)
        return t

    def schedule(self) -> list[TaskSlot]:
        slots: list[TaskSlot] = []
        finish_time: dict[int, float] = {}
        pe_free: dict[int, float] = {p: 0.0 for p in range(self.params.num_pes)}
        pending: dict[int, int] = {
            tid: len(node.predecessor_set) for tid, node in self.graph.tasks.items()
        }
        ready: list[int] = [tid for tid, n in pending.items() if n == 0 and
                            self.graph.tasks[tid].is_mappable]

        while ready:
            # Pick the task that can start earliest
            best_tid = -1
            best_start = float("inf")
            for tid in ready:
                data_ready = self._data_ready(tid, finish_time)
                pe = self.assignment[tid]
                start = max(data_ready, pe_free[pe])
                if start < best_start:
                    best_start = start
                    best_tid = tid

            tid = best_tid
            ready.remove(tid)
            node = self.graph.tasks[tid]
            pe = self.assignment[tid]

            data_ready = self._data_ready(tid, finish_time)
            start = max(data_ready, pe_free[pe])
            comp_s = node.compute_time_ns * 1e-9
            finish = start + comp_s

            slots.append(TaskSlot(
                task_id=tid, pe_id=pe,
                start_time=start, compute_time=comp_s,
                finish_time=finish, dvfs_factor=1.0,
            ))
            finish_time[tid] = finish
            pe_free[pe] = finish

            for succ_id in node.successors:
                if succ_id == -1:
                    continue
                if succ_id in pending:
                    pending[succ_id] -= 1
                    if pending[succ_id] == 0:
                        ready.append(succ_id)

        return sorted(slots, key=lambda s: s.start_time)


# ============================================================================
# PowerModel — compute power trace from schedule
# ============================================================================
class PowerModel:
    """Build per-PE power trace from a task schedule."""

    def __init__(self, params: SimParams):
        self.params = params

    def build_power_trace(
        self,
        schedule: list[TaskSlot],
        total_time: Optional[float] = None,
    ) -> tuple[list[list[float]], float]:
        """Return (pe_power_trace, end_time).

        pe_power_trace[pe_id] = [power_W at t0, t1, t2, ...]
        Each step is params.dt seconds.
        """
        dt = self.params.dt
        if total_time is None:
            total_time = max(s.finish_time for s in schedule) if schedule else 0.0
        n_steps = max(1, int(math.ceil(total_time / dt)))

        # Initialise: all PEs idle, all routers idle
        pe_trace = [[self.params.powerIdle] * n_steps for _ in range(self.params.num_pes)]
        router_trace = [[0.0] * n_steps for _ in range(self.params.num_routers)]

        for slot in schedule:
            start_step = int(slot.start_time / dt)
            end_step = min(n_steps, int(math.ceil(slot.finish_time / dt)))
            for s in range(start_step, end_step):
                pe_trace[slot.pe_id][s] = self.params.powerCompute

        # Router power: small fixed background (negligible for thermal)
        # In OMNeT++ routers have pLeak=1e-3W.  Keep simple for now.

        return pe_trace, router_trace, total_time


# ============================================================================
# ThermalSimulator — explicit-Euler RC thermal network
# ============================================================================
class ThermalSimulator:
    """Explicit-Euler RC thermal network solver, replicating
    ThermalModel::updateTemperature() from ThermalTrace.cc."""

    def __init__(self, params: SimParams):
        self.p = params

        self._neighbours: dict[int, list[int]] = {}
        self._precompute_neighbours()

    def _precompute_neighbours(self):
        """Cache 4-directional mesh neighbours."""
        for pe in range(self.p.num_pes):
            r, c = divmod(pe, self.p.cols)
            nbrs = []
            if r > 0:            nbrs.append((r - 1) * self.p.cols + c)
            if r < self.p.rows - 1: nbrs.append((r + 1) * self.p.cols + c)
            if c > 0:            nbrs.append(r * self.p.cols + (c - 1))
            if c < self.p.cols - 1: nbrs.append(r * self.p.cols + (c + 1))
            self._neighbours[pe] = nbrs

    def simulate(
        self,
        pe_power_trace: list[list[float]],
        router_power_trace: list[list[float]],
        initial_temps: Optional[list[float]] = None,
        record_trace: bool = False,
    ) -> ThermalResult:
        """Run thermal simulation over the power trace.

        Returns ThermalResult with max/avg temperatures per PE.
        """
        dt = self.p.dt
        n_steps = len(pe_power_trace[0])

        # Initialise temperatures
        T_pe = [self.p.Tambient] * self.p.num_pes
        T_router = [self.p.Tambient] * self.p.num_routers
        if initial_temps and len(initial_temps) == self.p.num_pes:
            T_pe = list(initial_temps)

        # Accumulators
        pe_max = list(T_pe)
        pe_sum = [0.0] * self.p.num_pes
        active_steps = [0] * self.p.num_pes

        # Optional full trace
        pe_trace_out: Optional[list[list[float]]] = (
            [[] for _ in range(self.p.num_pes)] if record_trace else None
        )

        for step in range(n_steps):
            P_pe = [pe_power_trace[pe][step] for pe in range(self.p.num_pes)]
            P_router = [router_power_trace[r][step] for r in range(self.p.num_routers)]

            dT_pe = [0.0] * self.p.num_pes
            dT_router = [0.0] * self.p.num_routers

            # --- PE layer ---
            for i in range(self.p.num_pes):
                heat = P_pe[i]
                heat -= (T_pe[i] - self.p.Tambient) / self.p.RconvPE
                heat -= (T_pe[i] - T_router[i]) / self.p.Rpe2router
                for n in self._neighbours[i]:
                    heat -= (T_pe[i] - T_pe[n]) / self.p.RlateralPE
                dT_pe[i] = (heat / self.p.Cpe) * dt

            # --- Router layer ---
            for i in range(self.p.num_routers):
                heat = P_router[i]
                heat -= (T_router[i] - self.p.Tambient) / self.p.RconvRouter
                heat -= (T_router[i] - T_pe[i]) / self.p.Rpe2router
                for n in self._neighbours[i]:
                    heat -= (T_router[i] - T_router[n]) / self.p.RlateralRouter
                dT_router[i] = (heat / self.p.Crouter) * dt

            # Apply Euler step
            for i in range(self.p.num_pes):
                T_pe[i] += dT_pe[i]
                T_router[i] += dT_router[i]

            # Track stats
            for i in range(self.p.num_pes):
                if T_pe[i] > pe_max[i]:
                    pe_max[i] = T_pe[i]
                pe_sum[i] += T_pe[i]
                active_steps[i] += 1

            if record_trace and pe_trace_out is not None:
                for i in range(self.p.num_pes):
                    pe_trace_out[i].append(T_pe[i])

        # Average
        pe_avg = [
            pe_sum[i] / max(1, active_steps[i])
            for i in range(self.p.num_pes)
        ]

        end_time = n_steps * dt

        return ThermalResult(
            schedule=[],   # filled by caller
            pe_max_temp=pe_max,
            pe_avg_temp=pe_avg,
            pe_temp_trace=pe_trace_out,
            sim_end_time=end_time,
        )


# ============================================================================
# Top-level simulator: schedule → power → thermal → DVFS → reschedule
# ============================================================================
def simulate_thermal(
    graph: TaskGraph,
    assignment: dict[int, int],
    params: Optional[SimParams] = None,
    max_dvfs_iter: int = 3,
    verbose: bool = False,
) -> ThermalResult:
    """Full thermal simulation for a given task-to-PE assignment.

    1. Schedule tasks (respecting DAG + PE serialization)
    2. Build power trace from schedule
    3. Run RC thermal solver
    4. If DVFS triggered for any task, re-schedule with adjusted
       compute times and repeat (up to max_dvfs_iter times).
    """
    if params is None:
        params = SimParams()

    scheduler = TaskScheduler(graph, assignment, params)
    power = PowerModel(params)
    thermal = ThermalSimulator(params)

    pe_temps = [params.Tambient] * params.num_pes

    for iteration in range(max_dvfs_iter):
        # 1. Schedule
        schedule = scheduler.schedule()

        if not schedule:
            return ThermalResult(
                schedule=[], pe_max_temp=pe_temps, pe_avg_temp=pe_temps,
            )

        # 2. Apply DVFS based on current PE temperatures at task start
        dvfs_applied = False
        for slot in schedule:
            pe_t = pe_temps[slot.pe_id]  # temp at approx start
            if pe_t > params.Tthrottle:
                factor = 1.0 + params.throttleBeta * (pe_t - params.Tthrottle)
                if factor > 1.0:
                    slot.compute_time *= factor
                    slot.finish_time = slot.start_time + slot.compute_time
                    slot.dvfs_factor = factor
                    dvfs_applied = True

        # 3. Build power trace
        pe_power_trace, router_power_trace, end_time = power.build_power_trace(schedule)

        # 4. Run thermal solver (always record full trace for per-task temps)
        result = thermal.simulate(
            pe_power_trace, router_power_trace,
            initial_temps=pe_temps, record_trace=True,
        )
        result.schedule = schedule

        # 4b. Extract per-task start-time temperatures
        #     task_start_temps[task_id][pe_id] = T of PE_j when task_i started
        result.task_start_temps = _extract_task_start_temps(
            schedule, result.pe_temp_trace, params
        )

        # 5. Check if DVFS changed
        max_delta = max(abs(result.pe_max_temp[i] - pe_temps[i])
                        for i in range(params.num_pes))
        pe_temps = list(result.pe_max_temp)

        if not dvfs_applied or iteration == max_dvfs_iter - 1:
            break

        if verbose and dvfs_applied:
            print(f"  [DVFS iter {iteration+1}] max dT = {max_delta:.2f} K")

    return result


# ============================================================================
# Helpers
# ============================================================================
def _extract_task_start_temps(
    schedule: list[TaskSlot],
    pe_temp_trace: Optional[list[list[float]]],
    params: SimParams,
) -> dict[int, dict[int, float]]:
    """For each task, record the temperature of every PE at the moment
    that task started computing.

    Returns {task_id: {pe_id: T_K}}.
    """
    result: dict[int, dict[int, float]] = {}
    if pe_temp_trace is None:
        return result
    n_steps = len(pe_temp_trace[0]) if pe_temp_trace else 0
    if n_steps == 0:
        return result

    dt = params.dt
    for slot in schedule:
        step = min(n_steps - 1, int(slot.start_time / dt))
        temps_at_start: dict[int, float] = {}
        for pe in range(params.num_pes):
            temps_at_start[pe] = pe_temp_trace[pe][step]
        result[slot.task_id] = temps_at_start
    return result


