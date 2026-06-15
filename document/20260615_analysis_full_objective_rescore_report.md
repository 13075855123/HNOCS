# analysis_full_objective_rescore 结果整理与 baseline 比较

生成日期：2026-06-15  
数据目录：`D:\HNOCS\out\experimental results\analysis_full_objective_rescore`

## 1. 数据口径

本文档只整理 `analysis_full_objective_rescore` 中已经离线统一重算后的结果，没有重跑 OMNeT++，也没有修改源实验目录。统一重算的核心目的是：把 Full-GA、消融实验、主文 baseline methods 和随机集合代表 mapping 都放到同一个 full-objective comparable score 口径下比较。

需要特别区分：

- `ReferenceMapping` 是 initial/reference mapping，也就是 normalization reference，不作为 baseline method。
- 主文 baseline methods 只包括 `Thermal-SA-TAS` 和 `CommAware-Heuristic`。
- `RandomBest`、`RandomMedian`、`RandomP10`、`RandomP90` 是随机集合中选出的代表 mapping，适合补充材料或 sanity/control 分析，不作为主文 baseline method。

九个 raw metrics 为：

| 指标 | 含义 | 越低越好 |
|---|---|---|
| `Tmax (C)` | 峰值温度 | 是 |
| `sigmaT (K)` | 温度空间不均衡 | 是 |
| `Hot PE` | 热点 PE 数 | 是 |
| `Makespan (us)` | 应用完成时间 | 是 |
| `DVFS (%)` | DVFS 惩罚 | 是 |
| `Comm` | 通信代价 | 是 |
| `Congestion` | 拥塞代理指标 | 是 |
| `Load imb.` | 负载不均衡 | 是 |
| `Energy (mJ)` | PE optical communication energy | 是 |

表中 `x +/- y` 表示 10 个 seed 的均值 +/- 标准差；没有标准差的行为 `n=1` 的确定性或 selected mapping 结果。

## 2. 有效性与一致性检查

本分析包自带审计结果显示：

- `validity_audit.csv`：348 行全部 `valid=True`，`run_ok=True`，`valid_for_cost=True`。
- `cost_reference_audit.csv`：292 行全部 `matches_canonical=True`，说明各方法使用的 normalization reference 与 canonical reference 一致。
- `formula_validation_full_ga.csv`：80 行全部 `matches_stored=True`，最大公式误差为 0，说明 Full-GA 的重算 full-objective score 可精确复现原始保存的 `TR2_composite_cost`。

## 3. 九指标详细结果

### 3.1 GEMM

| Method | n | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 6.000 | 54.93 | 2.143 | 6.0 | 120.41 | 1.84 | 104448.0 | 22528.0 | 0.920 | 1.571 |
| Full-GA | 10 | 3.780 +/- 0.037 | 53.09 +/- 0.18 | 1.366 +/- 0.036 | 0.0 | 116.74 +/- 0.05 | 0.00 | 62054.4 +/- 6914.8 | 8396.8 +/- 647.6 | 0.844 +/- 0.080 | 1.516 +/- 0.000 |
| Thermal-SA-TAS | 10 | 5.026 +/- 0.519 | 53.64 +/- 0.63 | 1.380 +/- 0.108 | 0.4 +/- 0.5 | 157.68 +/- 21.72 | 0.03 +/- 0.05 | 101273.6 +/- 18415.9 | 17305.6 +/- 4248.2 | 1.908 +/- 0.708 | 1.737 +/- 0.117 |
| CommAware-Heuristic | 1 | 8.166 | 53.26 | 0.947 | 0.0 | 325.70 | 0.00 | 6144.0 | 2048.0 | 12.524 | 2.632 |
| thermal-only | 10 | 8.497 +/- 1.020 | 51.13 +/- 0.45 | 0.973 +/- 0.109 | 0.0 | 317.35 +/- 44.69 | 0.00 | 93286.4 +/- 37804.7 | 34918.4 +/- 3145.1 | 9.193 +/- 3.429 | 2.588 +/- 0.239 |
| comm-only | 10 | 7.409 +/- 0.731 | 52.32 +/- 0.92 | 1.015 +/- 0.102 | 0.1 +/- 0.3 | 307.84 +/- 25.24 | 0.00 +/- 0.01 | 8396.8 +/- 4846.5 | 1740.8 +/- 971.5 | 10.244 +/- 2.544 | 2.537 +/- 0.135 |
| wout-thermal | 10 | 3.925 +/- 0.175 | 53.71 +/- 0.48 | 1.586 +/- 0.134 | 0.1 +/- 0.3 | 116.88 +/- 0.67 | 0.03 +/- 0.10 | 47616.0 +/- 4404.4 | 8396.8 +/- 647.6 | 0.920 +/- 0.098 | 1.519 +/- 0.006 |
| wout-comm | 10 | 4.030 +/- 0.127 | 52.34 +/- 0.16 | 1.203 +/- 0.036 | 0.0 | 116.77 +/- 0.07 | 0.00 | 93388.8 +/- 16713.5 | 17715.2 +/- 2601.8 | 0.806 | 1.516 +/- 0.000 |

