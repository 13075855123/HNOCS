# Full-Objective 统一重算分析说明

本目录存放论文实验图表和表格可追溯使用的派生 CSV。所有文件均基于已有实验结果离线生成：没有重跑 OMNeT++，也没有修改任何原始实验结果目录。

## 当前论文口径

本目录已按新的论文口径重新生成：

- `ReferenceMapping`：initial/reference mapping，也就是 normalization reference；它不是 baseline method。
- `Full-GA`：本文主方法。
- 主文 baseline methods：`Thermal-SA-TAS` 和 `CommAware-Heuristic`。
- 消融方法：`thermal-only`、`comm-only`、`wout-thermal`、`wout-comm`。
- Random Mapping Ensemble：作为补充随机集合分析单独保留，不作为主文 baseline method。

因此，当前 CSV 不再使用旧的 `Original` 作为 baseline method，也不再使用 `original_*` 或 `baseline_score` 这类容易误读的列名。相关字段统一改为：

- `reference_*`：reference mapping 的数值。
- `method_*`：当前方法的数值。
- `delta_vs_reference`：当前方法相对 reference mapping 的差值。
- `relative_change_pct_vs_reference`：当前方法相对 reference mapping 的相对变化。

## 数据来源

所有输入结果均位于：

```text
D:\HNOCS\out\experimental results
```

本次分析读取以下结果集：

- `B-2-v4`：主方法 full GA，seed `40-49`。
- `B-2-v4-ablation`：四组消融实验：
  - `thermal-only`
  - `comm-only`
  - `wout-thermal`
  - `wout-comm`
- `comm-aware-baseline-v1`：主文 baseline method 之一。
- `thermal-sa-tas-results\final`：主文 baseline method 之一。
- `random-mapping-ensemble-v2`：补充随机集合分析。

生成本目录的脚本为：

```text
D:\HNOCS\experiment\paper_analysis\rescore_full_objective_sources.py
```

## 为什么需要统一重算

消融实验使用了不同 objective 权重进行优化。因此，消融目录中原始保存的 `TR2_composite_cost` 只表示该消融自身 objective 下的 cost，不能直接与 full GA 的 `TR2_composite_cost` 横向比较。

本分析采用统一口径：对每个最终 mapping，使用其 raw metrics 和同 workload 的 baseline `config.cost_reference` 重新计算九项 normalized terms，然后套用 full GA 权重，得到可比较的 `full-objective comparable score`。

full GA 权重如下：

| Term | Weight |
|---|---:|
| `f_thermal` | 1.0 |
| `f_sigma` | 1.0 |
| `f_hot` | 0.6 |
| `f_makespan` | 1.2 |
| `f_comm` | 0.4 |
| `f_congestion` | 0.7 |
| `f_dvfs` | 0.4 |
| `f_load` | 0.2 |
| `f_energy` | 0.5 |

统一 score 公式为：

```text
full_score =
  1.0*f_thermal
+ 1.0*f_sigma
+ 0.6*f_hot
+ 1.2*f_makespan
+ 0.4*f_comm
+ 0.7*f_congestion
+ 0.4*f_dvfs
+ 0.2*f_load
+ 0.5*f_energy
```

为保证严谨性，九项 normalized terms 均从 raw metrics 和 `cost_reference` 重新计算，不直接复用已有 `cost_terms.f_*`。原因是部分消融实验中，被禁用的 objective 项可能在 `cost_terms` 中被写成 `0`，例如 `w_E=0` 时 `f_energy` 可能不是完整 normalized energy term。

## 文件说明

### 审计与溯源文件

- `manifest.csv`：本次分析发现并读取的 `metrics.json`、`history.json` 和 summary CSV 清单。
- `canonical_parser_schema.csv`：不同结果 schema 到统一字段的解析映射。
- `cost_reference_audit.csv`：检查所有方法和 workload 是否使用与 `B-2-v4` 一致的 normalization reference。
- `formula_validation_full_ga.csv`：验证 full GA 的重算 score 是否能精确复现原始 `TR2_composite_cost`。
- `validity_audit.csv`：每条 canonical run 的有效性检查结果。
- `spot_check_samples.csv`：人工抽查用的代表样本。

### Run-level 数据源

- `full_objective_rescore_runs.csv`：ReferenceMapping、Full-GA、消融、主文 baseline 和 Random 补充方法的统一 canonical run-level 总表。
- `ablation_vs_reference_full_objective_runs.csv`：四个消融实验相对 ReferenceMapping 的逐 seed 比较。
- `main_baseline_full_objective_runs.csv`：主文 baseline methods 相对 ReferenceMapping 的比较，仅包含 `Thermal-SA-TAS` 和 `CommAware-Heuristic`。
- `random_ensemble_full_objective_source.csv`：Random Mapping Ensemble 的补充分析 source，仅包含 `RandomBest`、`RandomMedian`、`RandomP10`、`RandomP90`。

