# B-2-v4 实验结果整理与分析

数据来源：`D:\HNOCS\out\B-2-v4`，已合并 seed 40-49 共 10 个 GA seed；随机映射对照来自 `D:\HNOCS\out\random-mapping-ensemble-v1`，每个 workload 50 个 random mapping 样本。所有 GA 核心指标均从各 workload 的 `metrics.json` 结构化字段读取。

## 1. 目录整理

- `B-2-v4-extra1-seeds` 中的 `seed_45` 到 `seed_49` 已移入 `B-2-v4`。
- `D:\HNOCS\out` 下当前只保留一个 B-2-v4 结果目录；随机映射对照目录单独保留。

## 2. 有效性与收敛检查

- 40 条 GA workload-seed 记录均 `run_ok=true` 且 `valid_for_cost=true`。
- 温度来源均为 `.vec`，`temperature_complete=true`，每条记录解析到 16 个 PE，未使用 final-only thermal snapshot fallback。
- 未发现 `T_max=-273.1C`、`makespan=0`、`E=0` 或 `history.json` 全代 `best_fitness=Infinity`。
- GA 收敛标志：36/40 条判定收敛；未触发早停但仿真有效的记录为 GEMM seed 40, HNN seed 46, GEMM seed 48, GEMM seed 49。
- VOPD 的 `avg_fitness=Infinity` 出现 246/373 代，但 `best_fitness=Infinity` 为 0 代；这表示部分个体无效污染了均值，不表示整代无效。

## 3. 10-seed GA 汇总

| Workload | Baseline cost | B-2-v4 cost mean±std | 95% CI half | Cost improvement | Tmax change | sigma_T change | Hot PE | Makespan change | Comm change | Congestion change | PE+optical energy change |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 6.0000 | 3.7796±0.0366 | 0.0262 | 37.01% | -1.85 C | -36.26% | 6 -> 0.0 (0-0) | -3.05% | -40.59% | -62.73% | -3.47% |
| MPEG4 | 6.0000 | 4.1326±0.0746 | 0.0533 | 31.12% | -2.17 C | -17.67% | 2 -> 0.0 (0-0) | -0.40% | -20.76% | -60.00% | -0.47% |
| VOPD | 5.0000 | 4.4059±0.0860 | 0.0615 | 11.88% | -0.24 C | -7.38% | 0 -> 0.0 (0-0) | -1.40% | -22.23% | -55.87% | -1.11% |
| HNN | 6.0000 | 5.1357±0.1923 | 0.1376 | 14.40% | 0.12 C | -29.52% | 16 -> 7.9 (2-13) | 11.63% | -23.02% | -18.00% | -2.93% |

## 4. GA 与随机映射对照

| Workload | Random valid/total | Random best cost | Random median cost | GA mean cost | GA worst cost | GA mean vs random best | Random samples <= GA worst |
|---|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 50/50 | 4.2126 | 5.2148 | 3.7796 | 3.8446 | 10.28% lower | 0 |
| MPEG4 | 50/50 | 4.7412 | 5.1126 | 4.1326 | 4.2428 | 12.84% lower | 0 |
| VOPD | 45/50 | 5.0226 | 5.5877 | 4.4059 | 4.5359 | 12.28% lower | 0 |
| HNN | 50/50 | 6.0269 | 6.5255 | 5.1357 | 5.4626 | 14.79% lower | 0 |

结论：四个 workload 中，10 个 GA seed 的最差 cost 仍全部低于 50 个 random mapping 中的最佳有效 cost；因此 GA 的改进不是随机重映射偶然造成的。VOPD 的 random ensemble 有 5/50 个无效样本，说明该 workload 的搜索空间更容易产生不可计成本映射；GA 最终 10 条结果均有效。

## 5. 分 workload 论文口径

- GEMM：热、性能、通信、拥塞和能耗均稳定改善。复合代价平均改善 37.01%，Tmax 平均变化 -1.85 C，sigma_T 平均变化 -36.26%，makespan 平均变化 -3.05%，通信/拥塞分别变化 -40.59%/-62.73%，PE+光通信能耗变化 -3.47%。
- MPEG4：热、通信和拥塞改善稳定，能耗小幅下降；性能平均小幅改善但幅度不大；存在 seed 间方向不一致，升高/变差 seed=40。复合代价平均改善 31.12%，Tmax 平均变化 -2.17 C，sigma_T 平均变化 -17.67%，makespan 平均变化 -0.40%，通信/拥塞分别变化 -20.76%/-60.00%，PE+光通信能耗变化 -0.47%。
- VOPD：主要优势来自复合代价、通信、拥塞和能耗改善；Tmax 变化很小且不稳定；存在 seed 间方向不一致，升高/变差 seed=40, 41, 46, 48，makespan 仅小幅改善。复合代价平均改善 11.88%，Tmax 平均变化 -0.24 C，sigma_T 平均变化 -7.38%，makespan 平均变化 -1.40%，通信/拥塞分别变化 -22.23%/-55.87%，PE+光通信能耗变化 -1.11%。
- HNN：典型多目标折中。热点 PE 从 16 降至平均 7.9，sigma_T、通信、拥塞和能耗改善；但 makespan 平均变差，Tmax 没有稳定下降；存在 seed 间方向不一致，升高/变差 seed=41, 43, 45, 46, 49。复合代价平均改善 14.40%，Tmax 平均变化 0.12 C，sigma_T 平均变化 -29.52%，makespan 平均变化 11.63%，通信/拥塞分别变化 -23.02%/-18.00%，PE+光通信能耗变化 -2.93%。

## 6. 生成文件

- `runs_summary.csv`：40 条 GA seed-workload 明细。
- `aggregate_summary.csv` / `aggregate_summary.json`：10-seed GA 聚合统计，含 mean/std/95% CI half/min/max。
- `validity_report.csv`：GA 有效性检查明细。
- `convergence_report.csv`：每条 GA run 的 generation、早停和 `avg_fitness=Infinity` 诊断。
- `ga_vs_random_summary.csv` / `ga_vs_random_summary.json`：GA 与随机映射 ensemble 对照。
- `b2_v4_analysis.md`：本文档。