### 3.2 MPEG4

| Method | n | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 6.000 | 54.45 | 1.300 | 2.0 | 122.07 | 0.07 | 420000.0 | 88000.0 | 0.567 | 1.133 |
| Full-GA | 10 | 4.133 +/- 0.075 | 52.27 +/- 0.41 | 1.071 +/- 0.037 | 0.0 | 121.58 +/- 0.32 | 0.00 | 332800.0 +/- 39046.4 | 35200.0 +/- 10293.5 | 0.707 +/- 0.137 | 1.128 +/- 0.002 |
| Thermal-SA-TAS | 10 | 4.919 +/- 0.305 | 53.23 +/- 0.53 | 1.158 +/- 0.069 | 0.1 +/- 0.3 | 121.94 +/- 0.38 | 0.00 +/- 0.00 | 471600.0 +/- 63984.7 | 88800.0 +/- 27635.7 | 0.769 +/- 0.166 | 1.131 +/- 0.002 |
| CommAware-Heuristic | 1 | 7.342 | 52.54 | 1.201 | 0.0 | 192.90 | 0.00 | 40000.0 | 20000.0 | 8.105 | 1.511 |
| thermal-only | 10 | 6.222 +/- 1.079 | 51.44 +/- 0.41 | 0.884 +/- 0.030 | 0.0 | 165.34 +/- 16.38 | 0.00 | 366800.0 +/- 71181.8 | 120400.0 +/- 37686.4 | 3.760 +/- 2.142 | 1.363 +/- 0.088 |
| comm-only | 10 | 5.923 +/- 0.872 | 53.08 +/- 1.09 | 1.180 +/- 0.097 | 0.5 +/- 0.8 | 147.63 +/- 16.25 | 0.04 +/- 0.07 | 87200.0 +/- 48066.6 | 18000.0 +/- 3399.3 | 4.426 +/- 1.837 | 1.269 +/- 0.087 |
| wout-thermal | 10 | 4.277 +/- 0.143 | 53.50 +/- 0.45 | 1.203 +/- 0.043 | 0.0 | 121.31 +/- 0.38 | 0.00 | 265600.0 +/- 33103.2 | 31200.0 +/- 9761.6 | 0.740 +/- 0.191 | 1.127 +/- 0.002 |
| wout-comm | 10 | 4.400 +/- 0.105 | 51.86 +/- 0.10 | 1.008 +/- 0.024 | 0.0 | 121.64 +/- 0.39 | 0.00 | 466400.0 +/- 37532.8 | 70400.0 +/- 10013.3 | 0.567 | 1.128 +/- 0.002 |

### 3.3 VOPD

