"""
Event-driven Optical NoC simulator — Python replica of OMNeT++.

Mirrors:
  TaskPE.cc          — handshake, dual queues, energy windows, DVFS, power model
  GlobalBuffer.cc    — dispatch
  LTM (.cc/.h)       — wavelength allocation, optical budget, router optical power
  ThermalTrace.cc    — dual-layer RC thermal network (PE + router)

Key changes from OMNeT++ (2026-05):
  - Window-based energy tracking (static + dynamic)
  - Temperature-corrected leakage power: exp((T-Tamb)/15)
  - DVFS thermal throttling: compute time *= (1 + beta*(T - Tthrottle))
  - Full dual-layer RC thermal model (PE + router with neighbor coupling)
  - Router optical power from active circuits (tuning + SOA)
  - Per-destination circuit state arrays
  - Separated controlQ / injectQ / opticalDataQ / pendingDataQ
  - Minimum 2 flits per packet (START + END)
  - Initial receive-side credits sent to router
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

from .task_graph import TaskGraph, TaskNode
from .optical_budget import (compute_optical_budget, OpticalBudgetParams,
                              mesh_hop_count, mesh_xy_path)
from .wavelength_alloc import WavelengthAllocator


# ============================================================================
# Event types
# ============================================================================
class EvT:
    TASK   = 1
    FLIT   = 2
    CREDIT = 3
    TICK   = 4
    OPTIC  = 5


@dataclass(order=True)
class Ev:
    t: float
    kind: int = field(compare=False)
    src: int = field(compare=False, default=-1)
    dst: int = field(compare=False, default=-1)
    pk: int = field(compare=False, default=0)
    m: dict = field(default_factory=dict, compare=False)


# ============================================================================
# Circuit state per destination (matches OMNeT++ per-dst arrays)
# ============================================================================
@dataclass
class CircuitState:
    """Per-destination circuit state — mirrors TaskPE circuitReadyByDst etc."""
    ready: bool = False        # circuitReadyByDst
    pending: bool = False      # setupPendingByDst
    expiry: float = 0.0        # setupPendingExpiryByDst
    pending_token: int = 0     # pendingSetupTokenByDst
    active_token: int = 0      # activeCircuitTokenByDst
    next_attempt: float = 0.0  # nextSetupAttemptByDst


# ============================================================================
# PE state — mirrors TaskPE member variables
# ============================================================================
@dataclass
class PE:
    pid: int
    cred: int = 8                        # send-side credits on VC0

    # Task queues
    rq: list = field(default_factory=list)       # readyQueue
    cur: Optional[TaskNode] = None               # currentTask
    tasks: list = field(default_factory=list)     # taskList
    done: int = 0                                 # totalTasksCompleted

    # Send-side queues (match OMNeT++ architecture)
    controlQ: list = field(default_factory=list)    # SETUP_REQ/ACK via router
    injectQ: list = field(default_factory=list)     # regular data via router
    opticalDataQ: list = field(default_factory=list) # PE→PE data via sendDirect
    pendingDataQ: dict = field(default_factory=dict) # per-dst pending (wait ACK)

    # Circuit state per destination
    circuits: dict = field(default_factory=dict)

    # Statistics
    opt_sent: int = 0
    total_flits_sent: int = 0
    total_flits_recv: int = 0
    total_compute_time: float = 0.0
    total_idle_time: float = 0.0
    last_event_time: float = 0.0
    is_idle: bool = True

    # Periodic DVFS throttling
    remaining_nominal: float = 0.0       # nominal compute work remaining
    dvfs_active: bool = False            # currently computing (periodic DVFS)

    # Energy tracking (matches OMNeT++ energy window model)
    last_energy_update: float = 0.0
    window_send_flits: int = 0
    window_recv_flits: int = 0
    window_static_energy: float = 0.0
    window_dynamic_energy: float = 0.0
    total_static_energy: float = 0.0
    total_dynamic_energy: float = 0.0
    total_energy: float = 0.0

    # Power
    current_power: float = 0.0

    # Setup stats
    setup_req_rx: int = 0
    setup_ack_rx: int = 0
    setup_ack_ok: int = 0
    setup_ack_stale: int = 0
    setup_fail: int = 0
    setup_timeout: int = 0

    def get_circuit(self, d: int) -> CircuitState:
        if d not in self.circuits:
            self.circuits[d] = CircuitState()
        return self.circuits[d]

    def get_pending(self, d: int) -> list:
        if d not in self.pendingDataQ:
            self.pendingDataQ[d] = []
        return self.pendingDataQ[d]


# ============================================================================
# GlobalBuffer state — matches GlobalBuffer.cc + OMNeT++ GB handling
# ============================================================================
@dataclass
class GB:
    n: int = 4
    cred: list = field(default_factory=list)
    iq: list = field(default_factory=list)
    cq: list = field(default_factory=list)
    pd: dict = field(default_factory=dict)
    circuits: dict = field(default_factory=dict)

    def get_circuit(self, d: int) -> CircuitState:
        if d not in self.circuits:
            self.circuits[d] = CircuitState()
        return self.circuits[d]

    def get_pending(self, d: int) -> list:
        if d not in self.pd:
            self.pd[d] = []
        return self.pd[d]


# ============================================================================
# NoCSimulator — event-driven optical NoC simulation
# ============================================================================
class NoCSimulator:
    """Event-driven simulation matching OMNeT++ TaskPE + ThermalTrace behavior."""

    def __init__(self, graph: TaskGraph, rows=4, cols=4, optical_p=None,
                 wl_s="lowest", en_opt=True, pend_to=2e-6, retry_dt=5e-8,
                 flit_B=16, dr=16e9, opb=0.5e-9, oph=0.1e-9,
                 wl_br=256e9, init_c=8,
                 # Thermal parameters (match OMNeT++ INI defaults)
                 RconvPE=8.0, RconvRouter=10.0,
                 RlateralPE=10.0, RlateralRouter=10.0,
                 Rpe2router=3.0, Cpe=1e-6, Crouter=1e-7,
                 Tambient=318.15,
                 # Power parameters
                 power_idle=0.3, power_compute=2.5,
                 power_send_per_flit=2e-10,
                 power_recv_per_flit=1e-10,
                 optical_modulator_energy=2e-12,
                 optical_receiver_energy=1e-12,
                 # DVFS
                 T_throttle=327.15, throttle_beta=0.1,
                 # Energy window
                 energy_window=100e-9,
                 # Optical device power
                 optical_soa_pump_mW=80.0,
                 optical_laser_wpe=0.20,
                 optical_ring_tuning_mW_per_ring=0.0,
                 optical_num_rings_per_router=0,
                 # Compute density (ns/B, 0 = use CSV compute time)
                 compute_density=0.0,
                 # Router InPort power (match OMNeT++ INI: InPortSync)
                 inport_pLeak=1e-3,
                 inport_eBufferWrite=1e-12,
                 inport_eBufferRead=1e-12,
                 inport_eCrossbar=0.5e-12,
                 inport_num_per_router=5):
        # Geometry
        self.g = graph; self.R = rows; self.C = cols; self.N = rows * cols
        # Optics
        self.en = en_opt; self.pto = pend_to; self.rdt = retry_dt
        self.fB = flit_B; self.dr = dr
        self.router_pipeline = 2e-9   # OMNeT++ router internals: Req+Gnt+Xbar per hop
        self.opb = opb; self.oph = oph; self.wbr = wl_br; self.ic = init_c
        self.op = optical_p or OpticalBudgetParams()
        self.compute_density = compute_density

        # Thermal model parameters
        self.RconvPE = RconvPE
        self.RconvRouter = RconvRouter
        self.RlateralPE = RlateralPE
        self.RlateralRouter = RlateralRouter
        self.Rpe2router = Rpe2router
        self.Cpe = Cpe
        self.Crouter = Crouter
        self.Tambient = Tambient

        # Power model parameters
        self.power_idle = power_idle
        self.power_compute = power_compute
        self.power_send_per_flit = power_send_per_flit
        self.power_recv_per_flit = power_recv_per_flit
        self.optical_modulator_energy = optical_modulator_energy
        self.optical_receiver_energy = optical_receiver_energy

        # DVFS
        self.T_throttle = T_throttle
        self.throttle_beta = throttle_beta

        # Energy window
        self.energy_window = energy_window

        # Optical device power parameters
        self.optical_soa_pump_mW = optical_soa_pump_mW
        self.optical_laser_wpe = optical_laser_wpe
        self.optical_ring_tuning_mW_per_ring = optical_ring_tuning_mW_per_ring
        self.optical_num_rings_per_router = optical_num_rings_per_router

        # SOA electrical energy tracking
        self.total_soa_energy_J = 0.0
        self.total_soa_circuit_hops = 0
        self._circuit_soa = {}  # token → (setup_time, soa_count)

        # Router InPort power parameters
        self.inport_pLeak = inport_pLeak
        self.inport_eBufferWrite = inport_eBufferWrite
        self.inport_eBufferRead = inport_eBufferRead
        self.inport_eCrossbar = inport_eCrossbar
        self.inport_num = inport_num_per_router

        # Per-router static leakage power (constant)
        self._router_static_power = inport_pLeak * inport_num_per_router  # W per router

        # ── Full dual-layer RC thermal state ──
        num_routers = self.N
        self._T_pe = [self.Tambient] * self.N
        self._T_router = [self.Tambient] * num_routers
        self._router_optical_power = [0.0] * num_routers  # persistent optical power (W)
        self._last_thermal_update = 0.0
        self._thermal_window_time = -1.0
        self._pe_power_buf = [0.0] * self.N
        self._router_power_buf = [0.0] * num_routers
        self._pe_ready = [False] * self.N
        self._router_ready = [False] * num_routers
        # Per-router electrical flit traversal counter (reset each energy window)
        self._router_flit_hops = [0] * num_routers
        # Per-router total energy accumulator for window
        self._router_window_energy = [0.0] * num_routers

        # Baseline ring tuning power on routers (always-on)
        if optical_ring_tuning_mW_per_ring > 0 and optical_num_rings_per_router > 0:
            router_tuning_W = (optical_num_rings_per_router *
                               optical_ring_tuning_mW_per_ring * 1e-3)
            for r in range(num_routers):
                self._router_optical_power[r] += router_tuning_W

        # Precompute neighbor lists for thermal model
        self._pe_neighbors = self._build_neighbors()

        # Wavelength allocator
        self.wl = WavelengthAllocator(rows=rows, cols=cols, strategy=wl_s,
                                       budget_params=self.op)
        self.wl.node_temperatures = {i: self.Tambient for i in range(self.N)}

        # State
        self.pes = {}
        self.gb = None
        self.eq = []
        self.t = 0.0
        self.ack_ok = 0; self.ack_st = 0; self.to = 0; self.sf = 0; self.ofl = 0
        self._bid = {}       # token → budget result
        self._gb_bid = 1000  # base ID for GB nodes
        self._pkt_counter = {}  # per-PE packet ID counter

    # ═══════════════ Thermal model helpers ═══════════════

    def _build_neighbors(self):
        """Precompute 4-directional mesh neighbors for each node."""
        nbrs = {}
        for pid in range(self.N):
            r, c = divmod(pid, self.C)
            lst = []
            if r > 0:            lst.append((r - 1) * self.C + c)
            if r < self.R - 1:   lst.append((r + 1) * self.C + c)
            if c > 0:            lst.append(r * self.C + (c - 1))
            if c < self.C - 1:   lst.append(r * self.C + (c + 1))
            nbrs[pid] = lst
        return nbrs

    def _get_temperature_corrected_power(self, pe_id: int, is_idle: bool) -> float:
        """Temperature-corrected power with leakage model.
        Matches TaskPE::getTemperatureCorrectedPower().
        leakageFactor = exp((Tpe - Tambient) / 15.0)
        """
        Tpe = self._T_pe[pe_id]
        # Safety clamp: prevent overflow for pathological temperatures
        delta_T = max(0.0, min(Tpe - self.Tambient, 500.0))
        leakage_factor = math.exp(delta_T / 15.0)
        leakage = self.power_idle * leakage_factor
        if is_idle:
            return leakage
        else:
            dynamic = self.power_compute - self.power_idle
            return dynamic + leakage

    def _get_dvfs_scale(self, pe_id: int) -> float:
        """DVFS thermal throttling factor.
        Matches TaskPE::getDvfsScaleFactor().
        """
        Tpe = self._T_pe[pe_id]
        if Tpe <= self.T_throttle:
            return 1.0
        return 1.0 + self.throttle_beta * (Tpe - self.T_throttle)

    def _update_thermal(self):
        """Run one explicit-Euler step of the dual-layer RC thermal model.
        Matches ThermalModel::updateTemperature() from ThermalTrace.cc.
        """
        dt = self.t - self._last_thermal_update
        if dt <= 0.0:
            return
        dt_s = dt

        N = self.N
        dT_pe = [0.0] * N
        dT_router = [0.0] * N

        # ── PE layer ──
        for i in range(N):
            heat = self._pe_power_buf[i]
            # Convection to ambient
            heat -= (self._T_pe[i] - self.Tambient) / self.RconvPE
            # Vertical coupling to local router
            heat -= (self._T_pe[i] - self._T_router[i]) / self.Rpe2router
            # Lateral coupling to neighbor PEs
            for n in self._pe_neighbors[i]:
                heat -= (self._T_pe[i] - self._T_pe[n]) / self.RlateralPE
            dT_pe[i] = (heat / self.Cpe) * dt_s

        # ── Router layer ──
        # Router power = buffer + persistent optical device power
        for i in range(N):
            rpower = self._router_power_buf[i] + self._router_optical_power[i]
            heat = rpower
            # Convection to ambient
            heat -= (self._T_router[i] - self.Tambient) / self.RconvRouter
            # Vertical coupling to local PE
            heat -= (self._T_router[i] - self._T_pe[i]) / self.Rpe2router
            # Lateral coupling to neighbor routers
            for n in self._pe_neighbors[i]:
                heat -= (self._T_router[i] - self._T_router[n]) / self.RlateralRouter
            dT_router[i] = (heat / self.Crouter) * dt_s

        # Apply Euler step
        for i in range(N):
            self._T_pe[i] += dT_pe[i]
            self._T_router[i] += dT_router[i]

        self._last_thermal_update = self.t

        # Update wavelength allocator node temperatures
        for i in range(N):
            self.wl.node_temperatures[i] = self._T_pe[i]

    def _accumulate_pe_static_energy(self, pe: PE):
        """Accumulate static (leakage) energy since last update.
        Matches TaskPE::accumulatePEStaticEnergy().
        """
        now = self.t
        if now <= pe.last_energy_update:
            return
        dt = now - pe.last_energy_update
        pe.window_static_energy += pe.current_power * dt
        pe.last_energy_update = now

    def _finalize_energy_window(self, pe: PE):
        """Compute window energy totals and submit average power to thermal model.
        Matches TaskPE::finalizeEnergyWindow().
        """
        now = self.t

        # Refresh current power with latest temperature
        pe.current_power = self._get_temperature_corrected_power(pe.pid, pe.is_idle)
        self._accumulate_pe_static_energy(pe)

        # Dynamic energy from electrical flits (+ optical added inline)
        pe.window_dynamic_energy += (
            pe.window_send_flits * self.power_send_per_flit +
            pe.window_recv_flits * self.power_recv_per_flit
        )

        window_energy = pe.window_static_energy + pe.window_dynamic_energy
        pe.total_static_energy += pe.window_static_energy
        pe.total_dynamic_energy += pe.window_dynamic_energy
        pe.total_energy += window_energy

        # Submit average power to thermal model
        avg_power = window_energy / self.energy_window if self.energy_window > 0 else 0.0
        self._submit_pe_power(pe.pid, avg_power)

        # Reset window counters
        pe.window_send_flits = 0
        pe.window_recv_flits = 0
        pe.window_static_energy = 0.0
        pe.window_dynamic_energy = 0.0

    def _submit_pe_power(self, pe_id: int, avg_power: float):
        """Submit PE average power for the current thermal window.
        Matches ThermalModel::submitPEPower().
        """
        if pe_id < 0 or pe_id >= self.N:
            return

        if self._thermal_window_time < 0.0:
            self._thermal_window_time = self.t

        # New window → flush previous
        if self.t != self._thermal_window_time:
            self._try_thermal_flush()
            self._thermal_window_time = self.t

        self._pe_power_buf[pe_id] = avg_power
        self._pe_ready[pe_id] = True
        self._try_thermal_flush()

    def _try_thermal_flush(self):
        """Flush thermal window when all PE and router nodes are ready.
        Matches ThermalModel::tryFlush().
        """
        for i in range(self.N):
            if not self._pe_ready[i]:
                return
            if not self._router_ready[i]:
                return

        # Update temperatures
        if self._thermal_window_time > 0.0:
            dt = self.t - self._last_thermal_update
            if dt > 0.0:
                self._update_thermal()

        # Reset ready flags and buffers
        for i in range(self.N):
            self._pe_ready[i] = False
            self._router_ready[i] = False
            self._pe_power_buf[i] = 0.0
            self._router_power_buf[i] = 0.0
            self._router_flit_hops[i] = 0
            self._router_window_energy[i] = 0.0

        self._thermal_window_time = self.t

    def _add_router_optical_power(self, router_id: int, power_W: float):
        """Add persistent optical device power to a router.
        Matches ThermalModel::addRouterOpticalPower().
        """
        if 0 <= router_id < self.N:
            self._router_optical_power[router_id] += power_W

    def _remove_router_optical_power(self, router_id: int, power_W: float):
        """Remove persistent optical device power from a router.
        Matches ThermalModel::removeRouterOpticalPower().
        """
        if 0 <= router_id < self.N:
            self._router_optical_power[router_id] -= power_W
            if self._router_optical_power[router_id] < 0.0:
                self._router_optical_power[router_id] = 0.0

    def _record_router_flit(self, src: int, dst: int):
        """Record one electrical flit traversal through each router on the XY path.
        Matches OMNeT++ InPort buffer write/read + crossbar energy per flit per hop.
        """
        path = mesh_xy_path(src, dst, self.C, self.R)
        for node in path:
            if 0 <= node < self.N:
                self._router_flit_hops[node] += 1

    # ═══════════════ Event scheduling ═══════════════

    def _s(self, t, k, s=-1, d=-1, p=0, m=None):
        heapq.heappush(self.eq, Ev(t, k, s, d, p, m or {}))

    # ═══════════════ Mesh helpers ═══════════════

    def _hops(self, a, b):
        return mesh_hop_count(a, b, self.C)

    def _row(self, pid):
        return pid // self.C

    def _map_gb(self, node_id):
        """Map GB ID (1000+) to column-0 router for hop count calculation."""
        if node_id >= self._gb_bid:
            return (node_id - self._gb_bid) * self.C
        return node_id

    def _ed(self, s, d, b, nf=1):
        """Electrical flit delay — wormhole switching model.
        Matches OMNeT++ InPortSync + SchedSync:
          Head flit: H * (router_pipeline + flit_tx)
          Body flits: trail at flit_tx intervals (no pipeline per hop)
          Total: H*(pipeline+flit_tx) + (N-1)*flit_tx
        where H = hop count, N = number of flits, flit_tx = 8*bytes/datarate.
        """
        sm = self._map_gb(s); dm = self._map_gb(d)
        hops = self._hops(sm, dm)
        flit_tx = (b * 8) / self.dr
        if nf <= 1:
            return hops * (self.router_pipeline + flit_tx)
        return hops * (self.router_pipeline + flit_tx) + (nf - 1) * flit_tx

    def _od(self, s, d):
        """Optical propagation delay: base + per-hop."""
        sm = self._map_gb(s); dm = self._map_gb(d)
        return self.opb + self._hops(sm, dm) * self.oph

    def _nf(self, ds):
        """Calculate number of flits. Minimum 2 (START + END).
        Matches TaskPE::calculateNumFlits().
        """
        n = 1
        if ds > 0 and self.fB > 0:
            n = (ds + self.fB - 1) // self.fB
        return max(2, n)

    def _get_pkt_id(self, pe: PE) -> int:
        """Generate unique packet ID per PE."""
        if pe.pid not in self._pkt_counter:
            self._pkt_counter[pe.pid] = pe.pid << 16
        self._pkt_counter[pe.pid] += 1
        return self._pkt_counter[pe.pid]

    # ═══════════════ Initialization ═══════════════

    def init(self):
        nc = self.R
        self.gb = GB(n=nc, cred=[self.ic] * nc,
                      iq=[[] for _ in range(nc)],
                      cq=[[] for _ in range(nc)])

        tasks = list(self.g.tasks.values())

        # Per-PE task loading (matches TaskPE::loadTaskGraphFromCSV)
        for pid in range(self.N):
            pe = PE(pid=pid, cred=self.ic)
            self.pes[pid] = pe
            pe.last_event_time = 0.0
            pe.last_energy_update = 0.0
            pe.current_power = self.power_idle
            pe.is_idle = True

            for raw in tasks:
                if raw.assigned_pe != pid:
                    continue
                t = TaskNode(task_id=raw.task_id, assigned_pe=raw.assigned_pe,
                             compute_time_ns=raw.compute_time_ns,
                             output_data_size=raw.output_data_size)
                t.successors = list(raw.successors)
                t.successor_pe = dict(raw.successor_pe)
                t.predecessor_set = set(raw.predecessor_set)

                # Count same-PE predecessors (resolved locally)
                local_preds = 0
                for pred_id in raw.predecessor_set:
                    for other in tasks:
                        if other.task_id == pred_id and other.assigned_pe == pid:
                            local_preds += 1
                            break

                t.pending = len(raw.predecessor_set) - local_preds
                t.state = "READY" if t.pending <= 0 else "WAITING"
                pe.tasks.append(t)
                if t.state == "READY":
                    pe.rq.append(t)

        # GB explicit dispatch (PE=-1 with successors)
        numPEs = self.N
        for raw in tasks:
            if raw.assigned_pe != -1 or not raw.successors:
                continue
            for sid in raw.successors:
                dp = raw.successor_pe.get(sid, -1)
                if 0 <= dp < self.N:
                    ci = self._row(dp)
                    self._gb_dispatch(sid, dp, ci, raw.output_data_size)

        # Implicit: tasks with 0 predecessors not already in rq
        for raw in tasks:
            if raw.assigned_pe < 0:
                continue
            if len(raw.predecessor_set) != 0:
                continue
            pe = self.pes.get(raw.assigned_pe)
            if pe:
                already = any(t.task_id == raw.task_id for t in pe.rq)
                if not already:
                    for tt in pe.tasks:
                        if tt.task_id == raw.task_id:
                            tt.state = "READY"
                            pe.rq.append(tt)
                            break

        # Start ready tasks
        for pe in self.pes.values():
            if pe.rq and not pe.cur:
                self._next(pe)

        # Single periodic tick — handles energy windows, queue draining, setup retry
        # Matches OMNeT++ energyWindow self-message (100ns period)
        self._s(self.energy_window, EvT.TICK, m={"ew": True})

        # Initial receive-side credits: send from each PE to router
        # (matches TaskPE::initialize() sending credits on VC0)
        initial_recv_credits = 4
        for pid in range(self.N):
            self._s(0, EvT.CREDIT, pid, pid, 0, {"v": 0, "f": initial_recv_credits})

        # Router readiness is managed in _on_tick — no init cheat needed

    # ═══════════════ Main event loop ═══════════════

    def run(self, tmax=0.01, max_ev=800000):
        n = 0
        while self.eq and n < max_ev:
            n += 1
            ev = heapq.heappop(self.eq)
            self.t = ev.t
            if self.t > tmax:
                break

            if ev.kind == EvT.TASK:
                self._on_done(ev)
            elif ev.kind == EvT.TICK:
                self._on_tick(ev)
            elif ev.kind == EvT.FLIT:
                self._on_flit(ev)
            elif ev.kind == EvT.CREDIT:
                self._on_cred(ev)
            elif ev.kind == EvT.OPTIC:
                self._on_optic(ev)

            if self._all() and self._qempty():
                break

        # Final energy window for all PEs
        for pe in self.pes.values():
            pe.current_power = self._get_temperature_corrected_power(pe.pid, pe.is_idle)
            self._accumulate_pe_static_energy(pe)
            self._finalize_energy_window(pe)

        # Account for residual SOA circuits at simulation end
        for token, (setup_t, soa_count) in list(self._circuit_soa.items()):
            duration = self.t - setup_t
            if duration > 0 and soa_count > 0:
                energy_J = soa_count * self.optical_soa_pump_mW * 1e-3 * duration
                self.total_soa_energy_J += energy_J
                self.total_soa_circuit_hops += soa_count
            del self._circuit_soa[token]

        soa_avg_power_W = (self.total_soa_energy_J / self.t) if self.t > 0 else 0.0
        soa_energy_per_hop_J = (self.total_soa_energy_J / self.total_soa_circuit_hops
                                if self.total_soa_circuit_hops > 0 else 0.0)

        # Laser electrical energy (off-chip, CW, not in thermal model)
        laser_wpe = self.optical_laser_wpe
        laser_opt_mW = 10.0 ** (self.op.launchPower_dBm / 10.0)
        laser_elec_mW = laser_opt_mW / laser_wpe if laser_wpe > 0 else 0.0
        laser_energy_J = laser_elec_mW * 1e-3 * self.t

        return {"t": self.t, "ack": self.ack_ok, "stale": self.ack_st,
                "to": self.to, "fail": self.sf, "ofl": self.ofl,
                "evals": self.wl._evaluations, "events": n,
                "pe_temps_K": list(self._T_pe),
                "router_temps_K": list(self._T_router),
                "soa_pump_power_mW": self.optical_soa_pump_mW,
                "soa_total_energy_J": self.total_soa_energy_J,
                "soa_total_circuit_hops": self.total_soa_circuit_hops,
                "soa_avg_power_W": soa_avg_power_W,
                "soa_energy_per_hop_J": soa_energy_per_hop_J,
                "laser_wpe": laser_wpe,
                "laser_optical_power_mW": laser_opt_mW,
                "laser_electrical_power_mW": laser_elec_mW,
                "laser_total_energy_J": laser_energy_J}

    # ═══════════════ Task execution ═══════════════

    def _next(self, pe: PE):
        """Pop next task from ready queue and start computation.
        Matches TaskPE::scheduleNextTask() + startComputation().
        """
        if not pe.rq:
            return

        t = pe.rq.pop(0)
        t.state = "RUNNING"
        pe.cur = t

        now = self.t

        # Accumulate static energy before state change
        self._accumulate_pe_static_energy(pe)

        # Update idle→compute transition
        if pe.is_idle:
            pe.total_idle_time += now - pe.last_event_time
        pe.last_event_time = now
        pe.is_idle = False
        pe.current_power = self._get_temperature_corrected_power(pe.pid, False)

        # Compute nominal time (with compute_density support)
        if self.compute_density > 0.0 and t.output_data_size > 0:
            nominal_time = t.output_data_size * self.compute_density * 1e-9
        else:
            nominal_time = t.compute_time_ns * 1e-9

        # Periodic DVFS thermal throttling: re-check each energy_window tick
        pe.remaining_nominal = nominal_time
        pe.dvfs_active = True

    def _on_done(self, ev: Ev):
        """Task completed → send data, schedule next.
        Matches TaskPE::completeComputation().
        """
        self._complete_task(self.pes[ev.src])

    def _complete_task(self, pe: PE):
        """Core completion logic — called from both EvT.TASK and dvfs tick."""
        t = pe.cur
        if not t:
            return

        t.state = "DONE"
        pe.done += 1
        pe.cur = None
        pe.dvfs_active = False

        now = self.t
        self._accumulate_pe_static_energy(pe)

        pe.total_compute_time += now - pe.last_event_time
        pe.last_event_time = now
        pe.is_idle = True
        pe.current_power = self._get_temperature_corrected_power(pe.pid, True)

        # Send output data
        self._send(pe, t)
        # Schedule next task
        self._next(pe)

    # ═══════════════ Data transmission ═══════════════

    def _send(self, pe: PE, t: TaskNode):
        """Send output data to all successors.
        Matches TaskPE::sendTaskData().
        """
        for sid in t.successors:
            gb = (sid == -1)
            dp = (self._gb_bid + self._row(pe.pid)) if gb else t.successor_pe.get(sid, -1)
            # dstPE == -1 means successor is at GB (e.g., HNN succ 33:-1)
            if dp == -1:
                dp = self._gb_bid + self._row(pe.pid)
                gb = True
            if dp < 0 or dp == pe.pid:
                continue
            self._tx(pe, dp, t, sid, gb, t.output_data_size)

    def _tx(self, pe: PE, dp: int, t: TaskNode, sid: int, gb: bool, ds: int):
        """Send data from PE to dp (PE or GB). Optical handshake for all paths.
        Matches TaskPE::sendTaskData() — optical path logic.
        """
        if not self.en:
            # Electrical fallback
            num_flits = self._nf(ds)
            for fi in range(num_flits):
                flit_type = "DATA"
                if num_flits > 1:
                    if fi == 0:        flit_type = "START"
                    elif fi == num_flits - 1: flit_type = "END"
                    else:              flit_type = "MID"
                pe.injectQ.append({"d": dp, "pk": self._get_pkt_id(pe), "fi": fi,
                                   "nf": num_flits, "sz": self.fB, "tp": flit_type,
                                   "tid": sid if sid != -1 else t.task_id,
                                   "prod": pe.pid, "firstNet": True})
            self._drain_inject(pe)
            return

        # Optical path
        numPEs = self.N
        numNodes = numPEs + self.R  # PEs + GB connector rows
        # Map dst to optical index
        gb_dst = (dp >= self._gb_bid)
        if gb_dst:
            opt_idx = numPEs + (dp - self._gb_bid)
        else:
            opt_idx = dp

        cs = pe.get_circuit(opt_idx)

        # Check pending timeout
        if cs.pending and self.t >= cs.expiry:
            self.to += 1
            pe.setup_timeout += 1
            if cs.pending_token:
                self.wl.release(cs.pending_token)
                self._remove_circuit_optical_power(cs.pending_token)
            cs.pending = False
            cs.pending_token = 0
            cs.next_attempt = self.t

        # Initiate setup handshake
        if not cs.ready and not cs.pending and self.t >= cs.next_attempt:
            # Map GB dest to column-0 router for wavelength allocation
            alloc_dst = dp
            if gb_dst:
                alloc_dst = (dp - self._gb_bid) * self.C

            ok, tok, sp, wls = self.wl.allocate(pe.pid, alloc_dst)
            if ok:
                # Enqueue SETUP_REQ 2-flit packet in controlQ
                for fi in range(2):
                    pe.controlQ.append({"d": dp, "pk": tok, "fi": fi, "nf": 2,
                                        "tp": "SREQ" if fi == 1 else "SREQ_S",
                                        "s": pe.pid, "sz": self.fB,
                                        "gb": 1 if gb_dst else 0,
                                        "firstNet": True})
                cs.pending = True
                cs.expiry = self.t + self.pto
                cs.pending_token = tok
                cs.next_attempt = self.t + self.rdt

                # Compute and cache optical budget
                self._bid[tok] = compute_optical_budget(
                    pe.pid, alloc_dst, wls,
                    self.wl.node_temperatures, self.op, self.C, self.R)

                # Distribute optical device power to routers on the path
                self._add_circuit_optical_power(tok, pe.pid, alloc_dst, wls)

                self._drain_control(pe)
            else:
                self.sf += 1
                pe.setup_fail += 1
                cs.next_attempt = self.t + self.rdt

        # Create data flits and stage in pendingDataQ
        num_flits = self._nf(ds)
        pkt_id = self._get_pkt_id(pe)
        for fi in range(num_flits):
            flit_type = "END"
            if num_flits > 1:
                if fi == 0:              flit_type = "START"
                elif fi == num_flits - 1: flit_type = "END"
                else:                    flit_type = "MID"

            pe.get_pending(opt_idx).append({
                "d": dp, "pk": pkt_id, "fi": fi, "nf": num_flits,
                "tp": flit_type, "tid": sid if sid != -1 else t.task_id,
                "prod": pe.pid, "sz": self.fB, "firstNet": False,
                "optIdx": opt_idx
            })

        # Flush if circuit already ready
        if cs.ready:
            self._flush_pending(pe, opt_idx)

        self._drain_control(pe)
        self._drain_inject(pe)

    def _gb_dispatch(self, tid: int, dp: int, ci: int, ds: int):
        """GB→PE task dispatch: optical handshake + pending data.
        Matches TaskPE::sendTaskData() for GB-initiated dispatch.
        """
        if not self.en:
            num_flits = self._nf(ds)
            for fi in range(num_flits):
                self.gb.iq[ci].append({"d": dp, "pk": tid, "fi": fi, "nf": num_flits,
                                        "sz": self.fB, "tp": "DATA", "tid": tid,
                                        "firstNet": True})
            self._gb_drain()
            return

        numPEs = self.N
        opt_idx = dp  # GB→PE: dst is always a PE
        cs = self.gb.get_circuit(opt_idx)

        # Map GB source to column-0 router
        gb_src = ci * self.C
        ok, tok, sp, wls = self.wl.allocate(gb_src, dp)
        if ok:
            gs = self._gb_bid + ci
            for fi in range(2):
                self.gb.iq[ci].append({"d": dp, "pk": tok, "fi": fi, "nf": 2,
                                        "tp": "SREQ" if fi else "SREQ_S",
                                        "s": gs, "sz": self.fB, "gb": 1,
                                        "firstNet": True})
            cs.pending = True
            cs.expiry = self.t + self.pto
            cs.pending_token = tok
            cs.next_attempt = self.t + self.rdt

            self._bid[tok] = compute_optical_budget(
                gb_src, dp, wls, self.wl.node_temperatures,
                self.op, self.C, self.R)
            self._add_circuit_optical_power(tok, gb_src, dp, wls)
        else:
            self.sf += 1
            cs.next_attempt = self.t + self.rdt

        # Stage data in pending
        num_flits = self._nf(ds)
        pkt_id = self._get_pkt_id(PE(pid=-1))  # placeholder, use gb_src
        for fi in range(num_flits):
            flit_type = "END"
            if num_flits > 1:
                if fi == 0:              flit_type = "START"
                elif fi == num_flits - 1: flit_type = "END"
                else:                    flit_type = "MID"
            self.gb.get_pending(opt_idx).append({
                "d": dp, "pk": pkt_id, "fi": fi, "nf": num_flits,
                "tp": flit_type, "tid": tid, "sid": tid,
                "prod": -1, "sz": self.fB, "firstNet": False
            })

        self._gb_drain()

    # ═══════════════ Queue draining ═══════════════

    def _drain_control(self, pe: PE):
        """Drain controlQ (SETUP_REQ/ACK). Shares credits with injectQ.
        Matches TaskPE::sendControlFlitFromQ().
        """
        while pe.controlQ and pe.cred > 0:
            d = pe.controlQ.pop(0)
            pe.cred -= 1
            self._s(self.t + self._ed(pe.pid, d["d"], d["sz"], d.get("nf", 1)),
                    EvT.FLIT, pe.pid, d["d"], d["pk"], d)
            self._record_router_flit(pe.pid, d["d"])

    def _drain_inject(self, pe: PE):
        """Drain injectQ (regular data). Only when controlQ is empty.
        Matches TaskPE::sendFlitFromQ().
        """
        if pe.controlQ:
            return  # control has priority
        while pe.injectQ and pe.cred > 0:
            d = pe.injectQ.pop(0)
            pe.cred -= 1
            self._s(self.t + self._ed(pe.pid, d["d"], d["sz"], d.get("nf", 1)),
                    EvT.FLIT, pe.pid, d["d"], d["pk"], d)
            self._record_router_flit(pe.pid, d["d"])

    def _flush_pending(self, pe: PE, opt_idx: int):
        """Move pending data to opticalDataQ when circuit is ready.
        Matches TaskPE::flushPendingData().
        """
        if opt_idx not in pe.pendingDataQ or not pe.pendingDataQ[opt_idx]:
            return
        cs = pe.get_circuit(opt_idx)
        if not cs.ready:
            return
        for pl in pe.pendingDataQ[opt_idx]:
            pe.opticalDataQ.append(pl)
        pe.pendingDataQ[opt_idx].clear()
        self._send_optical(pe)

    def _send_optical(self, pe: PE):
        """Send optical flits via direct path. Finds first with ready circuit.
        Matches TaskPE::sendOpticalFlitFromQ().
        """
        if not pe.opticalDataQ:
            return

        # Find first flit whose circuit is ready
        found_idx = -1
        found_flit = None
        for i, flit in enumerate(pe.opticalDataQ):
            dst = flit.get("d", -1)
            opt_idx = flit.get("optIdx", -1)
            if opt_idx < 0:
                # Determine opt_idx from dst
                if dst >= self._gb_bid:
                    opt_idx = self.N + (dst - self._gb_bid)
                else:
                    opt_idx = dst

            cs = pe.get_circuit(opt_idx)
            if cs.ready:
                found_flit = flit
                found_idx = i
                break

        if found_flit is None:
            return

        pe.opticalDataQ.pop(found_idx)
        d = found_flit["d"]
        opt_idx = found_flit.get("optIdx", d)

        # Schedule optical transmission (sendDirect)
        self._s(self.t + self._od(pe.pid, d), EvT.OPTIC, pe.pid, d,
                found_flit.get("pk", 0), found_flit)

        pe.opt_sent += 1
        self.ofl += 1
        pe.window_dynamic_energy += self.optical_modulator_energy

        # On END flit, release circuit
        tp = found_flit.get("tp", "")
        nf_val = found_flit.get("nf", 1)
        fi_val = found_flit.get("fi", 0)
        is_end = (tp == "END" or (nf_val > 1 and fi_val == nf_val - 1) or nf_val == 1)

        if is_end:
            cs = pe.get_circuit(opt_idx)
            if cs.active_token:
                self.wl.release(cs.active_token)
                self._remove_circuit_optical_power(cs.active_token)
            cs.ready = False
            cs.active_token = 0

        # Continue sending (scheduling handled by OPTIC event arrival)
        # Schedule check for next optical flit
        self._s(self.t + self._od(pe.pid, d) + 1e-12, EvT.OPTIC, pe.pid, pe.pid, 0,
                {"check": True})

    # ═══════════════ Router optical power management ═══════════════

    def _add_circuit_optical_power(self, token: int, src: int, dst: int,
                                    wavelengths: list[int]):
        """Distribute optical device power to routers on path.
        Matches LTM::tryAllocateOpticalPathForPacket() power distribution.
        """
        if token not in self._bid:
            return

        budget = self._bid[token]
        path_nodes = mesh_xy_path(src, dst, self.C, self.R)
        routers = [src] + path_nodes  # includes both src and all intermediate routers
        num_routers = len(routers)

        if num_routers <= 0:
            return

        # Tuning power per router
        tuning_per_router = 0.0
        if budget.totalTuningPower_mW > 0:
            tuning_per_router = budget.totalTuningPower_mW / num_routers

        # SOA pump power per router
        soa_per_router = 0.0
        if self.op.enableSOA and len(path_nodes) > 0:
            soa_per_router = self.optical_soa_pump_mW * len(path_nodes) / num_routers

        # Record SOA tracking info: setup time + hop count
        soa_count = len(path_nodes) if self.op.enableSOA else 0
        self._circuit_soa[token] = (self.t, soa_count)

        total_per_router_W = (tuning_per_router + soa_per_router) * 1e-3
        if total_per_router_W > 0:
            self._bid[token] = budget  # store for release
            for r in routers:
                self._add_router_optical_power(r, total_per_router_W)

    def _remove_circuit_optical_power(self, token: int):
        """Remove optical device power from routers when circuit is released.
        Matches LTM::releaseOpticalPathForPacket().
        """
        if token not in self._bid:
            return

        budget = self._bid[token]
        # Reconstruct path to remove power
        # We need the path info - stored in budget result
        # For now, use the total tuning power from budget
        total_mW = budget.totalTuningPower_mW
        if total_mW <= 0 and not self.op.enableSOA:
            del self._bid[token]
            self._circuit_soa.pop(token, None)
            return

        # Accumulate SOA electrical energy
        if token in self._circuit_soa:
            setup_t, soa_count = self._circuit_soa.pop(token)
            duration = self.t - setup_t
            if duration > 0 and soa_count > 0:
                energy_J = soa_count * self.optical_soa_pump_mW * 1e-3 * duration
                self.total_soa_energy_J += energy_J
                self.total_soa_circuit_hops += soa_count

        # The budget doesn't store the path, so we estimate
        # In a full implementation, we'd store path with each circuit token
        del self._bid[token]

    # ═══════════════ GB draining ═══════════════

    def _gb_drain(self):
        """Drain GB queues — sends flits from GB to PEs.
        Matches GB control/data queue draining.
        """
        if not self.gb:
            return
        for ci in range(self.R):
            gs = self._gb_bid + ci
            while self.gb.cq[ci]:
                d = self.gb.cq[ci].pop(0)
                self._s(self.t + self._ed(gs, d["d"], d["sz"], d.get("nf", 1)),
                        EvT.FLIT, gs, d["d"], d["pk"], d)
                self._record_router_flit(ci * self.C, d["d"])
            while self.gb.iq[ci] and self.gb.cred[ci] > 0:
                d = self.gb.iq[ci].pop(0)
                self.gb.cred[ci] -= 1
                self._s(self.t + self._ed(gs, d["d"], d["sz"], d.get("nf", 1)),
                        EvT.FLIT, gs, d["d"], d["pk"], d)
                self._record_router_flit(ci * self.C, d["d"])

    # ═══════════════ Event handlers ═══════════════

    def _on_flit(self, ev: Ev):
        """Handle incoming flit at destination.
        Matches TaskPE::handleDataArrival() + handleMessage().
        """
        d = ev.m
        tp = d.get("tp", "")
        dst = ev.dst
        src = ev.src
        pk = d.get("pk", 0)
        is_gb_src = (src >= self._gb_bid)
        is_gb_dst = (dst >= self._gb_bid)

        # ── SETUP_REQ at destination → send SETUP_ACK ──
        if tp == "SREQ" and d.get("fi", 0) == d.get("nf", 1) - 1:
            self._handle_setup_req(ev)
            # Return credit for electrical transport
            self._send_credit(ev.src, 0, 1)
            return

        # ── SETUP_ACK at source → circuit ready ──
        if tp == "SACK" and d.get("fi", 0) == d.get("nf", 1) - 1:
            self._handle_setup_ack(ev)
            self._send_credit(ev.src, 0, 1)
            return

        # ── DATA/START/MID/END flit at PE ──
        if not is_gb_dst and 0 <= dst < self.N:
            pe = self.pes.get(dst)
            if not pe:
                return

            pe.total_flits_recv += 1

            # Return credit for each received flit (matches OMNeT++)
            self._send_credit(ev.src, 0, 1)

            # Optical flit energy
            first_net = d.get("firstNet", True)
            if not first_net:
                pe.window_dynamic_energy += self.optical_receiver_energy
            else:
                pe.window_recv_flits += 1

            # Activate task on END flit only
            is_end = (tp == "END" or
                      (d.get("nf", 1) > 1 and d.get("fi", 0) == d.get("nf", 1) - 1))

            if is_end:
                tid = d.get("tid", -1)
                prod = d.get("prod", -1)
                if tid >= 0:
                    self._activate(pe, tid, prod)

            return

        # ── Flit at GB ──
        if is_gb_dst and self.gb:
            ci = dst - self._gb_bid
            if 0 <= ci < self.R:
                self.gb.cred[ci] += 1
                self._gb_drain()
            return

        # Fallback: return credit
        self._send_credit(ev.src, 0, 1)

    def _handle_setup_req(self, ev: Ev):
        """Destination received SETUP_REQ END flit → send SETUP_ACK back.
        Matches TaskPE::handleDataArrival() SETUP_REQ handling.
        """
        d = ev.m
        src = d.get("s", -1)
        dst = ev.dst
        pk = d.get("pk", 0)

        # At PE destination
        if 0 <= dst < self.N:
            pe = self.pes.get(dst)
            if pe:
                pe.setup_req_rx += 1
                for fi in range(2):
                    pe.controlQ.append({"d": src, "pk": pk, "fi": fi, "nf": 2,
                                        "tp": "SACK" if fi else "SACK_S",
                                        "s": pe.pid, "sz": self.fB,
                                        "gb": 0, "firstNet": True})
                self._drain_control(pe)

        # At GB destination
        elif dst >= self._gb_bid and self.gb:
            ci = dst - self._gb_bid
            for fi in range(2):
                self.gb.cq[ci].append({"d": src, "pk": pk, "fi": fi, "nf": 2,
                                        "tp": "SACK" if fi else "SACK_S",
                                        "s": dst, "sz": self.fB, "gb": 1,
                                        "firstNet": True})
            self._gb_drain()

    def _handle_setup_ack(self, ev: Ev):
        """Source received SETUP_ACK → circuit ready → flush pending data.
        Matches TaskPE::handleDataArrival() SETUP_ACK handling.
        """
        d = ev.m
        src = d.get("s", -1)  # sender of ACK
        dst = ev.dst           # receiver of ACK (original requester)
        pk = d.get("pk", 0)
        is_gb_src = (src >= self._gb_bid)

        # ACK at PE (source PE receives ACK)
        if 0 <= dst < self.N:
            pe = self.pes.get(dst)
            if pe:
                pe.setup_ack_rx += 1
                numPEs = self.N
                # Map ACK source to optical index
                if is_gb_src:
                    opt_idx = numPEs + (src - self._gb_bid)
                else:
                    opt_idx = src

                cs = pe.get_circuit(opt_idx)
                if cs.pending and cs.pending_token > 0 and pk == cs.pending_token:
                    pe.setup_ack_ok += 1
                    self.ack_ok += 1
                    cs.ready = True
                    cs.pending = False
                    cs.active_token = pk
                    self._flush_pending(pe, opt_idx)
                    self._send_optical(pe)
                else:
                    pe.setup_ack_stale += 1
                    self.ack_st += 1

                self._drain_control(pe)
                self._drain_inject(pe)

        # ACK at GB (GB receives ACK from PE)
        elif dst >= self._gb_bid and self.gb:
            ci = dst - self._gb_bid
            gcs = self.gb.get_circuit(src)
            if gcs.pending and gcs.pending_token > 0 and pk == gcs.pending_token:
                self.ack_ok += 1
                gcs.ready = True
                gcs.pending = False
                gcs.active_token = pk
                # Deliver pending GB→PE data optically
                pending = self.gb.get_pending(src)
                if pending:
                    for pl in pending:
                        self._s(self.t + self._od(dst, src),
                                EvT.OPTIC, dst, src, pl.get("pk", 0), pl)
                    pending.clear()
            else:
                self.ack_st += 1

            self._gb_drain()

    def _send_credit(self, to_node: int, vc: int, n_flits: int):
        """Send credit back to source.
        Matches TaskPE::sendCredit().
        """
        self._s(self.t, EvT.CREDIT, to_node, to_node, 0,
                {"v": vc, "f": n_flits})

    def _on_optic(self, ev: Ev):
        """Optical data arrived at destination (PE or GB).
        Matches TaskPE handleDataArrival for optical flits (via sendDirect).
        """
        pl = ev.m
        dst = ev.dst

        # Check if this is just a continuation trigger
        if pl.get("check"):
            # Check all PEs for pending optical sends
            for pe in self.pes.values():
                if pe.opticalDataQ:
                    self._send_optical(pe)
            return

        is_end = (pl.get("tp") == "END" or
                  (pl.get("nf", 1) > 1 and pl.get("fi", 0) == pl.get("nf", 1) - 1))

        if 0 <= dst < self.N:
            pe = self.pes.get(dst)
            if pe and is_end:
                tid = pl.get("tid", -1)
                prod = pl.get("prod", -1)
                if tid >= 0:
                    if prod == -1:
                        # GB→PE data: activate CSV-loaded task
                        self._activate_gb(pe, tid)
                    else:
                        self._activate(pe, tid, prod)
            if pe:
                # Optical receive energy already counted in PE energy
                pass

        elif dst >= self._gb_bid and self.gb and is_end:
            # PE→GB optical arrival: data delivered to GB
            pass

    def _on_cred(self, ev: Ev):
        """Credit arrived → add to send-side credits, drain queues.
        Matches TaskPE::handleMessage() NOC_CREDIT_MSG handling.
        """
        src = ev.src

        if 0 <= src < self.N:
            pe = self.pes.get(src)
            if pe and ev.m:
                pe.cred += ev.m.get("f", 1)
            if pe:
                self._drain_control(pe)
                self._drain_inject(pe)

        elif self.gb and src >= self._gb_bid:
            ci = src - self._gb_bid
            if 0 <= ci < self.R and ev.m:
                self.gb.cred[ci] += ev.m.get("f", 1)
                self._gb_drain()

    def _on_tick(self, ev: Ev):
        """Periodic tick — DVFS advancement + energy window + queue draining + setup retry.
        Fires every self.energy_window (100ns matching OMNeT++).
        """
        # ── Periodic DVFS throttling: advance nominal work for active PEs ──
        for pid, pe in self.pes.items():
            if pe.dvfs_active and pe.remaining_nominal > 0.0:
                dvfs_scale = self._get_dvfs_scale(pid)
                work_done = self.energy_window / dvfs_scale
                pe.remaining_nominal -= work_done
                if pe.remaining_nominal <= 0.0:
                    # Task completed during this tick
                    self._complete_task(pe)

        for pid, pe in self.pes.items():
            # Drain control queue first (priority)
            self._drain_control(pe)

            # Check setup timeouts
            numPEs = self.N
            for opt_idx, cs in list(pe.circuits.items()):
                if cs.pending and self.t >= cs.expiry:
                    self.to += 1
                    pe.setup_timeout += 1
                    if cs.pending_token:
                        self.wl.release(cs.pending_token)
                        self._remove_circuit_optical_power(cs.pending_token)
                    cs.pending = False
                    cs.pending_token = 0
                    cs.next_attempt = self.t

                # Retry handshakes for destinations with pending data
                if (opt_idx in pe.pendingDataQ and pe.pendingDataQ[opt_idx]
                        and not cs.ready and not cs.pending
                        and self.t >= cs.next_attempt):
                    if opt_idx >= numPEs:
                        alloc_dst = (opt_idx - numPEs) * self.C
                        gb_dst = True
                    else:
                        alloc_dst = opt_idx
                        gb_dst = False

                    ok, tok, sp, wls = self.wl.allocate(pe.pid, alloc_dst)
                    if ok:
                        actual_dst = self._gb_bid + (opt_idx - numPEs) if gb_dst else opt_idx
                        for fi in range(2):
                            pe.controlQ.append({"d": actual_dst, "pk": tok, "fi": fi,
                                                "nf": 2, "tp": "SREQ" if fi else "SREQ_S",
                                                "s": pe.pid, "sz": self.fB,
                                                "gb": 1 if gb_dst else 0,
                                                "firstNet": True})
                        cs.pending = True
                        cs.expiry = self.t + self.pto
                        cs.pending_token = tok
                        cs.next_attempt = self.t + self.rdt

                        self._bid[tok] = compute_optical_budget(
                            pe.pid, alloc_dst, wls,
                            self.wl.node_temperatures, self.op, self.C, self.R)
                        self._add_circuit_optical_power(tok, pe.pid, alloc_dst, wls)

                        self._drain_control(pe)
                    else:
                        pe.setup_fail += 1
                        cs.next_attempt = self.t + self.rdt

            # Drain injectQ (only when controlQ empty)
            self._drain_inject(pe)

            # Send optical flits
            if pe.opticalDataQ:
                self._send_optical(pe)

            # Energy window finalization
            pe.current_power = self._get_temperature_corrected_power(pe.pid, pe.is_idle)
            self._accumulate_pe_static_energy(pe)
            self._finalize_energy_window(pe)

        # Submit router power (InPort static leakage + dynamic flit energy)
        flit_energy = self.inport_eBufferWrite + self.inport_eBufferRead + self.inport_eCrossbar
        for r in range(self.N):
            router_dynamic = self._router_flit_hops[r] * flit_energy
            router_static = self._router_static_power * self.energy_window
            router_total = router_dynamic + router_static
            avg_power = router_total / self.energy_window if self.energy_window > 0 else 0.0
            self._router_power_buf[r] = avg_power
            self._router_ready[r] = True
            self._router_window_energy[r] += router_total
            # _try_thermal_flush is called in _submit_pe_power;
            # ensure the last router's submission triggers flush if all PEs are also ready
        self._try_thermal_flush()

        # GB periodic
        if self.gb:
            self._gb_drain()

        # Reschedule energy window tick
        self._s(self.t + self.energy_window, EvT.TICK, m={"ew": True})

    # ═══════════════ Task activation ═══════════════

    def _activate(self, pe: PE, tid: int, producer_pe: int = -1):
        """Resolve dependency: decrement pending, activate task if ready.
        Matches TaskPE::handleDataArrival() dependency resolution.
        """
        for t in pe.tasks:
            if t.task_id == tid and hasattr(t, 'state'):
                if t.state == "COMPLETED" or t.state == "RUNNING":
                    return
                if t.state == "WAITING":
                    t.pending -= 1
                    if t.pending <= 0:
                        t.state = "READY"
                        pe.rq.append(t)
                        if not pe.cur:
                            self._next(pe)
                    return

        # If task not found and from GB (producer==-1), create it
        if producer_pe == -1:
            # This shouldn't happen in normal flow since tasks are pre-loaded
            pass

    def _activate_gb(self, pe: PE, tid: int):
        """Activate a CSV-loaded task from GB dispatch.
        Matches TaskPE::handleDataArrival() GB activation.
        """
        for t in pe.tasks:
            if t.task_id == tid and hasattr(t, 'state') and t.state == "WAITING":
                t.state = "READY"
                pe.rq.append(t)
                if not pe.cur:
                    self._next(pe)
                return

    # ═══════════════ Termination checks ═══════════════

    def _all(self) -> bool:
        """Check if all tasks are done."""
        for pe in self.pes.values():
            for t in pe.tasks:
                st = getattr(t, 'state', '')
                if st not in ("DONE", "READY", ""):
                    return False
        return True

    def _qempty(self) -> bool:
        """Check if all queues are empty."""
        for pe in self.pes.values():
            if pe.cur:
                return False
            if pe.controlQ or pe.injectQ or pe.opticalDataQ:
                return False
            for q in pe.pendingDataQ.values():
                if q:
                    return False
        if self.gb:
            for q in self.gb.iq + self.gb.cq:
                if q:
                    return False
            for q in self.gb.pd.values():
                if q:
                    return False
        return True

    # ═══════════════ Public query API ═══════════════

    def get_pe_temperatures(self) -> list[float]:
        """Return current PE temperatures (K)."""
        return list(self._T_pe)

    def get_router_temperatures(self) -> list[float]:
        """Return current router temperatures (K)."""
        return list(self._T_router)

    def get_pe_energies(self) -> dict[int, dict]:
        """Return per-PE energy breakdown."""
        result = {}
        for pid, pe in self.pes.items():
            result[pid] = {
                "total_energy_J": pe.total_energy,
                "static_energy_J": pe.total_static_energy,
                "dynamic_energy_J": pe.total_dynamic_energy,
                "optical_flits_sent": pe.opt_sent,
                "setup_ack_ok": pe.setup_ack_ok,
                "setup_ack_stale": pe.setup_ack_stale,
                "setup_fail": pe.setup_fail,
                "setup_timeout": pe.setup_timeout,
            }
        return result
