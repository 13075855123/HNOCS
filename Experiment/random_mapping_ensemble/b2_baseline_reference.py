"""B-2-compatible baseline extraction and cost-reference helpers."""

from __future__ import annotations

from dataclasses import dataclass

from mapping.omnet_cost_model import CostReference, OmnetCostModel, OmnetScalars, SimParams
from mapping.omnet_evaluator import OmnetEvaluator
from mapping.task_graph import TaskGraph


PE_OPTICAL_ENERGY_KEY = "E7_pe_optical_comm_energy_J"
LEGACY_TOTAL_ENERGY_KEY = "E7_total_energy_J"


@dataclass(frozen=True)
class CostWeights:
    """Cost weights matching the current B-2 defaults."""

    w_T: float = 1.0
    w_sigma: float = 1.0
    w_hot: float = 0.6
    w_makespan: float = 1.2
    w_H: float = 0.4
    w_congestion: float = 0.7
    w_D: float = 0.4
    w_L: float = 0.2
    w_E: float = 0.5
    w_peak: float = 0.0


@dataclass(frozen=True)
class OmnetRunConfig:
    """OMNeT++ execution paths and runtime settings."""

    omnet_bin: str = "D:/HNOCS/libhnocs.exe"
    omnet_ned_paths: str = "D:/HNOCS/src;D:/HNOCS/examples/task_driven"
    omnet_workdir: str = "D:/HNOCS/examples/task_driven"
    omnet_ini: str = "D:/HNOCS/examples/task_driven/omnetpp.ini"
    omnet_base_config: str = "ONoCGeneral"
    omnetpp_root: str = "D:/omnetpp/omnetpp-6.3.0"
    omnet_timeout_s: float = 60.0
    verbose: bool = False


@dataclass
class BaselineReference:
    """Original static mapping evaluation and normalized cost reference."""

    assignment: dict[int, int]
    scalars: OmnetScalars
    cost_reference: CostReference
    composite_cost: float
    cost_terms: dict[str, float]


def extract_original_assignment(graph: TaskGraph) -> dict[int, int]:
    """Extract Original static mapping with the same rule as B-2."""
    return {
        tid: node.assigned_pe
        for tid, node in graph.tasks.items()
        if not node.is_gb_task and node.assigned_pe >= 0
    }


def make_original_static_tasks_mappable(graph: TaskGraph) -> None:
    """Turn static non-GB tasks into B-2-style mappable tasks."""
    for node in graph.tasks.values():
        if not node.is_gb_task and node.assigned_pe >= 0:
            node.assigned_pe = -2
    graph._topo_order = None


def build_omnet_evaluator(config: OmnetRunConfig) -> OmnetEvaluator:
    """Create the same evaluator type used by B-2."""
    return OmnetEvaluator(
        omnet_bin=config.omnet_bin,
        ned_paths=config.omnet_ned_paths,
        work_dir=config.omnet_workdir,
        base_ini=config.omnet_ini,
        base_config=config.omnet_base_config,
        omnetpp_root=config.omnetpp_root,
        timeout_s=config.omnet_timeout_s,
        verbose=config.verbose,
    )


def build_cost_model(
    graph: TaskGraph,
    params: SimParams,
    weights: CostWeights,
    reference: CostReference | None = None,
) -> OmnetCostModel:
    """Create a B-2-compatible OMNeT++ cost model."""
    return OmnetCostModel(
        graph,
        rows=params.rows,
        cols=params.cols,
        w_T=weights.w_T,
        w_H=weights.w_H,
        w_D=weights.w_D,
        w_L=weights.w_L,
        w_E=weights.w_E,
        w_sigma=weights.w_sigma,
        w_hot=weights.w_hot,
        w_makespan=weights.w_makespan,
        w_congestion=weights.w_congestion,
        Tambient=params.Tambient,
        T_throttle=params.Tthrottle,
        reference=reference,
    )


def evaluate_original_reference(
    graph: TaskGraph,
    assignment: dict[int, int],
    evaluator: OmnetEvaluator,
    cost_model: OmnetCostModel,
    workload_name: str,
) -> BaselineReference:
    """Evaluate Original and construct the baseline-normalized reference."""
    scalars = evaluator.evaluate(graph, assignment)
    require_valid_scalars(workload_name, "Original", scalars)
    cost_reference = cost_model.make_reference(assignment, scalars)
    cost_model.reference = cost_reference
    composite_cost = cost_model.total_cost(assignment, scalars)
    cost_terms = cost_model.cost_breakdown(assignment, scalars)
    return BaselineReference(
        assignment=assignment,
        scalars=scalars,
        cost_reference=cost_reference,
        composite_cost=composite_cost,
        cost_terms=cost_terms,
    )


def require_valid_scalars(workload_name: str, stage: str, scalars: OmnetScalars) -> None:
    """Abort when an OMNeT++ result is not usable for composite cost."""
    if scalars.valid_for_cost:
        return
    reason = scalars.failure_reason or "unknown evaluator failure"
    raise RuntimeError(
        f"{workload_name} {stage} OMNeT++ run is invalid: {reason}. "
        f"makespan={scalars.makespan_s}, "
        f"T_max={scalars.pe_peak_temp_K}, "
        f"E_pe_opt={scalars.pe_optical_comm_energy_J}, "
        f"temperature_source={scalars.temperature_source}, "
        f"parsed_pe_count={scalars.parsed_pe_count}"
    )


def scalars_status(scalars: OmnetScalars) -> dict[str, object]:
    """Return the run_status payload used by B-2 metrics.json."""
    return {
        "run_ok": scalars.run_ok,
        "valid_for_cost": scalars.valid_for_cost,
        "failure_reason": scalars.failure_reason,
        "temperature_source": scalars.temperature_source,
        "temperature_complete": scalars.temperature_complete,
        "parsed_pe_count": scalars.parsed_pe_count,
        "parsed_temp_timepoints": scalars.parsed_temp_timepoints,
    }


def analytical_comm_cost(
    graph: TaskGraph,
    assignment: dict[int, int],
    rows: int,
    cols: int,
) -> float:
    """B-2 analytical C1 communication cost: hops * producer output bytes."""
    if rows <= 0 or cols <= 0:
        raise ValueError(f"invalid mesh dimensions: rows={rows}, cols={cols}")
    hops_cache: dict[tuple[int, int], int] = {}

    def hops(a: int, b: int) -> int:
        if a == b:
            return 0
        key = (a, b) if a < b else (b, a)
        if key not in hops_cache:
            r1, c1 = divmod(a, cols)
            r2, c2 = divmod(b, cols)
            hops_cache[key] = abs(r1 - r2) + abs(c1 - c2)
        return hops_cache[key]

    total = 0.0
    for tid in graph.mappable_task_ids:
        node = graph.tasks[tid]
        for pred_id in node.predecessor_set:
            pred_node = graph.tasks.get(pred_id)
            if pred_node is None or pred_node.is_gb_task:
                continue
            pred_pe = assignment.get(pred_id)
            this_pe = assignment.get(tid)
            if pred_pe is not None and this_pe is not None:
                total += hops(pred_pe, this_pe) * pred_node.output_data_size
    return total