| Method | n | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 5.000 | 52.22 | 0.987 | 0.0 | 89.33 | 0.00 | 1396000.0 | 252000.0 | 0.358 | 0.751 |
| Full-GA | 10 | 4.406 +/- 0.086 | 51.98 +/- 0.38 | 0.914 +/- 0.034 | 0.0 | 88.09 +/- 0.83 | 0.00 | 1085600.0 +/- 95739.5 | 111200.0 +/- 28893.7 | 0.385 +/- 0.087 | 0.742 +/- 0.005 |
| Thermal-SA-TAS | 10 | 4.502 +/- 0.071 | 52.22 +/- 0.42 | 0.942 +/- 0.022 | 0.0 | 88.32 +/- 0.97 | 0.00 | 903200.0 +/- 56223.4 | 146600.0 +/- 16493.8 | 0.358 | 0.743 +/- 0.005 |
| CommAware-Heuristic | 1 | 8.896 | 52.56 | 1.172 | 0.0 | 110.27 | 0.00 | 120000.0 | 60000.0 | 7.889 | 0.859 |
| thermal-only | 10 | 6.843 +/- 0.863 | 50.98 +/- 0.26 | 0.792 +/- 0.008 | 0.0 | 101.37 +/- 6.22 | 0.00 | 930400.0 +/- 137002.2 | 371800.0 +/- 41797.9 | 3.598 +/- 1.401 | 0.814 +/- 0.033 |
| comm-only | 10 | 6.477 +/- 0.559 | 52.53 +/- 0.80 | 1.065 +/- 0.093 | 0.0 | 101.11 +/- 2.75 | 0.00 | 260400.0 +/- 130369.7 | 65200.0 +/- 3794.7 | 3.941 +/- 1.118 | 0.811 +/- 0.014 |
| wout-thermal | 10 | 4.491 +/- 0.144 | 52.86 +/- 0.59 | 1.016 +/- 0.042 | 0.0 | 87.41 +/- 0.56 | 0.00 | 784200.0 +/- 106154.8 | 82400.0 +/- 21925.1 | 0.457 +/- 0.129 | 0.738 +/- 0.003 |
| wout-comm | 10 | 4.732 +/- 0.161 | 51.76 +/- 0.28 | 0.879 +/- 0.023 | 0.0 | 87.80 +/- 0.31 | 0.00 | 1461400.0 +/- 171163.5 | 221200.0 +/- 38357.4 | 0.358 | 0.742 +/- 0.002 |

### 3.4 HNN

| Method | n | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 6.000 | 55.67 | 2.454 | 16.0 | 203.18 | 11.14 | 2195456.0 | 163840.0 | 0.303 | 4.651 |
| Full-GA | 10 | 5.136 +/- 0.192 | 55.79 +/- 0.70 | 1.730 +/- 0.089 | 7.9 +/- 3.6 | 226.80 +/- 17.06 | 3.34 +/- 2.80 | 1690009.6 +/- 102248.8 | 134348.8 +/- 14030.4 | 0.450 +/- 0.156 | 4.515 +/- 0.066 |
| Thermal-SA-TAS | 10 | 5.690 +/- 0.193 | 57.46 +/- 0.54 | 1.848 +/- 0.096 | 13.0 +/- 0.8 | 208.41 +/- 11.92 | 8.88 +/- 1.40 | 1896448.0 +/- 193636.8 | 169574.4 +/- 26205.9 | 0.250 +/- 0.056 | 4.628 +/- 0.099 |
| CommAware-Heuristic | 1 | 7.070 | 57.19 | 2.774 | 5.0 | 352.55 | 2.49 | 163840.0 | 49152.0 | 2.465 | 5.300 |
| thermal-only | 10 | 9.952 +/- 1.092 | 53.28 +/- 0.20 | 1.278 +/- 0.112 | 0.0 | 638.29 +/- 86.33 | 0.00 | 1907097.6 +/- 279804.7 | 351436.8 +/- 60006.4 | 3.532 +/- 0.978 | 6.547 +/- 0.459 |
| comm-only | 10 | 6.017 +/- 0.352 | 57.74 +/- 1.08 | 1.853 +/- 0.213 | 11.3 +/- 0.9 | 295.51 +/- 49.73 | 7.61 +/- 3.58 | 969932.8 +/- 137415.2 | 82739.2 +/- 11871.3 | 0.837 +/- 0.262 | 5.037 +/- 0.227 |
| wout-thermal | 10 | 5.237 +/- 0.134 | 57.19 +/- 0.75 | 1.856 +/- 0.075 | 12.4 +/- 0.8 | 200.82 +/- 3.88 | 6.92 +/- 1.30 | 1520435.2 +/- 162661.6 | 114688.0 +/- 12808.0 | 0.281 +/- 0.034 | 4.521 +/- 0.063 |
| wout-comm | 10 | 5.367 +/- 0.212 | 55.11 +/- 0.65 | 1.617 +/- 0.093 | 7.1 +/- 2.5 | 228.64 +/- 19.30 | 1.48 +/- 1.37 | 2156134.4 +/- 164829.2 | 203980.8 +/- 30517.6 | 0.526 +/- 0.098 | 4.451 +/- 0.043 |

