# 必做 Baseline 实现计划

日期：2026-06-12

用途：本文档面向后续 Codex 实现实验对比方法。目标不是精确复现某一篇论文的完整工具链，而是在 HNOCS/OMNeT++ 平台中实现公平、可复现、可解释的 representative baselines。

## 1. 当前结论

`Original static mapping` 已经实现，不需要另起一套算法。

现有 B-2 运行流程中已经有以下逻辑：

- 从输入静态 CSV 中读取原始 `peId >= 0` 作为 baseline assignment。
- 调用 `_extract_baseline(graph)` 得到 `baseline_asgn`。
- 调用 `_make_mappable(graph)` 将原始静态任务置为 `peId = -2`，供后续优化器搜索。
- 在 GA 前先执行 `evaluator.evaluate(graph, baseline_asgn)`，得到 baseline OMNeT++ metrics。
- 用 `OmnetCostModel.make_reference(baseline_asgn, bl_scalars)` 构造 baseline-normalized reference。

相关文件：

- `D:\HNOCS\experiment\B-2\run.py`
- `D:\HNOCS\experiment\mapping\task_graph.py`
- `D:\HNOCS\experiment\mapping\omnet_evaluator.py`
- `D:\HNOCS\experiment\mapping\omnet_cost_model.py`
- `D:\HNOCS\examples\task_driven\static\tasks_gemm_static.csv`
- `D:\HNOCS\examples\task_driven\static\tasks_mpeg4_static.csv`
- `D:\HNOCS\examples\task_driven\static\tasks_vopd_static.csv`
- `D:\HNOCS\examples\task_driven\static\tasks_hnn_static.csv`

后续新增 baseline 时，应复用同一套静态 CSV、同一套 OMNeT++ evaluator、同一套 metrics 结构，避免 baseline 与 proposed B-2 的仿真口径不一致。

标准加载顺序应与 B-2 保持一致：

1. `graph = TaskGraph.from_csv(csv_path)`。
2. `baseline_asgn = _extract_baseline(graph)`。
3. 先用 `baseline_asgn` 评估 `Original`。
4. 调用 `_make_mappable(graph)`，将原始静态任务转为后续 baseline 可重映射任务。
5. 其他 baseline 只给 `graph.mappable_task_ids` 生成 assignment。

## 2. 必做 Baseline Set

建议论文主实验至少包含：

| Baseline | 当前状态 | 目标角色 |
|---|---|---|
| Original static mapping | 已实现 | 原始任务映射锚点 |
| Random mapping ensemble | 待实现 | 随机搜索强度下限和偶然性检查 |
| CommAware-Heuristic | 待实现 | 通信/拥塞感知代表方法 |
| ThermalGreedy / TAPP-inspired | 待实现 | 热感知代表方法 |

不建议把这些 baseline 的 fitness 写成 proposed GA 的完整 composite cost。每个 baseline 应只优化其代表性目标，然后统一交给 OMNeT++ 做最终评估。

## 3. 统一实现约束

### 3.1 输入

每个 baseline 使用相同输入：

- Task graph：由 `TaskGraph.from_csv()` 读取。
- 原始静态映射：由 `_extract_baseline(graph)` 得到。
- 目标 PE 拓扑：当前主实验固定为 4x4 mesh，即 16 个 PE；`SimParams.rows/cols` 与 `examples\task_driven\omnetpp.ini` 中的 `**.rows` / `**.columns` 当前均为 4/4。注意：`OmnetEvaluator` 当前解析温度 `.vec` 时也按 16 个 PE 读取，若未来改拓扑，必须同步修改 evaluator 的 PE 数配置。
- 任务属性：
  - CSV 字段：`taskId`, `peId`, `compTime_ns`, `outSize_B`, successors
  - Python 字段：`task_id`, `assigned_pe`, `compute_time_ns`, `output_data_size`, `successors`
- 通信权重：优先使用边上的输出数据量；若当前图结构只在 task 上记录 `outSize_B`，则按 producer task 的 `outSize_B` 赋给每条 outgoing edge。

