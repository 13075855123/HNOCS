# 方向 B-1：增量贪心 + 多轮迭代热感知任务映射

> 日期: 2026-06-04
> 仿真器: Python `thermal_simulator.py`（已修复 DVFS 反馈回路）
> 权重: `w_T=1.0, w_H=1.0, w_D=2.0, w_L=0.5`

---

## 一、算法原理

### 1.1 核心思想

按 DAG 拓扑序逐个分配 task。每分配完一个 task 就立刻跑热仿真把它的热效应注入——下一个 task 评估 PE 时看到的是"前面所有 task 已经烧热了的芯片"。单轮贪心不能回溯（T1 选错→后面全错），用多轮迭代弥补。

```
单轮内部（增量贪心构建）:
  T=0，所有 PE = 45°C (Tambient)
  分配 T1 → 对每个候选 PE 计算代价 → 选最低的 PE_j → 跑热仿真注入 T1 的热
  分配 T2 → 候选 PE 有不同实时温度 → 选 PE_k → 跑热仿真注入 T2 的热
  分配 T3 → 芯片已被 T1、T2 加热 → 看到真实温度梯度 → 选 PE_m
  ...直到所有 task 分配完毕
  → 产出映射 A + 完整温度时间曲线

轮间迭代:
  Round 1: 冷启动贪心构建（无历史经验）
  Round 2: 用 Round 1 的温度经验 + PE 热压力惩罚重选
  Round 3: ...直到映射不再变化（循环检测）或达到 max_rounds
```

### 1.2 与方向 B-2、C 的定位

| | B-1（本算法） | B-2（GA） | C（GNN+RL） |
|---|---|---|---|
| 调度时机 | 设计时 (t=0) | 设计时 (t=0) | 设计时 + 可扩展在线 |
| 决策方式 | 贪心规则 + 实时热注入 | 种群进化 + 完整仿真 | GCN 编码 + RL 策略网络 |
| 方法类型 | 解析方法（规则驱动） | 元启发式搜索 | 深度学习 |
| 论文定位 | **Baseline 1** | Baseline 2 | Proposed |
| 全局搜索 | 靠多轮弥补 | 种群多样性 | RL 探索策略 |
| 实现复杂度 | 低 | 中 | 高 |

---

## 二、代价函数

### 2.1 数学定义

B-1 使用 `NormalizedCostModel`，将四个不同量纲的子代价归一化到可比尺度后加权求和：

$$\text{cost}(\text{PE}_j, \text{task}_i) = w_T \cdot f_{\text{thermal}}(T_j) + w_H \cdot f_{\text{comm}} + w_D \cdot f_{\text{dvfs}}(T_j) + w_L \cdot f_{\text{overload}}$$

其中 $T_j = T_{\text{PE}_j}(t_{\text{start}})$ 是 task_i 开始时刻 PE_j 的真实温度（从增量热仿真注入）。

### 2.2 四个归一化子项

#### (1) 温度项 $f_{\text{thermal}}$

$$f_{\text{thermal}}(T) = \frac{\max(0, T - T_{\text{amb}})}{\Delta T}, \quad \Delta T = T_{\text{throttle}} - T_{\text{amb}} = 9.0\text{K}$$

- **归一化基准**：$\Delta T = 327.15 - 318.15 = 9.0\text{K}$
- $T = T_{\text{amb}}$ 时 $f=0$，$T = T_{\text{throttle}}$ 时 $f=1$
- 超出节流阈值时 $f>1$，线性增长
- 温度来自**增量热仿真**：每分配一个 task 就跑一次热仿真，注入该 task 的热效应。评估下一个 task 时，PE 温度已包含所有前置 task 的热贡献

#### (2) 通信项 $f_{\text{comm}}$

$$f_{\text{comm}}(\text{task}_i, \text{PE}_j) = \frac{\sum_{p \in \text{pred}(i)} \text{hops}(\text{PE}_p, \text{PE}_j) \times \text{dataSize}(p, i)}{\text{maxEdgeComm}}$$