## 4. 相对 ReferenceMapping 的 full-objective score 比较

### 4.1 GEMM

| Method | n | Score | Delta vs reference | Change vs reference |
|---|---:|---:|---:|---:|
| Full-GA | 10 | 3.780 +/- 0.037 | -2.220 | -37.01% |
| Thermal-SA-TAS | 10 | 5.026 +/- 0.519 | -0.974 | -16.24% |
| CommAware-Heuristic | 1 | 8.166 | +2.166 | +36.10% |
| thermal-only | 10 | 8.497 +/- 1.020 | +2.497 | +41.62% |
| comm-only | 10 | 7.409 +/- 0.731 | +1.409 | +23.48% |
| wout-thermal | 10 | 3.925 +/- 0.175 | -2.075 | -34.58% |
| wout-comm | 10 | 4.030 +/- 0.127 | -1.970 | -32.84% |

### 4.2 MPEG4

| Method | n | Score | Delta vs reference | Change vs reference |
|---|---:|---:|---:|---:|
| Full-GA | 10 | 4.133 +/- 0.075 | -1.867 | -31.12% |
| Thermal-SA-TAS | 10 | 4.919 +/- 0.305 | -1.081 | -18.01% |
| CommAware-Heuristic | 1 | 7.342 | +1.342 | +22.36% |
| thermal-only | 10 | 6.222 +/- 1.079 | +0.222 | +3.70% |
| comm-only | 10 | 5.923 +/- 0.872 | -0.077 | -1.28% |
| wout-thermal | 10 | 4.277 +/- 0.143 | -1.723 | -28.72% |
| wout-comm | 10 | 4.400 +/- 0.105 | -1.600 | -26.67% |

### 4.3 VOPD

| Method | n | Score | Delta vs reference | Change vs reference |
|---|---:|---:|---:|---:|
| Full-GA | 10 | 4.406 +/- 0.086 | -0.594 | -11.88% |
| Thermal-SA-TAS | 10 | 4.502 +/- 0.071 | -0.498 | -9.96% |
| CommAware-Heuristic | 1 | 8.896 | +3.896 | +77.93% |
| thermal-only | 10 | 6.843 +/- 0.863 | +1.843 | +36.87% |
| comm-only | 10 | 6.477 +/- 0.559 | +1.477 | +29.54% |
| wout-thermal | 10 | 4.491 +/- 0.144 | -0.509 | -10.18% |
| wout-comm | 10 | 4.732 +/- 0.161 | -0.268 | -5.35% |

### 4.4 HNN

| Method | n | Score | Delta vs reference | Change vs reference |
|---|---:|---:|---:|---:|
| Full-GA | 10 | 5.136 +/- 0.192 | -0.864 | -14.40% |
| Thermal-SA-TAS | 10 | 5.690 +/- 0.193 | -0.310 | -5.16% |
| CommAware-Heuristic | 1 | 7.070 | +1.070 | +17.83% |
| thermal-only | 10 | 9.952 +/- 1.092 | +3.952 | +65.87% |
| comm-only | 10 | 6.017 +/- 0.352 | +0.017 | +0.28% |
| wout-thermal | 10 | 5.237 +/- 0.134 | -0.763 | -12.72% |
| wout-comm | 10 | 5.367 +/- 0.212 | -0.633 | -10.55% |

## 5. 与主文 baseline methods 的比较

### 5.1 Full-GA 与 baseline methods 的 full-objective score

这里的 reduction 使用 `(baseline_score - Full-GA_score) / baseline_score`。数值越大，说明 Full-GA 相对该 baseline method 的 score 降低越明显。

