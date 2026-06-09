# 热感知重映射 vs Baseline — 对比指标体系

> 日期: 2026-06-03
> 目标: 定义热感知重映射（B-1/B-2/C）与静态映射（baseline）对比的完整指标体系
> 仿真器: Python `thermal_simulator.py` + `noc_simulator.py`（优化），OMNeT++（最终验证）

---

## 因果链总览

热感知重映射改变 **task→PE 分配**，通过三条因果链影响最终结果：

```
重映射 → PE分配变化
  ├─ 链1: 温度分布更均匀 → DVFS节流减少 → 完成时间缩短（收益）
  ├─ 链2: 依赖task可能放得更远 → 通信跳数增加 → 网络能耗增加（代价）
  └─ 链3: 总能耗 = 链1收益 vs 链2代价 的博弈（综合）
```

指标体系需覆盖每条链的**每个环节**，确保能解释"为什么好/为什么不好"。

---

## 一、温度指标（直接优化目标）

重映射**直接改变**温度分布，是论文最核心的卖点。

| # | 指标 | 定义 | 数据来源 | 重要性 |
|:---:|------|------|:---:|------|
| T1 | **PE峰值温度** | $\max_{i,t} \; T_{\text{PE}_i}(t)$ | `ThermalResult.pe_max_temp` | ★★★★★ 最直观的热安全指标 |
| T2 | **PE平均温度** | $\frac{1}{N}\sum_i \overline{T}_{\text{PE}_i}$ | `ThermalResult.pe_avg_temp` | ★★★ 整体热状态 |
| T3 | **温度标准差** | $\sigma_T = \text{std}(T_{\text{PE}_i}(t))$ 取稳态时间平均 | 从 `pe_temp_trace` 计算 | ★★★★★ **"热均衡"的核心量化** |
| T4 | **最大温度梯度** | $\Delta T_{\max} = \max_{t}[\max_i T_i(t) - \min_i T_i(t)]$ | 从 `pe_temp_trace` 计算 | ★★★★ 论文最常用的热均匀性指标 |
| T5 | **超阈值PE数** | $|\{i : \max_t T_i(t) > T_{\text{throttle}}\}|$ | 从 `pe_temp_trace` 统计 | ★★★★ DVFS触发面 |
| T6 | **超阈值时间占比** | 各PE温度超过 $T_{\text{throttle}}$ 的累计时间 / 总时间 | 从 `pe_temp_trace` 统计 | ★★★ 区分"短暂超温"和"持续过热" |
| T7 | **Router峰值温度** | $\max_{i,t} \; T_{\text{R}_i}(t)$ | `ThermalResult.router_max_temp` | ★★★ 光器件调谐功率直接相关 |

### 可视化建议

- **4×4热力图**：baseline vs remapped，取仿真中间时刻 + 结束时刻各一张（共4张子图）
- **最热PE温度曲线**：baseline vs B-1 vs B-2 vs C 叠在同一张图上

---

## 二、性能指标（温度→性能的传导）

温度更均匀 → DVFS少触发 → 完成更快。这是热均衡的**收益体现**。

| # | 指标 | 定义 | 数据来源 | 重要性 |
|:---:|------|------|:---:|------|
| P1 | **总完成时间 (makespan)** | 最后一个task完成的时间 | `ThermalResult.sim_end_time` | ★★★★★ 论文第二核心指标 |
| P2 | **加速比** | $\text{makespan}_{\text{baseline}} / \text{makespan}_{\text{remapped}}$ | 计算 | ★★★★★ 一句话总结性能收益 |
| P3 | **DVFS总罚时** | $\sum_k (\text{actualWork}_k \times \text{dvfsScale}_k - \text{actualWork}_k)$ | 从 `TaskSlot` 计算 | ★★★★ 量化"节流损失了多少性能" |
| P4 | **DVFS触发task比例** | 有节流的task数 / 总task数 | 从 `TaskSlot` 统计 | ★★★ 节流的普遍程度 |
| P5 | **平均DVFS因子** | $\overline{\text{dvfsScale}}$ 所有task | 从 `TaskSlot` 统计 | ★★★ 节流平均严重程度 |
| P6 | **最大DVFS因子** | $\max(\text{dvfsScale})$ | 从 `TaskSlot` 统计 | ★★★ 最严重热点对单个task的影响 |
| P7 | **每PE计算负载** | 每个PE上分配的task总计算量 | 从mapping统计 | ★★ 辅助解释温度分布 |

