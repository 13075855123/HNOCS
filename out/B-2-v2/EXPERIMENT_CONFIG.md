# B-2-v2 实验配置说明

生成日期：2026-06-09

本文件记录 `out/B-2-v2` 目录中已生成实验结果对应的算法参数、代价函数、权重系数和评价指标定义。注意：该目录仍包含 `optic` 的历史结果；当前论文版本和最新 `experiment/B-2/run.py --all` 已移除 Optic，仅使用 GEMM、MPEG4、VOPD、HNN 四个基准。

## 1. 原始运行命令

```powershell
python experiment\B-2\run.py --all --workers 8 --generations 30 --population 50 --seed 42 -o out\B-2-v2
```

## 2. 本目录包含的 workload

`out/B-2-v2` 中包含五组已生成结果：

| Workload | 目录 | 当前论文是否使用 |
|---|---|---|
| GEMM | `gemm` | 是 |
| MPEG4 | `mpeg4` | 是 |
| VOPD | `vopd` | 是 |
| HNN | `hnn` | 是 |
| Optic | `optic` | 否，已从论文和最新 `--all` 默认列表移除 |

每个 workload 目录包含：

- `metrics.json`：baseline 与 B-2 映射的完整指标、代价项、配置。
- `history.json`：每一代 GA 的 best/avg/worst fitness。
- `remapped.csv`：GA 找到的最终映射。
- `summary.txt`：简要结果摘要。

## 3. GA 参数

| 参数 | 值 |
|---|---:|
| population size | 50 |
| max generations | 30 |
| crossover rate | 0.8 |
| mutation rate | 0.1 |
| elite count | 2 |
| tournament size | 3 |
| early-stopping patience | 10 generations |
| random seed | 42 |
| parallel workers | 8 |
| OMNeT++ timeout per individual | 60 s |
| fitness name | `baseline_normalized_v2` |

终止规则：

- 最多运行 30 代。
- 如果最优 fitness 连续 10 代无改善，则提前停止。
- 超时或无效仿真个体赋予 `Infinity` fitness。

## 4. 适应度函数

B-2-v2 使用基线归一化多目标代价函数。对每个 workload，先仿真静态 baseline 映射 `M0`，用其指标作为归一化分母；随后 GA 搜索映射 `M`。

总目标函数：

```text
F(M) =
    w_T          * f_thermal
  + w_sigma      * f_sigma
  + w_hot        * f_hot
  + w_makespan   * f_makespan
  + w_H          * f_comm
  + w_congestion * f_congestion
  + w_D          * f_dvfs
  + w_L          * f_load
  + w_E          * f_energy
```

权重系数：

| 权重 | 值 | 含义 |
|---|---:|---|
| `w_T` | 1.0 | 峰值温度项 |
| `w_sigma` | 1.0 | 温度标准差项 |
| `w_hot` | 0.6 | 过热 PE 数量项 |
| `w_makespan` | 1.2 | makespan 项 |
| `w_H` | 0.4 | 通信距离项 |
| `w_congestion` | 0.7 | 静态通信拥塞项 |
| `w_D` | 0.4 | DVFS 惩罚项 |
| `w_L` | 0.2 | 负载不均衡项 |
| `w_E` | 0.5 | 总能耗项 |
| `w_peak` | 0.0 | 额外峰值超阈值惩罚，本次未启用 |

## 5. 各代价项定义

### 5.1 峰值温度项 `f_thermal`

```text
f_thermal = max(0, T_max(M) - T_amb) / max(0, T_max(M0) - T_amb)
```

- `T_max`：所有 PE、所有时间步中的最高温度。
- `T_amb = 318.15 K = 45 C`。

### 5.2 温度标准差项 `f_sigma`

```text
f_sigma = sigma_T(M) / sigma_T(M0)
```

- `sigma_T`：所有 PE、所有时间步温度样本的标准差。

### 5.3 过热 PE 数项 `f_hot`

```text
if N_hot(M0) > 0:
    f_hot = N_hot(M) / N_hot(M0)
else:
    f_hot = N_hot(M) / 16
```

- `N_hot`：峰值温度超过 `T_throttle = 327.15 K = 54 C` 的 PE 数量。

### 5.4 Makespan 项 `f_makespan`

```text
f_makespan = makespan(M) / makespan(M0)
```

### 5.5 通信距离项 `f_comm`

```text
f_comm = comm_cost(M) / comm_cost(M0)
comm_cost = sum_over_edges( Manhattan_hops(src_pe, dst_pe) * data_size )
```

- 使用 4x4 mesh Manhattan 距离。
- GlobalBuffer 任务不参与映射。

### 5.6 静态拥塞项 `f_congestion`

```text
f_congestion = congestion_cost(M) / congestion_cost(M0)
```

其中 `congestion_cost` 定义为：