| Workload | Full-GA score | Thermal-SA-TAS score | GA reduction vs Thermal-SA-TAS | CommAware score | GA reduction vs CommAware |
|---|---:|---:|---:|---:|---:|
| GEMM | 3.780 +/- 0.037 | 5.026 +/- 0.519 | 24.79% | 8.166 | 53.72% |
| MPEG4 | 4.133 +/- 0.075 | 4.919 +/- 0.305 | 15.99% | 7.342 | 43.71% |
| VOPD | 4.406 +/- 0.086 | 4.502 +/- 0.071 | 2.13% | 8.896 | 50.48% |
| HNN | 5.136 +/- 0.192 | 5.690 +/- 0.193 | 9.75% | 7.070 | 27.36% |

### 5.2 Full-GA minus Thermal-SA-TAS 的九指标差值

负值表示 Full-GA 更低。所有九个指标均按“越低越好”解释。

| Workload | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -0.55 | -0.014 | -0.4 | -40.94 | -0.03 | -39219.2 | -8908.8 | -1.064 | -0.220 |
| MPEG4 | -0.96 | -0.087 | -0.1 | -0.35 | -0.00 | -138800.0 | -53600.0 | -0.061 | -0.003 |
| VOPD | -0.24 | -0.028 | +0.0 | -0.24 | +0.00 | +182400.0 | -35400.0 | +0.027 | -0.001 |
| HNN | -1.67 | -0.118 | -5.1 | +18.39 | -5.54 | -206438.4 | -35225.6 | +0.200 | -0.113 |

解读：

- GEMM 和 MPEG4 上，Full-GA 相对 Thermal-SA-TAS 在 score、热指标、makespan、通信、拥塞和能耗上都更优，属于较稳健优势。
- VOPD 上，Full-GA 的 full-objective score 只比 Thermal-SA-TAS 低 2.13%，属于接近优势。Full-GA 的拥塞和热指标更好，但 raw communication cost 高于 Thermal-SA-TAS，load imbalance 也略高。
- HNN 上，Full-GA 的 score 更低，热点数、DVFS、通信、拥塞和能耗更好，但 makespan 比 Thermal-SA-TAS 高约 18.39 us，load imbalance 也更高。这里应写成多目标折中，而不是所有指标同步改善。

### 5.3 Full-GA minus CommAware-Heuristic 的九指标差值

| Workload | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -0.17 | +0.419 | +0.0 | -208.96 | +0.00 | +55910.4 | +6348.8 | -11.680 | -1.116 |
| MPEG4 | -0.27 | -0.131 | +0.0 | -71.32 | +0.00 | +292800.0 | +15200.0 | -7.398 | -0.384 |
| VOPD | -0.58 | -0.258 | +0.0 | -22.18 | +0.00 | +965600.0 | +51200.0 | -7.503 | -0.117 |
| HNN | -1.40 | -1.045 | +2.9 | -125.75 | +0.84 | +1526169.6 | +85196.8 | -2.015 | -0.785 |

解读：

- CommAware-Heuristic 大幅压低 communication cost 和 congestion proxy，但以 makespan、load imbalance 和 energy 的显著恶化为代价，因此 full-objective score 在四个 workload 上都高于 Full-GA。
- GEMM 上 CommAware 的 `sigmaT` 低于 Full-GA，但整体 score 仍明显更差，主要因为 makespan、load imbalance 和 energy 代价过高。
- HNN 上 CommAware 的 Hot PE 数更低，但 Full-GA 的温度均匀性、makespan、load imbalance、energy 和 composite score 更优；写作时不应只摘取 Hot PE 单项。

## 6. Full-GA 与四组消融实验的比较

本节比较 Full-GA 与 `thermal-only`、`comm-only`、`wout-thermal`、`wout-comm`。其中：

- `thermal-only` 和 `comm-only` 用来检查单一目标驱动是否会牺牲系统级综合表现。
- `wout-thermal` 和 `wout-comm` 用来检查去掉热相关项或通信相关项后，完整 full objective 是否仍有稳定收益。

### 6.1 Full-objective score 对比

这里的 reduction 使用 `(ablation_score - Full-GA_score) / ablation_score`。数值越大，说明 Full-GA 相对该消融版本的 score 降低越明显。