### Summary 表

- `ablation_vs_reference_full_objective_summary.csv`：四个消融实验在统一 full objective 下的 mean/std/CI/min/max 汇总。
- `main_baseline_full_objective_summary.csv`：主文 baseline methods 的汇总。
- `random_ensemble_full_objective_summary.csv`：Random Mapping Ensemble 的补充汇总。

### 论文图表 source CSV

- `figure2_composite_cost_source.csv`：ReferenceMapping vs Full-GA 的 full-objective composite score 图的数据源。
- `figure3_nine_metric_grouped_source.csv`：Full-GA 相对 ReferenceMapping 的九项指标变化，按五类分组：
  - 热安全
  - 性能
  - 通信压力
  - 映射均衡
  - 能耗
- `figure4_baseline_and_ablation_source.csv`：Full-GA、四组消融、`Thermal-SA-TAS` 和 `CommAware-Heuristic` 的统一 full-objective 对比数据源。

注意：本目录目前只生成 source CSV，没有生成图像文件。

## 画图应使用的文件

正文图优先使用以下三个已经整理好的 source CSV：

| 图 | 使用文件 | 用途 |
|---|---|---|
| Figure 2 | `figure2_composite_cost_source.csv` | 绘制 ReferenceMapping vs Full-GA 的 full-objective composite score，表达主方法相对 normalization reference 的改善。 |
| Figure 3 | `figure3_nine_metric_grouped_source.csv` | 绘制 Full-GA 相对 ReferenceMapping 的九项指标变化。 |
| Figure 4 | `figure4_baseline_and_ablation_source.csv` | 绘制 Full-GA、四组消融、Thermal-SA-TAS 和 CommAware-Heuristic 的统一 full-objective 对比。 |

补充材料或扩展图可以使用以下文件：

- `ablation_vs_reference_full_objective_summary.csv`：画四组消融的 workload-level 均值、标准差和 CI。
- `ablation_vs_reference_full_objective_runs.csv`：画消融实验的逐 seed 点图、连线图或箱线图。
- `main_baseline_full_objective_summary.csv`：画主文 baseline methods 的汇总对比。
- `main_baseline_full_objective_runs.csv`：画主文 baseline methods 的 run-level 或 seed-level 对比。
- `random_ensemble_full_objective_source.csv`：画 Random Mapping Ensemble 的补充对比。
- `random_ensemble_full_objective_summary.csv`：画 Random Mapping Ensemble 的补充汇总。
- `full_objective_rescore_runs.csv`：需要自定义图或重新分组时使用的总表。

以下文件主要用于审计、复现和检查，不建议作为正式画图主数据源：

- `manifest.csv`
- `canonical_parser_schema.csv`
- `cost_reference_audit.csv`
- `formula_validation_full_ga.csv`
- `validity_audit.csv`
- `spot_check_samples.csv`

## 主文 baseline methods 的处理方式

当前主文 baseline methods 只包括：

- `Thermal-SA-TAS`
- `CommAware-Heuristic`

它们的比较文件为：

```text
main_baseline_full_objective_runs.csv
main_baseline_full_objective_summary.csv
```

`main_baseline_full_objective_runs.csv` 中共有 `44` 行：

- `Thermal-SA-TAS`：`40` 行，即 4 个 workload x 10 个 seed。
- `CommAware-Heuristic`：`4` 行，即每个 workload 1 行。

这些方法在 `figure4_baseline_and_ablation_source.csv` 中与 `Full-GA` 和四组消融一起展示。`ReferenceMapping` 不作为 baseline method bar 出现在 Figure 4 中。

## Random Mapping Ensemble 的处理方式

`random-mapping-ensemble-v2` 不作为主文 baseline method，而是作为补充随机集合分析单独保留。它没有把所有随机样本逐个放入正文图表，而是读取该目录中已经整理出的代表 mapping：

- `RandomBest`
- `RandomMedian`
- `RandomP10`
- `RandomP90`

读取路径如下：

```text
random-mapping-ensemble-v2\<workload>\original\metrics.json
random-mapping-ensemble-v2\<workload>\random\metrics.json
random-mapping-ensemble-v2\<workload>\random\selected\random_best\metrics.json
random-mapping-ensemble-v2\<workload>\random\selected\random_median\metrics.json
random-mapping-ensemble-v2\<workload>\random\selected\random_p10\metrics.json
random-mapping-ensemble-v2\<workload>\random\selected\random_p90\metrics.json
```

处理逻辑如下：