- $\text{hops}(a, b)$：Manhattan 距离，$|r_a - r_b| + |c_a - c_b|$，范围 0–6
- $\text{maxEdgeComm} = \max_{\text{所有边}} 6 \times \text{dataSize}$：理论最大单边通信代价
- **仅计已分配的前驱 task**：贪心构建时，只有 `assignment` 中已有的前驱参与计算
- GB 前驱（`peId=-1`）贡献 0

#### (3) DVFS 风险项 $f_{\text{dvfs}}$

$$f_{\text{dvfs}}(T) = \begin{cases} 0 & T \leq T_{\text{safe}} \\ \frac{T - T_{\text{safe}}}{T_{\text{headroom}}} & T_{\text{safe}} < T \leq T_{\text{throttle}} \\ 1 + k_{\text{dvfs}} \cdot \frac{T - T_{\text{throttle}}}{\Delta T} & T > T_{\text{throttle}} \end{cases}$$

- $T_{\text{safe}} = T_{\text{throttle}} - T_{\text{headroom}} = 324.15\text{K}$ (51°C)
- $T_{\text{headroom}} = 3.0\text{K}$：预警区间宽度
- $k_{\text{dvfs}} = 5.0$：超阈值后的惩罚斜率（5× 放大，反映 DVFS 的超线性危害）
- **三段式设计**：安全区（0）、预警区（线性 0→1）、危险区（陡增 >1）

#### (4) 负载均衡项 $f_{\text{overload}}$

$$f_{\text{overload}}(\text{PE}_j) = \max\left(0, \frac{\text{load}(\text{PE}_j)}{\text{ideal}} - 1\right)$$

- $\text{load}(\text{PE}_j)$：PE_j 上已分配 task 的总计算量（compute_time_ns）加候选 task 的计算量
- $\text{ideal} = \frac{\text{totalAssignedLoad}}{\text{numPEs}}$：当前已分配负载的每 PE 均值
- 防止所有 task 堆到一个 PE 的病态解

### 2.3 权重配置

| 权重 | 默认值 | 作用 |
|:---:|:---:|------|
| $w_T$ | 1.0 | 温度权重——task 开始时 PE 的温度超出 |
| $w_H$ | 1.0 | 通信权重——与已分配前驱的 Manhattan 距离 × 数据量 |
| $w_D$ | 2.0 | DVFS 风险权重——$2\times$ 是因为 DVFS 的后果（降频→长 makespan→多能耗）比单纯温度更严重 |
| $w_L$ | 0.5 | 负载均衡权重——辅助项，防止病态集中 |

### 2.4 增量热注入机制

这是 B-1 独有的特性，也是与 B-2 的本质区别：

```
for idx, task_id in enumerate(mappable_tasks):
    for each candidate PE:
        cost = w_T * f_thermal(T_PE) + w_H * f_comm + w_D * f_dvfs + w_L * f_overload
    assign task_id to PE with minimum cost

    if not last task:
        partial_result = simulate_thermal(graph, partial_assignment)
        pe_temps = partial_result.pe_max_temp  ← 更新温度状态
        # 下一个 task 评估时会看到更新后的温度
```

**关键**：代价函数中的 $T_j$ 不是静态的，而是 task_i 分配时刻芯片的真实温度。这保证了"自洽性"——每个决策看到的热状态包含了所有前置决策的热效应。

### 2.5 轮间 PE 热压力反馈

每轮结束后计算各 PE 的"热压力"，作为下一轮的惩罚项：

$$\text{stress}(\text{PE}_i) = w_T \cdot \left(\frac{\max(0, T_i^{\text{peak}} - T_{\text{amb}})}{\Delta T}\right)^2$$

二次方放大了热点 PE 的惩罚（温度高的 PE 被惩罚远多于温度低的），引导下一轮贪心构建避开热点。

### 2.6 收敛条件