| Workload | Full-GA score | thermal-only | GA reduction | comm-only | GA reduction | wout-thermal | GA reduction | wout-comm | GA reduction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 3.780 +/- 0.037 | 8.497 +/- 1.020 | 55.52% | 7.409 +/- 0.731 | 48.99% | 3.925 +/- 0.175 | 3.71% | 4.030 +/- 0.127 | 6.21% |
| MPEG4 | 4.133 +/- 0.075 | 6.222 +/- 1.079 | 33.58% | 5.923 +/- 0.872 | 30.23% | 4.277 +/- 0.143 | 3.37% | 4.400 +/- 0.105 | 6.07% |
| VOPD | 4.406 +/- 0.086 | 6.843 +/- 0.863 | 35.62% | 6.477 +/- 0.559 | 31.98% | 4.491 +/- 0.144 | 1.90% | 4.732 +/- 0.161 | 6.90% |
| HNN | 5.136 +/- 0.192 | 9.952 +/- 1.092 | 48.40% | 6.017 +/- 0.352 | 14.65% | 5.237 +/- 0.134 | 1.93% | 5.367 +/- 0.212 | 4.31% |

总体上，Full-GA 相对 `thermal-only` 和 `comm-only` 的优势明显，说明只优化热或只优化通信都会产生较大的系统级副作用。相对 `wout-thermal` 和 `wout-comm`，Full-GA 的优势幅度较小但四个 workload 全部为正，说明完整九项 full objective 的收益更像是稳健的综合校正，而不是由单个 workload 的偶然结果驱动。

### 6.2 Full-GA minus thermal-only 的九指标差值

负值表示 Full-GA 更低。所有九个指标均按“越低越好”解释。

| Workload | Score delta | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -4.718 | +1.96 | +0.394 | +0.0 | -200.61 | +0.00 | -31232.0 | -26521.6 | -8.349 | -1.072 |
| MPEG4 | -2.089 | +0.83 | +0.186 | +0.0 | -43.76 | +0.00 | -34000.0 | -85200.0 | -3.052 | -0.235 |
| VOPD | -2.437 | +1.00 | +0.122 | +0.0 | -13.29 | +0.00 | +155200.0 | -260600.0 | -3.212 | -0.071 |
| HNN | -4.816 | +2.51 | +0.452 | +7.9 | -411.49 | +3.34 | -217088.0 | -217088.0 | -3.083 | -2.032 |

分析：`thermal-only` 能压低温度相关指标，尤其在 HNN 上把 Hot PE 降到 0，但代价是 makespan、load imbalance 和 energy 大幅恶化。Full-GA 相比 `thermal-only` 的 composite score 大幅下降，主要来自性能、拥塞、负载均衡和能耗的恢复。这个结果适合用来说明：单纯追求热扩散并不等价于系统级最优。

### 6.3 Full-GA minus comm-only 的九指标差值

| Workload | Score delta | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -3.629 | +0.77 | +0.352 | -0.1 | -191.11 | -0.00 | +53657.6 | +6656.0 | -9.400 | -1.021 |
| MPEG4 | -1.790 | -0.81 | -0.109 | -0.5 | -26.04 | -0.04 | +245600.0 | +17200.0 | -3.719 | -0.141 |
| VOPD | -2.071 | -0.55 | -0.151 | +0.0 | -13.03 | +0.00 | +825200.0 | +46000.0 | -3.555 | -0.068 |
| HNN | -0.881 | -1.96 | -0.123 | -3.4 | -68.71 | -4.28 | +720076.8 | +51609.6 | -0.388 | -0.522 |

分析：`comm-only` 按预期压低通信相关指标，因此 Full-GA 的 raw communication cost 和 congestion 在多数组合上高于 `comm-only`。但 `comm-only` 对 makespan、load imbalance、energy 以及部分热指标的副作用很明显，最终 full-objective score 仍被 Full-GA 稳定超过。HNN 上 Full-GA 相对 `comm-only` 的 score reduction 只有 14.65%，低于 GEMM、MPEG4、VOPD，说明 HNN 的通信压缩目标与系统级折中之间冲突更强。

### 6.4 Full-GA minus wout-thermal 的九指标差值

