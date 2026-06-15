# Thermal-SA-TAS v3 integrated multi-seed analysis

本报告聚合 seed 40-49 的 Thermal-SA-TAS v3 integrated preset 结果。聚合指标全部来自每个 workload 的 `metrics.json` 结构化字段；有效性检查同时读取 `history.json`。

- 有效性：40/40 个 seed-workload 组合通过检查。
- 无效判定覆盖：`run_ok=false`、`valid_for_cost=false`、`T_max=-273.1 C`、`makespan=0`、`E_total=0`、`history.json` 全代 best_fitness/best_score 为 Infinity。
- 对照口径：original mapping 为每个 seed 输出中的 `original/metrics.json`；B-2-v4 GA 对照来自 `D:\HNOCS\out\B-2-v4\aggregate_summary.json`。

## Composite cost vs original and B-2-v4

| Workload | Thermal-SA-TAS cost mean ± CI95 | vs original | B-2-v4 GA cost mean | B-2-v4 vs original | SA cost - GA cost |
| --- | --- | --- | --- | --- | --- |
| GEMM | 5.0255 ± 0.3716 | -16.24% | 3.7796 | -37.01% | 1.2460 (32.97%) |
| MPEG4 | 4.9191 ± 0.2181 | -18.01% | 4.1326 | -31.12% | 0.7865 (19.03%) |
| VOPD | 4.5019 ± 0.0509 | -9.96% | 4.4059 | -11.88% | 0.0960 (2.18%) |
| HNN | 5.6903 ± 0.1381 | -5.16% | 5.1357 | -14.40% | 0.5546 (10.80%) |

## Mean change relative to original mapping

| Workload | Cost % | Tmax ΔC | SigmaT % | Hot PE Δ | Makespan % | Comm % | Congestion % | Load % | Energy % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GEMM | -16.24% | -1.294 | -35.63% | -5.60 | 30.96% | -3.04% | -23.18% | 107.33% | 10.56% |
| MPEG4 | -18.01% | -1.214 | -10.99% | -1.90 | -0.11% | 12.29% | 0.91% | 35.58% | -0.20% |
| VOPD | -9.96% | 0.002 | -4.57% | 0.00 | -1.13% | -35.30% | -41.83% | 0.00% | -1.01% |
| HNN | -5.16% | 1.790 | -24.72% | -3.00 | 2.58% | -13.62% | 3.50% | -17.53% | -0.50% |

## Workload-level interpretation

- GEMM：复合代价平均 -16.24%，Tmax -1.294 C，sigma_T -35.63%，makespan 30.96%，通信 -3.04%，能耗 10.56%。
- MPEG4：复合代价平均 -18.01%，Tmax -1.214 C，sigma_T -10.99%，makespan -0.11%，通信 12.29%，能耗 -0.20%。
- VOPD：复合代价平均 -9.96%，Tmax 0.002 C，sigma_T -4.57%，通信 -35.30%，能耗 -1.01%；makespan 平均 -1.13%。可表述为 v3 integrated 下温度均匀性、通信和能耗改善，Tmax 多 seed 平均基本持平，不宜夸大为稳定峰温下降。
- HNN：复合代价平均 -5.16%，热点 PE 平均变化 -3.00，sigma_T -24.72%；但 Tmax 平均变化为 1.790 C，makespan 平均 2.58%。因此应写成降低热点/温度不均衡和通信/能耗的多目标折中，不要表述为 Tmax 或 makespan 全面改善。

## Paper-ready conclusion

Thermal-SA-TAS v3 integrated 在 seed 40-49 上稳定优于 original mapping：四个 workload 的 TR2 composite cost 均为负向变化，且 40/40 个 seed-workload 组合通过有效性检查。
与 B-2-v4 GA 相比，Thermal-SA-TAS 的平均 cost 在四个 workload 上均更高，因此可作为有效但较弱的启发式 baseline，而不是主方法的替代。
trade-off 主要出现在 HNN：热点 PE 和温度不均衡下降，但 Tmax 不应夸大为改善，makespan 也存在明显变差；GEMM 的 makespan/能耗也存在代价上升，说明 Thermal-SA-TAS 更偏热稳定而非系统级综合最优。
