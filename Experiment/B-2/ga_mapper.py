"""
B-2: Genetic Algorithm for Thermal-Aware Task Mapping.

Each "individual" = a complete mapping (all tasks → PE assignment).
Evaluate = run OMNeT++ simulation → parse .sca/.vec → OmnetCostModel.total_cost().

Population evolves through tournament selection, uniform crossover,
per-task mutation, and elitism over 20-30 generations.

Cost function:
  baseline-normalized weighted sum of peak temperature, sigma_T, N_hot,
  makespan, energy, communication, congestion, DVFS, and load terms.
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from mapping.task_graph import TaskGraph
from mapping.omnet_cost_model import CostReference, SimParams

# Module-level path variables — set by run.py before parallel workers spawn.
# Windows defaults (D:/...) required because ProcessPoolExecutor on Windows
# uses 'spawn' and workers re-import this module with fresh globals.
_omnet_bin = "D:/HNOCS/libhnocs.exe"
_omnet_ned_paths = "D:/HNOCS/src;D:/HNOCS/examples/task_driven"
_omnet_work_dir = "D:/HNOCS/examples/task_driven"
_omnet_base_ini = "D:/HNOCS/examples/task_driven/omnetpp.ini"
_omnet_base_config = "ONoCGeneral"
_omnetpp_root = "D:/omnetpp/omnetpp-6.3.0"
_omnet_timeout_s = 60.0


# ============================================================================
# Configuration
# ============================================================================
@dataclass
class GAConfig:
    """GA hyperparameters, cost-function weights, and OMNeT++ paths."""

    # Population
    population_size: int = 50
    num_generations: int = 30
    elite_count: int = 2
    tournament_size: int = 3

    # Genetic operators
    crossover_rate: float = 0.8
    mutation_rate: float = 0.1

    # Cost function weights
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

    # Baseline denominators for normalized main-experiment fitness.
    cost_reference: CostReference | None = None

    # Parallel evaluation
    n_workers: int = 1

    # Early stopping
    patience: int = 10

    # Random seed (None = non-deterministic)
    seed: int | None = None

    # OMNeT++ paths
    omnet_bin: str = "/d/HNOCS/libhnocs_dbg.exe"
    omnet_ned_paths: str = "/d/HNOCS/src;/d/HNOCS/examples/task_driven"
    omnet_work_dir: str = "/d/HNOCS/examples/task_driven"
    omnet_base_ini: str = "/d/HNOCS/examples/task_driven/omnetpp.ini"
    omnet_base_config: str = "ONoCGeneral"
    omnetpp_root: str = "/d/omnetpp/omnetpp-6.3.0"
    omnet_timeout_s: float = 60.0
    omnet_verbose: bool = False


# ============================================================================
# Individual
# ============================================================================
@dataclass
class GAIndividual:
    """One member of the GA population."""

    chromosome: list[int]
    fitness: float = float("inf")
    omnet_info: dict | None = None

    def to_assignment(self, mappable_ids: list[int]) -> dict[int, int]:
        return dict(zip(mappable_ids, self.chromosome))


# ============================================================================
# Result
# ============================================================================
@dataclass
class GAResult:
    best_assignment: dict[int, int]
    best_fitness: float
    generation_history: list[dict] = field(default_factory=list)
    num_generations: int = 0
    converged: bool = False
    elapsed_time_s: float = 0.0


# ============================================================================
# Fitness evaluation (top-level, pickleable for parallel execution)
# ============================================================================
def evaluate_fitness(
    assignment: dict[int, int],
    graph: TaskGraph,
    w_T: float = 1.0,
    w_H: float = 1.0,
    w_D: float = 2.0,
    w_L: float = 0.5,
    w_E: float = 0.0,
    w_peak: float = 0.0,
    w_sigma: float = 0.0,
    w_hot: float = 0.0,
    w_makespan: float = 0.0,
    w_congestion: float = 0.0,
    cost_reference: CostReference | None = None,
    omnet_bin: str | None = None,
    omnet_ned_paths: str | None = None,
    omnet_work_dir: str | None = None,
    omnet_base_ini: str | None = None,
    omnet_base_config: str | None = None,
    omnetpp_root: str | None = None,
    omnet_timeout_s: float | None = None,
) -> tuple[float, dict]:
    """Pickleable OMNeT++ fitness evaluation.

    Windows ProcessPool workers use spawn and re-import this module, so path
    configuration must be passed explicitly instead of relying on parent globals.
    """
    from mapping.omnet_evaluator import OmnetEvaluator
    from mapping.omnet_cost_model import OmnetCostModel

    evaluator = OmnetEvaluator(
        omnet_bin=omnet_bin or _omnet_bin,
        ned_paths=omnet_ned_paths or _omnet_ned_paths,
        work_dir=omnet_work_dir or _omnet_work_dir,
        base_ini=omnet_base_ini or _omnet_base_ini,
        base_config=omnet_base_config or _omnet_base_config,
        omnetpp_root=omnetpp_root or _omnetpp_root,
        timeout_s=omnet_timeout_s if omnet_timeout_s is not None else _omnet_timeout_s,
        verbose=False,
    )
    cost_model = OmnetCostModel(
        graph, w_T=w_T, w_H=w_H, w_D=w_D, w_L=w_L, w_E=w_E,
        w_sigma=w_sigma, w_hot=w_hot, w_makespan=w_makespan,
        w_congestion=w_congestion, reference=cost_reference,
    )

    scalars = evaluator.evaluate(graph, assignment)

    if scalars.makespan_s <= 0 and not scalars.pe_peak_temp_K:
        return float("inf"), {}

    fitness = cost_model.total_cost(assignment, scalars)

    if scalars.pe_peak_temp_K and w_peak > 0:
        delta_T = cost_model.T_throttle - cost_model.Tamb
        fitness += w_peak * max(0.0, scalars.pe_peak_temp_K - cost_model.T_throttle) / max(delta_T, 0.001)

    return fitness, {
        "T_max_K": scalars.pe_peak_temp_K,
        "sigma_T_K": scalars.sigma_T_K,
        "N_hot": scalars.N_hot,
        "eta_dvfs_pct": scalars.eta_dvfs_pct,
        "makespan_s": scalars.makespan_s,
        "pe_total_energy_J": scalars.pe_total_energy_J,
        "soa_total_energy_J": scalars.soa_energy_J,
        "tuning_total_energy_J": scalars.tuning_energy_J,
        "laser_total_energy_J": scalars.laser_energy_J,
        "pe_optical_comm_energy_J": scalars.pe_optical_comm_energy_J,
        "optical_budget_count": scalars.optical_budget_count,
        "optical_min_signal_margin_dB": scalars.optical_min_signal_margin_dB,
        "optical_min_snr_dB": scalars.optical_min_snr_dB,
        "optical_max_ber": scalars.optical_max_ber,
        "optical_max_temp_adjusted_loss_dB": scalars.optical_max_temp_adjusted_loss_dB,
        "optical_max_ring_detuning_nm": scalars.optical_max_ring_detuning_nm,
        "optical_max_path_tuning_power_mW": scalars.optical_max_path_tuning_power_mW,
        "optical_max_waveguide_crossing_loss_dB": scalars.optical_max_waveguide_crossing_loss_dB,
        "cost_breakdown": cost_model.cost_breakdown(assignment, scalars),
    }


# ============================================================================
# GA Mapper
# ============================================================================
class GAMapper:
    """Genetic algorithm optimizer for thermal-aware task-to-PE mapping."""

    def __init__(
        self,
        graph: TaskGraph,
        params: SimParams | None = None,
        config: GAConfig | None = None,
        verbose: bool = False,
    ):
        self.graph = graph
        self.params = params or SimParams()
        self.config = config or GAConfig()
        self.verbose = verbose

        self._mappable_ids = graph.mappable_task_ids
        self._num_tasks = len(self._mappable_ids)
        self._num_pes = self.params.num_pes

        if self._num_tasks == 0:
            raise ValueError("Task graph has no mappable tasks (peId=-2)")

        self._rng = random.Random(self.config.seed)

    # ------------------------------------------------------------------
    # Chromosome construction
    # ------------------------------------------------------------------
    def _random_chromosome(self) -> list[int]:
        return [self._rng.randrange(self._num_pes) for _ in range(self._num_tasks)]

    def _seeded_chromosome(self, assignment: dict[int, int]) -> list[int]:
        return [assignment[tid] for tid in self._mappable_ids]

    # ------------------------------------------------------------------
    # Population initialization
    # ------------------------------------------------------------------
    def _initialize_population(
        self, seed_assignment: dict[int, int] | None = None,
    ) -> list[GAIndividual]:
        pop = []
        if seed_assignment:
            chromo = self._seeded_chromosome(seed_assignment)
            pop.append(GAIndividual(chromosome=list(chromo)))
        else:
            pop.append(GAIndividual(chromosome=self._random_chromosome()))

        for _ in range(len(pop), self.config.population_size):
            if self._rng.random() < 0.5:
                pop.append(GAIndividual(chromosome=self._random_chromosome()))
            else:
                base = self._rng.choice(pop).chromosome
                variant = list(base)
                for i in range(self._num_tasks):
                    if self._rng.random() < 0.2:
                        variant[i] = self._rng.randrange(self._num_pes)
                pop.append(GAIndividual(chromosome=variant))

        return pop

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def _evaluate_population(self, population: list[GAIndividual]) -> None:
        """Evaluate fitness for all individuals using OMNeT++ simulations."""
        cfg = self.config

        if cfg.n_workers <= 1:
            from mapping.omnet_evaluator import OmnetEvaluator
            from mapping.omnet_cost_model import OmnetCostModel

            evaluator = OmnetEvaluator(
                omnet_bin=cfg.omnet_bin,
                ned_paths=cfg.omnet_ned_paths,
                work_dir=cfg.omnet_work_dir,
                base_ini=cfg.omnet_base_ini,
                base_config=cfg.omnet_base_config,
                omnetpp_root=cfg.omnetpp_root,
                timeout_s=cfg.omnet_timeout_s,
                verbose=self.verbose,
            )
            cost_model = OmnetCostModel(
                self.graph,
                w_T=cfg.w_T, w_H=cfg.w_H, w_D=cfg.w_D, w_L=cfg.w_L,
                w_E=cfg.w_E, w_sigma=cfg.w_sigma, w_hot=cfg.w_hot,
                w_makespan=cfg.w_makespan, w_congestion=cfg.w_congestion,
                reference=cfg.cost_reference,
            )

            for ind in population:
                if ind.fitness < float("inf"):
                    continue
                assignment = ind.to_assignment(self._mappable_ids)
                scalars = evaluator.evaluate(self.graph, assignment)

                if scalars.makespan_s <= 0 and not scalars.pe_peak_temp_K:
                    ind.fitness = float("inf")
                    ind.omnet_info = {}
                    continue

                fit = cost_model.total_cost(assignment, scalars)
                if scalars.pe_peak_temp_K and cfg.w_peak > 0:
                    delta_T = cost_model.T_throttle - cost_model.Tamb
                    fit += cfg.w_peak * max(0.0, scalars.pe_peak_temp_K - cost_model.T_throttle) / max(delta_T, 0.001)

                ind.fitness = fit
                ind.omnet_info = {
                    "T_max_K": scalars.pe_peak_temp_K,
                    "sigma_T_K": scalars.sigma_T_K,
                    "N_hot": scalars.N_hot,
                    "eta_dvfs_pct": scalars.eta_dvfs_pct,
                    "makespan_s": scalars.makespan_s,
                    "pe_total_energy_J": scalars.pe_total_energy_J,
                    "pe_optical_comm_energy_J": scalars.pe_optical_comm_energy_J,
                    "optical_budget_count": scalars.optical_budget_count,
                    "optical_min_signal_margin_dB": scalars.optical_min_signal_margin_dB,
                    "optical_min_snr_dB": scalars.optical_min_snr_dB,
                    "optical_max_ber": scalars.optical_max_ber,
                    "optical_max_temp_adjusted_loss_dB": scalars.optical_max_temp_adjusted_loss_dB,
                    "optical_max_ring_detuning_nm": scalars.optical_max_ring_detuning_nm,
                    "optical_max_path_tuning_power_mW": scalars.optical_max_path_tuning_power_mW,
                    "optical_max_waveguide_crossing_loss_dB": scalars.optical_max_waveguide_crossing_loss_dB,
                    "cost_breakdown": cost_model.cost_breakdown(assignment, scalars),
                }
        else:
            pending: list[tuple[int, GAIndividual]] = []
            for idx, ind in enumerate(population):
                if ind.fitness >= float("inf"):
                    pending.append((idx, ind))

            if not pending:
                return

            with ProcessPoolExecutor(max_workers=cfg.n_workers) as ex:
                futures = {}
                for idx, ind in pending:
                    assignment = ind.to_assignment(self._mappable_ids)
                    fut = ex.submit(
                        evaluate_fitness,
                        assignment, self.graph,
                        cfg.w_T, cfg.w_H, cfg.w_D, cfg.w_L,
                        cfg.w_E, cfg.w_peak, cfg.w_sigma, cfg.w_hot,
                        cfg.w_makespan, cfg.w_congestion, cfg.cost_reference,
                        cfg.omnet_bin, cfg.omnet_ned_paths, cfg.omnet_work_dir,
                        cfg.omnet_base_ini, cfg.omnet_base_config,
                        cfg.omnetpp_root, cfg.omnet_timeout_s,
                    )
                    futures[fut] = idx

                for fut in as_completed(futures):
                    idx = futures[fut]
                    fit, info = fut.result()
                    population[idx].fitness = fit
                    population[idx].omnet_info = info

    # ------------------------------------------------------------------
    # Selection — tournament
    # ------------------------------------------------------------------
    def _tournament_select(self, population: list[GAIndividual]) -> GAIndividual:
        k = min(self.config.tournament_size, len(population))
        candidates = self._rng.sample(population, k)
        return min(candidates, key=lambda ind: ind.fitness)

    # ------------------------------------------------------------------
    # Crossover — uniform
    # ------------------------------------------------------------------
    def _uniform_crossover(
        self, parent1: GAIndividual, parent2: GAIndividual,
    ) -> list[int]:
        child = []
        for pe1, pe2 in zip(parent1.chromosome, parent2.chromosome):
            if self._rng.random() < 0.5:
                child.append(pe1)
            else:
                child.append(pe2)
        return child

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def _mutate(self, chromosome: list[int]) -> None:
        for i in range(len(chromosome)):
            if self._rng.random() < self.config.mutation_rate:
                chromosome[i] = self._rng.randrange(self._num_pes)

    # ------------------------------------------------------------------
    # Single generation step
    # ------------------------------------------------------------------
    def _next_generation(
        self, population: list[GAIndividual],
    ) -> list[GAIndividual]:
        cfg = self.config
        sorted_pop = sorted(population, key=lambda ind: ind.fitness)

        next_pop: list[GAIndividual] = []
        for i in range(min(cfg.elite_count, len(sorted_pop))):
            elite = sorted_pop[i]
            next_pop.append(GAIndividual(
                chromosome=list(elite.chromosome),
                fitness=elite.fitness,
                omnet_info=elite.omnet_info,
            ))

        while len(next_pop) < cfg.population_size:
            p1 = self._tournament_select(population)
            p2 = self._tournament_select(population)

            if self._rng.random() < cfg.crossover_rate:
                child_chromo = self._uniform_crossover(p1, p2)
            else:
                better = p1 if p1.fitness <= p2.fitness else p2
                child_chromo = list(better.chromosome)

            self._mutate(child_chromo)
            next_pop.append(GAIndividual(chromosome=child_chromo))

        return next_pop[:cfg.population_size]

    # ------------------------------------------------------------------
    # Main GA loop
    # ------------------------------------------------------------------
    def run(
        self, seed_assignment: dict[int, int] | None = None,
    ) -> GAResult:
        t0 = time.perf_counter()
        cfg = self.config

        population = self._initialize_population(seed_assignment)
        best_fitness = float("inf")
        best_assignment: dict[int, int] = {}
        stagnant = 0
        history: list[dict] = []

        for gen in range(1, cfg.num_generations + 1):
            self._evaluate_population(population)

            sorted_pop = sorted(population, key=lambda ind: ind.fitness)
            gen_best = sorted_pop[0]
            gen_avg = sum(ind.fitness for ind in population) / len(population)
            gen_worst = sorted_pop[-1].fitness

            gen_pe_max = (
                gen_best.omnet_info.get("T_max_K", self.params.Tambient)
                if gen_best.omnet_info else self.params.Tambient
            )

            history.append({
                "generation": gen,
                "best_fitness": gen_best.fitness,
                "avg_fitness": gen_avg,
                "worst_fitness": gen_worst,
                "pe_max_temp_K": gen_pe_max,
                "best_info": gen_best.omnet_info or {},
            })

            improved = gen_best.fitness < best_fitness
            if improved:
                best_fitness = gen_best.fitness
                best_assignment = gen_best.to_assignment(self._mappable_ids)
                stagnant = 0
            else:
                stagnant += 1

            if self.verbose:
                tag = " *" if improved else ""
                print(f"  Gen {gen:3d}: best={gen_best.fitness:.4f}  "
                      f"avg={gen_avg:.4f}  pe_max={gen_pe_max - 273.15:.1f}C{tag}")

            if stagnant >= cfg.patience and gen > cfg.patience:
                if self.verbose:
                    print(f"  Converged at generation {gen} "
                          f"(no improvement for {cfg.patience} generations)")
                elapsed = time.perf_counter() - t0
                return GAResult(
                    best_assignment=best_assignment,
                    best_fitness=best_fitness,
                    generation_history=history,
                    num_generations=gen,
                    converged=True,
                    elapsed_time_s=elapsed,
                )

            if gen < cfg.num_generations:
                population = self._next_generation(population)

        elapsed = time.perf_counter() - t0
        return GAResult(
            best_assignment=best_assignment,
            best_fitness=best_fitness,
            generation_history=history,
            num_generations=len(history),
            converged=stagnant >= cfg.patience,
            elapsed_time_s=elapsed,
        )