| Workload | Score delta | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -0.145 | -0.62 | -0.220 | -0.1 | -0.14 | -0.03 | +14438.4 | +0.0 | -0.076 | -0.003 |
| MPEG4 | -0.144 | -1.22 | -0.133 | +0.0 | +0.27 | +0.00 | +67200.0 | +4000.0 | -0.032 | +0.001 |
| VOPD | -0.085 | -0.87 | -0.101 | +0.0 | +0.68 | +0.00 | +301400.0 | +28800.0 | -0.071 | +0.004 |
| HNN | -0.101 | -1.40 | -0.126 | -4.5 | +25.98 | -3.58 | +169574.4 | +19660.8 | +0.168 | -0.006 |

分析：去掉热相关项后，`wout-thermal` 往往会得到更低的 communication cost，但热安全和热点控制变差。Full-GA 相比 `wout-thermal` 在四个 workload 上 score 都更低，主要是以一定通信代价换取更好的 Tmax、sigmaT、Hot PE 或 DVFS。HNN 最能体现这个折中：Full-GA 的热点数平均少 4.5 个、DVFS 惩罚更低，但 makespan 和通信代价更高。

### 6.5 Full-GA minus wout-comm 的九指标差值

| Workload | Score delta | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -0.250 | +0.75 | +0.163 | +0.0 | -0.03 | +0.00 | -31334.4 | -9318.4 | +0.038 | +0.001 |
| MPEG4 | -0.267 | +0.41 | +0.062 | +0.0 | -0.06 | +0.00 | -133600.0 | -35200.0 | +0.140 | -0.001 |
| VOPD | -0.327 | +0.23 | +0.035 | +0.0 | +0.29 | +0.00 | -375800.0 | -110000.0 | +0.027 | +0.001 |
| HNN | -0.231 | +0.67 | +0.113 | +0.8 | -1.84 | +1.86 | -466124.8 | -69632.0 | -0.076 | +0.064 |

分析：去掉通信相关项后，`wout-comm` 通常获得更低温度或更低热不均衡，但通信和拥塞明显变差。Full-GA 相比 `wout-comm` 的 score 优势来自通信与拥塞项的恢复；同时需要承认它在若干 workload 上牺牲了一些热指标。这个对比适合支持“通信压力必须显式进入 objective，否则热导向映射会把光层通信代价推高”的论点。

### 6.6 消融对比小结

1. `thermal-only` 与 `comm-only` 的结果证明单目标优化不适合本文问题：它们可以强化某一类指标，但会在 makespan、load imbalance、energy 或热稳定性上产生更大代价。
2. `wout-thermal` 与 `wout-comm` 的结果证明完整 full objective 的每类项都有必要，但增益不是简单单调改善所有 raw metrics，而是通过权衡把 composite score 稳定压低。
3. 对论文写作而言，消融结果最安全的表述是：完整目标函数在四个 workload 上均取得最低或更低的统一 full-objective score；单项 raw metric 可能被某个消融版本超过，但这些局部优势通常伴随其他系统指标恶化。
4. HNN 的消融结果尤其应写成多目标折中：Full-GA 相比 `wout-thermal` 强化热/DVFS控制但牺牲部分性能和通信，相比 `wout-comm` 强化通信/拥塞控制但牺牲部分热指标。

## 7. Random Mapping Ensemble 补充结果

随机集合结果不是 10-seed 平均 baseline，而是每个 workload 中已经选出的代表 mapping。因此下面只作为补充 sanity/control，不进入主文 baseline method 比较。

### 7.1 GEMM

| Method | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RandomBest | 4.047 | 53.29 | 1.498 | 0.0 | 116.78 | 0.00 | 75776.0 | 10240.0 | 1.187 | 1.518 |
| RandomMedian | 5.227 | 53.52 | 1.383 | 0.0 | 146.76 | 0.00 | 113664.0 | 24576.0 | 2.431 | 1.678 |
| RandomP10 | 4.660 | 54.06 | 1.607 | 1.0 | 116.68 | 0.02 | 76800.0 | 18432.0 | 1.758 | 1.518 |
| RandomP90 | 5.913 | 54.15 | 1.456 | 1.0 | 196.29 | 0.04 | 67584.0 | 20480.0 | 3.383 | 1.943 |

### 7.2 MPEG4

