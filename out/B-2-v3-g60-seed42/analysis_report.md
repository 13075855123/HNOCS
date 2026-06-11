# B-2-v3-g60 实验分析报告

生成日期：2026-06-10  
结果目录：`D:\HNOCS\out\B-2-v3-g60`

## 1. 实验输入与产物完整性

用户在主机上运行的命令为：

```powershell
python experiment\B-2\run.py `
  --all `
  --workers 8 `
  --generations 60 `
  --population 50 `
  --seed 42 `
  --omnet-timeout 300 `
  -o out\B-2-v3-g60 `
  --omnet-bin "E:\mzj\HNOCS_mzj\libhnocs.exe" `
  --omnet-ned-paths "E:\mzj\HNOCS_mzj\src;E:\mzj\HNOCS_mzj\examples\task_driven" `
  --omnet-workdir "E:\mzj\HNOCS_mzj\examples\task_driven" `
  --omnet-ini "E:\mzj\HNOCS_mzj\examples\task_driven\omnetpp.ini" `
  --omnetpp-root "S:\omnetpp-6.3.0"
```

本次目录中实际存在四个 workload：

- `gemm`
- `hnn`
- `mpeg4`
- `vopd`

没有 `optic`。这是因为当前 `experiment\B-2\run.py` 的 `BENCHMARKS` 只包含 `GEMM/MPEG4/VOPD/HNN` 四项，因此这次 `--all` 没有生成 `optic`，不是结果文件丢失。

每个 workload 下均存在：

- `metrics.json`
- `history.json`
- `remapped.csv`
- `summary.txt`

## 2. 算法设置

本次实验使用 B-2 遗传算法进行 task-to-PE 映射优化。根据当前代码，核心设置如下：

| 项目 | 值 |
|---|---:|
| Population size | 50 |
| Generation cap | 60 |
| Workers | 8 |
| Seed | 42 |
| Crossover rate | 0.8 |
| Mutation rate | 0.1 |
| Elite count | 2 |
| Tournament size | 3 |
| Early-stop patience | 10 |
| Fitness | `baseline_normalized_v2` |
| Mesh size | 4 x 4 PE |
| Ambient temperature | 318.15 K = 45.00 C |
| Throttle temperature | 327.15 K = 54.00 C |
| OMNeT++ timeout | 300 s |

遗传算法流程：

1. 一个个体表示一个完整映射，即所有可映射 task 到 PE 的分配。
2. 初始种群由随机染色体及其变体组成。
3. 每个个体都通过 OMNeT++ 仿真得到热、性能、能耗等指标。
4. 适应度由 `OmnetCostModel.total_cost()` 计算。
5. 选择方式为 tournament selection，规模为 3。
6. 交叉方式为 uniform crossover，概率为 0.8。
7. 变异方式为逐 task 随机改 PE，概率为 0.1。
8. 每代保留 2 个 elite。
9. 如果连续 10 代 best fitness 没有改善，则提前停止。

## 3. 目标函数与系数

本次适应度函数是 baseline-normalized weighted sum：

```text
TR2 =
  w_T         * f_thermal
+ w_sigma     * f_sigma
+ w_hot       * f_hot
+ w_makespan  * f_makespan
+ w_H         * f_comm
+ w_congestion* f_congestion
+ w_D         * f_dvfs
+ w_L         * f_load
+ w_E         * f_energy
```

各项含义：

| 项 | 含义 |
|---|---|
| `f_thermal` | 峰值 PE 温升，相对 baseline 峰值温升归一化 |
| `f_sigma` | PE 温度标准差，相对 baseline 归一化 |
| `f_hot` | 超过 throttle 的 PE 数，相对 baseline 归一化；baseline 为 0 时退化为按 PE 数归一化 |
| `f_makespan` | makespan，相对 baseline 归一化 |
| `f_comm` | 分析通信代价 `sum(hops * dataSize)`，相对 baseline 归一化 |
| `f_congestion` | XY 路由下最大物理边负载，相对 baseline 归一化 |
| `f_dvfs` | 平均 DVFS penalty，相对 baseline 归一化；baseline 为 0 时按百分数归一化 |
| `f_load` | PE 计算负载不均衡，相对 baseline 归一化 |
| `f_energy` | 总能耗，相对 baseline 归一化 |