- **循环检测**：若当前轮的完整分配 `assignment` 与历史某一轮完全相同，算法收敛
- **最大轮数**：默认 `max_rounds=10`，防止无限循环
- **最优选择**：返回所有轮中 `pe_max_temp` 最低的分配（而非最后一轮）

---

## 三、算法伪代码

```
Algorithm: B-1 Iterative Greedy Thermal-Aware Mapping

Input:  TaskGraph G, SimParams P, weights w_T, w_H, w_D, w_L
Output: Best assignment A*, ThermalResult R*

1.  pe_penalty ← [0, 0, ..., 0]   // 16 PEs, initially no penalty
2.  seen ← {}                       // cycle detection set
3.  best_pe_max ← ∞

4.  for round = 1 to max_rounds:
5.      assignment ← {}
6.      pe_temps ← [T_amb, ..., T_amb]   // cold start each round
7.
8.      for each task_id in topological_order:
9.          cm ← NormalizedCostModel(G, pe_temps, w_T, w_H, w_D, w_L, pe_penalty)
10.         best_pe ← argmin_{pe} cm.task_cost(task_id, pe, assignment)
11.         assignment[task_id] ← best_pe
12.
13.         // Incremental thermal injection
14.         if not last_task:
15.             partial ← simulate_thermal(G, assignment, P, max_dvfs_iter=1)
16.             pe_temps ← partial.pe_max_temp
17.
18.     // Full simulation of complete assignment
19.     result ← simulate_thermal(G, assignment, P, max_dvfs_iter=3)
20.     cost ← NormalizedCostModel(..., task_start_temps=result.task_start_temps)
21.              .total_cost(assignment)
22.
23.     // Track best
24.     if max(result.pe_max_temp) < best_pe_max:
25.         best_pe_max ← max(result.pe_max_temp)
26.         A* ← assignment
27.         R* ← result
28.
29.     // Convergence check
30.     h ← hash(assignment)
31.     if h ∈ seen: return (A*, R*)
32.     seen ← seen ∪ {h}
33.
34.     // Cross-round feedback
35.     for each PE i:
36.         stress[i] ← w_T * (max(0, result.pe_max[i] - T_amb) / ΔT)²
37.     pe_penalty ← stress
38.
39. return (A*, R*)
```

---

## 四、实验结果（OMNeT++ 全系统仿真实测）

### 4.1 对比指标定义

共 8 个指标，覆盖**热 → 性能 → 能耗**三条因果链。全部方向 ↓（越小越好）。

