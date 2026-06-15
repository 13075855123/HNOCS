"""B-2-compatible grouped metrics schema for baseline experiments."""

from __future__ import annotations

from mapping.omnet_cost_model import OmnetCostModel, OmnetScalars, SimParams
from mapping.task_graph import TaskGraph

from b2_baseline_reference import (
    PE_OPTICAL_ENERGY_KEY,
    analytical_comm_cost,
    scalars_status,
)


def grouped_metrics(
    graph: TaskGraph,
    assignment: dict[int, int],
    scalars: OmnetScalars,
    cost_model: OmnetCostModel,
    params: SimParams,
    baseline_makespan_s: float | None = None,
) -> dict[str, object]:
    """Wrap one evaluated mapping in the same section layout as B-2."""
    composite_cost = cost_model.total_cost(assignment, scalars)
    cost_terms = cost_model.cost_breakdown(assignment, scalars)
    c1 = analytical_comm_cost(graph, assignment, params.rows, params.cols)

    performance: dict[str, float] = {
        "P1_makespan_s": scalars.makespan_s,
        "P3_dvfs_penalty_pct": scalars.eta_dvfs_pct,
    }
    if baseline_makespan_s and baseline_makespan_s > 0 and scalars.makespan_s > 0:
        performance["P2_speedup"] = baseline_makespan_s / scalars.makespan_s

    return {
        "thermal": {
            "T1_pe_peak_temp_K": scalars.pe_peak_temp_K,
            "T3_temp_std_K": scalars.sigma_T_K,
            "T5_over_throttle_count": scalars.N_hot,
        },
        "performance": performance,
        "communication": {
            "C1_total_comm_cost": c1,
        },
        "optical": {
            "O1_budget_count": scalars.optical_budget_count,
            "O2_min_signal_margin_dB": scalars.optical_min_signal_margin_dB,
            "O3_min_snr_dB": scalars.optical_min_snr_dB,
            "O4_max_ber": scalars.optical_max_ber,
            "O5_max_temp_adjusted_loss_dB": scalars.optical_max_temp_adjusted_loss_dB,
            "O6_max_ring_detuning_nm": scalars.optical_max_ring_detuning_nm,
            "O7_max_path_tuning_power_mW": scalars.optical_max_path_tuning_power_mW,
            "O8_max_waveguide_crossing_loss_dB": scalars.optical_max_waveguide_crossing_loss_dB,
        },
        "energy": {
            "E1_pe_total_energy_J": scalars.pe_total_energy_J,
            "E4_soa_energy_J": scalars.soa_energy_J,
            "E5_tuning_energy_J": scalars.tuning_energy_J,
            "E6_laser_energy_J": scalars.laser_energy_J,
            PE_OPTICAL_ENERGY_KEY: scalars.pe_optical_comm_energy_J,
        },
        "tradeoff": {
            "TR2_composite_cost": composite_cost,
            "cost_terms": cost_terms,
        },
        "run_status": scalars_status(scalars),
    }