### 3.2 输出

每个 baseline 输出一个覆盖所有 mappable non-GB tasks 的 assignment：

```text
dict[int, int]  # taskId -> peId, keys must cover graph.mappable_task_ids
```

并写出可被 OMNeT++ 独立运行的静态 CSV：

```text
out/<experiment-name>/<baseline>/<workload>/mapping.csv
```

CSV 写出应复用：

```text
D:\HNOCS\experiment\mapping\csv_writer.py
```

### 3.3 统一评估

每个 baseline 都必须通过同一 OMNeT++ evaluator 评估，而不是只报告 proxy score：

```python
scalars = evaluator.evaluate(graph, assignment)
cost_terms = OmnetCostModel(...).cost_breakdown(assignment, scalars)
# metrics.json should wrap cost_terms into the same grouped schema used by B-2:
# thermal / performance / communication / optical / energy / tradeoff / run_status
```

最终报告指标至少包括：

- `TR2_composite_cost`
- `T1_pe_peak_temp_K`
- `T3_temp_std_K`
- `T5_over_throttle_count`
- `P1_makespan_s`
- `P3_dvfs_penalty_pct`
- `C1_total_comm_cost`
- `tradeoff.cost_terms.raw_congestion_cost`
- `tradeoff.cost_terms.raw_load_imbalance`
- `E7_pe_optical_comm_energy_J`
- optical metrics：`O2_min_signal_margin_dB`, `O4_max_ber`, `O7_max_path_tuning_power_mW` 等当前 `metrics.json` 中已有字段

### 3.4 命名原则

论文和输出目录中统一使用 literature-inspired 命名：

- `Original`
- `RandomBest` / `RandomMedian`
- `CommAware-Heuristic`
- `ThermalGreedy`

不要写成：

- exact reproduction of Murali et al.
- exact reproduction of TAPP
- exact reproduction of Hu and Marculescu

建议论文中写：

> We implement literature-inspired baselines that capture the core objective of representative prior mapping algorithms under the same HNOCS/OMNeT++ evaluation pipeline.

## 4. Original Static Mapping

### 4.1 状态

已实现。

### 4.2 后续复用方式

新增 baseline runner 时，应保留 Original 作为所有 workload 的第一个评估项：

1. 读取 `tasks_*_static.csv`。
2. 提取原始 `peId >= 0`。
3. 用 OMNeT++ 评估。
4. 保存为 `metrics.json` 中的 `original` 或 `baseline` 字段。

### 4.3 注意事项

- 不要修改原始 static CSV。
- 不要把 `out\B-2-v3-g60-seed42` 和 `out\B-2-v3-g60-seed43` 的历史结果覆盖。
- 如果修改 baseline 评估逻辑、fitness 定义或 OMNeT++ 参数，旧结果不能和新结果直接混表。

## 5. Random Mapping Ensemble

### 5.1 目的

Random baseline 用于回答两个问题：

- proposed mapping 是否只是随机扰动也能达到的结果；
- 不同 workload 的 mapping search space 是否存在大量近似等价解。

### 5.2 推荐配置

每个 workload 至少运行：

```text
N = 50 random mappings
seeds = 0..49 或固定随机种子列表
```

如果 OMNeT++ 评估成本过高，可先实现：

```text
N = 30
```

论文主表建议报告：

- `RandomBest`
- `RandomMedian`
- 可选 `RandomP10` / `RandomP90`

### 5.3 算法

输入：

- mappable task list
- PE list：主实验使用 `range(SimParams.num_pes)`，即 PE 0..15
- optional diagnostic only：原始 mapping 中使用过的 PE 集合

步骤：

1. 在调用 `_make_mappable(graph)` 后，收集 `graph.mappable_task_ids`。
2. 生成 PE 候选集合；主实验必须使用全部 16 个 PE，而不是只使用原始 mapping 已占用的 PE。
3. 每个 seed 对每个 mappable task 独立随机选择一个 PE。
4. 允许多个 task 映射到同一 PE；这与当前 GA chromosome 表达一致。
5. 不引入 0..15 之外的新 PE。
6. 对每个 random assignment 跑 OMNeT++。
7. 以 `TR2_composite_cost` 选 `RandomBest`，同时保留 median。

