"""Thermal resistance proxy for the ThermalRC-LS baseline.

The functions here deliberately avoid OMNeT++ candidate evaluation and avoid
the proposed full composite objective.  OMNeT++ data may be used once to
calibrate an Original mapping temperature vector.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from mapping.task_graph import TaskGraph


@dataclass(frozen=True)
class RCObjectiveWeights:
    """Search weights for the lightweight ThermalRC-LS objective."""

    objective: str = "rc"
    w_tmax: float = 0.55
    w_sigma: float = 0.30
    w_hot: float = 0.10
    w_comm: float = 0.05

    def validate(self) -> None:
        if self.objective not in ("rc", "thermal_only"):
            raise ValueError(f"unsupported objective: {self.objective}")
        for name, value in asdict(self).items():
            if name == "objective":
                continue
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative, got {value}")
        if self.objective == "thermal_only" and abs(self.w_comm) > 1e-15:
            raise ValueError("thermal_only objective must have w_comm=0")


@dataclass(frozen=True)
class RCProxyConfig:
    rows: int = 4
    cols: int = 4
    Tambient: float = 318.15
    T_hot: float = 327.15
    power_idle: float = 0.3
    power_compute: float = 2.5
    leakage_base_power: float = 0.3
    ridge_lambda: float = 1e-3
    synthetic_self_R: float = 2.5
    synthetic_decay: float = 0.55

    @property
    def num_pes(self) -> int:
        return self.rows * self.cols

    def validate(self) -> None:
        if self.rows <= 0 or self.cols <= 0:
            raise ValueError(f"invalid mesh dimensions: rows={self.rows}, cols={self.cols}")
        if self.T_hot <= self.Tambient:
            raise ValueError("T_hot must be greater than Tambient")
        if self.power_compute <= self.power_idle:
            raise ValueError("power_compute must be greater than power_idle")
        if self.leakage_base_power < 0.0:
            raise ValueError("leakage_base_power must be non-negative")
        if self.ridge_lambda < 0.0:
            raise ValueError("ridge_lambda must be non-negative")
        if self.synthetic_self_R <= 0.0:
            raise ValueError("synthetic_self_R must be positive")
        if not 0.0 < self.synthetic_decay <= 1.0:
            raise ValueError("synthetic_decay must be in (0, 1]")


@dataclass(frozen=True)
class RCCalibration:
    """Metadata for the resistance matrix used by the proxy."""

    source: str
    distance_coefficients: list[float]
    ridge_lambda: float
    used_baseline_temperature: bool
    residual_rmse_K: float | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_power_proxy(graph: TaskGraph, config: RCProxyConfig) -> dict[int, float]:
    """Return per-task heat/power proxy values in W-like units.

    The dynamic part is proportional to compute_time_ns and normalized by the
    ideal compute time per PE, keeping values numerically close to the OMNeT++
    PE power parameters while preserving workload-specific imbalance.
    """
    config.validate()
    task_ids = graph.mappable_task_ids
    total_compute = sum(max(float(graph.tasks[tid].compute_time_ns), 0.0) for tid in task_ids)
    ideal_compute = total_compute / config.num_pes if total_compute > 0.0 else 1.0
    dynamic_power = config.power_compute - config.power_idle
    return {
        tid: dynamic_power * max(float(graph.tasks[tid].compute_time_ns), 0.0) / ideal_compute
        for tid in task_ids
    }


def base_power_vector(config: RCProxyConfig) -> list[float]:
    config.validate()
    return [config.leakage_base_power for _ in range(config.num_pes)]


def aggregate_power(
    assignment: dict[int, int],
    task_power: dict[int, float],
    config: RCProxyConfig,
    base_power: list[float] | None = None,
) -> list[float]:
    config.validate()
    power = list(base_power) if base_power is not None else base_power_vector(config)
    if len(power) != config.num_pes:
        raise ValueError(f"base power length must be {config.num_pes}, got {len(power)}")
    for tid, pe in assignment.items():
        if pe < 0 or pe >= config.num_pes:
            raise ValueError(f"task {tid} has invalid PE {pe}")
        power[pe] += task_power.get(tid, 0.0)
    return power


def temperature_proxy(
    resistance_matrix: list[list[float]],
    power: list[float],
    Tambient: float,
) -> list[float]:
    _validate_matrix(resistance_matrix, len(power))
    return [
        Tambient + sum(row[j] * power[j] for j in range(len(power)))
        for row in resistance_matrix
    ]


def communication_proxy(graph: TaskGraph, assignment: dict[int, int], cols: int) -> float:
    total = 0.0
    mappable = set(graph.mappable_task_ids)
    for src_id in graph.mappable_task_ids:
        src = graph.tasks[src_id]
        src_pe = assignment.get(src_id)
        if src_pe is None:
            continue
        for dst_id in src.successors:
            if dst_id == -1 or dst_id not in mappable:
                continue
            dst = graph.tasks.get(dst_id)
            if dst is None or dst.is_gb_task:
                continue
            dst_pe = assignment.get(dst_id)
            if dst_pe is None:
                continue
            total += manhattan(src_pe, dst_pe, cols) * src.output_data_size
    return total


def score_from_temp_and_comm(
    temps: list[float],
    comm_proxy: float | None,
    config: RCProxyConfig,
    weights: RCObjectiveWeights,
    denominators: dict[str, float],
) -> dict[str, Any]:
    weights.validate()
    tmax = max(temps) if temps else config.Tambient
    sigma = stddev(temps)
    hot_count = sum(1 for temp in temps if temp >= config.T_hot)
    f_tmax = tmax / _positive(denominators.get("Tmax_proxy", 0.0), config.Tambient)
    f_sigma = sigma / _positive(denominators.get("SigmaT_proxy", 0.0), 1.0)
    f_hot = hot_count / max(1.0, float(denominators.get("HotCount_proxy", 0.0)))
    score = (
        weights.w_tmax * f_tmax
        + weights.w_sigma * f_sigma
        + weights.w_hot * f_hot
    )
    payload = {
        "score": score,
        "Tmax_proxy": tmax,
        "SigmaT_proxy": sigma,
        "HotCount_proxy": hot_count,
        "f_tmax": f_tmax,
        "f_sigma": f_sigma,
        "f_hot": f_hot,
        "weights": asdict(weights),
        "temperatures_K": temps,
    }
    if weights.objective != "thermal_only":
        if comm_proxy is None:
            raise ValueError("rc objective requires comm_proxy")
        f_comm = comm_proxy / _positive(denominators.get("CommProxy", 0.0), 1.0)
        payload["CommProxy"] = comm_proxy
        payload["f_comm"] = f_comm
        payload["score"] = score + weights.w_comm * f_comm
    return payload


def proxy_score(
    graph: TaskGraph,
    assignment: dict[int, int],
    task_power: dict[int, float],
    resistance_matrix: list[list[float]],
    config: RCProxyConfig,
    weights: RCObjectiveWeights,
    denominators: dict[str, float] | None = None,
    base_power: list[float] | None = None,
) -> dict[str, Any]:
    power = aggregate_power(assignment, task_power, config, base_power=base_power)
    temps = temperature_proxy(resistance_matrix, power, config.Tambient)
    comm = None if weights.objective == "thermal_only" else communication_proxy(graph, assignment, config.cols)
    raw = raw_proxy_terms(temps, comm, config, weights.objective)
    den = denominators or raw
    score = score_from_temp_and_comm(temps, comm, config, weights, den)
    score["power_W"] = power
    return score


def raw_proxy_terms(
    temps: list[float],
    comm_proxy: float | None,
    config: RCProxyConfig,
    objective: str = "rc",
) -> dict[str, float]:
    terms = {
        "Tmax_proxy": max(temps) if temps else config.Tambient,
        "SigmaT_proxy": stddev(temps),
        "HotCount_proxy": float(sum(1 for temp in temps if temp >= config.T_hot)),
    }
    if objective != "thermal_only":
        terms["CommProxy"] = float(comm_proxy or 0.0)
    return terms


def calibrate_or_synthetic_R(
    config: RCProxyConfig,
    baseline_power: list[float],
    baseline_temperature: list[float] | None,
) -> tuple[list[list[float]], RCCalibration]:
    """Build an R matrix using one Original observation when available."""
    config.validate()
    if baseline_temperature and len(baseline_temperature) == config.num_pes:
        matrix, calibration = calibrate_distance_bin_R(
            config,
            baseline_power,
            baseline_temperature,
        )
        if calibration.source == "calibrated_distance_bins":
            return matrix, calibration

    matrix = synthetic_distance_decay_R(config)
    reason = "missing baseline temperature vector"
    if baseline_temperature is not None and len(baseline_temperature) != config.num_pes:
        reason = (
            f"baseline temperature length {len(baseline_temperature)} "
            f"does not match num_pes {config.num_pes}"
        )
    coeffs = distance_coefficients_from_matrix(matrix, config)
    return matrix, RCCalibration(
        source="synthetic_distance_decay",
        distance_coefficients=coeffs,
        ridge_lambda=config.ridge_lambda,
        used_baseline_temperature=False,
        residual_rmse_K=None,
        reason=reason,
    )


def calibrate_distance_bin_R(
    config: RCProxyConfig,
    baseline_power: list[float],
    baseline_temperature: list[float],
) -> tuple[list[list[float]], RCCalibration]:
    """Fit distance-bin coefficients with ridge regression.

    The single Original observation gives 16 equations, so this intentionally
    fits a low-dimensional symmetric model R_kl = beta[Manhattan(k,l)] rather
    than a full 16x16 matrix.
    """
    config.validate()
    if len(baseline_power) != config.num_pes:
        raise ValueError(f"baseline power length must be {config.num_pes}")
    if len(baseline_temperature) != config.num_pes:
        raise ValueError(f"baseline temperature length must be {config.num_pes}")

    max_dist = config.rows + config.cols - 2
    x_rows: list[list[float]] = []
    y: list[float] = []
    for pe in range(config.num_pes):
        row = [0.0 for _ in range(max_dist + 1)]
        for other in range(config.num_pes):
            row[manhattan(pe, other, config.cols)] += baseline_power[other]
        x_rows.append(row)
        y.append(max(0.0, float(baseline_temperature[pe]) - config.Tambient))

    beta = _ridge_solve(x_rows, y, config.ridge_lambda)
    beta = [max(0.0, value) for value in beta]
    if not beta or max(beta) <= 1e-12:
        matrix = synthetic_distance_decay_R(config)
        return matrix, RCCalibration(
            source="synthetic_distance_decay",
            distance_coefficients=distance_coefficients_from_matrix(matrix, config),
            ridge_lambda=config.ridge_lambda,
            used_baseline_temperature=False,
            reason="calibrated coefficients were all non-positive",
        )

    matrix = matrix_from_distance_coefficients(beta, config)
    pred = [
        sum(x_rows[i][d] * beta[d] for d in range(len(beta)))
        for i in range(config.num_pes)
    ]
    rmse = math.sqrt(sum((pred[i] - y[i]) ** 2 for i in range(config.num_pes)) / config.num_pes)
    return matrix, RCCalibration(
        source="calibrated_distance_bins",
        distance_coefficients=beta,
        ridge_lambda=config.ridge_lambda,
        used_baseline_temperature=True,
        residual_rmse_K=rmse,
    )


def synthetic_distance_decay_R(config: RCProxyConfig) -> list[list[float]]:
    config.validate()
    coeffs = [
        config.synthetic_self_R * (config.synthetic_decay ** dist)
        for dist in range(config.rows + config.cols - 1)
    ]
    return matrix_from_distance_coefficients(coeffs, config)


def matrix_from_distance_coefficients(
    coefficients: list[float],
    config: RCProxyConfig,
) -> list[list[float]]:
    return [
        [
            float(coefficients[manhattan(pe, other, config.cols)])
            for other in range(config.num_pes)
        ]
        for pe in range(config.num_pes)
    ]


def distance_coefficients_from_matrix(
    matrix: list[list[float]],
    config: RCProxyConfig,
) -> list[float]:
    _validate_matrix(matrix, config.num_pes)
    coeffs = []
    for dist in range(config.rows + config.cols - 1):
        vals = [
            matrix[pe][other]
            for pe in range(config.num_pes)
            for other in range(config.num_pes)
            if manhattan(pe, other, config.cols) == dist
        ]
        coeffs.append(sum(vals) / len(vals) if vals else 0.0)
    return coeffs


def resistance_matrix_rows(matrix: list[list[float]]) -> list[dict[str, float | int]]:
    rows = []
    for src, row in enumerate(matrix):
        for dst, value in enumerate(row):
            rows.append({"pe": src, "source_pe": dst, "R_K_per_W": value})
    return rows


def power_vector_rows(power: list[float], temps: list[float] | None = None) -> list[dict[str, float | int]]:
    rows = []
    for pe, value in enumerate(power):
        row: dict[str, float | int] = {"pe": pe, "P_proxy_W": value}
        if temps is not None and pe < len(temps):
            row["T_proxy_K"] = temps[pe]
        rows.append(row)
    return rows


def manhattan(pe_a: int, pe_b: int, cols: int) -> int:
    r1, c1 = divmod(pe_a, cols)
    r2, c2 = divmod(pe_b, cols)
    return abs(r1 - r2) + abs(c1 - c2)


def stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _positive(value: float, fallback: float) -> float:
    return value if value > 1e-12 else fallback


def _validate_matrix(matrix: list[list[float]], size: int) -> None:
    if len(matrix) != size:
        raise ValueError(f"matrix row count must be {size}, got {len(matrix)}")
    bad = [idx for idx, row in enumerate(matrix) if len(row) != size]
    if bad:
        raise ValueError(f"matrix rows must have length {size}; bad rows={bad}")


def _ridge_solve(x_rows: list[list[float]], y: list[float], ridge: float) -> list[float]:
    if not x_rows:
        return []
    n_cols = len(x_rows[0])
    xtx = [[0.0 for _ in range(n_cols)] for _ in range(n_cols)]
    xty = [0.0 for _ in range(n_cols)]
    for row, target in zip(x_rows, y):
        for i in range(n_cols):
            xty[i] += row[i] * target
            for j in range(n_cols):
                xtx[i][j] += row[i] * row[j]
    for i in range(n_cols):
        xtx[i][i] += ridge
    return _gaussian_solve(xtx, xty)


def _gaussian_solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [list(a[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) <= 1e-18:
            continue
        if pivot != col:
            aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= scale
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if abs(factor) <= 1e-18:
                continue
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]