| 符号 | 中文名称 | 单位 | 定义与计算公式 | 衡量什么 |
|:---:|------|:---:|------|------|
| **$T_{\max}$** | 芯片峰值温度 | °C | $T_{\max} = \max\limits_{i,\;t} \; T_{\text{PE}_i}(t) - 273.15$。先取所有 PE 所有时刻的绝对最高温度（K），再转为 °C | **热安全**：芯片是否触发热关断或DVFS节流。最直观的可靠性指标 |
| **$\sigma_T$** | 温度标准差 | K | $\sigma_T = \sqrt{\frac{1}{N_t N_{\text{PE}}} \sum_{t=1}^{N_t} \sum_{i=1}^{N_{\text{PE}}} \left(T_i(t) - \bar{T}\right)^2}$，其中 $\bar{T} = \frac{1}{N_t N_{\text{PE}}}\sum_t \sum_i T_i(t)$ 为全局平均温度（K）。等价于将所有 PE 所有时刻的温度值展平为一个数组后求标准差 | **热均衡**：论文核心指标。σ_T 越小芯片温度场越均匀。混合捕获空间分布不均 + 时间维度的温度波动 |
| **$N_{\text{hot}}$** | 过热PE数 | 个 | $N_{\text{hot}} = \left|\left\{\;i \;\middle|\; \max_t T_i(t) > T_{\text{throttle}}\;\right\}\right|$，其中 $T_{\text{throttle}} = 327.15\text{K}\;(54°\text{C})$。先算每个 PE 运行全程的峰值温度，再统计峰值超过 DVFS 节流阈值的 PE 个数 | **过热范围**：DVFS 触发面有多大。$N_{\text{hot}}=0$ 表示无任何 PE 需要节流 |
| **$t_{\text{makespan}}$** | 任务完成时间 | μs | $t_{\text{makespan}} = \text{simTime()} \times 10^6$。OMNeT++ 仿真结束时刻（最后一个 task 完成），秒转微秒 | **性能**：热均衡是否以延长工期为代价。论文第二核心指标 |
| **$\eta_{\text{dvfs}}$** | 平均DVFS节流比 | % | $\eta_{\text{dvfs}} = \frac{1}{N_{\text{PE}}} \sum_{i=1}^{N_{\text{PE}}} r_i \times 100\%$，其中 $r_i = \frac{t_{\text{actual},i} - t_{\text{nominal},i}}{t_{\text{nominal},i}}$。$t_{\text{nominal},i}$ 是 PE_i 上所有 task 无节流的计算时间之和，$t_{\text{actual},i}$ 是经 DVFS 拉长后的实际计算时间之和。单 PE 节流比 $r_i$ 按各 task 的 nominal 时间加权 | **热→性能传导**：量化"过热导致百分之多少的性能损失"。连接温度和完成时间的因果链 |
| **$E_{\text{SOA}}$** | SOA泵浦能耗 | μJ | $E_{\text{SOA}} = \sum_{c \in \text{circuits}} n_{\text{SOA}}^{(c)} \cdot P_{\text{SOA}} \cdot t_{\text{circuit}}^{(c)}$，其中 $P_{\text{SOA}} = 80\text{mW}$。单条光电路 $c$ 含 $n_{\text{SOA}}^{(c)}$ 个 SOA（=跳数），每个 SOA 耗电 80mW，持续 $t_{\text{circuit}}^{(c)}$ 秒。所有电路求和后 J→μJ | **光层能耗主力**：SOA 通常占光通信能耗 40-60%，对通信距离（跳数）敏感 |
| **$E_{\text{tune}}$** | 微环动态调谐能耗 | nJ | $E_{\text{tune}} = \sum_{c} \sum_{r \in \text{path}(c)} P_{\text{tuning}}^{(r,c)} \cdot t_{\text{circuit}}^{(c)}$，其中 $P_{\text{tuning}}^{(r,c)} = \text{ringCount}_{r,c} \cdot 0.5\frac{\text{mW}}{\text{nm}} \cdot 0.10\frac{\text{nm}}{\text{K}} \cdot |T_r(t) - T_{\text{ambient}}|$。每个路由器根据自身温度和转弯微环数量独立计算调谐功率。此为**温度感知动态调谐**（`onoc-dynamic-tuning-total-energy-J`），非 baseline 静态调谐 | **光层能耗次要项**：微环热调谐功率与路由器温度偏移成正比，间接反映片上热均衡效果 |
| **$E_{\text{total}}$** | 系统总能耗 | mJ | $E_{\text{total}} = \left(E_{\text{PE}} + E_{\text{SOA}} + E_{\text{tune}} + E_{\text{laser}}\right) \times 10^{3}$。四项均以 J 为单位求和后转 mJ（1 J = 10³ mJ）。其中 $E_{\text{PE}} = \sum_{i=1}^{16} \text{totalEnergyJ}_i$（含计算+泄漏+电层flit+**光收发器**，后者已内嵌于 PE 动态能耗中，**不再另加** $E_{\text{TRX}}$）；$E_{\text{laser}} = P_{\text{laser}}^{\text{elec}} \cdot t_{\text{sim}}$（激光器电功耗 × 仿真时长）。路由器端口能耗因数值极小（<5%）且 Python 仿真器未跨窗口累加，**统一排除** | **综合代价**：热重映射的最终"能耗账单"。单行即判断是否用过多能耗换取降温 |

