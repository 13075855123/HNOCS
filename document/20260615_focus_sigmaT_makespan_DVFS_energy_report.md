# sigmaT、Makespan、DVFS、Energy 四指标聚焦分析

生成日期：2026-06-15  
数据目录：`D:\HNOCS\out\experimental results\analysis_full_objective_rescore`  
输出口径：基于 `full_objective_rescore_runs.csv` 中 `valid=True` 的记录重新聚合。

## 1. 关注指标

本文只关注四个更适合论文主线叙事的指标：

| 指标 | 含义 | 越低越好 | 论文解释重点 |
|---|---|---:|---|
| `sigmaT (K)` | PE 间温度空间不均衡 | 是 | 映射是否降低热分布不均 |
| `Makespan (us)` | 应用完成时间 | 是 | 映射是否改善或牺牲性能 |
| `DVFS (%)` | DVFS 惩罚 | 是 | 热压力是否触发降频代价 |
| `Energy (mJ)` | PE optical communication energy | 是 | 映射对系统通信能耗的影响 |

表中 `x +/- y` 表示 10 个 seed 的均值 +/- 标准差；`n=1` 的方法没有误差项。`ReferenceMapping` 是 initial/reference mapping，不是 baseline method。

## 2. 四指标详细结果

### 2.1 GEMM

| Method | n | Score | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 6.000 | 2.143 | 120.41 | 1.84 | 1.571 |
| Full-GA | 10 | 3.780 +/- 0.037 | 1.366 +/- 0.036 | 116.74 +/- 0.05 | 0.00 | 1.516 +/- 0.000 |
| Thermal-SA-TAS | 10 | 5.026 +/- 0.519 | 1.380 +/- 0.108 | 157.68 +/- 21.72 | 0.03 +/- 0.05 | 1.737 +/- 0.117 |
| CommAware-Heuristic | 1 | 8.166 | 0.947 | 325.70 | 0.00 | 2.632 |
| thermal-only | 10 | 8.497 +/- 1.020 | 0.973 +/- 0.109 | 317.35 +/- 44.69 | 0.00 | 2.588 +/- 0.239 |
| comm-only | 10 | 7.409 +/- 0.731 | 1.015 +/- 0.102 | 307.84 +/- 25.24 | 0.00 +/- 0.01 | 2.537 +/- 0.135 |
| wout-thermal | 10 | 3.925 +/- 0.175 | 1.586 +/- 0.134 | 116.88 +/- 0.67 | 0.03 +/- 0.10 | 1.519 +/- 0.006 |
| wout-comm | 10 | 4.030 +/- 0.127 | 1.203 +/- 0.036 | 116.77 +/- 0.07 | 0.00 | 1.516 +/- 0.000 |

### 2.2 MPEG4

| Method | n | Score | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 6.000 | 1.300 | 122.07 | 0.07 | 1.133 |
| Full-GA | 10 | 4.133 +/- 0.075 | 1.071 +/- 0.037 | 121.58 +/- 0.32 | 0.00 | 1.128 +/- 0.002 |
| Thermal-SA-TAS | 10 | 4.919 +/- 0.305 | 1.158 +/- 0.069 | 121.94 +/- 0.38 | 0.00 +/- 0.00 | 1.131 +/- 0.002 |
| CommAware-Heuristic | 1 | 7.342 | 1.201 | 192.90 | 0.00 | 1.511 |
| thermal-only | 10 | 6.222 +/- 1.079 | 0.884 +/- 0.030 | 165.34 +/- 16.38 | 0.00 | 1.363 +/- 0.088 |
| comm-only | 10 | 5.923 +/- 0.872 | 1.180 +/- 0.097 | 147.63 +/- 16.25 | 0.04 +/- 0.07 | 1.269 +/- 0.087 |
| wout-thermal | 10 | 4.277 +/- 0.143 | 1.203 +/- 0.043 | 121.31 +/- 0.38 | 0.00 | 1.127 +/- 0.002 |
| wout-comm | 10 | 4.400 +/- 0.105 | 1.008 +/- 0.024 | 121.64 +/- 0.39 | 0.00 | 1.128 +/- 0.002 |

### 2.3 VOPD

| Method | n | Score | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 5.000 | 0.987 | 89.33 | 0.00 | 0.751 |
| Full-GA | 10 | 4.406 +/- 0.086 | 0.914 +/- 0.034 | 88.09 +/- 0.83 | 0.00 | 0.742 +/- 0.005 |
| Thermal-SA-TAS | 10 | 4.502 +/- 0.071 | 0.942 +/- 0.022 | 88.32 +/- 0.97 | 0.00 | 0.743 +/- 0.005 |
| CommAware-Heuristic | 1 | 8.896 | 1.172 | 110.27 | 0.00 | 0.859 |
| thermal-only | 10 | 6.843 +/- 0.863 | 0.792 +/- 0.008 | 101.37 +/- 6.22 | 0.00 | 0.814 +/- 0.033 |
| comm-only | 10 | 6.477 +/- 0.559 | 1.065 +/- 0.093 | 101.11 +/- 2.75 | 0.00 | 0.811 +/- 0.014 |
| wout-thermal | 10 | 4.491 +/- 0.144 | 1.016 +/- 0.042 | 87.41 +/- 0.56 | 0.00 | 0.738 +/- 0.003 |
| wout-comm | 10 | 4.732 +/- 0.161 | 0.879 +/- 0.023 | 87.80 +/- 0.31 | 0.00 | 0.742 +/- 0.002 |