本次权重：

| 系数 | 值 |
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

注意：`w_peak = 0.0`，因此额外的超过 throttle 惩罚没有启用。是否超过 throttle 主要通过 `f_hot` 与 OMNeT++ 仿真产生的 DVFS penalty 间接进入目标函数。

baseline 的 composite cost 不一定都是 6.0。对于 `vopd`，baseline 没有 hot PE 且 DVFS penalty 为 0，因此 `f_hot = 0`、`f_dvfs = 0`，baseline cost 为 5.0。

## 4. 相对 baseline 的总体结果

| Workload | TR2 Cost | T_max | sigma_T | Hot PE | Makespan | DVFS | Comm | Energy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 6.000 -> 3.925 (-34.59%) | 54.91C -> 52.87C (-2.04C) | 2.554K -> 1.840K (-27.96%) | 6 -> 0 | 119.64us -> 115.97us (-3.06%) | 1.77% -> 0.00% | 104448 -> 70656 (-32.35%) | 1.569mJ -> 1.515mJ (-3.45%) |
| HNN | 6.000 -> 5.116 (-14.74%) | 55.70C -> 55.13C (-0.57C) | 3.054K -> 2.062K (-32.49%) | 16 -> 4 | 204.22us -> 264.69us (+29.61%) | 11.01% -> 0.63% | 2195456 -> 1761280 (-19.78%) | 4.661mJ -> 4.583mJ (-1.68%) |
| MPEG4 | 6.000 -> 4.035 (-32.75%) | 54.43C -> 52.73C (-1.69C) | 1.540K -> 1.459K (-5.28%) | 2 -> 0 | 121.73us -> 90.92us (-25.31%) | 0.06% -> 0.00% | 420000 -> 196000 (-53.33%) | 1.133mJ -> 0.969mJ (-14.48%) |
| VOPD | 5.000 -> 4.094 (-18.12%) | 52.19C -> 52.31C (+0.12C) | 1.151K -> 1.367K (+18.78%) | 0 -> 0 | 87.43us -> 42.35us (-51.56%) | 0.00% -> 0.00% | 1396000 -> 796000 (-42.98%) | 0.747mJ -> 0.500mJ (-33.05%) |

结论：

- 四个 workload 的 composite cost 均下降，说明目标函数意义下的综合权衡均优于原始 baseline 映射。
- `gemm` 是最干净的改进之一：峰值温度、温度均匀性、hot PE、makespan、通信、能耗全部改善。
- `mpeg4` 也是强正向结果：hot PE 清零，makespan、通信、能耗均显著下降。
- `hnn` 是 tradeoff 案例：热指标、DVFS、通信和能耗改善，但 makespan 明显变差，增加 29.61%。不能将 `hnn` 表述为性能改进。
- `vopd` 是另一个 tradeoff 案例：makespan、通信、能耗大幅改善，但峰值温度略升，温度标准差明显变差。不能将 `vopd` 表述为热均匀性改进。

## 5. 收敛与运行时间

| Workload | Actual generations | Converged | Last improvement generation | Early-stop basis | Elapsed |
|---|---:|---:|---:|---|---:|
| GEMM | 52 | True | 42 | 42 后连续 10 代无改善 | 128.26 min |
| HNN | 47 | True | 37 | 37 后连续 10 代无改善 | 219.59 min |
| MPEG4 | 23 | True | 13 | 13 后连续 10 代无改善 | 84.36 min |
| VOPD | 34 | True | 24 | 24 后连续 10 代无改善 | 113.73 min |

