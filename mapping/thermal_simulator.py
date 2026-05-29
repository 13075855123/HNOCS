"""
ThermalSimulator — Python replica of the OMNeT++ RC thermal model.

Mirrors ThermalModel::updateTemperature() (ThermalTrace.cc:237-290)
and the TaskPE power/DVFS model.

Key updates matching OMNeT++ (2026-05):
  - Temperature-corrected leakage power: exp((Tpe - Tamb) / 15)
  - DVFS thermal throttling: compute_time *= (1 + beta*(T - Tthrottle))
  - Persistent router optical power (tuning + SOA)
  - Dual-layer RC thermal network (PE + router) with neighbor coupling

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

    # DVFS throttling (matches OMNeT++ TaskPE)
    Tthrottle:      float = 320.0    # K  (46.85 C)
    throttleBeta:   float = 0.05     # 5 % slowdown per K above threshold

    # Temperature-corrected leakage: factor = exp((T - Tamb) / leakage_divisor)
    leakageDivisor: float = 15.0

    # Time discretisation
    dt:             float = 100e-9   # 100 ns

    # Communication — matching OMNeT++ TaskMesh.ned + SchedSync.cc
    flitSize:       int = 16         # bytes
    linkDatarate:   float = 16e9     # 16 Gbps (TaskLink)
    routerPipeline: float = 20e-9    # 20 ns router internals (Req+Gnt+Xbar)
    initialCredits: int = 4          # flits per VC (InPortSync/GlobalBuffer)
    schedClk:       float = 8e-9     # scheduler clock = flitTxTime

    # Optical device power (for router thermal model)
    opticalSoaPump_mW: float = 80.0
    opticalRingTuning_mW_per_ring: float = 0.0
    opticalNumRingsPerRouter: int = 0

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
    nominal_compute_time: float = 0.0  # before DVFS


@dataclass
class ThermalResult:
    """Output of one thermal simulation run."""
    schedule: list[TaskSlot]              # per-task timing
    pe_max_temp: list[float]              # K, index = PE id
    pe_avg_temp: list[float]              # K, averaged over active period
    router_max_temp: list[float]          # K, index = router id
    router_avg_temp: list[float]          # K
    pe_temp_trace: Optional[list[list[float]]] = None  # [pe_id][time_step]
    router_temp_trace: Optional[list[list[float]]] = None
    # Per-task start-time temperatures: {task_id: {pe_id: T_K}}
    task_start_temps: Optional[dict[int, dict[int, float]]] = None
    sim_end_time: float = 0.0


# ============================================================================
# Temperature-corrected power model (matches OMNeT++ TaskPE)
# ============================================================================
def get_temperature_corrected_power(
    is_idle: bool, pe_temp: float, params: SimParams
) -> float:
    """Compute temperature-corrected PE power with leakage model.
    Matches TaskPE::getTemperatureCorrectedPower().

    leakageFactor = exp((Tpe - Tambient) / leakageDivisor)
    - idle:  power = powerIdle * leakageFactor
    - compute: power = (powerCompute - powerIdle) + leakage
    """
    leakage_factor = math.exp((pe_temp - params.Tambient) / params.leakageDivisor)
    leakage = params.powerIdle * leakage_factor
    if is_idle:
        return leakage
    else:
        dynamic = params.powerCompute - params.powerIdle
        return dynamic + leakage


def get_dvfs_scale(pe_temp: float, params: SimParams) -> float:
    """DVFS thermal throttling factor.
    Matches TaskPE::getDvfsScaleFactor().
    """
    if pe_temp <= params.Tthrottle:
        return 1.0
    return 1.0 + params.throttleBeta * (pe_temp - params.Tthrottle)


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

    def _comm_delay(self, pred_id: int, dst_pe: int) -> float:
        """Communication delay matching OMNeT++ wormhole switching.

        Head flit: H * (routerPipeline + flitTxTime) per hop.
        Body flits: follow at flitTxTime intervals after head.
        Injection: N * flitTxTime to clock all flits out of source PE.

        Total = H*(routerPipeline + flitTxTime) + N*flitTxTime
        """
        pred_node = self.graph.tasks.get(pred_id)
        if pred_node is None or pred_node.is_gb_task:
            return 0.0
        src_pe = self.assignment.get(pred_id)
        if src_pe is None:
            return 0.0
        hops = self._hops(src_pe, dst_pe)
        p = self.params
        flit_tx = (8.0 * p.flitSize) / p.linkDatarate  # 8 ns
        n_flits = max(2, (pred_node.output_data_size +
                          p.flitSize - 1) // p.flitSize)
        per_hop = p.routerPipeline + flit_tx               # ~28 ns
        return hops * per_hop + n_flits * flit_tx

    def _data_ready(self, tid: int, finish_time: dict[int, float]) -> float:
        """Earliest time task *tid* can start (all predecessor data arrived)."""
        node = self.graph.tasks[tid]
        dst_pe = self.assignment[tid]
        t = 0.0
        for pred_id in node.predecessor_set:
            pred_finish = finish_time.get(pred_id, 0.0)
            delay = self._comm_delay(pred_id, dst_pe)
            t = max(t, pred_finish + delay)
        return t

    def schedule(self, pe_temps: Optional[list[float]] = None) -> list[TaskSlot]:
        """Produce task schedule with optional DVFS based on PE temperatures."""
        slots: list[TaskSlot] = []
        finish_time: dict[int, float] = {}
        pe_free: dict[int, float] = {p: 0.0 for p in range(self.params.num_pes)}
        # Count only data-producing (non-GB) predecessors
        pending: dict[int, int] = {}
        for tid, node in self.graph.tasks.items():
            n = sum(1 for p in node.predecessor_set
                    if not self.graph.tasks[p].is_gb_task)
            pending[tid] = n
        ready: list[int] = [tid for tid, n in pending.items() if n == 0 and
                            tid in self.assignment]

        while ready:
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

            # Compute nominal compute time
            nominal_comp = node.compute_time_ns * 1e-9

            # Apply DVFS if PE temperatures available
            dvfs = 1.0
            if pe_temps and pe < len(pe_temps):
                dvfs = get_dvfs_scale(pe_temps[pe], self.params)

            comp_s = nominal_comp * dvfs
            finish = start + comp_s

            slots.append(TaskSlot(
                task_id=tid, pe_id=pe,
                start_time=start,
                compute_time=comp_s,
                nominal_compute_time=nominal_comp,
                finish_time=finish,
                dvfs_factor=dvfs,
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
# PowerModel — compute power trace from schedule (temperature-corrected)
# ============================================================================
class PowerModel:
    """Build per-PE power trace from a task schedule with temperature-corrected power."""

    def __init__(self, params: SimParams):
        self.params = params

    def build_power_trace(
        self,
        schedule: list[TaskSlot],
        pe_temps: Optional[list[float]] = None,
        total_time: Optional[float] = None,
    ) -> tuple[list[list[float]], list[list[float]], float]:
        """Return (pe_power_trace, router_power_trace, end_time).

        Power is temperature-corrected using the leakage model.
        Router power starts at 0 (optical device power added separately).
        """
        dt = self.params.dt
        if total_time is None:
            total_time = max(s.finish_time for s in schedule) if schedule else 0.0
        n_steps = max(1, int(math.ceil(total_time / dt)))

        # Initialize: all PEs idle, all routers idle
        pe_trace = [[0.0] * n_steps for _ in range(self.params.num_pes)]
        router_trace = [[0.0] * n_steps for _ in range(self.params.num_routers)]

        # Default temperatures if not provided
        if pe_temps is None:
            pe_temps = [self.params.Tambient] * self.params.num_pes

        # Fill base idle power for all PEs (temperature-corrected)
        for pe_id in range(self.params.num_pes):
            idle_power = get_temperature_corrected_power(True, pe_temps[pe_id], self.params)
            for s in range(n_steps):
                pe_trace[pe_id][s] = idle_power

        # Override compute periods with temperature-corrected compute power
        for slot in schedule:
            start_step = int(slot.start_time / dt)
            end_step = min(n_steps, int(math.ceil(slot.finish_time / dt)))
            pe_temp = pe_temps[slot.pe_id] if slot.pe_id < len(pe_temps) else self.params.Tambient
            compute_power = get_temperature_corrected_power(False, pe_temp, self.params)
            for s in range(start_step, end_step):
                pe_trace[slot.pe_id][s] = compute_power

        return pe_trace, router_trace, total_time


# ============================================================================
# ThermalSimulator — explicit-Euler RC thermal network
# ============================================================================
class ThermalSimulator:
    """Explicit-Euler RC thermal network solver, replicating
    ThermalModel::updateTemperature() from ThermalTrace.cc.

    Supports persistent router optical power (tuning + SOA) that
    is added on top of the dynamic router power trace.
    """

    def __init__(self, params: SimParams):
        self.p = params
        self._neighbours: dict[int, list[int]] = {}
        self._precompute_neighbours()
        # Persistent optical device power on routers (W)
        self._router_optical_power: list[float] = []

    def _precompute_neighbours(self):
        """Cache 4-directional mesh neighbours."""
        for pe in range(self.p.num_pes):
            r, c = divmod(pe, self.p.cols)
            nbrs = []
            if r > 0:               nbrs.append((r - 1) * self.p.cols + c)
            if r < self.p.rows - 1: nbrs.append((r + 1) * self.p.cols + c)
            if c > 0:               nbrs.append(r * self.p.cols + (c - 1))
            if c < self.p.cols - 1: nbrs.append(r * self.p.cols + (c + 1))
            self._neighbours[pe] = nbrs

    def set_router_optical_power(self, power_W: list[float]):
        """Set persistent router optical device power (W per router)."""
        self._router_optical_power = list(power_W)

    def simulate(
        self,
        pe_power_trace: list[list[float]],
        router_power_trace: list[list[float]],
        initial_temps: Optional[list[float]] = None,
        initial_router_temps: Optional[list[float]] = None,
        record_trace: bool = False,
    ) -> ThermalResult:
        """Run thermal simulation over the power trace.

        Router power at each step = power_trace + persistent optical power.

        Returns ThermalResult with max/avg temperatures per PE and router.
        """
        dt = self.p.dt
        n_steps = len(pe_power_trace[0])

        # Initialize temperatures
        T_pe = [self.p.Tambient] * self.p.num_pes
        T_router = [self.p.Tambient] * self.p.num_routers
        if initial_temps and len(initial_temps) == self.p.num_pes:
            T_pe = list(initial_temps)
        if initial_router_temps and len(initial_router_temps) == self.p.num_routers:
            T_router = list(initial_router_temps)

        # Accumulators
        pe_max = list(T_pe)
        pe_sum = [0.0] * self.p.num_pes
        active_steps = [0] * self.p.num_pes
        router_max = list(T_router)
        router_sum = [0.0] * self.p.num_routers
        router_active_steps = [0] * self.p.num_routers

        # Optional full trace
        pe_trace_out: Optional[list[list[float]]] = (
            [[] for _ in range(self.p.num_pes)] if record_trace else None
        )
        router_trace_out: Optional[list[list[float]]] = (
            [[] for _ in range(self.p.num_routers)] if record_trace else None
        )

        # Ensure router_optical_power is sized correctly
        optical_power = self._router_optical_power
        while len(optical_power) < self.p.num_routers:
            optical_power.append(0.0)

        for step in range(n_steps):
            P_pe = [pe_power_trace[pe][step] for pe in range(self.p.num_pes)]
            # Router power = trace + persistent optical power
            P_router = [
                router_power_trace[r][step] + optical_power[r]
                for r in range(self.p.num_routers)
            ]

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
            for i in range(self.p.num_routers):
                if T_router[i] > router_max[i]:
                    router_max[i] = T_router[i]
                router_sum[i] += T_router[i]
                router_active_steps[i] += 1

            if record_trace:
                if pe_trace_out is not None:
                    for i in range(self.p.num_pes):
                        pe_trace_out[i].append(T_pe[i])
                if router_trace_out is not None:
                    for i in range(self.p.num_routers):
                        router_trace_out[i].append(T_router[i])

        # Average
        pe_avg = [
            pe_sum[i] / max(1, active_steps[i])
            for i in range(self.p.num_pes)
        ]
        router_avg = [
            router_sum[i] / max(1, router_active_steps[i])
            for i in range(self.p.num_routers)
        ]

        end_time = n_steps * dt

        return ThermalResult(
            schedule=[],
            pe_max_temp=pe_max,
            pe_avg_temp=pe_avg,
            router_max_temp=router_max,
            router_avg_temp=router_avg,
            pe_temp_trace=pe_trace_out,
            router_temp_trace=router_trace_out,
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
    2. Apply DVFS based on current PE temperatures
    3. Build power trace from schedule (temperature-corrected)
    4. Run RC thermal solver
    5. If DVFS triggered for any task, re-schedule with updated
       temperatures and repeat (up to max_dvfs_iter times).
    """
    if params is None:
        params = SimParams()

    scheduler = TaskScheduler(graph, assignment, params)
    power = PowerModel(params)
    thermal = ThermalSimulator(params)

    pe_temps = [params.Tambient] * params.num_pes
    router_temps = [params.Tambient] * params.num_routers

    for iteration in range(max_dvfs_iter):
        # 1. Schedule with current PE temperatures (for DVFS)
        schedule = scheduler.schedule(pe_temps=pe_temps)

        if not schedule:
            return ThermalResult(
                schedule=[], pe_max_temp=pe_temps, pe_avg_temp=pe_temps,
                router_max_temp=router_temps, router_avg_temp=router_temps,
            )

        # 2. Apply DVFS (already done in schedule() when pe_temps provided)
        dvfs_applied = any(s.dvfs_factor > 1.0 for s in schedule)

        # 3. Build power trace (temperature-corrected)
        pe_power_trace, router_power_trace, end_time = power.build_power_trace(
            schedule, pe_temps=pe_temps
        )

        # 4. Run thermal solver
        result = thermal.simulate(
            pe_power_trace, router_power_trace,
            initial_temps=pe_temps,
            initial_router_temps=router_temps,
            record_trace=True,
        )
        result.schedule = schedule

        # 4b. Extract per-task start-time temperatures
        result.task_start_temps = _extract_task_start_temps(
            schedule, result.pe_temp_trace, params
        )

        # 5. Check if DVFS changed
        max_delta = max(abs(result.pe_max_temp[i] - pe_temps[i])
                        for i in range(params.num_pes))
        pe_temps = list(result.pe_max_temp)
        router_temps = list(result.router_max_temp)

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
