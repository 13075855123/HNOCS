# CommAware-Heuristic 与 B-2-v4 九指标对比

生成日期：2026-06-13

## 数据来源

- CommAware-Heuristic：`D:\HNOCS\out\comm-aware-baseline-v1`
- Proposed GA / B-2-v4：`D:\HNOCS\out\B-2-v4`
- B-2-v4 汇总口径：`seed_40` 到 `seed_49`，`gen_60`，每个 workload n=10。
- 所有数值均从 `metrics.json` 的结构化字段读取，没有解析 `summary.txt`。

## 对比口径

九个指标对应当前论文 composite objective 中的九项系统指标：

1. `Tmax (C)`：PE 峰值温度，越低越好。
2. `Temp std (K)`：空间温度标准差，越低越均匀。
3. `Hot PE count`：超过 throttle 阈值的 PE 数，越低越好。
4. `Makespan (us)`：任务完成时间，越低越好。
5. `Comm cost`：分析通信代价 `hops * producer output_data_size`，越低越好。
6. `Congestion`：XY routing 最大物理边负载，越低越好。
7. `DVFS penalty (%)`：平均节流惩罚，越低越好。
8. `Load imbalance`：PE compute load 不均衡，越低越好。
9. `PE+optical energy (mJ)`：PE + SOA + tuning + laser 能耗，越低越好。

`TR2_composite_cost` 不是九个子指标之一，但作为总体参考单独列出。

## 实验结构差异

| 维度 | CommAware-Heuristic baseline | B-2-v4 proposed GA |
| --- | --- | --- |
| 方法角色 | literature-inspired communication-aware baseline | 本文 proposed simulation-in-the-loop remapping |
| 搜索目标 | `raw_comm_cost + lambda_cong * max_edge_load` | baseline-normalized composite cost |
| 是否使用 OMNeT++ 反馈搜索 | 否；OMNeT++ 只用于最终评估 | 是；每个候选 mapping 经 OMNeT++ evaluator 评估 |
| 纳入搜索的指标 | 通信距离 proxy 与 XY edge congestion proxy | 热、温度均匀性、热点、makespan、通信、拥塞、DVFS、负载、能耗 |
| 随机性 | 确定性 greedy + local swap | GA，多 seed：40-49 |
| 输出口径 | 每个 workload 一个 CommAware mapping | 每个 workload 10 个 seed 的 best mapping，本文档使用均值+-标准差 |
| 论文表述边界 | 不能声称 exact reproduction of Murali/Hu/Tosun | 作为本文 proposed 方法结果 |

## 有效性检查

| Workload | Original valid | CommAware valid | B-2-v4 valid seeds |
| --- | --- | --- | --- |
| GEMM | True | True | 10/10 |
| MPEG4 | True | True | 10/10 |
| VOPD | True | True | 10/10 |
| HNN | True | True | 10/10 |

## TR2 Composite Cost 总览

| Workload | Original | CommAware | B-2-v4 mean+-std | CommAware delta | B-2 mean delta |
| --- | --- | --- | --- | --- | --- |
| GEMM | 6.000 | 8.166 | 3.780 +- 0.037 | +36.1% | -37.0% |
| MPEG4 | 6.000 | 7.342 | 4.133 +- 0.075 | +22.4% | -31.1% |
| VOPD | 5.000 | 8.896 | 4.406 +- 0.086 | +77.9% | -11.9% |
| HNN | 6.000 | 7.070 | 5.136 +- 0.192 | +17.8% | -14.4% |

## 九指标绝对值

