# B-2-v3-g60 前八项 Todo 完成说明

生成日期：2026-06-10  
主结果目录：`D:\HNOCS\out\B-2-v3-g60`

## 1. 确认最终采用哪组结果

已完成。

建议将 `D:\HNOCS\out\B-2-v3-g60` 作为当前 B-2 主结果。原因：

- 当前 `experiment\B-2\run.py --all` 默认只包含 `GEMM/MPEG4/VOPD/HNN` 四项，和本次目录一致。
- 本次设置为 `--generations 60`、`--population 50`、`--seed 42`，且四个 workload 均触发早停收敛。
- 本次 `history.json` 未出现 `avg_fitness = Infinity` 或 `worst_fitness = Infinity`，收敛曲线可解释性优于第二次。

使用边界：

- `out\B-2-v3-g60` 作为主结果。
- `out\B-2-v2` 只作为 30 代对比或调参过程说明。
- 不要把 `out\B-2` 旧目标函数下的 composite cost 和本次 composite cost 直接比较。

## 2. 画收敛曲线

已完成。

生成文件：

- `convergence_best_fitness.png`
- `convergence_population_fitness.png`
- `convergence_history_flat.csv`

推荐论文主图使用：

```text
convergence_best_fitness.png
```

它展示四个 workload 的 `best_fitness` 随 generation 的变化。

辅助图使用：

```text
convergence_population_fitness.png
```

它展示每个 workload 的 `best / avg / worst fitness`。本次数据没有 Infinity，因此该图可用。

注意：本次设置 generation cap 为 60，但实际早停代数为：

| Workload | Actual generations | Converged |
|---|---:|---:|
| GEMM | 52 | True |
| HNN | 47 | True |
| MPEG4 | 23 | True |
| VOPD | 34 | True |

图注建议写：

> The x-axis shows the actual generations executed before early stopping; all workloads converged before the 60-generation cap.

## 3. 画主结果柱状图或表格

已完成。

生成文件：

- `main_metrics_baseline_vs_b2.png`
- `metrics_summary_table.csv`
- `metrics_relative_changes.csv`

`main_metrics_baseline_vs_b2.png` 包含八个指标：

- TR2 composite cost
- `T_max`
- `sigma_T`
- hot PE count
- makespan
- DVFS penalty
- communication cost
- total energy

`metrics_summary_table.csv` 是 baseline 与 B-2 的绝对值表。  
`metrics_relative_changes.csv` 是相对 baseline 的变化量/变化率表。

推荐论文表格优先使用以下绝对值：

| Workload | TR2 Cost | T_max | sigma_T | Hot PE | Makespan | DVFS | Comm | Energy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 6.000 -> 3.925 | 54.91C -> 52.87C | 2.554K -> 1.840K | 6 -> 0 | 119.64us -> 115.97us | 1.77% -> 0.00% | 104448 -> 70656 | 1.569mJ -> 1.515mJ |
| HNN | 6.000 -> 5.116 | 55.70C -> 55.13C | 3.054K -> 2.062K | 16 -> 4 | 204.22us -> 264.69us | 11.01% -> 0.63% | 2195456 -> 1761280 | 4.661mJ -> 4.583mJ |
| MPEG4 | 6.000 -> 4.035 | 54.43C -> 52.73C | 1.540K -> 1.459K | 2 -> 0 | 121.73us -> 90.92us | 0.06% -> 0.00% | 420000 -> 196000 | 1.133mJ -> 0.969mJ |
| VOPD | 5.000 -> 4.094 | 52.19C -> 52.31C | 1.151K -> 1.367K | 0 -> 0 | 87.43us -> 42.35us | 0.00% -> 0.00% | 1396000 -> 796000 | 0.747mJ -> 0.500mJ |

## 4. 单独标注 tradeoff case

已完成。

需要单独标注两个 workload：

### HNN

HNN 的 composite cost 降低，热相关指标也明显改善：

- `T_max`: 55.70C -> 55.13C
- `sigma_T`: 3.054K -> 2.062K
- hot PE: 16 -> 4
- DVFS: 11.01% -> 0.63%

但 makespan 变差：

- makespan: 204.22us -> 264.69us，增加 29.61%

论文/报告中应写为：

> HNN improves thermal safety and DVFS behavior under the composite objective, but at the cost of a longer makespan.

不要写成 HNN 性能提升。

### VOPD

VOPD 的性能、通信和能耗改善很强：

- makespan: 87.43us -> 42.35us，下降 51.56%
- communication cost: 1396000 -> 796000，下降 42.98%
- total energy: 0.747mJ -> 0.500mJ，下降 33.05%

但热均匀性变差：

- `T_max`: 52.19C -> 52.31C，增加 0.12C
- `sigma_T`: 1.151K -> 1.367K，增加 18.78%

论文/报告中应写为：

> VOPD obtains large performance, communication, and energy gains, while sacrificing temperature uniformity.

