# Full-Objective 统一重算的必要性说明

本文档说明为什么在论文实验整理阶段，需要对消融实验和对比方法的最终 mapping 进行 `full-objective comparable score` 统一重算。该说明对应当前分析目录：

```text
D:\HNOCS\out\experimental results\analysis_full_objective_rescore
```

生成脚本为：

```text
D:\HNOCS\experiment\paper_analysis\rescore_full_objective_sources.py
```

## 1. 当前论文口径

当前论文实验中，`Original` 不再作为 baseline method 使用，而应表述为：

```text
ReferenceMapping = initial/reference mapping = normalization reference
```

也就是说，`ReferenceMapping` 的作用是提供初始映射和归一化参照，而不是作为主文中的 baseline method 与本文方法竞争。

当前主文 baseline methods 只有：

- `Thermal-SA-TAS`
- `CommAware-Heuristic`

Random Mapping Ensemble 作为补充随机集合分析保留，但不进入主文 baseline method 列表。

## 2. 为什么不能直接比较原始 `TR2_composite_cost`

主方法 `Full-GA` 和四组消融实验虽然都输出了 `TR2_composite_cost`，但这些 cost 并不一定来自同一个 objective。

四组消融的优化目标分别改变了权重：

- `thermal-only`：只保留热相关项。
- `comm-only`：只保留通信相关项。
- `wout-thermal`：去掉热相关项。
- `wout-comm`：去掉通信相关项。

因此，消融目录中的原始 `TR2_composite_cost` 只能说明该 mapping 在“自身消融 objective”下的得分，不能直接用于回答：

```text
这个 mapping 如果放回完整 full objective 下，到底综合表现如何？
```

例如，`thermal-only` 可能在自身热目标下得到很低 cost，但它可能牺牲 makespan、通信拥塞、负载均衡或能耗。若直接拿它的原始 cost 和 `Full-GA` cost 比较，就会把不同计分规则混在一起，导致不公平甚至方向错误的结论。

## 3. 统一重算要解决的问题

统一重算的核心目的，是把所有最终 mapping 放回同一把尺子下评估。

这个“同一把尺子”就是 full GA objective：

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

统一重算回答的是：

```text
给定一个已经由某个方法产生的最终 mapping，
如果用 full objective 的九项指标和权重重新评价，
它的综合系统级表现是多少？
```

这样可以公平比较：

- `Full-GA`
- 四组消融 mapping
- `Thermal-SA-TAS`
- `CommAware-Heuristic`
- 补充分析中的 Random representative mappings

## 4. 九项 normalized terms 的含义

统一重算使用九项 normalized terms，按论文叙事组织为五类：

| 类别 | normalized term | 含义 |
|---|---|---|
| 热安全 | `f_thermal` | 峰值温度相对 reference peak excess 的归一化值 |
| 热安全 | `f_sigma` | 温度空间不均匀性相对 reference 的归一化值 |
| 热安全 | `f_hot` | 热点 PE 数相对 reference 的归一化值 |
| 性能 | `f_makespan` | makespan 相对 reference 的归一化值 |
| 性能 | `f_dvfs` | DVFS penalty 相对 reference 的归一化值 |
| 通信压力 | `f_comm` | raw communication cost 相对 reference 的归一化值 |
| 通信压力 | `f_congestion` | congestion proxy 相对 reference 的归一化值 |
| 映射均衡 | `f_load` | load imbalance 相对 reference 的归一化值 |
| 能耗 | `f_energy` | PE + optical communication energy 相对 reference 的归一化值 |

这些 term 的 denominator 来自同 workload 的 `config.cost_reference`。因此，每个 workload 内的分数可解释为“相对同一个 ReferenceMapping 的系统级变化”。

## 5. 为什么必须从 raw metrics 重新计算，而不是直接读 `cost_terms.f_*`

实现中有一个关键风险：部分消融实验禁用了某些 objective 权重，被禁用项在 `cost_terms` 中可能被写成 `0`。

典型例子是：

```text
w_E = 0 时，stored cost_terms.f_energy 可能为 0
```

但在 full-objective 统一评价中，能耗项必须参与评分。因此，不能直接复用 stored `cost_terms.f_energy`。正确做法是从 raw energy 和 reference energy 重新计算：

```text
f_energy = pe_optical_comm_energy_J / reference.pe_optical_comm_energy_J
```

同理，为避免不同实验脚本或 schema 下的字段差异，本次统一重算对九项 terms 全部采用 raw metrics + `config.cost_reference` 的方式重新计算。

这样可以避免两个错误：

- 把消融 objective 中禁用项的 `0` 当成真实性能改善。
- 把不同 objective 下的原始 `TR2_composite_cost` 当成同一口径分数。

## 6. `ReferenceMapping` 的角色

`ReferenceMapping` 不是 baseline method。它的角色有两个：

1. 作为 initial/reference mapping，提供方法改进的参照点。
2. 作为 normalization reference，提供 `config.cost_reference` 中的 denominator。

因此，在论文图表中应避免写成：

```text
Full-GA vs Original baseline
```

更严谨的写法是：

```text
Full-GA relative to the reference mapping
```

或中文：

```text
Full-GA 相对初始参考映射的变化
```

主文 baseline methods 应只写：