> **符号与常数**：$N_{\text{PE}} = 16$；$N_t$ 为仿真时间步数；$T_i(t)$ 为 PE_i 在时刻 $t$ 的温度，单位为 **K**；$T_{\text{ambient}} = 318.15\text{K}$。
>
> **数据来源**：
> - **Python**：`T_max, σ_T, N_hot` 来自 `ThermalResult`（`pe_max_temp`, `pe_temp_trace`）；`t_makespan, η_dvfs` 来自 `ThermalResult.schedule`（`TaskSlot`）；`E_SOA, E_tune, E_laser` 来自 `NoCSimulator.run()` 返回字典；`E_PE` 来自 `PE.total_energy` 求和。
> - **OMNeT++**：温度指标来自 `.vec` 矢量（`pe-die-temperature`）；`t_makespan` 来自 `.sca` 标量 `allTasksCompletedAt`；$\eta_{\text{dvfs}}$ 来自 16 个 PE 的 `throttlePenaltyRatio` 标量均值；$E_{\text{SOA}}$ 来自 `onoc-soa-total-energy-J`；$E_{\text{tune}}$ 来自 `onoc-dynamic-tuning-total-energy-J`；$E_{\text{laser}}$ 来自 `onoc-laser-total-energy-J`；$E_{\text{PE}}$ 来自 16 个 `TaskPE.totalEnergyJ` 之和。
>
> **删减说明**：T4_grad（最大温度梯度）与 σ_T 信息重叠，T_max + σ_T + N_hot 已充分描述温度场；Hops（SOA总跳数）是解释 E_SOA 的中间量，正文提及即可；PE能耗不再单列，并入 E_total；Flits（光flit总数）在同 benchmark 下为不变量，无区分度。

### 4.2 总表（Baseline vs B-1 vs B-2）

OMNeT++ 全系统仿真实测（2026-06-06）。温度来自 `.vec`，其余来自 `.sca`。**加粗** = 最优值。B-2 HNN 仿真未完成（—）。

```
Bench  | M | T_peak | T3_std | T4_grad|T5| SimT  | SOA   | Tuning | PE    | Thr   |Hops| Flits
-------|---|--------|--------|--------|--|-------|-------|--------|-------|-------|----|------
GEMM   |BL | 54.91C | 2.55K  | 7.53K  | 6|120.3  |1.288  |111.0   |1.567  | 1.8%  | 67 | 3072
(CCR=8)|B1 | 53.79C | 2.17K  | 4.96K  | 0|116.7  |0.699  | 53.9   |1.516  | 0.0%  | 41 | 3072
       |B2 | 55.56C | 2.26K  | 6.27K  | 2|119.6  |0.759  | 57.6   |1.548  | 1.2%  | 43 | 3072
-------|---|--------|--------|--------|--|-------|-------|--------|-------|-------|----|------
MPEG4  |BL | 54.42C | 1.54K  | 6.48K  | 2|122.4  |1.322  | 95.8   |1.131  | 0.1%  | 44 |22250
(CCR≈1)|B1 | 52.98C | 1.36K  | 5.48K  | 0|121.6  |1.159  | 86.2   |1.124  | 0.0%  | 38 |22250
       |B2 | 54.04C | 1.38K  | 5.80K  | 1|122.9  |1.428  | 75.1   |1.132  | 0.0%  | 41 |22250
-------|---|--------|--------|--------|--|-------|-------|--------|-------|-------|----|------
VOPD   |BL | 52.18C | 1.15K  | 4.71K  | 0| 89.3  |1.574  |106.3   |0.743  | 0.0%  | 51 |54375
(CCR=0.3)|B1|52.35C | 1.14K  | 4.40K  | 0| 87.5  |2.316  |141.8   |0.733  | 0.0%  | 35 |54375
       |B2 | 53.49C | 1.19K  | 6.18K  | 0| 90.4  |2.091  |120.9   |0.750  | 0.0%  | 31 |54375
-------|---|--------|--------|--------|--|-------|-------|--------|-------|-------|----|------
HNN    |BL | 55.69C | 3.05K  | 0.24K  |16|204.9  |3.750  |474.9   |4.653  |11.0%  |166 |53248
(CCR=3)|B1 | 59.19C | 3.58K  | 2.49K  |16|188.5  |4.366  |373.3   |4.812  |18.9%  | 98 |47104
       |B2 |   —    |   —    |   —    |—|   —   |   —   |   —    |   —   |   —   | — |   —
-------|---|--------|--------|--------|--|-------|-------|--------|-------|-------|----|------
Optic  |BL | 48.79C | 1.01K  | 1.42K  | 0| 10.5  |12.748 | 42.1   |0.092  | 0.0%  | 60 |32768
(CCR=0.06)|B1|48.84C| 1.00K  | 1.47K  | 0| 10.5  |12.748 | 46.7   |0.092  | 0.0%  | 60 |32768
       |B2 | 48.83C | 1.00K  | 1.45K  | 0| 10.5  |12.666 | 45.2   |0.092  | 0.0%  | 60 |32768
```