### 2.4 HNN

| Method | n | Score | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|
| ReferenceMapping | 10 | 6.000 | 2.454 | 203.18 | 11.14 | 4.651 |
| Full-GA | 10 | 5.136 +/- 0.192 | 1.730 +/- 0.089 | 226.80 +/- 17.06 | 3.34 +/- 2.80 | 4.515 +/- 0.066 |
| Thermal-SA-TAS | 10 | 5.690 +/- 0.193 | 1.848 +/- 0.096 | 208.41 +/- 11.92 | 8.88 +/- 1.40 | 4.628 +/- 0.099 |
| CommAware-Heuristic | 1 | 7.070 | 2.774 | 352.55 | 2.49 | 5.300 |
| thermal-only | 10 | 9.952 +/- 1.092 | 1.278 +/- 0.112 | 638.29 +/- 86.33 | 0.00 | 6.547 +/- 0.459 |
| comm-only | 10 | 6.017 +/- 0.352 | 1.853 +/- 0.213 | 295.51 +/- 49.73 | 7.61 +/- 3.58 | 5.037 +/- 0.227 |
| wout-thermal | 10 | 5.237 +/- 0.134 | 1.856 +/- 0.075 | 200.82 +/- 3.88 | 6.92 +/- 1.30 | 4.521 +/- 0.063 |
| wout-comm | 10 | 5.367 +/- 0.212 | 1.617 +/- 0.093 | 228.64 +/- 19.30 | 1.48 +/- 1.37 | 4.451 +/- 0.043 |

## 3. Full-GA 相对 ReferenceMapping 的变化

| Workload | sigmaT delta | sigmaT change | Makespan delta | Makespan change | DVFS delta | DVFS change | Energy delta | Energy change |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -0.777 | -36.26% | -3.67 | -3.05% | -1.84 | -100.00% | -0.055 | -3.47% |
| MPEG4 | -0.230 | -17.67% | -0.49 | -0.40% | -0.07 | -100.00% | -0.005 | -0.47% |
| VOPD | -0.073 | -7.38% | -1.25 | -1.40% | +0.00 | NA | -0.008 | -1.11% |
| HNN | -0.725 | -29.52% | +23.62 | +11.63% | -7.81 | -70.05% | -0.136 | -2.93% |

解读：

- `sigmaT`：Full-GA 在四个 workload 上都低于 ReferenceMapping，说明任务重映射稳定降低温度空间不均衡。
- `Makespan`：GEMM、MPEG4、VOPD 都改善；HNN 变差 23.62 us，即 +11.63%，这是 HNN 最重要的代价项。
- `DVFS`：GEMM、MPEG4 和 HNN 明显降低；VOPD reference 本身 DVFS 为 0，因此没有改善空间。
- `Energy`：四个 workload 都降低，但 MPEG4 和 VOPD 的幅度较小，写作时不宜夸大为大幅节能。

## 4. Full-GA 与主文 baseline methods 的四指标比较

### 4.1 Full-GA minus Thermal-SA-TAS

负值表示 Full-GA 更低。

| Workload | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|
| GEMM | -0.014 | -40.94 | -0.03 | -0.220 |
| MPEG4 | -0.087 | -0.35 | -0.00 | -0.003 |
| VOPD | -0.028 | -0.24 | +0.00 | -0.001 |
| HNN | -0.118 | +18.39 | -5.54 | -0.113 |

分析：Full-GA 相对 Thermal-SA-TAS 在 `sigmaT` 和 `Energy` 上四个 workload 全部更低。GEMM 的性能优势最明显，makespan 低 40.94 us。MPEG4 和 VOPD 的差距较小，更适合写成轻微但一致的改善。HNN 是折中场景：Full-GA 明显降低 `sigmaT`、`DVFS` 和 `Energy`，但 makespan 比 Thermal-SA-TAS 高 18.39 us。

### 4.2 Full-GA minus CommAware-Heuristic

| Workload | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|
| GEMM | +0.419 | -208.96 | +0.00 | -1.116 |
| MPEG4 | -0.131 | -71.32 | +0.00 | -0.384 |
| VOPD | -0.258 | -22.18 | +0.00 | -0.117 |
| HNN | -1.045 | -125.75 | +0.84 | -0.785 |

