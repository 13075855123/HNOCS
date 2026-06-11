"""
OmnetCostModel — thermal-aware cost model using OMNeT++ aggregate scalars.

Replaces NormalizedCostModel for OMNeT++-based GA evaluation.
Since OMNeT++ does not provide per-task start-time temperatures, this model
uses aggregate scalars + analytical computation for the cost terms:

    fitness = weighted sum of baseline-normalized terms

Baseline-normalized main experiment terms:
    f_peak       : PE peak temperature excess over ambient
    f_sigma      : time-averaged spatial PE temperature standard deviation
    f_hot        : over-throttle PE count
    f_makespan   : task makespan
    f_energy     : PE + optical communication energy
    f_comm       : analytical communication hops * dataSize
    f_congestion : analytical max physical-edge load
    f_dvfs       : average DVFS penalty
    f_load       : compute load imbalance
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# Simulation parameters (matching omnetpp.ini [ONoCGeneral])
# ============================================================================
@dataclass
class SimParams:
    """Thermal / power / scheduling parameters matching omnetpp.ini."""

    rows: int = 4
    cols: int = 4

    # Thermal (K/W, J/K, K)
    RconvPE:        float = 8.0
    RconvRouter:    float = 10.0
    RlateralPE:     float = 10.0
    RlateralRouter: float = 10.0
    Rpe2router:     float = 3.0
    Cpe:            float = 1e-6
    Crouter:        float = 1e-7
    Tambient:       float = 318.15

    # Power (W)
    powerIdle:      float = 0.3
    powerCompute:   float = 2.5

    # DVFS throttling
    Tthrottle:      float = 327.15  # K (54 C)
    throttleBeta:   float = 0.1

    # Time discretisation
    dt:             float = 100e-9   # 100 ns

    # Communication
    flitSize:       int = 16
    linkDatarate:   float = 16e9
    routerPipeline: float = 20e-9

    # Optical device power
    opticalSoaPump_mW: float = 80.0

    @property
    def num_pes(self) -> int:
        return self.rows * self.cols

    @property
    def num_routers(self) -> int:
        return self.rows * self.cols


@dataclass
class OmnetScalars:
    """Aggregate scalars + vectors extracted from one OMNeT++ simulation run.

    Sources:
      .sca  → total_throttle_penalty_s, total_compute_time_nominal_s,
               throttle_penalty_ratios, pe_total_energy_J, makespan_s,
               soa_energy_J, tuning_energy_J, laser_energy_J
      .vec  → pe_max_temp_K, sigma_T_K, N_hot, PE temperature traces
      thermal_snapshot.json → pe_temps_final_K, router_temps_final_K
    """

    # --- .sca: Per-PE totals (summed across all 16 TaskPE) ---
    total_throttle_penalty_s: float = 0.0
    total_compute_time_nominal_s: float = 0.0
    pe_total_energy_J: float = 0.0
    optical_packets_sent: int = 0

    # --- .sca: Per-PE throttlePenaltyRatio (16 values, for η_dvfs) ---
    throttle_penalty_ratios: list[float] = field(default_factory=list)

    # --- .sca: Global (recorded once) ---
    makespan_s: float = 0.0

    # --- .sca: ONOC / LTM global (recorded once each) ---
    soa_energy_J: float = 0.0
    tuning_energy_J: float = 0.0
    laser_energy_J: float = 0.0

    # --- .sca: ONOC optical link-quality summaries (actual allocated paths) ---
    optical_budget_count: int = 0
    optical_min_signal_margin_dB: float = 0.0
    optical_min_snr_dB: float = 0.0
    optical_max_ber: float = 0.0
    optical_max_temp_adjusted_loss_dB: float = 0.0
    optical_max_ring_detuning_nm: float = 0.0
    optical_max_path_tuning_power_mW: float = 0.0
    optical_max_waveguide_crossing_loss_dB: float = 0.0

    # --- .vec: pe-die-temperature per-PE peak (true T_max, not final) ---
    pe_max_temp_K: list[float] = field(default_factory=list)

    # --- .vec: time-averaged spatial PE temperature standard deviation ---
    sigma_T_K: float = 0.0

    # --- .vec: number of PEs whose peak exceeds Tthrottle ---
    N_hot: int = 0

    # --- thermal_snapshot.json: final temperatures (fallback if .vec unavailable) ---
    pe_temps_final_K: list[float] = field(default_factory=list)
    router_temps_final_K: list[float] = field(default_factory=list)

    # --- Evaluator status / parser integrity ---
    run_ok: bool = False
    failure_reason: str = ""
    temperature_source: str = ""
    temperature_complete: bool = False
    parsed_pe_count: int = 0
    parsed_temp_timepoints: int = 0

    # ==================================================================
    # Derived properties
    # ==================================================================

    @property
    def pe_peak_temp_K(self) -> float:
        """True peak PE temperature (from .vec), falling back to final temps."""
        if self.pe_max_temp_K:
            return max(self.pe_max_temp_K)
        if self.pe_temps_final_K:
            return max(self.pe_temps_final_K)
        return 0.0

    @property
    def pe_optical_comm_energy_J(self) -> float:
        """Modeled PE + optical communication energy.

        This includes PE activity plus SOA, MRR tuning, and laser energy. It
        intentionally excludes electronic router buffer/crossbar/leakage energy.
        """
        return (self.pe_total_energy_J + self.soa_energy_J
                + self.tuning_energy_J + self.laser_energy_J)

    @property
    def total_energy_J(self) -> float:
        """Backward-compatible alias for pe_optical_comm_energy_J."""
        return self.pe_optical_comm_energy_J

    @property
    def dvfs_ratio(self) -> float:
        """Global DVFS ratio (kept for backward compat; prefer eta_dvfs_pct)."""
        if self.total_compute_time_nominal_s <= 0:
            return 0.0
        return self.total_throttle_penalty_s / self.total_compute_time_nominal_s

    @property
    def eta_dvfs_pct(self) -> float:
        """η_dvfs: per-PE average throttlePenaltyRatio × 100%.

        Paper definition: (1/16) Σ_i (t_actual,i - t_nominal,i)/t_nominal,i × 100%
        From OMNeT++ .sca: throttlePenaltyRatio per TaskPE.
        """
        if not self.throttle_penalty_ratios:
            return 0.0
        return sum(self.throttle_penalty_ratios) / len(self.throttle_penalty_ratios) * 100.0

    @property
    def valid_for_cost(self) -> bool:
        """True only when the run has all scalar fields required by fitness."""
        return (
            self.run_ok
            and self.temperature_complete
            and self.pe_peak_temp_K > 0.0
            and self.makespan_s > 0.0
            and self.pe_optical_comm_energy_J > 0.0
        )


@dataclass
class CostReference:
    """Baseline denominators for normalized GA fitness."""

    peak_excess_K: float = 1.0
    sigma_T_K: float = 1.0
    N_hot: float = 1.0
    makespan_s: float = 1.0
    pe_optical_comm_energy_J: float = 1.0

    @property
    def total_energy_J(self) -> float:
        """Backward-compatible alias for older result readers."""
        return self.pe_optical_comm_energy_J
    eta_dvfs_pct: float = 1.0
    comm_cost: float = 1.0
    congestion_cost: float = 1.0
    load_imbalance: float = 1.0

    @staticmethod
    def positive(value: float, fallback: float = 1.0) -> float:
        return value if value > 1e-12 else fallback


class OmnetCostModel:
    """Cost model using OMNeT++ aggregate scalars + analytical terms.

    The four cost components mirror NormalizedCostModel's structure but
    replace per-task temperature lookups with aggregate simulation outputs.

    f_dvfs is scaled by num_mappable_tasks so that the weighted sum has
    comparable magnitude to NormalizedCostModel's per-task accumulation.
    """

    def __init__(
        self,
        graph,  # TaskGraph
        rows: int = 4,
        cols: int = 4,
        w_T: float = 1.0,
        w_H: float = 1.0,
        w_D: float = 2.0,
        w_L: float = 0.5,
        w_E: float = 0.0,
        w_sigma: float = 0.0,
        w_hot: float = 0.0,
        w_makespan: float = 0.0,
        w_congestion: float = 0.0,
        Tambient: float = 318.15,
        T_throttle: float = 327.15,
        reference: CostReference | None = None,
    ):
        self.graph = graph
        self.rows = rows
        self.cols = cols
        self.num_pes = rows * cols
        self.w_T = w_T
        self.w_H = w_H
        self.w_D = w_D
        self.w_L = w_L
        self.w_E = w_E
        self.w_sigma = w_sigma
        self.w_hot = w_hot
        self.w_makespan = w_makespan
        self.w_congestion = w_congestion
        self.Tamb = Tambient
        self.T_throttle = T_throttle
        self._delta_T = max(T_throttle - Tambient, 0.001)
        self.reference = reference

        self._max_edge_comm = self._compute_max_edge_comm()
        self._task_loads: dict[int, float] = self._compute_task_loads()

        self._hops_cache: dict[tuple[int, int], int] = {}

    # ------------------------------------------------------------------
    # Normalization denominators
    # ------------------------------------------------------------------
    def _compute_max_edge_comm(self) -> float:
        max_comm = 0.0
        for node in self.graph.tasks.values():
            for pred_id in node.predecessor_set:
                pred_node = self.graph.tasks.get(pred_id)
                if pred_node is not None and not pred_node.is_gb_task:
                    max_comm = max(max_comm, 6.0 * pred_node.output_data_size)
        return max(max_comm, 1.0)

    def _compute_task_loads(self) -> dict[int, float]:
        return {
            tid: max(node.compute_time_ns, 1.0)
            for tid, node in self.graph.tasks.items()
            if node.is_mappable
        }

    # ------------------------------------------------------------------
    # Manhattan distance
    # ------------------------------------------------------------------
    def hops(self, pe_a: int, pe_b: int) -> int:
        if pe_a == pe_b:
            return 0
        key = (pe_a, pe_b) if pe_a < pe_b else (pe_b, pe_a)
        if key not in self._hops_cache:
            r1, c1 = divmod(pe_a, self.cols)
            r2, c2 = divmod(pe_b, self.cols)
            self._hops_cache[key] = abs(r1 - r2) + abs(c1 - c2)
        return self._hops_cache[key]

    # ------------------------------------------------------------------
    # Normalized sub-terms
    # ------------------------------------------------------------------
    def f_thermal(self, scalars: OmnetScalars) -> float:
        """Peak temperature term.

        With a baseline reference, returns current peak excess / baseline peak
        excess. Without a reference, keeps the original threshold-normalized
        behavior for backward compatibility.
        """
        T_peak = scalars.pe_peak_temp_K
        if T_peak <= 0:
            return 0.0
        excess = max(0.0, T_peak - self.Tamb)
        if self.reference is not None:
            return excess / CostReference.positive(self.reference.peak_excess_K)
        return excess / self._delta_T

    def f_sigma(self, scalars: OmnetScalars) -> float:
        """Temperature uniformity term: sigma_T / baseline sigma_T.

        sigma_T is the time average of the spatial standard deviation across
        PEs at each sampled time point.
        """
        if scalars.sigma_T_K <= 0:
            return 0.0
        if self.reference is not None:
            return scalars.sigma_T_K / CostReference.positive(self.reference.sigma_T_K)
        return scalars.sigma_T_K / max(self._delta_T, 1e-12)

    def f_hot(self, scalars: OmnetScalars) -> float:
        """Hot-PE count term."""
        if scalars.N_hot <= 0:
            return 0.0
        if self.reference is not None and self.reference.N_hot > 0:
            return scalars.N_hot / self.reference.N_hot
        return scalars.N_hot / max(self.num_pes, 1)

    def f_makespan(self, scalars: OmnetScalars) -> float:
        """Makespan term: current makespan / baseline makespan."""
        if scalars.makespan_s <= 0:
            return 0.0
        if self.reference is not None:
            return scalars.makespan_s / CostReference.positive(self.reference.makespan_s)
        return 0.0

    def f_dvfs(self, scalars: OmnetScalars) -> float:
        """DVFS penalty term.

        With a baseline reference, returns current eta / baseline eta. If the
        baseline has no DVFS, any new DVFS is penalized as a percentage fraction.
        Without a reference, keeps the old per-task scaled term.
        """
        if self.reference is not None:
            if self.reference.eta_dvfs_pct > 1e-12:
                return scalars.eta_dvfs_pct / self.reference.eta_dvfs_pct
            return scalars.eta_dvfs_pct / 100.0
        return scalars.eta_dvfs_pct / 100.0 * self.graph.num_mappable

    def comm_cost(self, assignment: dict[int, int]) -> float:
        """Raw analytical communication: sum(hops * dataSize)."""
        total = 0.0
        for tid in self.graph.mappable_task_ids:
            node = self.graph.tasks[tid]
            pe = assignment.get(tid)
            if pe is None:
                continue
            for pred_id in node.predecessor_set:
                pred_node = self.graph.tasks.get(pred_id)
                if pred_node is None or pred_node.is_gb_task:
                    continue
                pred_pe = assignment.get(pred_id)
                if pred_pe is None:
                    continue
                total += self.hops(pred_pe, pe) * pred_node.output_data_size
        return total

    def f_comm(self, assignment: dict[int, int]) -> float:
        """Communication term."""
        raw = self.comm_cost(assignment)
        if self.reference is not None:
            if self.reference.comm_cost > 1e-12:
                return raw / self.reference.comm_cost
            return raw / self._max_edge_comm
        return raw / self._max_edge_comm

    def load_imbalance(self, assignment: dict[int, int]) -> float:
        """Raw load imbalance: variance of per-PE compute_time / ideal^2."""
        total = sum(self._task_loads.values())
        ideal = total / self.num_pes
        if ideal < 1e-9:
            return 0.0
        loads = [0.0] * self.num_pes
        for tid, pe in assignment.items():
            loads[pe] += self._task_loads.get(tid, 0.0)
        var = sum((l - ideal) ** 2 for l in loads) / self.num_pes
        return var / (ideal * ideal)

    def f_load(self, assignment: dict[int, int]) -> float:
        """Load imbalance term."""
        raw = self.load_imbalance(assignment)
        if self.reference is not None:
            if self.reference.load_imbalance > 1e-12:
                return raw / self.reference.load_imbalance
            return raw
        return raw

    def congestion_cost(self, assignment: dict[int, int]) -> float:
        """Raw communication density proxy: max bytes assigned to one mesh edge.

        This is a static approximation of wavelength contention. It routes each
        predecessor-successor communication on a deterministic XY path and
        accumulates bytes per physical edge.
        """
        edge_loads: dict[tuple[int, int], float] = {}

        def add_edge(a: int, b: int, bytes_: float) -> None:
            key = (a, b) if a < b else (b, a)
            edge_loads[key] = edge_loads.get(key, 0.0) + bytes_

        def add_xy_path(src_pe: int, dst_pe: int, bytes_: float) -> None:
            if src_pe == dst_pe:
                return
            r1, c1 = divmod(src_pe, self.cols)
            r2, c2 = divmod(dst_pe, self.cols)
            cur_r, cur_c = r1, c1
            step_c = 1 if c2 > cur_c else -1
            while cur_c != c2:
                nxt_c = cur_c + step_c
                add_edge(cur_r * self.cols + cur_c, cur_r * self.cols + nxt_c, bytes_)
                cur_c = nxt_c
            step_r = 1 if r2 > cur_r else -1
            while cur_r != r2:
                nxt_r = cur_r + step_r
                add_edge(cur_r * self.cols + cur_c, nxt_r * self.cols + cur_c, bytes_)
                cur_r = nxt_r

        for tid in self.graph.mappable_task_ids:
            node = self.graph.tasks[tid]
            dst_pe = assignment.get(tid)
            if dst_pe is None:
                continue
            for pred_id in node.predecessor_set:
                pred_node = self.graph.tasks.get(pred_id)
                if pred_node is None or pred_node.is_gb_task:
                    continue
                src_pe = assignment.get(pred_id)
                if src_pe is None:
                    continue
                add_xy_path(src_pe, dst_pe, pred_node.output_data_size)

        return max(edge_loads.values(), default=0.0)

    def f_congestion(self, assignment: dict[int, int]) -> float:
        """Communication density term."""
        raw = self.congestion_cost(assignment)
        if self.reference is not None:
            if self.reference.congestion_cost > 1e-12:
                return raw / self.reference.congestion_cost
            return raw / self._max_edge_comm
        return raw / self._max_edge_comm

    def f_energy(self, scalars: OmnetScalars) -> float:
        """Energy term.

        With a baseline reference, returns PE + optical communication energy
        normalized by the corresponding baseline value.
        Without a reference, keeps the old ideal-compute-energy overhead term.
        """
        E_pe_opt = scalars.pe_optical_comm_energy_J
        if E_pe_opt <= 0:
            return 0.0
        if self.reference is not None:
            return E_pe_opt / CostReference.positive(self.reference.pe_optical_comm_energy_J)

        E_ref = sum(
            self._task_loads.get(tid, 0.0) * 1e-9 * 2.5  # compute_time_s * powerCompute
            for tid in self.graph.mappable_task_ids
        )
        if E_ref <= 0:
            return 0.0
        return max(0.0, (E_pe_opt - E_ref) / E_ref)

    # ------------------------------------------------------------------
    # Total cost
    # ------------------------------------------------------------------
    def total_cost(
        self,
        assignment: dict[int, int],
        scalars: OmnetScalars,
    ) -> float:
        return (
            self.w_T * self.f_thermal(scalars)
            + self.w_sigma * self.f_sigma(scalars)
            + self.w_hot * self.f_hot(scalars)
            + self.w_makespan * self.f_makespan(scalars)
            + self.w_H * self.f_comm(assignment)
            + self.w_congestion * self.f_congestion(assignment)
            + self.w_D * self.f_dvfs(scalars)
            + self.w_L * self.f_load(assignment)
            + self.w_E * self.f_energy(scalars)
        )

    def make_reference(
        self,
        baseline_assignment: dict[int, int],
        baseline_scalars: OmnetScalars,
    ) -> CostReference:
        """Build baseline denominators for normalized fitness."""
        return CostReference(
            peak_excess_K=max(0.0, baseline_scalars.pe_peak_temp_K - self.Tamb),
            sigma_T_K=baseline_scalars.sigma_T_K,
            N_hot=float(baseline_scalars.N_hot),
            makespan_s=baseline_scalars.makespan_s,
            pe_optical_comm_energy_J=baseline_scalars.pe_optical_comm_energy_J,
            eta_dvfs_pct=baseline_scalars.eta_dvfs_pct,
            comm_cost=self.comm_cost(baseline_assignment),
            congestion_cost=self.congestion_cost(baseline_assignment),
            load_imbalance=self.load_imbalance(baseline_assignment),
        )

    def cost_breakdown(
        self,
        assignment: dict[int, int],
        scalars: OmnetScalars,
    ) -> dict[str, float]:
        f_T = self.f_thermal(scalars)
        f_sigma = self.f_sigma(scalars)
        f_hot = self.f_hot(scalars)
        f_makespan = self.f_makespan(scalars)
        f_H = self.f_comm(assignment)
        f_congestion = self.f_congestion(assignment)
        f_D = self.f_dvfs(scalars)
        f_L = self.f_load(assignment)
        f_E = self.f_energy(scalars) if self.w_E > 0 else 0.0
        return {
            "f_thermal": f_T,
            "f_sigma": f_sigma,
            "f_hot": f_hot,
            "f_makespan": f_makespan,
            "f_comm": f_H,
            "f_congestion": f_congestion,
            "f_dvfs": f_D,
            "f_load": f_L,
            "f_energy": f_E,
            "total_cost": (self.w_T * f_T + self.w_sigma * f_sigma
                           + self.w_hot * f_hot
                           + self.w_makespan * f_makespan
                           + self.w_H * f_H
                           + self.w_congestion * f_congestion
                           + self.w_D * f_D + self.w_L * f_L
                           + self.w_E * f_E),
            "raw_comm_cost": self.comm_cost(assignment),
            "raw_congestion_cost": self.congestion_cost(assignment),
            "raw_load_imbalance": self.load_imbalance(assignment),
            "T_max_K": scalars.pe_peak_temp_K,
            "sigma_T_K": scalars.sigma_T_K,
            "N_hot": scalars.N_hot,
            "eta_dvfs_pct": scalars.eta_dvfs_pct,
            "makespan_s": scalars.makespan_s,
            "pe_optical_comm_energy_J": scalars.pe_optical_comm_energy_J,
            "optical_budget_count": scalars.optical_budget_count,
            "optical_min_signal_margin_dB": scalars.optical_min_signal_margin_dB,
            "optical_min_snr_dB": scalars.optical_min_snr_dB,
            "optical_max_ber": scalars.optical_max_ber,
            "optical_max_temp_adjusted_loss_dB": scalars.optical_max_temp_adjusted_loss_dB,
            "optical_max_ring_detuning_nm": scalars.optical_max_ring_detuning_nm,
            "optical_max_path_tuning_power_mW": scalars.optical_max_path_tuning_power_mW,
            "optical_max_waveguide_crossing_loss_dB": scalars.optical_max_waveguide_crossing_loss_dB,
        }