不要写成 VOPD 热指标全面改善。

## 5. 补 cost breakdown 图

已完成。

生成文件：

- `cost_breakdown.png`
- `cost_breakdown_weighted.csv`

`cost_breakdown.png` 是最终 B-2 映射的 stacked bar，显示每个 workload 的 weighted cost contribution。

主要读法：

| Workload | 最大贡献项 | 解释 |
|---|---|---|
| GEMM | makespan、thermal、sigma | 各项比较均衡，hot 和 DVFS 已清零 |
| HNN | makespan | composite 下降但性能代价仍是主要压力 |
| MPEG4 | sigma、makespan、thermal、load | 通信和能耗改善明显，但静态负载更不均衡 |
| VOPD | sigma、thermal、makespan、load | 性能收益强，但热均匀性是主要短板 |

## 6. 写实验设置

已完成。

本次应写入论文/报告的设置：

| 参数 | 值 |
|---|---:|
| population size | 50 |
| generation cap | 60 |
| random seed | 42 |
| workers | 8 |
| crossover rate | 0.8 |
| mutation rate | 0.1 |
| elite count | 2 |
| tournament size | 3 |
| early-stopping patience | 10 |
| fitness | `baseline_normalized_v2` |
| OMNeT++ timeout | 300 s |
| mesh | 4 x 4 |
| PE count | 16 |
| ambient temperature | 318.15 K / 45.00 C |
| throttle temperature | 327.15 K / 54.00 C |

实际运行命令已记录在：

```text
analysis_report.md
```

## 7. 写目标函数

已完成。

推荐论文公式：

```text
TR2 =
  w_T          f_thermal
+ w_sigma      f_sigma
+ w_hot        f_hot
+ w_makespan   f_makespan
+ w_H          f_comm
+ w_congestion f_congestion
+ w_D          f_dvfs
+ w_L          f_load
+ w_E          f_energy
```

本次权重：

| Weight | Value |
|---|---:|
| `w_T` | 1.0 |
| `w_sigma` | 1.0 |
| `w_hot` | 0.6 |
| `w_makespan` | 1.2 |
| `w_H` | 0.4 |
| `w_congestion` | 0.7 |
| `w_D` | 0.4 |
| `w_L` | 0.2 |
| `w_E` | 0.5 |
| `w_peak` | 0.0 |

解释注意：

- `w_D = 0.4` 表示 DVFS penalty 进入目标函数。
- `w_peak = 0.0` 只表示额外的 peak-over-throttle 惩罚没有启用。
- 超过 throttle 的影响仍通过 `f_hot`、`f_dvfs`，以及 OMNeT++ 仿真导致的 makespan/energy 变化进入目标函数。

## 8. 写结论时保持保守

已完成。

推荐结论：

> In the B-2-v3-g60 experiment, the GA-based mapper reduces the baseline-normalized composite cost for all four workloads. GEMM and MPEG4 show relatively consistent improvements across thermal, performance, communication, and energy metrics. HNN and VOPD exhibit workload-dependent tradeoffs: HNN improves thermal safety and DVFS behavior but increases makespan, while VOPD strongly reduces makespan, communication, and energy but worsens temperature uniformity. Therefore, B-2 should be interpreted as improving the composite mapping objective rather than uniformly improving every raw metric.

中文表述：

> B-2-v3-g60 在四个 workload 上均降低了 baseline-normalized composite cost，说明在综合目标函数意义下找到了更优映射。GEMM 与 MPEG4 的原始指标改善较一致；HNN 和 VOPD 则体现出 workload-dependent tradeoff：HNN 改善热安全性和 DVFS，但 makespan 变差；VOPD 显著改善 makespan、通信和能耗，但温度均匀性变差。因此，B-2 应表述为改善综合映射目标，而不是所有原始指标全面提升。

需要避免的表述：

- B-2 在所有 benchmark 上所有指标都提升。
- 60 代实验全面优于 30 代实验。
- HNN 的性能得到提升。
- VOPD 的热均匀性得到改善。

## 生成文件清单

| 文件 | 用途 |
|---|---|
| `analysis_report.md` | 完整严谨分析 |
| `TODO_1_TO_8_COMPLETED.md` | 前八项完成说明 |
| `make_figures_and_tables.py` | 图表和 CSV 生成脚本 |
| `metrics_summary_table.csv` | baseline 与 B-2 绝对指标表 |
| `metrics_relative_changes.csv` | 相对 baseline 的变化率/变化量 |
| `convergence_history_flat.csv` | 展平后的每代历史数据 |
| `cost_breakdown_weighted.csv` | cost breakdown 数值 |
| `convergence_best_fitness.png` | 主收敛曲线 |
| `convergence_population_fitness.png` | best/avg/worst fitness 曲线 |
| `main_metrics_baseline_vs_b2.png` | 主结果成对柱状图 |
| `cost_breakdown.png` | cost breakdown stacked bar |