1. `random\selected\...` 下的四个代表 mapping 作为补充 random candidates 进入 `random_ensemble_full_objective_source.csv`。
2. `original\metrics.json` 和 `random\metrics.json` 用于提供同 workload 的 baseline `cost_reference` 和权重信息。
3. 由于 selected mapping 自身不带完整 `config.cost_reference`，脚本从同 workload 的 `random\metrics.json` 或 `original\metrics.json` 读取 reference。
4. 对每个 selected mapping 抽取 raw metrics，包括 `T_max`、`sigma_T`、`N_hot`、`makespan`、`DVFS`、`comm`、`congestion`、`load_imbalance` 和 `energy`。
5. 使用 full GA 权重重新计算 `full_objective_comparable_score`。
6. Random 结果不进入 `figure4_baseline_and_ablation_source.csv`，避免与主文 baseline methods 混淆。

输出行数如下：

| Method | 行数 | 说明 |
|---|---:|---|
| `RandomBest` | 4 | 每个 workload 1 行 |
| `RandomMedian` | 4 | 每个 workload 1 行 |
| `RandomP10` | 4 | 每个 workload 1 行 |
| `RandomP90` | 4 | 每个 workload 1 行 |

因此，Random baseline 不是 seed `40-49` 的 10 次统计结果，而是每个 workload 使用随机集合中已经选出的代表 mapping。对应 summary 中每个 Random 方法的 `n=1`，不应画成 10-seed 误差棒。

写作时需要明确：

- `RandomBest` 是 best-of-ensemble selected mapping，不是一次普通随机映射。
- `RandomMedian`、`RandomP10`、`RandomP90` 反映随机集合分布中的代表位置。
- 如果在补充材料中只放一个 random result，优先说明其选择规则；避免把 `RandomBest` 表述成一般随机方法的平均水平。

## 验证结果摘要

本次按新口径重新生成和检查结果如下：

- Canonical run rows：`348`
- Ablation-vs-reference comparison rows：`160`
- Main baseline comparison rows：`44`
- Random ensemble comparison rows：`16`
- Figure 2 source rows：`80`
- Figure 3 source rows：`360`
- Figure 4 source rows：`244`
- Full GA formula validation rows：`80`
- Full GA formula mismatches：`0`
- Maximum formula error：`0`
- Cost reference audit rows：`292`
- Cost reference mismatches：`0`
- Validity audit rows：`348`
- Invalid rows：`0`
- `history_all_best_fitness_infinite`：`0`

额外一致性检查：

- 旧文件 `ablation_full_objective_rescore_runs.csv`、`ablation_full_objective_rescore_summary.csv`、`baseline_full_objective_rescore_runs.csv`、`baseline_full_objective_rescore_summary.csv` 已删除。
- `figure4_baseline_and_ablation_source.csv` 仅包含：
  - `Full-GA`
  - `thermal-only`
  - `comm-only`
  - `wout-thermal`
  - `wout-comm`
  - `Thermal-SA-TAS`
  - `CommAware-Heuristic`
- Figure 4 不包含 `ReferenceMapping`，也不包含 `RandomBest/RandomMedian/RandomP10/RandomP90`。
- 新图表 source 和 summary 的二次复算 mismatch 为 `0`。

## 有效性检查规则

每条 run 采用以下规则检查：

- `run_ok` 不是 false。
- `valid_for_cost` 不是 false。
- `T_max` 为有限值，且不是无效哨兵值 `-273.1 C`。
- `makespan_s > 0`。
- `pe_optical_comm_energy_J > 0`。
- full-objective score 为有限值。
- GA 型 `history.json` 不是全代 `best_fitness = Infinity`。

Thermal-SA-TAS 的 `history.json` 不是 GA history schema，因此 GA 专属的 `best_fitness` 检查会标记为不适用，而不是失败。

## 使用和写作注意事项

- `ReferenceMapping` 是 initial/reference mapping 或 normalization reference，不是 baseline method。
- 跨方法比较时，使用 `method_full_objective_comparable_score` 或 `full_objective_comparable_score`。
- 相对变化应写成相对 `ReferenceMapping`，使用 `delta_vs_reference` 或 `relative_change_pct_vs_reference`。
- 不要直接横向比较消融实验的 `stored_TR2_composite_cost`，因为它们来自不同 objective。
- 主文 baseline methods 只写 `Thermal-SA-TAS` 和 `CommAware-Heuristic`。
- Random Mapping Ensemble 如需展示，建议放补充材料，并明确 selected mapping 规则。
- VOPD 不应表述为所有热指标都改善。
- HNN 应表述为多目标折中，不应写成所有指标同步改善。

## 再生成命令

在 `D:\HNOCS` 下执行：

```powershell
python D:\HNOCS\experiment\paper_analysis\rescore_full_objective_sources.py `
  --results-root "D:\HNOCS\out\experimental results"
```

该命令只会覆盖本分析目录中的派生 CSV，不会修改源实验结果目录。