### 5.4 约束

Random 不使用任何通信、热、能耗、makespan 信息。否则它不再是纯随机对照。

`RandomBest` 可以在所有 random samples 完成 OMNeT++ 评估后，按 `TR2_composite_cost` 做事后选择；这只是报告方式，不是 random generator 的 fitness。

## 6. CommAware-Heuristic

### 6.1 参考文献

核心参考：

1. Murali, S., & De Micheli, G. (2004). Bandwidth-constrained mapping of cores onto NoC architectures. *DATE 2004*. https://doi.org/10.1109/DATE.2004.1269002
2. Hu, J., & Marculescu, R. (2005). Energy- and performance-aware mapping for regular NoC architectures. *IEEE Transactions on Computer-Aided Design of Integrated Circuits and Systems, 24*(4), 551-562. https://doi.org/10.1109/TCAD.2005.844106
3. Tosun, S. (2011). New heuristic algorithms for energy aware application mapping and routing on mesh-based NoCs. *Journal of Systems Architecture, 57*(1), 69-78. https://doi.org/10.1016/j.sysarc.2010.10.001

这些文献都支持一个共同思想：task/core mapping 应尽量把高通信量任务放近，降低带宽压力、通信距离、通信能耗和延迟。本文 baseline 只复现这一核心思想，不复现具体工具链。

### 6.2 Baseline 类型

`communication-aware / bandwidth-aware / hop-energy-aware heuristic`

### 6.3 Objective

只优化通信 proxy，不使用 thermal、DVFS、optical tuning、makespan 的完整 OMNeT++ 结果。

推荐 proxy：

```text
CommProxy(M) =
    sum_{(i,j) in E} traffic_ij * hop_distance(M(i), M(j))
  + lambda_cong * max_edge_load(M)
```

其中：

- `traffic_ij`：任务 i 到任务 j 的通信字节数。
- `hop_distance`：mesh Manhattan distance。
- `max_edge_load`：按 XY routing 估计的最大物理链路负载。
- `lambda_cong`：默认可取 0.1 到 1.0，需要写入实验配置。

不要加入：

- peak temperature
- hot PE count
- DVFS penalty
- PE + optical total energy
- baseline-normalized full composite cost

### 6.4 推荐算法

采用确定性 greedy + local swap，便于复现。

步骤：

1. 构建 task communication graph。
2. 计算每个 task 的 communication degree：

```text
comm_degree(t) = sum traffic on incoming/outgoing edges
```

3. 选择 `comm_degree` 最大的 task 作为 seed task。
4. 将 seed task 放到中心 PE 候选之一。4x4 mesh 没有唯一中心，建议固定候选顺序为 `[5, 6, 9, 10]`，选择使初始 `CommProxy` 最低的 PE；若并列，取较小 PE id。
5. 对剩余 task 按 `comm_degree` 从高到低排序。
6. 每次放置一个 task，枚举所有 PE，选择使增量 `CommProxy` 最小的 PE。
7. 初始构造完成后，执行 fixed-iteration pairwise swap：

```text
for iter in 1..K:
    enumerate or sample task pairs (a,b)
    if swap(a,b) reduces CommProxy:
        accept
```

8. 输出最终 mapping。

推荐参数：

```text
K = 5 full passes 或 1000 sampled swaps
lambda_cong = 0.25
tie-breaker = lower load imbalance, then lower PE id
```

### 6.5 预期表现

可能较强：

- VOPD：长 pipeline / 通信路径明显。
- MPEG4：分支和汇聚结构明显。

可能较弱：

- HNN：如果热点和 DVFS 是主要矛盾，纯通信优化可能把高负载任务聚集到局部区域。
- GEMM：若计算热源比通信更主导，通信优化收益有限。