### 可视化建议

- **完成时间柱状图**：5 benchmark × 4方法（baseline / B-1 / B-2 / C），每组一个cluster
- **DVFS罚时堆叠图**：每个PE的罚时贡献占比（baseline vs remapped）

---

## 三、通信指标（性能代价）

热均衡可能把依赖task放得更远，这是**代价侧**。

| # | 指标 | 定义 | 数据来源 | 重要性 |
|:---:|------|------|:---:|------|
| C1 | **总通信代价** | $\sum_{(p,i) \in E} \text{hops}(\text{PE}_p, \text{PE}_i) \times \text{dataSize}(p,i)$ | `CostModel.cost_breakdown()["comm_cost"]` | ★★★★★ 量化重映射引入的通信开销 |
| C2 | **归一化通信代价** | 总通信代价 / 总数据量 | 计算 | ★★★★ 跨benchmark可比 |
| C3 | **平均通信跳数** | 总跳数 / 通信边数 | 计算 | ★★★ 单次通信的平均距离 |
| C4 | **光flit总数** | 所有光电路传输的总flit数 | `NoCSimulator.stats()["ofl"]` | ★★★ 直接影响光收发器能耗 |
| C5 | **SOA总跳数** | 所有光电路SOA跳数累加 | `NoCSimulator.stats()["soa_total_circuit_hops"]` | ★★★ 直接影响SOA能耗 |
| C6 | **通信跳数分布** | 直方图：1-hop / 2-hop / ... / 6-hop 通信的占比 | 从mapping统计 | ★★ 通信模式的结构性变化 |

### 可视化建议

- **散点图（核心）**：x轴=总通信代价，y轴=PE峰值温度。每个解一个点（baseline + B-1每轮 + B-2帕累托前沿 + C推理结果）——这张图是**论文最重要的trade-off可视化**

---

## 四、能耗指标（综合结果）

温度影响DVFS→影响完成时间→影响静态能耗；通信影响光层动态能耗。

| # | 指标 | 定义 | 数据来源 | 重要性 |
|:---:|------|------|:---:|------|
| E1 | **PE静态能耗** | $\sum_i P_{\text{idle}} \times t_{\text{idle},i} + P_{\text{compute}} \times t_{\text{compute},i}$ | Python 累加计算 | ★★★★ 受完成时间主导 |
| E2 | **PE动态能耗** | 电层flit收发能耗（若涉及电层通信） | `NoCSimulator.stats()` | ★★ |
| E3 | **光收发器能耗** | flit总数 × 40 pJ/flit | flit总数 × 40pJ | ★★★ |
| E4 | **SOA能耗** | $\sum \text{soaCount} \times 80\text{mW} \times \text{duration}$ | `NoCSimulator.stats()["soa_total_energy_J"]` | ★★★★ 光层能耗主导项 |
| E5 | **调谐能耗** | $\sum \text{tuningPower} \times \text{duration}$ | `NoCSimulator.stats()["dynamic_tuning_total_energy_J"]` | ★★★ 受ΔT和电路持续时间影响 |
| E6 | **激光器能耗** | 5mW × simTime | `NoCSimulator.stats()["laser_total_energy_J"]` | ★★★ 与完成时间成正比 |
| E7 | **总能耗** | PE + Router + SOA + Tuning + Laser + Trx | 求和 | ★★★★★ **最终综合评判指标** |

### 可视化建议