总 OMNeT++ 搜索耗时约 546.0 分钟，即约 9.1 小时。

与第二次实验不同，本次四个 `history.json` 中未发现 `avg_fitness = Infinity` 或 `worst_fitness = Infinity` 的 generation。也就是说，从记录看，本次种群统计是可解释的，没有被无效个体污染。

## 6. 最终 cost 贡献分解

下表列出最终 B-2 mapping 的加权贡献，即 `weight * normalized_term`。这些贡献之和等于最终 TR2 composite cost。

| Workload | Thermal | Sigma | Hot | Makespan | Comm | Congestion | DVFS | Load | Energy | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 0.794 | 0.720 | 0.000 | 1.163 | 0.271 | 0.318 | 0.000 | 0.175 | 0.483 | 3.925 |
| HNN | 0.946 | 0.675 | 0.150 | 1.555 | 0.321 | 0.560 | 0.023 | 0.394 | 0.492 | 5.116 |
| MPEG4 | 0.820 | 0.947 | 0.000 | 0.896 | 0.187 | 0.286 | 0.000 | 0.471 | 0.428 | 4.035 |
| VOPD | 1.017 | 1.188 | 0.000 | 0.581 | 0.228 | 0.239 | 0.000 | 0.507 | 0.335 | 4.094 |

读法：

- `hnn` 的最大贡献仍然是 makespan，说明当前权重下搜索为了降低热和 DVFS 仍牺牲了性能路径长度。
- `vopd` 的最大贡献是 `sigma_T` 和峰值温度项，说明虽然性能/通信/能耗很强，但热均匀性仍是主要短板。
- `mpeg4` 的 `f_load` 加权贡献达到 0.471，说明映射在换取通信和 makespan 改善时增加了计算负载不均衡。

## 7. 与第二次实验 `out\B-2-v2` 的直接对比

第二次实验为 30 代上限，第三次为 60 代上限。两次目标函数权重相同，但第三次命令显式指定了另一套 OMNeT++ 二进制、NED 路径、workdir、ini、OMNeT++ root 和 300s timeout；而 `metrics.json` 没有保存这些路径字段。因此，不能简单把第三次结果视为第二次结果的严格续跑。以下仅按最终产物做数值比较。

表中为：第三次结果减第二次结果。

| Workload | Cost | T_max | sigma_T | Hot PE | Makespan | Comm | Energy | 解释 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| GEMM | -0.054 | -0.25C | -0.050K | 0 | +0.08us | +8192 | -0.00003mJ | composite、热、能耗略优；通信比第二次差 |
| HNN | -0.136 | -0.92C | -0.125K | -4 | +21.47us | +122880 | +0.066mJ | composite 与热明显更好，但 makespan、通信、能耗比第二次差 |
| MPEG4 | 0.000 | 0.00C | 0.000K | 0 | 0.00us | 0 | 0.000mJ | 与第二次完全相同；第二次已在 23 代收敛 |
| VOPD | +0.031 | +0.04C | -0.033K | 0 | -0.95us | +150000 | -0.00968mJ | 性能和能耗略优、sigma 略优，但通信更差，composite 略差 |

关键结论：

- 60 代上限让 `gemm` 和 `hnn` 的 composite cost 进一步下降。
- `mpeg4` 没有变化，因为 30 代实验中它已经在 23 代收敛。
- `vopd` 的第三次 composite cost 反而比第二次略高，不能声称 60 代实验全面优于 30 代实验。
- `hnn` 第三次更偏向热安全，hot PE 从第二次的 8 降到 4，但 makespan 从第二次的 243.22us 增加到 264.69us。

## 8. 分 workload 解释

### GEMM

`gemm` 是第三次实验中最稳健的正向结果。最终 cost 从 6.000 降到 3.925，下降 34.59%。峰值温度降低 2.04C，hot PE 从 6 清零，DVFS penalty 从 1.77% 清零。makespan、通信和能耗也同步下降。