- `Thermal-SA-TAS`
- `CommAware-Heuristic`

## 7. 对消融实验的意义

统一重算后，消融实验可以回答更清晰的问题：

```text
去掉某一类目标后，最终 mapping 在完整系统目标下会损失多少？
```

这比直接报告消融自身 objective cost 更有论文价值。因为本文主张的是系统级多目标联合优化，而不是单独优化某一类指标。

例如：

- `thermal-only` 可以说明只关注热安全会不会牺牲性能、通信或能耗。
- `comm-only` 可以说明只关注通信压力是否会破坏热安全和能耗。
- `wout-thermal` 可以说明去掉热目标后，综合系统目标是否仍稳定。
- `wout-comm` 可以说明去掉通信目标后，通信和拥塞代价是否退化。

这些问题都必须在 full objective 下重新评价，才和论文主张一致。

## 8. 对 baseline methods 的意义

`Thermal-SA-TAS` 和 `CommAware-Heuristic` 的实验结果来自不同方法与不同输出 schema。统一重算把它们映射到同一套九项 normalized terms 和 full GA 权重下，避免出现以下问题：

- 某 baseline 使用自己的 proxy 或启发式目标，无法直接和 GA cost 对齐。
- 不同 result folder 的 schema 不同，字段位置不同，直接汇总容易出错。
- 只看个别 raw metric 会忽略系统级 tradeoff。

统一重算后，主文可以比较：

```text
在同一 full-objective 评价口径下，Full-GA 与 Thermal-SA-TAS / CommAware-Heuristic 的综合系统表现。
```

## 9. 对 Random Mapping Ensemble 的处理

Random Mapping Ensemble 当前只作为补充随机集合分析，不作为主文 baseline method。

它使用已整理出的 representative mappings：

- `RandomBest`
- `RandomMedian`
- `RandomP10`
- `RandomP90`

这些代表 mapping 每个 workload 只有一行，因此 summary 中每个 Random 方法的 `n=1`。写作时不能把 `RandomBest` 表述为普通随机映射的平均水平；它是 best-of-ensemble selected mapping。

如果在补充材料中展示 Random 结果，应明确：

```text
RandomBest 表示随机集合中的最优代表，而非一次随机抽样。
```

## 10. 当前生成的文件口径

当前用于主文和补充分析的关键文件为：

| 文件 | 用途 |
|---|---|
| `figure2_composite_cost_source.csv` | ReferenceMapping vs Full-GA 的 full-objective score |
| `figure3_nine_metric_grouped_source.csv` | Full-GA 相对 ReferenceMapping 的九项指标变化 |
| `figure4_baseline_and_ablation_source.csv` | Full-GA、四组消融、Thermal-SA-TAS、CommAware-Heuristic 的统一 full-objective 对比 |
| `main_baseline_full_objective_runs.csv` | 主文 baseline methods 的 run-level 数据 |
| `main_baseline_full_objective_summary.csv` | 主文 baseline methods 的汇总数据 |
| `ablation_vs_reference_full_objective_runs.csv` | 消融相对 ReferenceMapping 的 run-level 数据 |
| `ablation_vs_reference_full_objective_summary.csv` | 消融汇总数据 |
| `random_ensemble_full_objective_source.csv` | Random 补充分析数据 |
| `random_ensemble_full_objective_summary.csv` | Random 补充汇总数据 |

旧口径下的文件已经删除：

- `ablation_full_objective_rescore_runs.csv`
- `ablation_full_objective_rescore_summary.csv`
- `baseline_full_objective_rescore_runs.csv`
- `baseline_full_objective_rescore_summary.csv`

## 11. 已完成的验证

当前重算结果已经完成以下检查：

- full GA 公式复现误差为 `0`。
- `config.cost_reference` 全部一致，mismatch 为 `0`。
- validity audit 无无效行。
- Figure 2 / Figure 3 / Figure 4 与 run-level 数据二次复算一致，mismatch 为 `0`。
- summary 文件的 mean/std/CI/min/max 二次复算一致，mismatch 为 `0`。

这说明当前 CSV 是基于真实实验 `metrics.json` / `history.json` 的可追溯派生结果，而不是手工填数或从 `summary.txt` 解析出的结果。

## 12. 论文写作建议

建议采用以下表述：

```text
To enable fair comparison across ablation variants and heuristic baselines, we re-evaluated every final mapping under the same full-objective scoring function using the workload-specific reference mapping for normalization.
```

对应中文含义：

```text
为了公平比较不同消融变体和启发式 baseline，本研究将所有最终 mapping 放回同一 full-objective 评价函数下，并使用各 workload 的参考映射进行归一化。
```

不建议采用以下表述：

```text
Original is a baseline method.
```

也不建议直接写：

```text
thermal-only has lower original TR2_composite_cost than Full-GA.
```

更严谨的写法是：

```text
Although an ablation may optimize its own reduced objective, its final mapping is compared under the complete full-objective score to reveal the system-level contribution of the removed terms.
```

中文可写为：

```text
尽管某个消融实验可能在其简化 objective 下得到较低 cost，但本文统一使用完整 full-objective score 重新评价其最终 mapping，以揭示被移除目标项对系统级综合表现的贡献。
```