- **堆叠柱状图**：总能耗分解（baseline vs B-1 vs B-2 vs C，5 benchmark各一组）

---

## 五、综合权衡指标

| # | 指标 | 定义 | 为什么重要 |
|:---:|------|------|------|
| TR1 | **热-通信帕累托前沿** | 以通信代价为x、峰值温度为y，标出所有非支配解 | B-2(GA)可输出一组解而非单个解，展示trade-off空间 |
| TR2 | **综合代价函数值** | $w_T \times \text{thermal} + w_H \times \text{comm}$ | B-1/B-2/C的统一优化目标，验证各方法是否真的降低了目标 |
| TR3 | **边际降温成本** | $\Delta\text{comm} / \Delta T_{\text{peak}}$ | "降1°C需要多走多少跳"，审稿人喜欢的边际分析 |
| TR4 | **负载均衡度** | PE计算负载的标准差 / 平均值 | 辅助解释温度分布——温度均匀是否仅因负载均匀？ |

---

## 六、建议的论文图表清单

| # | 类型 | 内容 | 涉及指标 | 定位 |
|:---:|:---:|------|------|:---:|
| 表1 | 汇总表 | 5 benchmark × 4方法 × 6核心指标 | T1, T4, P1, C1, E7, P3 | 一表定全篇 |
| 图1 | 热力图 | 4×4网格温度分布（baseline vs best remapped），取2-3个时间快照 | T1, T4 | 最直观的热均衡可视化 |
| 图2 | 曲线图 | 最热PE的温度-时间曲线（baseline vs B-1 vs B-2 vs C叠图） | T1, T6 | 温度动态演化 |
| 图3 | 柱状图 | 完成时间对比（5 benchmark × 4方法） | P1, P2 | 性能收益 |
| 图4 | 散点图 | **通信代价 vs PE峰值温度** trade-off | C1, T1, TR1 | **论文核心图** |
| 图5 | 堆叠柱状图 | 总能耗分解（baseline vs remapped） | E1-E7 | 能耗全景 |
| 表2 | 细节表 | 单一benchmark(如HNN)的逐PE温度+节流统计 | T5, T6, P5, P6 | 深入分析 |

---

## 七、各Benchmark预期对比重点

不同benchmark的热特性不同，每个应侧重不同的指标：

| Benchmark | CCR | 最关注的指标 | 预期效果 |
|-----------|:---:|------|------|
| **HNN** | 3 | T1/T4/P3（DVFS重灾区） | 重映射收益最大：16 PE全部超温→热均衡后显著减少节流 |
| **GEMM** | 8 | T1/T4/P3（DVFS次重灾区） | 类似HNN但幅度稍小（计算量小一些） |
| **MPEG4** | 1 | P1/C1（平衡点） | 热均衡 vs 通信代价的取舍最微妙 |
| **VOPD** | 0.3 | C1/T1（通信为主） | 长流水线串行依赖，重映射空间有限 |
| **Optic** | 0.06 | T1/T4（热学观察） | 全并行无依赖，重映射可自由分配但task极短(1μs)，热效应微弱 |

---

## 八、对比流程

```
Step 1: Python 热仿真器
  baseline_mapping = {从CSV读取的静态分配}
  remapped_mapping = B-1/B-2/C 产出的分配
  
  for each mapping:
      result = thermal_simulator.simulate(mapping, task_graph)
      → ThermalResult (温度 + 时序 + DVFS)
      → CostModel.cost_breakdown → 通信代价

Step 2: 指标计算
  从 ThermalResult + CostModel → 计算 T1-T7, P1-P7, C1-C6, E1-E7, TR1-TR4

Step 3: OMNeT++ 最终验证（仅对最优解）
  将 remapped_mapping 写回 CSV → 跑 OMNeT++ 仿真一次
  → 对比 Python 预测值 vs OMNeT++ 实测值
  → 验证温度/时间/能耗偏差在可接受范围内（≤2%时间, ≤1K温度）
```