### 6.6 实现检查项

- 输出 mapping 是否覆盖所有 mappable tasks。
- 是否没有修改 GB task。
- 是否写出 `successorPE`。
- 是否只使用通信 proxy 做决策。
- 是否最终仍用 OMNeT++ 全系统 metrics 评估。

## 7. ThermalGreedy / TAPP-inspired

### 7.1 参考文献

核心参考：

1. Zhu, D., Chen, L., Pinkston, T. M., & Pedram, M. (2015). TAPP: Temperature-aware application mapping for NoC-based many-core processors. *DATE 2015*, 1241-1244. https://doi.org/10.7873/DATE.2015.1076
2. Mosayyebzadeh, A., Mehdizadeh Amiraski, M., & Hessabi, S. (2016). Thermal and power aware task mapping on 3D Network on Chip. *Computers & Electrical Engineering*. https://doi.org/10.1016/j.compeleceng.2015.12.001
3. Shen, L., Wu, N., Yan, G., & Ge, F. (2017). Thermal-aware task mapping for communication energy minimization on 3D NoC. *IEICE Electronics Express, 14*(22), 20170900. https://doi.org/10.1587/elex.14.20170900

这些文献支持 thermal-aware mapping 的核心思想：高功耗任务不应简单按通信距离聚集，而应结合热点、散热位置和温度均衡进行放置。本文 baseline 只实现 TAPP-inspired thermal spreading，不声称精确复现 TAPP。

### 7.2 Baseline 类型

`thermal-aware greedy / TAPP-inspired thermal spreading`

### 7.3 Objective

只优化热 proxy，并将通信作为 tie-breaker。

推荐 proxy：

```text
ThermalProxy(M) =
    max_pe estimated_heat_load(pe)
  + alpha_sigma * std_pe estimated_heat_load(pe)
  + alpha_center * center_heat_penalty(pe)
  + beta_comm * normalized_incremental_comm
```

其中：

- `estimated_heat_load(pe)` 可先用映射到该 PE 的 task `compute_time_ns` 总和作为 heat/load proxy；它不是物理功率，只是无仿真热负载近似。
- 如果已有 baseline OMNeT++ per-PE 温度或 power snapshot，可优先使用它构造 task heat weight。
- `center_heat_penalty` 用于避免所有高热任务落在中心或已热点区域。
- `beta_comm` 只做 tie-breaker，建议远小于 thermal 权重。

推荐默认：

```text
alpha_sigma = 0.5
alpha_center = 0.1
beta_comm = 0.05
```

不要加入：

- full composite cost
- DVFS penalty
- optical tuning energy
- makespan
- final OMNeT++ peak temperature直接反馈搜索，除非明确把它升级为 simulation-in-the-loop thermal baseline

### 7.4 推荐算法

采用 deterministic greedy placement。

步骤：

1. 计算每个 task 的 heat weight：

```text
heat_weight(t) = compute_time_ns(t)
```

可选增强：

```text
heat_weight(t) = compute_time_ns(t) * baseline_PE_temperature_factor(original_pe)
```

2. 将 task 按 `heat_weight` 从高到低排序。
3. 初始化每个 PE 的 estimated heat 为 0。
4. 对每个 task，枚举所有 PE：
   - 计算放置后的 `max estimated heat`。
   - 计算放置后的 heat std。
   - 计算 PE 位置惩罚。
   - 用通信增量作为弱 tie-breaker。
5. 选择 ThermalProxy 最低的 PE。
6. 可选执行少量 local swap，只接受 ThermalProxy 改善的交换。
7. 输出 mapping。

### 7.5 PE 位置惩罚建议

如果当前芯片模型是 2D mesh 且无显式 heat-sink distance，可采用简单位置 proxy：

```text
center_heat_penalty(pe) = normalized distance closeness to chip center
```

即中心 PE 惩罚较高，边缘 PE 惩罚较低。这样能模拟“高热任务尽量分散、避免中心堆叠”的 thermal spreading。