相对第二次实验，第三次进一步降低了 cost、峰值温度和 sigma_T，但通信从 62464 增加到 70656。这个变化说明 60 代搜索不是单纯继续压通信，而是在热和综合 cost 之间找到了另一个更优折中点。

### HNN

`hnn` 仍然是最难的 workload。相对 baseline，最终 cost 下降 14.74%，峰值温度下降 0.57C，sigma_T 下降 32.49%，hot PE 从 16 降到 4，DVFS penalty 从 11.01% 降到 0.63%。这些热相关指标明显改善。

但代价是 makespan 从 204.22us 增加到 264.69us，变差 29.61%。因此 `hnn` 的结论应写成“热安全性和综合目标改善，但性能存在显著退化”。如果论文或报告需要强调性能，`hnn` 必须单独解释，不能并入“性能全面提升”的叙述。

### MPEG4

`mpeg4` 是清晰的综合改进案例。cost 下降 32.75%，hot PE 从 2 清零，makespan 下降 25.31%，通信下降 53.33%，总能耗下降 14.48%。峰值温度和 sigma_T 也下降。

与第二次实验完全一致，说明当前搜索在 23 代已经稳定收敛，60 代上限没有提供额外收益。

### VOPD

`vopd` 的主要收益来自性能、通信和能耗。makespan 下降 51.56%，通信下降 42.98%，能耗下降 33.05%，这是很强的性能/能耗优化结果。

但热指标不是全面改善：峰值温度从 52.19C 增加到 52.31C，sigma_T 从 1.151K 增加到 1.367K。虽然仍无 hot PE，也没有 DVFS penalty，但温度分布变得更不均匀。报告中应写成“性能/通信/能耗收益显著，但热均匀性退化”。

相对第二次实验，第三次 `vopd` 的 makespan 和能耗略好，sigma_T 略好，但通信明显更差，最终 composite cost 略高。因此第三次 `vopd` 不是比第二次更好的综合结果。

## 9. 可用于论文/报告的保守表述

推荐表述：

> 在 B-2-v3-g60 实验中，GA 使用 baseline-normalized multi-objective cost 对四个 workload 进行任务映射优化。相对原始 baseline，四个 workload 的 composite cost 均下降，其中 GEMM 与 MPEG4 在热、性能、通信和能耗上表现出较一致的改进。HNN 和 VOPD 则体现出典型 tradeoff：HNN 显著降低 hot PE、温度离散度和 DVFS penalty，但 makespan 上升；VOPD 显著降低 makespan、通信和能耗，但温度标准差上升。因此 B-2 不应被描述为对所有 workload 的所有指标均改善，而应描述为在综合目标函数下取得更优权衡。

需要避免的表述：

- “第三次实验在所有 benchmark 上全面优于 baseline。”
- “60 代实验全面优于 30 代实验。”
- “HNN 的性能得到提升。”
- “VOPD 的热均匀性得到改善。”

## 10. 后续建议

1. 如果要把第三次作为论文主结果，建议主表使用相对 baseline 的四 workload 指标，并在正文中单独解释 `hnn` 和 `vopd` 的 tradeoff。
2. 如果要强调 60 代带来的收益，建议只说 `gemm` 和 `hnn` 的 composite 相比第二次继续下降；不要把 `vopd` 纳入“60 代更优”的证据。
3. 如果希望改善 `hnn` 的 makespan，可尝试提高 `w_makespan` 或降低热项权重，但这可能牺牲 hot PE 和 DVFS。
4. 如果希望改善 `vopd` 的热均匀性，可尝试提高 `w_sigma` 或降低通信/能耗项权重，但这可能削弱其当前很强的性能和能耗收益。
5. 建议未来在 `metrics.json` 中保存 OMNeT++ 路径、timeout、binary 版本或 hash，便于判断不同实验之间是否是严格可比的续跑。