| Workload | Method | Tmax (C) | Temp std (K) | Hot PE count | Makespan (us) | Comm cost | Congestion | DVFS penalty (%) | Load imbalance | PE+optical energy (mJ) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GEMM | Original | 54.934 | 2.143 | 6 | 120.41 | 104448 | 22528 | 1.835 | 0.920 | 1.571 |
| GEMM | CommAware-Heuristic | 53.258 | 0.947 | 0 | 325.70 | 6144 | 2048 | 0.000 | 12.524 | 2.632 |
| GEMM | B-2-v4 GA mean+-std (n=10) | 53.087 +- 0.176 | 1.366 +- 0.036 | 0 +- 0 | 116.74 +- 0.05 | 62054 +- 6915 | 8397 +- 648 | 0.000 +- 0.000 | 0.844 +- 0.080 | 1.516 +- 0.000 |
| MPEG4 | Original | 54.447 | 1.300 | 2 | 122.07 | 420000 | 88000 | 0.072 | 0.567 | 1.133 |
| MPEG4 | CommAware-Heuristic | 52.543 | 1.201 | 0 | 192.90 | 40000 | 20000 | 0.000 | 8.105 | 1.511 |
| MPEG4 | B-2-v4 GA mean+-std (n=10) | 52.274 +- 0.408 | 1.071 +- 0.037 | 0 +- 0 | 121.58 +- 0.32 | 332800 +- 39046 | 35200 +- 10293 | 0.000 +- 0.000 | 0.707 +- 0.137 | 1.128 +- 0.002 |
| VOPD | Original | 52.223 | 0.987 | 0 | 89.33 | 1396000 | 252000 | 0.000 | 0.358 | 0.751 |
| VOPD | CommAware-Heuristic | 52.563 | 1.172 | 0 | 110.27 | 120000 | 60000 | 0.000 | 7.889 | 0.859 |
| VOPD | B-2-v4 GA mean+-std (n=10) | 51.982 +- 0.381 | 0.914 +- 0.034 | 0 +- 0 | 88.09 +- 0.83 | 1085600 +- 95739 | 111200 +- 28894 | 0.000 +- 0.000 | 0.385 +- 0.087 | 0.742 +- 0.005 |
| HNN | Original | 55.668 | 2.454 | 16 | 203.18 | 2195456 | 163840 | 11.142 | 0.303 | 4.651 |
| HNN | CommAware-Heuristic | 57.186 | 2.774 | 5 | 352.55 | 163840 | 49152 | 2.492 | 2.465 | 5.300 |
| HNN | B-2-v4 GA mean+-std (n=10) | 55.786 +- 0.700 | 1.730 +- 0.089 | 7.9 +- 3.6 | 226.80 +- 17.06 | 1690010 +- 102249 | 134349 +- 14030 | 3.337 +- 2.805 | 0.450 +- 0.156 | 4.515 +- 0.066 |

## 九指标相对 Original 的变化

负数表示下降；本表九个指标均为越低越好，因此负数通常表示改善。

| Workload | Comparison | Tmax (C) | Temp std (K) | Hot PE count | Makespan (us) | Comm cost | Congestion | DVFS penalty (%) | Load imbalance | PE+optical energy (mJ) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GEMM | CommAware vs Original | -3.1% | -55.8% | -100.0% | +170.5% | -94.1% | -90.9% | -100.0% | +1261.0% | +67.6% |
| GEMM | B-2 mean vs Original | -3.4% | -36.3% | -100.0% | -3.0% | -40.6% | -62.7% | -100.0% | -8.3% | -3.5% |
| MPEG4 | CommAware vs Original | -3.5% | -7.6% | -100.0% | +58.0% | -90.5% | -77.3% | -100.0% | +1329.4% | +33.4% |
| MPEG4 | B-2 mean vs Original | -4.0% | -17.7% | -100.0% | -0.4% | -20.8% | -60.0% | -100.0% | +24.7% | -0.5% |
| VOPD | CommAware vs Original | +0.7% | +18.8% | n/a | +23.4% | -91.4% | -76.2% | n/a | +2103.4% | +14.5% |
| VOPD | B-2 mean vs Original | -0.5% | -7.4% | n/a | -1.4% | -22.2% | -55.9% | n/a | +7.7% | -1.1% |
| HNN | CommAware vs Original | +2.7% | +13.0% | -68.8% | +73.5% | -92.5% | -70.0% | -77.6% | +714.1% | +13.9% |
| HNN | B-2 mean vs Original | +0.2% | -29.5% | -50.6% | +11.6% | -23.0% | -18.0% | -70.1% | +48.5% | -2.9% |