如果后续已有真实 RC thermal resistance 或 per-PE cooling factor，应改用：

```text
cooling_penalty(pe) = thermal_resistance_to_ambient(pe)
```

### 7.6 预期表现

可能较强：

- HNN：热点 PE 数和温度均衡可能明显改善。
- GEMM：如果计算任务热权重差异明显，可能改善 thermal metrics。

可能较弱：

- VOPD：纯热扩散可能拉长通信路径，makespan、communication cost、energy 可能变差。
- MPEG4：若通信结构强，thermal greedy 可能损失部分通信局部性。

### 7.7 实现检查项

- 是否只用 thermal proxy 决策。
- 是否保留 communication tie-breaker 的低权重属性。
- 是否没有把 proposed GA 的 full fitness 泄漏进 baseline。
- 是否最终用 OMNeT++ 全系统 metrics 评估，而不是只报告 proxy。

## 8. 建议代码组织

建议新增一个实验目录，而不是混入 B-2 GA：

```text
D:\HNOCS\experiment\baselines\
    __init__.py
    run.py
    random_mapper.py
    comm_aware.py
    thermal_greedy.py
    common.py
```

推荐职责：

| File | Purpose |
|---|---|
| `common.py` | 提取 baseline、PE 坐标、hop distance、XY edge load、metrics 写出 |
| `random_mapper.py` | Random ensemble |
| `comm_aware.py` | CommAware-Heuristic |
| `thermal_greedy.py` | ThermalGreedy |
| `run.py` | CLI，批量运行 workload 和 baseline |

输出结构建议：

```text
out/baselines-v1/
    gemm/
        original/
            metrics.json
            mapping.csv
        random/
            metrics.json
            mappings/
        comm_aware/
            metrics.json
            mapping.csv
        thermal_greedy/
            metrics.json
            mapping.csv
    runs_summary.csv
    aggregate_summary.json
```

## 9. CLI 建议

示例：

```powershell
python experiment\baselines\run.py `
  --benchmarks gemm,mpeg4,vopd,hnn `
  --baselines original,random,comm_aware,thermal_greedy `
  --random-n 50 `
  --seed 42 `
  --out out\baselines-v1
```

默认应支持 dry run：

```powershell
python experiment\baselines\run.py --dry-run
```

## 10. 论文表格建议

主表推荐列：

| Workload | Original | RandomBest | CommAware | ThermalGreedy | Proposed GA |
|---|---:|---:|---:|---:|---:|
| GEMM | cost | cost | cost | cost | cost |
| MPEG4 | cost | cost | cost | cost | cost |
| VOPD | cost | cost | cost | cost | cost |
| HNN | cost | cost | cost | cost | cost |

补充表推荐列：

- peak temperature
- temp std
- hot PE count
- makespan
- communication cost
- congestion
- DVFS penalty
- `E7_pe_optical_comm_energy_J`

Random 应报告分布：

```text
Random median / best / p10 / p90
```

## 11. 实现优先级

第一批：

1. `Original` 复用并纳入统一 baseline runner。
2. `Random mapping ensemble`。
3. `CommAware-Heuristic`。
4. `ThermalGreedy`。

第二批：

1. 将四个 baseline 跑通 GEMM。
2. 再扩展到 MPEG4、VOPD、HNN。
3. 汇总 CSV 和 JSON。
4. 生成论文图表脚本。

验收条件：

- 每个 workload 至少有 `Original`、`RandomBest`、`RandomMedian`、`CommAware-Heuristic`、`ThermalGreedy` 的完整 metrics。
- 所有 baseline 使用同一 OMNeT++ 配置。
- 输出 mapping CSV 应可通过 `OmnetEvaluator` 生成的临时 ini 直接复跑；若要用 `examples\task_driven\omnetpp.ini` 手工复跑，需要把 CSV 复制到对应 mapping/static 目录并新增或覆盖相应 config。
- 文中不声称 exact reproduction，只称 literature-inspired implementation。