| Method | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RandomBest | 4.441 | 52.69 | 1.052 | 0.0 | 122.41 | 0.00 | 472000.0 | 40000.0 | 0.984 | 1.133 |
| RandomMedian | 5.257 | 54.13 | 1.254 | 1.0 | 122.44 | 0.02 | 428000.0 | 60000.0 | 0.962 | 1.134 |
| RandomP10 | 4.834 | 52.72 | 1.102 | 0.0 | 122.44 | 0.00 | 452000.0 | 72000.0 | 1.313 | 1.133 |
| RandomP90 | 5.970 | 54.15 | 1.332 | 1.0 | 132.85 | 0.02 | 300000.0 | 68000.0 | 2.541 | 1.191 |

### 7.3 VOPD

| Method | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RandomBest | 4.731 | 52.65 | 0.961 | 0.0 | 90.93 | 0.00 | 1374000.0 | 136000.0 | 0.358 | 0.759 |
| RandomMedian | 5.528 | 53.59 | 1.029 | 0.0 | 87.79 | 0.00 | 1838000.0 | 192000.0 | 1.005 | 0.744 |
| RandomP10 | 5.149 | 52.86 | 0.983 | 0.0 | 87.53 | 0.00 | 1144000.0 | 144000.0 | 1.198 | 0.739 |
| RandomP90 | 6.029 | 53.60 | 0.994 | 0.0 | 89.60 | 0.00 | 2418000.0 | 256000.0 | 1.291 | 0.755 |

### 7.4 HNN

| Method | Score | Tmax (C) | sigmaT (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imb. | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RandomBest | 5.538 | 57.84 | 1.998 | 11.0 | 218.50 | 8.89 | 1638400.0 | 114688.0 | 0.307 | 4.716 |
| RandomMedian | 6.511 | 56.82 | 1.848 | 10.0 | 296.62 | 3.71 | 2252800.0 | 229376.0 | 0.713 | 4.919 |
| RandomP10 | 6.128 | 57.15 | 2.090 | 12.0 | 258.36 | 5.58 | 2170880.0 | 163840.0 | 0.528 | 4.813 |
| RandomP90 | 6.997 | 58.11 | 1.572 | 11.0 | 330.03 | 10.86 | 1957888.0 | 229376.0 | 0.707 | 5.326 |

## 8. 可直接用于论文的结论边界

1. Full-GA 在四个 workload 上都降低了相对 ReferenceMapping 的 full-objective comparable score：GEMM -37.01%，MPEG4 -31.12%，VOPD -11.88%，HNN -14.40%。
2. 相对主文 baseline method，Full-GA 在四个 workload 上都取得更低 composite score；但 VOPD 相对 Thermal-SA-TAS 的优势较小，应写成接近优势。
3. GEMM 和 MPEG4 可较稳妥地表述为热安全、性能、通信压力和能耗的整体改善。
4. VOPD 不能写成所有热指标或所有 raw metrics 都同步改善。Full-GA 相对 ReferenceMapping 的 score、makespan、通信、拥塞和能耗改善更清晰；相对 Thermal-SA-TAS 时，Full-GA 的 raw communication cost 更高。
5. HNN 必须写成多目标折中：Full-GA 降低 composite score、热点 PE 数、DVFS、通信、拥塞和能耗，但 makespan 相对 ReferenceMapping 和 Thermal-SA-TAS 都更高。
6. 消融结果说明单独 `thermal-only` 或 `comm-only` 容易把系统推向极端：`thermal-only` 降低热指标但严重伤害 makespan、communication/load 和 energy；`comm-only` 降低通信/拥塞但也会带来较重的系统级代价。
7. `wout-thermal` 和 `wout-comm` 的结果说明完整 objective 的收益来自多目标协同：某些 raw metric 会被消融版本局部超过，但 Full-GA 在四个 workload 上都取得更低的统一 full-objective score。

## 9. 建议图表使用

- 主文九指标图：使用 `figure3_nine_metric_grouped_source.csv`，展示 Full-GA 相对 ReferenceMapping 的九项变化。
- 主文 baseline/ablation 图：使用 `figure4_baseline_and_ablation_source.csv`，只放 Full-GA、四组消融、Thermal-SA-TAS 和 CommAware-Heuristic。
- 随机集合：使用 `random_ensemble_full_objective_source.csv` 或 `random_ensemble_full_objective_summary.csv`，建议放补充材料，并明确 RandomBest 是 best-of-random selected mapping，不是普通随机映射的均值。