分析：CommAware-Heuristic 在 GEMM 上获得更低 `sigmaT`，但 makespan 和 energy 代价极大，因此不能只看温度均匀性单项。除 GEMM 的 `sigmaT` 和 HNN 的 `DVFS` 外，Full-GA 在这四个指标上大多优于 CommAware-Heuristic，尤其是 makespan 和 energy。

## 5. Full-GA 与消融实验的四指标比较

### 5.1 Full-GA minus thermal-only

| Workload | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|
| GEMM | +0.394 | -200.61 | +0.00 | -1.072 |
| MPEG4 | +0.186 | -43.76 | +0.00 | -0.235 |
| VOPD | +0.122 | -13.29 | +0.00 | -0.071 |
| HNN | +0.452 | -411.49 | +3.34 | -2.032 |

分析：`thermal-only` 的 `sigmaT` 更低，说明单纯热导向确实能进一步压平温度分布；但它严重牺牲 makespan 和 energy。HNN 上最极端：thermal-only 的 makespan 比 Full-GA 高 411.49 us，energy 高 2.032 mJ。这个对比说明单纯追求温度均匀性不是系统级最优。

### 5.2 Full-GA minus comm-only

| Workload | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|
| GEMM | +0.352 | -191.11 | -0.00 | -1.021 |
| MPEG4 | -0.109 | -26.04 | -0.04 | -0.141 |
| VOPD | -0.151 | -13.03 | +0.00 | -0.068 |
| HNN | -0.123 | -68.71 | -4.28 | -0.522 |

分析：除 GEMM 的 `sigmaT` 外，Full-GA 在这四个指标上基本都优于 `comm-only`。这说明只优化通信会导致明显的性能和能耗副作用，也不能稳定改善热均匀性。

### 5.3 Full-GA minus wout-thermal

| Workload | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|
| GEMM | -0.220 | -0.14 | -0.03 | -0.003 |
| MPEG4 | -0.133 | +0.27 | +0.00 | +0.001 |
| VOPD | -0.101 | +0.68 | +0.00 | +0.004 |
| HNN | -0.126 | +25.98 | -3.58 | -0.006 |

分析：加入热相关项后，Full-GA 的 `sigmaT` 在四个 workload 上都低于 `wout-thermal`，证明热项确实贡献了温度均匀性改善。代价是 MPEG4、VOPD 和 HNN 的 makespan 略高，其中 HNN 的性能代价最明显。HNN 同时得到更低 `sigmaT` 和更低 `DVFS`，说明热控制在 HNN 上有效，但性能折中必须如实呈现。

### 5.4 Full-GA minus wout-comm

| Workload | sigmaT (K) | Makespan (us) | DVFS (%) | Energy (mJ) |
|---|---:|---:|---:|---:|
| GEMM | +0.163 | -0.03 | +0.00 | +0.001 |
| MPEG4 | +0.062 | -0.06 | +0.00 | -0.001 |
| VOPD | +0.035 | +0.29 | +0.00 | +0.001 |
| HNN | +0.113 | -1.84 | +1.86 | +0.064 |

分析：`wout-comm` 更偏向热指标，因此它在 `sigmaT` 上常常低于 Full-GA。但 Full-GA 的完整 objective 会把通信压力纳入考虑，因此不追求最低 `sigmaT` 单项，而是保持整体 score 更低。只看这四个指标时，Full-GA 相对 `wout-comm` 的优势不像相对 `thermal-only` 或 `comm-only` 那样明显；这也说明完整方法的价值需要结合通信和拥塞项一起解释。

## 6. 可用于论文的精简表述

可以使用如下表述：

> Across the four workloads, the proposed Full-GA consistently reduces the spatial thermal imbalance (`sigmaT`) relative to the initial mapping, while also lowering DVFS penalty and optical communication energy in most cases. GEMM, MPEG4, and VOPD additionally show reduced makespan, whereas HNN exposes a deliberate multi-objective tradeoff: Full-GA reduces `sigmaT`, DVFS penalty, and energy, but increases makespan compared with the initial mapping and Thermal-SA-TAS.

中文写法：

> 四指标结果显示，Full-GA 相对初始映射在四个 workload 上均降低了温度空间不均衡，并整体降低 DVFS 惩罚和光通信能耗。GEMM、MPEG4 和 VOPD 同时保持或改善 makespan；HNN 则体现典型多目标折中，即 Full-GA 用较高 makespan 换取更低的 `sigmaT`、DVFS 惩罚和能耗。

消融分析可写为：

> The ablation results indicate that thermal-only optimization can further reduce `sigmaT`, but often at a large cost in makespan and energy. Conversely, removing thermal terms weakens temperature balancing. These trends confirm that thermal stability must be optimized jointly with performance and energy rather than as an isolated objective.

对应中文：

> 消融结果表明，单独热优化虽然可进一步降低 `sigmaT`，但通常会显著牺牲 makespan 和能耗；去除热项又会削弱温度均衡能力。因此，热稳定性需要与性能和能耗联合优化，而不宜作为孤立目标处理。