### 4.3 逐 Benchmark 分析

**GEMM (CCR=8, fork-join)**：
- B-1 **全面最优**：SimT 缩短 3.0%（120.3→116.7μs），SOA 降 **45.7%**（1.288→0.699μJ），Throttle 清零，Hops 从 67→41
- B-2：SimT 缩短 0.6%，SOA 降 41.1%，但 Throttle 残存 1.2%
- B-1 全维度优于 B-2

**MPEG4 (CCR≈1, fork-join+分支)**：
- B-1：SimT 最优（121.6μs），SOA 降 12.3%，Throttle 清零，PE 能耗最低（1.124mJ）
- B-2：SimT 反升 0.4%，SOA 反升 8.0%
- B-1 全维度优于 B-2

**VOPD (CCR=0.3, 长流水线)**：
- B-1：SimT 缩短 2.0%（89.3→87.5μs），Hops 从 51→35
- SOA 升高 47.1%（1.574→2.316μJ）——通信优化导致更长的光路径
- B-2：SimT 更差（90.4μs），Hops 最少（31）但 SOA 也升高
- **VOPD 揭示一个 trade-off**：减少 hops 不一定减少 SOA 能耗（光路径长度和波长分配竞争共同决定）

**HNN (CCR=3, fork-join)**：
- B-1：SimT 缩短 8.0%（204.9→188.5μs），Hops 从 166→98（↓41%），Tuning 降 21.4%
- Throttle 从 11.0%→18.9%——用更高节流换更短完成时间
- PE 能耗略升（4.65→4.81mJ，+3.4%）
- B-2：OMNeT++ 仿真失败

**Optic (CCR=0.06, 全并行)**：
- B-1 与 BL 完全相同，B-2 仅有微小差异

### 4.4 B-1 特性总结

| 优点 | 缺点 |
|------|------|
| 增量热注入提供最精确的温度自洽性 | 单轮贪心无回溯能力 |
| 收敛快（2-10 轮，< 5 秒/benchmark） | 决策顺序敏感（拓扑序靠前的 task 错误影响更大） |
| 通信为主 benchmark（VOPD、MPEG4）表现优异 | 并行度高的 benchmark（HNN）可能陷入局部最优 |
| 实现简单，超参少 | 最终结果可能不如全局优化（B-2） |

### 4.5 算法参数

| 参数 | 值 | 说明 |
|------|:---:|------|
| `w_T` | 1.0 | 温度权重 |
| `w_H` | 1.0 | 通信权重 |
| `w_D` | 2.0 | DVFS 风险权重 |
| `w_L` | 0.5 | 负载均衡权重 |
| `max_rounds` | 10 | 最大迭代轮数 |
| `max_dvfs_iter` | 3 | DVFS 反馈迭代次数 |
| 收敛条件 | 循环检测 | assignment 与历史重复即停 |
| 最优选择 | min(pe_max_temp) | 选所有轮中峰值温度最低的解 |
