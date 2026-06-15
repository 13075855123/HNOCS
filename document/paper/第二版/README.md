# 第二版论文写作与图表注意事项

本文档记录 `第二版` 草稿当前需要特别注意的实验解释口径，尤其是 unified full-objective rescore、主 baseline 对比和审稿风险。这里的内容用于指导正文、图注、补充材料和答审稿意见，不替代原始实验数据。

## 1. Full-objective comparable score 的定位

当前 `analysis_full_objective_rescore` 将 `Full-GA`、`Thermal-SA-TAS`、`CommAware-Heuristic`、消融实验和 reference mapping 投影到同一个 full-objective comparable score 上。这个做法可以保留，但写作时必须明确：

- 该 score 是本文提出方法的系统级设计目标，不是唯一客观真理。
- `Full-GA` 的搜索过程本来就优化这个 objective，因此它在该 score 上表现最好是预期结果，不能单独作为公平性证明。
- `ReferenceMapping` 是 normalization anchor / initial mapping / reference mapping，不是 baseline method。
- `Thermal-SA-TAS` 和 `CommAware-Heuristic` 是外部 baseline methods，但它们的搜索目标不是 full objective。
- 图中应使用 `Full-objective comparable score`，避免直接称为 `fitness comparison`，以降低“用 GA 训练目标评价所有方法”的循环论证观感。

推荐表述：

> Under the proposed full-system objective, Full-GA achieves the lowest comparable score because it directly optimizes the coupled thermal-performance-communication-energy objective.

避免表述：

> Full-GA universally outperforms all baselines.

## 2. 九项权重的审稿风险

审稿人很可能会追问九项 normalized terms 的权重如何确定，尤其是：

- 热相关项权重较高，`Thermal-SA-TAS` 在 full score 下较容易优于 reference mapping。
- 通信相关项权重较小，`CommAware-Heuristic` 在 full score 下可能明显差于 reference mapping。
- 如果没有先验解释，读者可能怀疑权重是为了让 `Full-GA` 赢而后验调出来的。

因此，正文或方法部分必须说明权重来自研究问题优先级，而不是来自 baseline 结果。建议解释如下：

| Term group | 写作解释 |
|---|---|
| `f_thermal`, `f_sigma` | 论文核心是 thermal-aware mapping，因此峰值温度与温度不均衡是主要优化目标。 |
| `f_hot`, `f_dvfs`, `f_congestion` | 这些项刻画热风险、DVFS 节流和通信瓶颈，是系统级副作用，应纳入中等权重。 |
| `f_makespan` | 防止方法只降低温度却严重牺牲执行时间，因此性能项必须保持较高权重。 |
| `f_comm`, `f_energy` | 通信与能耗是系统级指标，但本文不是纯通信映射或纯能耗优化论文，因此权重低于核心热/性能项。 |
| `f_load` | 作为映射质量和负载分散的辅助约束，防止极端不均衡映射。 |

写作时不要暗示这些权重是“客观唯一”的。更稳妥的定位是：它们定义了本文关注的 full-system design objective。

## 3. Baseline 结果的解释边界

`Thermal-SA-TAS` 与 `CommAware-Heuristic` 不能写成“也在优化 full objective 但失败”。更准确的说法是：

- `Thermal-SA-TAS` 是 thermal/proxy-guided baseline，关注热安全与热分布，投影到 full objective 后整体通常低于 reference mapping，但仍弱于 `Full-GA`。
- `CommAware-Heuristic` 是 communication/congestion proxy-guided baseline，可能改善通信 proxy，却可能引入热、DVFS、makespan、能耗或负载均衡方面的系统级代价；因此在 full objective 下高于 reference mapping 并不等于算法实现无效，而是说明 narrow objective 的跨层副作用。
- 对 `CommAware-Heuristic` 的负面结果要写成“single-aspect optimization can degrade the full-system objective”，不要写成“该 baseline 没有意义”。
- 对 `Thermal-SA-TAS` 的结果要区分 mean 和 seed-level variation；如果个别 seed 接近或略差于 reference mapping，主文不要只写均值结论。

## 4. 更客观的评价方式

Composite score 可以作为主设计目标，但不能单独承担公平性。建议采用三层证据：

1. 九项原始指标或 normalized terms

   必须展示或汇总 `Tmax`、`sigma_T`、`hot PE`、`makespan`、`communication cost`、`congestion`、`DVFS penalty`、`load imbalance` 和 `total energy`。这些指标比单个加权 score 更透明，可用于解释每个 workload 的真实 trade-off。

2. Pareto / trade-off 分析

   补充材料可画二维 trade-off，例如：

   - `Tmax` vs `makespan`
   - `sigma_T` vs `total energy`
   - `hot PE` vs `makespan`
   - `communication cost` vs thermal risk
   - `congestion` vs `makespan`

   目的不是证明每项都最优，而是说明 `Full-GA` 在多目标空间中取得更均衡的系统级折中。

3. 权重敏感性分析

   建议至少准备几组预先定义的权重，而不是围绕结果后验调权：

   | Sensitivity setting | 用途 |
   |---|---|
   | thermal-prioritized | 当前主设定，突出热安全和热均匀性。 |
   | balanced-term | 九项 normalized terms 近似等权，检查是否依赖特定权重。 |
   | balanced-group | 热、性能、通信、负载、能耗五类目标等权，避免项数多的类别天然占优。 |
   | performance-prioritized | 提高 `makespan` 和 DVFS/energy 相关权重，检查性能优先场景。 |
   | communication-prioritized | 提高 `f_comm` 和 `f_congestion` 权重，检查通信优先场景。 |

   如果 `Full-GA` 在多数合理权重下仍保持优势，结论会比单一 composite score 更稳。如果某些通信优先权重下 `CommAware-Heuristic` 接近或超过 `Full-GA`，也不一定是坏事，可以作为 trade-off 诚实呈现。

## 5. 图表和正文建议

- 主文可以保留 full-objective comparable score 图，但图注要说明该 score 是本文 objective 下的 comparable score。
- 主文不要只放 composite score；应配套九项指标变化图或表。
- `Thermal-SA-TAS` 应画 error bar 或 seed dots，因为它有 seed 40-49 的多 seed 结果。
- `CommAware-Heuristic` 当前是 deterministic/single-run baseline，不应画成 10-seed 误差棒。
- `ReferenceMapping` 可以作为 anchor 出现在 Figure 2，但不要在 baseline method comparison 中写作一个 baseline method。
- 结论要按 workload 写，尤其是 VOPD 和 HNN 不能写成所有指标同步改善。
- HNN 应作为多目标 trade-off case：热点 PE 和部分热/通信/能耗指标改善，但 makespan 可能变差。

## 6. 推荐论文措辞

可以使用：

> The composite score is used as the optimization objective of the proposed simulator-in-the-loop mapper. To avoid relying solely on this weighted objective, we also report the underlying normalized terms and raw system metrics.

可以使用：

> The external baselines optimize narrower proxy objectives. Their full-objective scores therefore indicate how these mappings transfer to the proposed cross-layer system objective, rather than how well they optimize their own native proxy.

可以使用：

> We further test whether the ranking is robust under alternative weight settings, including balanced, thermal-prioritized, performance-prioritized, and communication-prioritized variants.

避免使用：

> The proposed method is objectively best under all criteria.

避免使用：

> CommAware-Heuristic fails because its score is higher than the initial mapping.

避免使用：

> The selected weights prove the superiority of the proposed method.
