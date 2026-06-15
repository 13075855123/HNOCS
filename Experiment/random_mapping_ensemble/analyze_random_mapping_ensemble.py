"""Aggregate Random Mapping Ensemble outputs and compare with B-2-v4 GA."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, stdev


BENCHMARKS = ("gemm", "mpeg4", "vopd", "hnn")
SELECTED_KEYS = (
    ("original", "Original"),
    ("random_best", "RandomBest"),
    ("random_p10", "RandomP10"),
    ("random_median", "RandomMedian"),
    ("random_p90", "RandomP90"),
)
PE_OPTICAL_ENERGY_KEY = "E7_pe_optical_comm_energy_J"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build Random Mapping Ensemble aggregate tables and B-2-v4 comparison"
    )
    parser.add_argument("--random-root", default="out/random-mapping-ensemble-v2")
    parser.add_argument("--b2-root", default="out/B-2-v4")
    parser.add_argument("--benchmarks", default="gemm,mpeg4,vopd,hnn")
    parser.add_argument("--configured-random-n", type=int, default=3000)
    args = parser.parse_args(argv)

    random_root = Path(args.random_root)
    b2_root = Path(args.b2_root)
    benchmarks = [item.strip().lower() for item in args.benchmarks.split(",") if item.strip()]

    random_runs = []
    aggregate_rows = []
    compare_rows = []
    validity_rows = []

    for benchmark in benchmarks:
        random_payload = _read_json(random_root / benchmark / "random" / "metrics.json")
        sample_rows = _read_csv(random_root / benchmark / "random" / "samples.csv")
        random_runs.append(_run_summary_row(benchmark, random_payload))
        aggregate_rows.extend(_aggregate_metric_rows(benchmark, random_payload))
        validity_rows.extend(_validity_rows(benchmark, sample_rows))
        compare_rows.append(_compare_row(
            benchmark,
            random_payload,
            sample_rows,
            _load_ga_runs(b2_root, benchmark),
            configured_random_n=args.configured_random_n,
        ))

    _write_json_csv(random_root / "runs_summary", random_runs)
    _write_json_csv(random_root / "aggregate_summary", aggregate_rows)
    _write_json_csv(random_root / "compare_with_B-2-v4", compare_rows)
    _write_csv(random_root / "validity_report.csv", validity_rows)

    analysis_md = _analysis_markdown(compare_rows, aggregate_rows, random_runs)
    (random_root / "compare_with_B-2-v4.md").write_text(analysis_md, encoding="utf-8")
    (random_root / "random_v2_analysis.md").write_text(analysis_md, encoding="utf-8")
    return 0


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_json_csv(stem: Path, rows: list[dict[str, object]]) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    (stem.with_suffix(".json")).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    _write_csv(stem.with_suffix(".csv"), rows)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _run_summary_row(benchmark: str, payload: dict) -> dict[str, object]:
    status = payload.get("run_status", {})
    selection = payload.get("selection", {})
    config = payload.get("config", {})
    return {
        "benchmark": benchmark,
        "random_n": status.get("n_requested", config.get("random_n", "")),
        "seed_base": config.get("seed_base", ""),
        "workers": config.get("workers", ""),
        "n_valid": status.get("n_valid", ""),
        "n_invalid": status.get("n_invalid", ""),
        "original_cost": _cost(payload.get("original", {})),
        "random_best_cost": _selected_cost(selection, "RandomBest"),
        "random_median_cost": _selected_cost(selection, "RandomMedian"),
        "random_p10_cost": _selected_cost(selection, "RandomP10"),
        "random_p90_cost": _selected_cost(selection, "RandomP90"),
        "elapsed_s": status.get("elapsed_s", ""),
    }


def _aggregate_metric_rows(benchmark: str, payload: dict) -> list[dict[str, object]]:
    status = payload.get("run_status", {})
    rows = []
    for key, label in SELECTED_KEYS:
        metrics = payload.get(key, {})
        rows.append({
            "benchmark": benchmark.upper(),
            "mapping_kind": label,
            "requested_samples": status.get("n_requested", ""),
            "valid_samples": status.get("n_valid", ""),
            "invalid_samples": status.get("n_invalid", ""),
            "TR2_composite_cost": _cost(metrics),
            "T_max_C": _metric(metrics, "thermal", "T1_pe_peak_temp_K") - 273.15,
            "sigma_T_K": _metric(metrics, "thermal", "T3_temp_std_K"),
            "N_hot": _metric(metrics, "thermal", "T5_over_throttle_count"),
            "makespan_us": _metric(metrics, "performance", "P1_makespan_s") * 1e6,
            "DVFS_penalty_pct": _metric(metrics, "performance", "P3_dvfs_penalty_pct"),
            "comm_cost": _metric(metrics, "communication", "C1_total_comm_cost"),
            "congestion_proxy": _cost_term(metrics, "raw_congestion_cost"),
            "load_imbalance": _cost_term(metrics, "raw_load_imbalance"),
            "total_PE_optical_energy_mJ": _energy(metrics) * 1e3,
            "run_ok": metrics.get("run_status", {}).get("run_ok", ""),
            "valid_for_cost": metrics.get("run_status", {}).get("valid_for_cost", ""),
            "temperature_source": metrics.get("run_status", {}).get("temperature_source", ""),
            "parsed_pe_count": metrics.get("run_status", {}).get("parsed_pe_count", ""),
        })
    return rows


def _validity_rows(benchmark: str, sample_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    rows = []
    for row in sample_rows:
        tmax = _float(row.get("T1_pe_peak_temp_K", "nan"))
        makespan = _float(row.get("P1_makespan_s", "nan"))
        energy = _float(row.get("E7_pe_optical_comm_energy_J", "nan"))
        cost = _float(row.get("TR2_composite_cost", "nan"))
        valid = _truthy(row.get("valid_for_cost"))
        run_ok = _truthy(row.get("run_ok"))
        validity_notes = []
        if not run_ok:
            validity_notes.append("run_ok=false")
        if not valid:
            validity_notes.append("valid_for_cost=false")
        if math.isfinite(tmax) and abs((tmax - 273.15) - (-273.1)) < 0.2:
            validity_notes.append("T_max=-273.1C")
        if math.isfinite(makespan) and makespan == 0:
            validity_notes.append("makespan=0")
        if math.isfinite(energy) and energy == 0:
            validity_notes.append("energy=0")
        rows.append({
            "benchmark": benchmark.upper(),
            "sample_id": row.get("sample_id", ""),
            "sample_seed": row.get("sample_seed", ""),
            "run_ok": run_ok,
            "valid_for_cost": valid,
            "failure_reason": row.get("failure_reason", ""),
            "TR2_composite_cost": cost if math.isfinite(cost) else "",
            "T_max_C": tmax - 273.15 if math.isfinite(tmax) else "",
            "makespan_s": makespan if math.isfinite(makespan) else "",
            "total_PE_optical_energy_J": energy if math.isfinite(energy) else "",
            "temperature_source": row.get("temperature_source", ""),
            "parsed_pe_count": row.get("parsed_pe_count", ""),
            "mapping_csv": row.get("mapping_csv", ""),
            "validity_notes": "; ".join(validity_notes),
        })
    return rows


def _load_ga_runs(b2_root: Path, benchmark: str) -> list[dict[str, object]]:
    runs = []
    for metrics_path in sorted(b2_root.glob(f"seed_*/gen_60/{benchmark}/metrics.json")):
        payload = _read_json(metrics_path)
        history_path = metrics_path.parent / "history.json"
        history = _read_json(history_path) if history_path.exists() else []
        config = payload.get("config", {})
        pop = int(config.get("population_size", 50))
        elite = int(config.get("elite_count", 2))
        actual_generations = int(payload.get("b2_generations", len(history)))
        effective_evals = pop + max(0, actual_generations - 1) * max(0, pop - elite)
        best_fitness_values = [
            _float(item.get("best_fitness", "nan"))
            for item in history
            if isinstance(item, dict)
        ]
        runs.append({
            "benchmark": benchmark.upper(),
            "seed": config.get("seed", metrics_path.parts[-4].replace("seed_", "")),
            "cost": _cost(payload.get("b2", {})),
            "baseline_cost": _cost(payload.get("baseline", {})),
            "actual_generations": actual_generations,
            "configured_generations": config.get("num_generations", ""),
            "population_size": pop,
            "elite_count": elite,
            "effective_candidate_evals": effective_evals,
            "history_all_best_fitness_infinite": (
                bool(best_fitness_values)
                and all(not math.isfinite(value) for value in best_fitness_values)
            ),
        })
    if not runs:
        raise FileNotFoundError(f"no B-2-v4 metrics found for {benchmark} under {b2_root}")
    return runs


def _compare_row(
    benchmark: str,
    random_payload: dict,
    sample_rows: list[dict[str, str]],
    ga_runs: list[dict[str, object]],
    configured_random_n: int,
) -> dict[str, object]:
    ga_costs = [float(run["cost"]) for run in ga_runs if math.isfinite(float(run["cost"]))]
    random_costs = [
        _float(row.get("TR2_composite_cost", "nan"))
        for row in sample_rows
        if _truthy(row.get("valid_for_cost"))
    ]
    random_costs = [value for value in random_costs if math.isfinite(value)]

    status = random_payload.get("run_status", {})
    selection = random_payload.get("selection", {})
    ga_mean = mean(ga_costs)
    ga_std = stdev(ga_costs) if len(ga_costs) > 1 else 0.0
    ga_ci = _tcrit95(len(ga_costs)) * ga_std / math.sqrt(len(ga_costs)) if len(ga_costs) > 1 else 0.0
    ga_best = min(ga_costs)
    ga_worst = max(ga_costs)
    random_best = min(random_costs) if random_costs else math.nan
    random_median = _selected_cost(selection, "RandomMedian")
    ga_eval_values = [int(run["effective_candidate_evals"]) for run in ga_runs]
    return {
        "benchmark": benchmark.upper(),
        "requested_samples": status.get("n_requested", configured_random_n),
        "valid_samples": status.get("n_valid", len(random_costs)),
        "invalid_samples": status.get("n_invalid", ""),
        "original_cost": _cost(random_payload.get("original", {})),
        "random_best_cost": _selected_cost(selection, "RandomBest"),
        "random_p10_cost": _selected_cost(selection, "RandomP10"),
        "random_median_cost": random_median,
        "random_p90_cost": _selected_cost(selection, "RandomP90"),
        "random_elapsed_s": status.get("elapsed_s", ""),
        "random_elapsed_min": _float(status.get("elapsed_s", "nan")) / 60.0,
        "ga_n": len(ga_costs),
        "ga_seeds": ",".join(str(run["seed"]) for run in ga_runs),
        "ga_cost_mean": ga_mean,
        "ga_cost_std": ga_std,
        "ga_cost_ci95_half": ga_ci,
        "ga_cost_best": ga_best,
        "ga_cost_worst": ga_worst,
        "ga_configured_budget_pop_x_gen": configured_random_n,
        "ga_effective_candidate_evals_min": min(ga_eval_values),
        "ga_effective_candidate_evals_mean": mean(ga_eval_values),
        "ga_effective_candidate_evals_max": max(ga_eval_values),
        "ga_mean_advantage_over_random_best_pct": _advantage(random_best, ga_mean),
        "ga_mean_advantage_over_random_median_pct": _advantage(random_median, ga_mean),
        "ga_worst_advantage_over_random_best_pct": _advantage(random_best, ga_worst),
        "ga_worst_still_better_than_random_best": ga_worst < random_best,
        "random_samples_cost_le_ga_mean": sum(1 for cost in random_costs if cost <= ga_mean),
        "random_samples_cost_le_ga_worst": sum(1 for cost in random_costs if cost <= ga_worst),
        "random_samples_cost_le_ga_best": sum(1 for cost in random_costs if cost <= ga_best),
        "random_best_beats_ga_mean": random_best <= ga_mean,
        "random_best_beats_ga_best": random_best <= ga_best,
    }


def _analysis_markdown(
    compare_rows: list[dict[str, object]],
    aggregate_rows: list[dict[str, object]],
    run_rows: list[dict[str, object]],
) -> str:
    lines = [
        "# Random Mapping Ensemble v2 与 B-2-v4 对比",
        "",
        "数据来源：`D:\\HNOCS\\out\\random-mapping-ensemble-v2` 和 `D:\\HNOCS\\out\\B-2-v4`。Random v2 对 GEMM、MPEG4、HNN 请求 3000 个 random mappings；VOPD 因原始 3000 attempts 中存在 timeout invalid samples，已按 seed 顺序追加至 3000 个有效样本。每个 mapping 均经过 OMNeT++ evaluator 和 baseline-normalized composite cost 计算。所有指标均从 `metrics.json` / `samples.csv` 的结构化字段读取，未解析 `summary.txt`。",
        "",
        "## 1. 预算口径",
        "",
        "- B-2-v4 配置为 population=50、generations=60，即常用配置预算 3000 candidate slots/seed。",
        "- 按 GA 代码实际新个体评估计算，精英保留使满 60 代为 50 + 48*(60-1) = 2882 次 candidate evaluation；early stopping 会进一步降低实际评估次数。",
        "- Random v2 以 3000 个有效 random mappings/workload 作为公平对比口径。VOPD 为补足 timeout invalid samples，正式合并后的 requested attempts 高于 3000，但 valid samples 为 3000。",
        "",
        "## 2. 运行耗时与有效性",
        "",
        "| Workload | Requested | Valid | Invalid | Workers | Elapsed(min) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    total_elapsed = 0.0
    for row in run_rows:
        elapsed_s = _float(row.get("elapsed_s", "nan"))
        if math.isfinite(elapsed_s):
            total_elapsed += elapsed_s
        lines.append(
            f"| {str(row['benchmark']).upper()} | {row['random_n']} | {row['n_valid']} | "
            f"{row['n_invalid']} | {row['workers']} | {_fmt(elapsed_s / 60.0)} |"
        )

    lines.extend([
        f"",
        f"总墙钟耗时约 {_fmt(total_elapsed / 60.0)} min。按 random v1 串行耗时外推，3000 samples/workload 约为 362 min；本次用 8 workers 执行。VOPD 的 invalid samples 均记录在 `vopd/random/invalid_samples.csv`，失败原因主要为 `timeout after 60.0s`，另有少量解析后仍缺失必要字段的无效样本。",
        "",
        "## 3. Cost 对比",
        "",
        "| Workload | Random valid/total | Random best | Random p10 | Random median | Random p90 | GA mean±std | 95% CI half | GA best/worst | GA mean advantage vs random best | GA worst better? | Random <= GA mean/worst/best |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in compare_rows:
        valid_total = f"{row['valid_samples']}/{row['requested_samples']}"
        ga_mean_std = f"{_fmt(row['ga_cost_mean'])}±{_fmt(row['ga_cost_std'])}"
        ga_best_worst = f"{_fmt(row['ga_cost_best'])}/{_fmt(row['ga_cost_worst'])}"
        le_counts = (
            f"{row['random_samples_cost_le_ga_mean']}/"
            f"{row['random_samples_cost_le_ga_worst']}/"
            f"{row['random_samples_cost_le_ga_best']}"
        )
        lines.append(
            f"| {row['benchmark']} | {valid_total} | {_fmt(row['random_best_cost'])} | "
            f"{_fmt(row['random_p10_cost'])} | {_fmt(row['random_median_cost'])} | "
            f"{_fmt(row['random_p90_cost'])} | {ga_mean_std} | "
            f"{_fmt(row['ga_cost_ci95_half'])} | {ga_best_worst} | "
            f"{_fmt(row['ga_mean_advantage_over_random_best_pct'])}% | "
            f"{row['ga_worst_still_better_than_random_best']} | {le_counts} |"
        )

    lines.extend([
        "",
        "## 4. 九项指标代表样本",
        "",
        "| Workload | Mapping | Cost | T_max(C) | sigma_T(K) | N_hot | makespan(us) | DVFS(%) | comm | congestion | load imbalance | PE+opt energy(mJ) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in aggregate_rows:
        lines.append(
            f"| {row['benchmark']} | {row['mapping_kind']} | {_fmt(row['TR2_composite_cost'])} | "
            f"{_fmt(row['T_max_C'])} | {_fmt(row['sigma_T_K'])} | {_fmt(row['N_hot'], 0)} | "
            f"{_fmt(row['makespan_us'])} | {_fmt(row['DVFS_penalty_pct'])} | "
            f"{_fmt(row['comm_cost'], 0)} | {_fmt(row['congestion_proxy'], 0)} | "
            f"{_fmt(row['load_imbalance'])} | {_fmt(row['total_PE_optical_energy_mJ'])} |"
        )

    lines.extend(["", "## 5. 论文可用结论", ""])
    for row in compare_rows:
        if row["random_best_beats_ga_best"]:
            conclusion = "random best 已达到或超过 GA best，需要在论文中作为例外讨论。"
        elif row["random_best_beats_ga_mean"]:
            conclusion = "random best 接近或优于 GA mean，但未超过 GA best，说明该 workload 存在随机命中较优区域的可能。"
        elif row["ga_worst_still_better_than_random_best"]:
            conclusion = "10 个 GA seed 的最差结果仍优于 random best，支持 GA 不是随机重映射偶然收益。"
        else:
            conclusion = "GA mean 优于 random best，但存在 GA worst 不优于 random best 的重叠区，需谨慎表述稳定性。"
        lines.append(f"- {row['benchmark']}：{conclusion}")

    lines.extend([
        "",
        "解释口径：若某 workload 的 random best 接近 GA，优先从搜索空间偶然命中、目标权重偏向通信/拥塞项、以及 workload 负载/通信结构是否容易由纯随机打散热点来解释；不要把 random 结果解释为具备稳定优化能力，除非分布统计也支持。",
        "",
    ])
    return "\n".join(lines)


def _cost(metrics: object) -> float:
    if not isinstance(metrics, dict):
        return math.nan
    return _float(metrics.get("tradeoff", {}).get("TR2_composite_cost", "nan"))


def _metric(metrics: dict, section: str, key: str) -> float:
    return _float(metrics.get(section, {}).get(key, "nan"))


def _cost_term(metrics: dict, key: str) -> float:
    return _float(metrics.get("tradeoff", {}).get("cost_terms", {}).get(key, "nan"))


def _energy(metrics: dict) -> float:
    energy = metrics.get("energy", {})
    value = _float(energy.get(PE_OPTICAL_ENERGY_KEY, "nan"))
    if not math.isfinite(value):
        value = _float(energy.get("E7_total_energy_J", "nan"))
    return value


def _selected_cost(selection: dict, label: str) -> float:
    return _float(selection.get(label, {}).get("TR2_composite_cost", "nan"))


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _advantage(reference_cost: float, ga_cost: float) -> float:
    if not math.isfinite(reference_cost) or reference_cost == 0:
        return math.nan
    return (reference_cost - ga_cost) / reference_cost * 100.0


def _tcrit95(n: int) -> float:
    table = {
        2: 12.706,
        3: 4.303,
        4: 3.182,
        5: 2.776,
        6: 2.571,
        7: 2.447,
        8: 2.365,
        9: 2.306,
        10: 2.262,
        11: 2.228,
        12: 2.201,
        13: 2.179,
        14: 2.160,
        15: 2.145,
        16: 2.131,
        17: 2.120,
        18: 2.110,
        19: 2.101,
        20: 2.093,
    }
    return table.get(n, 1.96)


def _fmt(value: object, digits: int = 4) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    if digits == 0:
        return f"{number:.0f}"
    return f"{number:.{digits}f}"


if __name__ == "__main__":
    raise SystemExit(main())