## CommAware 相对 B-2-v4 GA 均值的差异

负数表示 CommAware 低于 B-2-v4 均值；正数表示 CommAware 高于 B-2-v4 均值。

| Workload | Tmax (C) | Temp std (K) | Hot PE count | Makespan (us) | Comm cost | Congestion | DVFS penalty (%) | Load imbalance | PE+optical energy (mJ) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GEMM | +0.3% | -30.7% | n/a | +179.0% | -90.1% | -75.6% | n/a | +1383.8% | +73.6% |
| MPEG4 | +0.5% | +12.2% | n/a | +58.7% | -88.0% | -43.2% | n/a | +1045.8% | +34.0% |
| VOPD | +1.1% | +28.2% | n/a | +25.2% | -88.9% | -46.0% | n/a | +1946.6% | +15.8% |
| HNN | +2.5% | +60.4% | -36.7% | +55.4% | -90.3% | -63.4% | -25.3% | +448.1% | +17.4% |

## Workload 级解释

### GEMM
- CommAware-Heuristic 将通信代价从 104448 降到 6144 (-94.1%)，拥塞从 22528 降到 2048 (-90.9%)。
- 与 B-2-v4 GA 均值相比，CommAware 的通信代价差异为 -90.1%，拥塞差异为 -75.6%。这说明它确实更激进地压缩通信 proxy。
- 代价是系统级指标恶化：makespan 相对 Original 为 +170.5%，Tmax 相对 Original 为 -3.1%，综合 cost 为 8.166，而 B-2-v4 GA 均值为 3.780。

### MPEG4
- CommAware-Heuristic 将通信代价从 420000 降到 40000 (-90.5%)，拥塞从 88000 降到 20000 (-77.3%)。
- 与 B-2-v4 GA 均值相比，CommAware 的通信代价差异为 -88.0%，拥塞差异为 -43.2%。这说明它确实更激进地压缩通信 proxy。
- 代价是系统级指标恶化：makespan 相对 Original 为 +58.0%，Tmax 相对 Original 为 -3.5%，综合 cost 为 7.342，而 B-2-v4 GA 均值为 4.133。

### VOPD
- CommAware-Heuristic 将通信代价从 1396000 降到 120000 (-91.4%)，拥塞从 252000 降到 60000 (-76.2%)。
- 与 B-2-v4 GA 均值相比，CommAware 的通信代价差异为 -88.9%，拥塞差异为 -46.0%。这说明它确实更激进地压缩通信 proxy。
- 代价是系统级指标恶化：makespan 相对 Original 为 +23.4%，Tmax 相对 Original 为 +0.7%，综合 cost 为 8.896，而 B-2-v4 GA 均值为 4.406。

### HNN
- CommAware-Heuristic 将通信代价从 2195456 降到 163840 (-92.5%)，拥塞从 163840 降到 49152 (-70.0%)。
- 与 B-2-v4 GA 均值相比，CommAware 的通信代价差异为 -90.3%，拥塞差异为 -63.4%。这说明它确实更激进地压缩通信 proxy。
- 代价是系统级指标恶化：makespan 相对 Original 为 +73.5%，Tmax 相对 Original 为 +2.7%，综合 cost 为 7.070，而 B-2-v4 GA 均值为 5.136。

## 结论

- CommAware-Heuristic 在四个 workload 上都显著降低了通信代价和 XY edge congestion proxy，且有时比 B-2-v4 GA 均值更低。
- 这种优势来自极端通信局部化；它不是系统级优化，未显式约束热分布、DVFS、makespan、负载均衡或能耗。
- 因此 CommAware 的综合 cost 在四个 workload 上均高于 Original，也明显高于 B-2-v4 GA 均值。
- B-2-v4 的优势不在于把通信 proxy 压到最低，而在于在九个目标之间取得系统级折中：多数 workload 同时降低热、makespan、通信、拥塞、DVFS 和能耗；HNN 仍表现为多目标折中。
- 论文中应将 CommAware-Heuristic 写作通信感知 baseline，用于证明“只做通信局部化不足以替代本文的 simulation-in-the-loop system-level remapping”。