```text
将每条任务依赖通信按确定性 XY 路径投影到物理 mesh 边；
统计每条物理边累计字节量；
取最大物理边负载作为 congestion_cost。
```

该项是波长/光路竞争的静态代理指标，不是运行时真实并发光路数量。

### 5.7 DVFS 项 `f_dvfs`

```text
if eta_dvfs(M0) > 0:
    f_dvfs = eta_dvfs(M) / eta_dvfs(M0)
else:
    f_dvfs = eta_dvfs(M) / 100
```

- `eta_dvfs`：16 个 PE 的平均 throttle penalty ratio，单位为百分比。

### 5.8 负载均衡项 `f_load`

```text
load_imbalance = Var(load_PE_k) / ideal_load^2
f_load = load_imbalance(M) / load_imbalance(M0)
```

- `load_PE_k`：分配到第 `k` 个 PE 的总名义计算时间。
- `ideal_load`：总名义计算时间除以 16。

### 5.9 总能耗项 `f_energy`

```text
f_energy = E_total(M) / E_total(M0)
```

`E_total` 包含：

- PE 总能耗；
- SOA 泵浦能耗；
- MRR 动态调谐能耗；
- laser 能耗。

## 6. 仿真与系统参数

| 参数 | 值 |
|---|---:|
| mesh size | 4 x 4 |
| PE count | 16 |
| router count | 16 |
| ambient temperature | 318.15 K / 45 C |
| DVFS throttle temperature | 327.15 K / 54 C |
| DVFS beta | 0.1 per C |
| thermal step `dt` | 100 ns |
| PE idle power | 0.3 W |
| PE compute power | 2.5 W |
| SOA pump power | 80 mW |
| PE `Rconv` | 8 K/W |
| router `Rconv` | 10 K/W |
| PE lateral resistance | 10 K/W |
| router lateral resistance | 10 K/W |
| PE-router vertical resistance | 3 K/W |
| PE heat capacitance | 1e-6 J/K |
| router heat capacitance | 1e-7 J/K |

OMNeT++ 相关路径：

| 项 | 值 |
|---|---|
| OMNeT++ binary | `D:/HNOCS/libhnocs.exe` |
| NED paths | `/d/HNOCS/src;/d/HNOCS/examples/task_driven` |
| workdir | `/d/HNOCS/examples/task_driven` |
| ini file | `/d/HNOCS/examples/task_driven/omnetpp.ini` |
| OMNeT++ root | `/d/omnetpp/omnetpp-6.3.0` |
| base config | `ONoCGeneral` |

## 7. Baseline 归一化分母

以下数值来自各 workload 的 `metrics.json -> config -> cost_reference`。

| Workload | peak_excess_K | sigma_T_K | N_hot | makespan_s | total_energy_J | eta_dvfs_pct | comm_cost | congestion_cost | load_imbalance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 9.908546 | 2.554207 | 6 | 0.000119635 | 0.001568842 | 1.768449 | 104448 | 22528 | 0.920254 |
| MPEG4 | 9.425106 | 1.540399 | 2 | 0.000121728 | 0.001133477 | 0.064521 | 420000 | 88000 | 0.567062 |
| VOPD | 7.188967 | 1.151278 | 0 | 0.000087427 | 0.000747293 | 0.000000 | 1396000 | 252000 | 0.358025 |
| HNN | 10.703680 | 3.054065 | 16 | 0.000204219 | 0.004661220 | 11.014128 | 2195456 | 163840 | 0.302810 |
| Optic | 3.796623 | 1.019801 | 0 | 0.000009233 | 0.000106125 | 0.000000 | 0 | 0 | 0 |

## 8. 本次结果简表

| Workload | generations | converged | best fitness | baseline cost | B-2 cost |
|---|---:|---|---:|---:|---:|
| GEMM | 30 | false | 3.978109 | 6.000000 | 3.978109 |
| MPEG4 | 23 | true | 4.034964 | 6.000000 | 4.034964 |
| VOPD | 30 | false | 4.063081 | 5.000000 | 4.063081 |
| HNN | 30 | false | 5.252067 | 6.000000 | 5.252067 |
| Optic | 27 | true | 3.691597 | 3.700000 | 3.691597 |

## 9. 解释注意事项

1. `TR2_composite_cost` 是 B-2-v2 目标函数下的复合代价，只能在同一目标函数版本内解释。
2. `out/B-2` 旧实验与 `out/B-2-v2` 的复合代价不可直接比较，因为目标函数权重和项定义不同。
3. 对跨版本比较，应使用原始指标：`T_max`、`sigma_T`、`N_hot`、makespan、通信代价、DVFS 惩罚、总能耗。
4. 本次实验使用单随机种子 `seed=42`；论文若需要统计可信度，应补充多 seed 或在正文中明确说明。
5. GEMM、VOPD、HNN 在 30 代内未收敛，应表述为“给定搜索预算下找到的最佳映射”，不应声称全局最优。
