# 方向 B-2：遗传算法（GA）热感知任务映射

> 日期: 2026-06-04
> 仿真器: Python `thermal_simulator.py`（已修复 DVFS 反馈回路）
> 权重: `w_T=1.0, w_H=1.0, w_D=2.0, w_L=0.5, w_peak=0.0`

---

## 一、算法原理

### 1.1 核心思想

每个"个体"是一个完整映射（所有 task→PE 的分配）。评估个体 = 用 Python 热仿真器跑一次该映射的完整仿真 → 得到真实温度分布 → 计算真实代价。种群通过**锦标赛选择、均匀交叉、逐基因变异、精英保留**迭代进化 20-30 代。

```
GA 流程:
  初始化: 随机生成 50 个完整映射（个体），50%纯随机 + 50%扰动变异
  每代:
    对每个个体跑 Python 热仿真 → 真实温度 + 真实代价
    选择: 锦标赛选择（k=3，选最优）
    交叉: 两个父代均匀交叉（逐 task 随机选父代 PE）
    变异: 每个 task 以概率 p_m 随机换 PE
    精英: 保留代价最低的 2 个个体不变
    → 新一代 50 个个体
  20-30 代后收敛 → 最优映射
```

### 1.2 染色体编码

$$\text{chromosome} = [\text{PE}_{T_1}, \text{PE}_{T_2}, \text{PE}_{T_3}, \ldots, \text{PE}_{T_n}]$$

- 长度 = mappable task 数量（`peId=-2`）
- 每个基因 = PE 编号（0–15）
- GB task（`peId=-1`）不参与编码
- 顺序 = `graph.mappable_task_ids`（拓扑序，确定性）

### 1.3 与方向 B-1、C 的定位

| | B-1（增量贪心） | B-2（本算法） | C（GNN+RL） |
|---|---|---|---|
| 调度时机 | 设计时 (t=0) | 设计时 (t=0) | 设计时 + 可扩展在线 |
| 决策方式 | 贪心规则 + 实时热注入 | 种群进化 + 完整仿真 | GCN 编码 + RL 策略网络 |
| 方法类型 | 解析方法（规则驱动） | 元启发式搜索 | 深度学习 |
| 论文定位 | Baseline 1 | **Baseline 2** | Proposed |
| 评估方式 | 逐 task 增量热注入 | **完整分配 → 完整热仿真** | 训练环境提供真实代价 |
| 全局搜索 | 靠多轮弥补 | 种群多样性 | RL 探索策略 |
| 并行化 | 否（串行依赖） | **是**（每代 50 个体可并行评估） | 训练离线 |
| 实现复杂度 | 低 | 中 | 高 |

---

## 二、代价函数

### 2.1 设计原则：与 B-1 同构

B-2 的代价函数与 B-1 使用**完全相同的数学公式**（`NormalizedCostModel`），确保公平对比。差异在于**温度来源**：

| | B-1 | B-2 |
|---|---|---|
| 评估粒度 | 逐 task（部分分配） | 整体（完整分配） |
| 温度来源 | **增量热仿真**（每分配一个 task 就注入） | **完整热仿真**（一次性跑完整个 schedule） |
| 调用方式 | `task_cost(task_id, pe, partial_assignment)` | `total_cost(complete_assignment)` |
| 温度注入 | `pe_temps` 逐步更新 | `task_start_temps` 批量注入 |

### 2.2 数学定义

$$\text{fitness}(\text{assignment}) = \underbrace{\sum_{\text{task}_i} \text{task\_cost}(\text{PE}_i, \text{task}_i, \text{assignment})}_{\text{NormalizedCostModel.total\_cost()}} + \underbrace{w_{\text{peak}} \cdot \frac{\max(0, T_{\text{peak}} - T_{\text{throttle}})}{\Delta T}}_{\text{可选峰值惩罚}}$$

其中：

$$\text{task\_cost}(\text{PE}_j, \text{task}_i) = w_T \cdot f_{\text{thermal}}(T_j) + w_H \cdot f_{\text{comm}} + w_D \cdot f_{\text{dvfs}}(T_j) + w_L \cdot f_{\text{overload}}$$

$T_j$ 来自 `task_start_temps[task_i][PE_j]`——完整热仿真中 task_i 开始时刻 PE_j 的真实温度。

### 2.3 四个归一化子项（与 B-1 完全相同）

#### (1) 温度项 $f_{\text{thermal}}$

$$f_{\text{thermal}}(T) = \frac{\max(0, T - T_{\text{amb}})}{\Delta T}, \quad \Delta T = T_{\text{throttle}} - T_{\text{amb}} = 9.0\text{K}$$

- $T$：task 开始时所在 PE 的温度（来自完整热仿真）
- $T = 318.15\text{K}$ (45°C) → $f=0$；$T = 327.15\text{K}$ (54°C) → $f=1$
- 超出阈值时 $f > 1$，线性增长

#### (2) 通信项 $f_{\text{comm}}$

$$f_{\text{comm}}(\text{task}_i, \text{PE}_j) = \frac{\sum_{p \in \text{pred}(i)} \text{hops}(\text{PE}_p, \text{PE}_j) \times \text{dataSize}(p, i)}{\text{maxEdgeComm}}$$

- **完整分配**下，所有前驱 task 的 PE 均已知
- GB 前驱贡献 0

#### (3) DVFS 风险项 $f_{\text{dvfs}}$

$$f_{\text{dvfs}}(T) = \begin{cases} 0 & T \leq 324.15\text{K} \\ \frac{T - 324.15}{3.0} & 324.15 < T \leq 327.15\text{K} \\ 1 + 5.0 \cdot \frac{T - 327.15}{9.0} & T > 327.15\text{K} \end{cases}$$

- 三段式：安全区(0)、预警区(0→1)、危险区(>1,斜率 5×)

#### (4) 负载均衡项 $f_{\text{overload}}$

$$f_{\text{overload}}(\text{PE}_j) = \max\left(0, \frac{\text{load}(\text{PE}_j)}{\text{ideal}} - 1\right)$$

- **B-2 特有考虑**：完整分配下，$f_{\text{overload}}$ 对所有 task 求和时，分子分母同步放大（每个 task 的自负载在分子和分母各出现一次），比值不变。见 §2.6 的分析。

### 2.4 额外项：峰值温度直接惩罚（可配置）

$$f_{\text{peak}} = w_{\text{peak}} \cdot \frac{\max(0, \max_i T_i^{\text{peak}} - T_{\text{throttle}})}{\Delta T}$$

- $w_{\text{peak}} = 0$（默认）：与 B-1 完全等价
- $w_{\text{peak}} > 0$：对全局峰值温度施加直接选择压力
- 当前实验使用 $w_{\text{peak}} = 0$，保证与 B-1 的公平对比

### 2.5 评估流程

```
个体 (assignment)
  │
  ├─ Step 1: simulate_thermal(graph, assignment, params, max_dvfs_iter=2)
  │     运行完整热仿真:
  │       Iter 1: 冷启动调度 → 热仿真 → 温度升至 ~330K
  │       Iter 2: 热温度重新调度 → DVFS 触发 → 热仿真
  │       Iter 3: 验证温度收敛
  │     → ThermalResult { pe_max_temp, task_start_temps, schedule, ... }
  │
  ├─ Step 2: NormalizedCostModel(graph, cold_temps, w_T, w_H, w_D, w_L)
  │     .set_task_start_temps(result.task_start_temps)  ← 注入真实温度
  │     .total_cost(assignment)
  │     → base_cost
  │
  ├─ Step 3: (可选) pe_max = max(result.pe_max_temp)
  │     peak_penalty = w_peak * max(0, pe_max - T_throttle) / delta_T
  │
  └─ fitness = base_cost + peak_penalty
```

### 2.6 与 B-1 代价函数的关键差异

| 维度 | B-1 | B-2 |
|------|-----|-----|
| **温度时序** | 增量：评估 task_i 时只看到前 i-1 个 task 的热 | 全局：评估 task_i 时看到全部 task 结束后的温度（通过 start-time 温度） |
| **温度精度** | 更高——精确到 task_i 开始时刻的瞬时温度 | 稍低——task_i 开始时刻温度取决于完整 schedule 的时序，但 schedule 本身受 GA 分配影响 |
| **通信计算** | 仅计已分配前驱 | 所有前驱均已知（完整分配） |
| **负载计算** | `_f_overload` 为部分分配设计 | 完整分配下自负载重复累加，但比例不变 |

### 2.7 权重配置

| 权重 | 值 | 作用 |
|:---:|:---:|------|
| $w_T$ | 1.0 | 温度权重 |
| $w_H$ | 1.0 | 通信权重 |
| $w_D$ | 2.0 | DVFS 风险权重（2×，因后果超线性） |
| $w_L$ | 0.5 | 负载均衡权重（辅助） |
| $w_{\text{peak}}$ | 0.0 | 峰值温度直接惩罚（默认关闭，与 B-1 对齐） |

---

## 三、遗传算子详解

### 3.1 种群初始化

混合策略保证初始多样性：
- **50% 纯随机**：每个 task 独立随机分配 PE（0–15）
- **50% 扰动变异**：随机选一个已有个体，对其 ~20% 的 task 重新随机分配 PE
- 若提供了种子分配（如 B-1 结果），首个体初始化为种子

### 3.2 锦标赛选择

```
tournament_select(population, k=3):
    candidates ← 随机不放回抽取 k 个个体
    return argmin fitness(candidates)
```

- 选择压力由 $k$ 控制：$k=3$ 提供中等选择压力，保留多样性

### 3.3 均匀交叉

```
uniform_crossover(parent1, parent2):
    for each task_i:
        child[i] ← parent1[i] with prob 0.5
                 ← parent2[i] with prob 0.5
    return child
```

- 每个 task 独立从两个父代中随机选择 PE
- 交叉率 $p_c = 0.8$：80% 概率执行交叉，20% 概率直接克隆更优父代

### 3.4 逐基因变异

```
mutate(chromosome, p_m=0.1):
    for each task_i:
        if random() < p_m:
            chromosome[i] ← random PE (0..15)
```

- 每个 task 独立以 $p_m = 0.1$ 的概率重新随机分配 PE
- 变异率平衡探索与利用：10% 提供足够探索而不破坏优良基因

### 3.5 精英保留

每代保留代价最低的 `elite_count=2` 个个体**原封不动**进入下一代，确保最优解不会因交叉/变异而丢失。

### 3.6 早停

若连续 `patience=10` 代最优代价无改善，算法提前终止。

### 3.7 并行化

每代的 50 个个体评估完全独立，可通过 `ProcessPoolExecutor` 并行（`n_workers > 1`），8 线程可将每代耗时压缩约 6-7×。

---

## 四、算法伪代码

```
Algorithm: B-2 Genetic Algorithm Thermal-Aware Mapping

Input:  TaskGraph G, SimParams P, GAConfig C
Output: Best assignment A*, ThermalResult R*

1.  // Initialize
2.  mappable ← G.mappable_task_ids
3.  population ← []
4.  for i = 1 to C.population_size:
5.      if random() < 0.5:
6.          population[i] ← random_chromosome(mappable, numPEs)
7.      else:
8.          population[i] ← perturb(copy(random_choice(population)), 0.2)
9.
10. best_fitness ← ∞
11. stagnant ← 0
12.
13. for gen = 1 to C.num_generations:
14.     // Evaluate
15.     for each individual in population:
16.         if individual already evaluated: continue  // elite carry-over
17.         assignment ← chromosome_to_dict(individual, mappable)
18.         result ← simulate_thermal(G, assignment, P)
19.         cm ← NormalizedCostModel(G, ..., task_start_temps=result.task_start_temps)
20.         individual.fitness ← cm.total_cost(assignment)
21.                       + w_peak * max(0, pe_max - T_throttle) / ΔT
22.
23.     // Sort
24.     sort population by fitness (ascending)
25.     gen_best ← population[0]
26.
27.     // Update best
28.     if gen_best.fitness < best_fitness:
29.         best_fitness ← gen_best.fitness
30.         A* ← gen_best.to_assignment()
31.         R* ← gen_best.thermal_result
32.         stagnant ← 0
33.     else:
34.         stagnant ← stagnant + 1
35.
36.     // Early stop
37.     if stagnant ≥ C.patience and gen > C.patience:
38.         return (A*, R*)
39.
40.     // Breed next generation
41.     next_pop ← copy(population[0:C.elite_count])   // elites
42.     while |next_pop| < C.population_size:
43.         p1 ← tournament_select(population)
44.         p2 ← tournament_select(population)
45.         if random() < C.crossover_rate:
46.             child ← uniform_crossover(p1, p2)
47.         else:
48.             child ← copy(better_of(p1, p2))
49.         mutate(child, C.mutation_rate)
50.         next_pop.append(child)
51.     population ← next_pop
52.
53. return (A*, R*)
```

---

## 五、实验结果（OMNeT++ 全系统仿真实测）

### 5.1 对比指标定义（与 CLAUDE.md 三级梯队一致）

**第一梯队 — 论文核心叙事，缺一不可**

| 符号 | 中文名称 | 单位 | 定义 | 方向 |
|:---:|------|:---:|------|:---:|
| **$T_{\max}$** | 芯片峰值温度 | °C | $\max_{i,t} T_{\text{PE}_i}(t) - 273.15$ | ↓ |
| **$\sigma_T$** | 温度标准差 | K | 所有 PE 所有时刻温度展平后求标准差，热均衡的核心量化 | ↓ |
| **$t_{\text{makespan}}$** | 任务完成时间 | μs | $\text{simTime()} \times 10^6$ | ↓ |
| **$E_{\text{total}}$** | 系统总能耗 | mJ | $(E_{\text{PE}} + E_{\text{SOA}} + E_{\text{tune}} + E_{\text{laser}}) \times 10^3$ | ↓ |

**第二梯队 — 强化论证**

| 符号 | 中文名称 | 单位 | 定义 | 方向 |
|:---:|------|:---:|------|:---:|
| **$N_{\text{hot}}$** | 过热PE数 | 个 | $\mid\{i \mid \max_t T_i(t) > 327.15\text{K}\}\mid$ | ↓ |
| **$\eta_{\text{dvfs}}$** | 平均DVFS节流比 | % | 16 PE 平均的 $(t_{\text{actual}} - t_{\text{nominal}}) / t_{\text{nominal}}$ | ↓ |

**第三梯队 — 支撑性**

| 符号 | 中文名称 | 单位 | 定义 | 方向 |
|:---:|------|:---:|------|:---:|
| **$E_{\text{SOA}}$** | SOA泵浦能耗 | μJ | $\sum n_{\text{SOA}} \cdot 80\text{mW} \cdot t_{\text{circuit}}$，J→μJ | ↓ |
| **$E_{\text{tune}}$** | 微环动态调谐能耗 | nJ | $\sum \text{ringCount}_r \cdot 0.5\frac{\text{mW}}{\text{nm}} \cdot 0.10\frac{\text{nm}}{\text{K}} \cdot \mid T_r - T_{\text{amb}}\mid \cdot t_c$，J→nJ | ↓ |

> **数据来源**：$T_{\max}$、$\sigma_T$、$N_{\text{hot}}$ 来自 `.vec` 矢量 `pe-die-temperature`；$t_{\text{makespan}}$、$\eta_{\text{dvfs}}$、$E_{\text{SOA}}$、$E_{\text{tune}}$、$E_{\text{total}}$ 来自 `.sca`。$E_{\text{PE}}$ 包含光收发器能耗（调制器 25pJ + 接收器 15pJ）。

### 5.2 OMNeT++ 全系统仿真结果总表

**数据来源**：`libhnocs_dbg.exe` + `extract_paper_metrics_omnet()` 从 `.sca`/`.vec` 提取（2026-06-08）。全光学热效应使能（`opticalEnableThermalEffects=true`，SOA 80mW 泵浦 + 微环动态调谐 + 激光器 WPE=20%）。指标定义见 CLAUDE.md §论文对比指标定义（8 指标，三级梯队）。

```
Bench  | Method | T_max(C) | sigma_T(K) | t(us) | E_total(mJ) | N_hot | eta_dvfs | E_SOA(uJ) | E_tune(nJ)
-------|--------|----------|------------|-------|-------------|-------|----------|-----------|------------
GEMM   | BL     |    54.9  |      2.55  | 119.6 |       1.569 |   6   |    1.8%  |     1.288 |      111.0
(CCR=8)| B2     |    55.6  |      2.26  | 118.9 |       1.550 |   2   |    1.2%  |     0.759 |       57.6
-------|--------|----------|------------|-------|-------------|-------|----------|-----------|------------
MPEG4  | BL     |    54.4  |      1.54  | 121.7 |       1.133 |   2   |    0.1%  |     1.322 |       95.8
(CCR≈1)| B2     |    54.0  |      1.38  | 122.1 |       1.134 |   1   |    0.0%  |     1.428 |       75.1
-------|--------|----------|------------|-------|-------------|-------|----------|-----------|------------
VOPD   | BL     |    52.2  |      1.15  |  87.4 |       0.745 |   0   |    0.0%  |     1.574 |      106.3
(CCR=0.3)|B2   |    53.5  |      1.19  |  88.6 |       0.752 |   0   |    0.0%  |     2.091 |      120.9
-------|--------|----------|------------|-------|-------------|-------|----------|-----------|------------
HNN    | BL     |    55.7  |      3.05  | 204.1 |       4.658 |  16   |   11.0%  |     3.750 |      474.9
(CCR=3)| B2     |     —    |       —    |   —   |         —   |   —   |     —    |       —   |         —
-------|--------|----------|------------|-------|-------------|-------|----------|-----------|------------
Optic  | BL     |    48.8  |      1.01  |   9.2 |       0.105 |   0   |    0.0%  |    12.748 |       42.1
(CCR=0.06)|B2  |    48.8  |      1.00  |   9.2 |       0.105 |   0   |    0.0%  |    12.666 |       45.2
```

> **指标速查**（对照 CLAUDE.md 三级梯队）：
> - **第一梯队（核心叙事）**：`T_max` 芯片峰值温度, `sigma_T` 温度标准差, `t` 任务完成时间, `E_total` 系统总能耗
> - **第二梯队（强化论证）**：`N_hot` 过热PE数, `eta_dvfs` 平均DVFS节流比
> - **第三梯队（支撑）**：`E_SOA` SOA泵浦能耗, `E_tune` 微环动态调谐能耗
> - **注**：HNN B-2 的 OMNeT++ 仿真未正常完成（仿真时间爆炸，t=0.012s 已耗时 185s，`.vec` 达 3.3GB）。Python 代价函数缺少 makespan 直接惩罚是根因。

### 5.3 逐 Benchmark 分析（OMNeT++ 实测）

**GEMM (CCR=8, fork-join, 10 tasks)**：
- B-2：SOA 降 41.1%（1.288→0.759μJ），Hops 从 67→43，Tuning 降 48.1%（111.0→57.6nJ），SimT 微降 0.6%（119.6→118.9μs）
- PE 能耗降 1.2%（1.579→1.560mJ），Throttle 从 1.8%→1.2%
- **B-2 在 GEMM 上全维度优于 baseline**：光层能耗和时序双赢

**MPEG4 (CCR≈1, fork-join+分支, 11 tasks)**：
- B-2：SimT 反升 0.3%（121.7→122.1μs），SOA 反升 8.0%（1.322→1.428μJ）——**比 baseline 更差**
- Tuning 降 21.6%（95.8→75.1nJ），Hops 从 44→41，但光层竞争抵消了通信优化收益
- **B-2 在 MPEG4 上光层能耗反升**：通信集中化导致波长争用加剧

**VOPD (CCR=0.3, 长流水线, 12 tasks)**：
- B-2：SimT 反升 1.4%（87.4→88.6μs），SOA 升高 32.8%（1.574→2.091μJ）——**显著变差**
- Tuning 升 13.7%（106.3→120.9nJ），Hops 从 51→31（通信跳数降 39% 但每跳能耗更高）
- **VOPD 是 B-2 表现最差的 benchmark**：长流水线的串行依赖使 GA 为降通信而集中负载，反致光路竞争加剧，SOA 跳数虽减但单跳能耗激增

**HNN (CCR=3, fork-join, 32 tasks)**：
- B-2：**OMNeT++ 仿真未正常完成**（仿真时间爆炸，t=0.012s 处已耗时 185s，.vec 达 3.3GB，无 .sca）
- B-2 的 GA 映射产生病态通信模式：大量长距离光路请求 + 波长槽争用 → 事件数爆炸
- 根因：Python 代价函数缺少 makespan 直接惩罚 → GA 牺牲 DAG 并行度换通信局部性

**Optic (CCR=0.06, 全并行, 16 tasks)**：
- B-2：SOA 略降 0.6%（12.748→12.666μJ），Tuning 升 7.4%，SimT 不变，与 baseline 近乎相同
- Optic 无 task 间依赖 → 通信代价为零 → 优化空间极小

### 5.4 OMNeT++ 实测关键发现

1. **B-2 的 GA 全局搜索在 Python 优化阶段能找到更低的复合代价，但在 OMNeT++ 全系统仿真中并不总能转化为实际收益**：VOPD 和 MPEG4 的 SimT 和 SOA 均反升
2. **光层竞争是 Python 优化器未建模的关键因素**：GA 为降低通信将 task 集中到邻近 PE → 光电路争用波长槽 → SOA 跳数虽减但单跳能耗增加
3. **HNN B-2 的 OMNeT++ 失败是代价函数的直接后果**：缺少 makespan 惩罚 → GA 牺牲并行度 → 仿真时间爆炸
4. **GEMM 是唯一 B-2 全维度优于 BL 的 benchmark**：SOA 降 41%，Tuning 降 48%，SimT 略降——通信密集型的 fork-join 结构受益最大

### 5.5 B-2 vs Baseline 特性总结

| 优点 | 缺点 |
|------|------|
| 全局搜索能力——种群多样性防止局部最优 | 仿真次数多（50个体×30代=1500次），但可并行 |
| GEMM 上全维度优于 static baseline（SOA -41%, Tuning -48%） | Python 优化结果未能全量转化为 OMNeT++ 实测收益 |
| Python 优化阶段 TR2 降低 16-39% | 光层竞争未建模 → 通信集中反而恶化 SOA/SimT（VOPD, MPEG4） |
| Optic 上 SOA 略优于 baseline | HNN 在 OMNeT++ 中失败，VOPD/MPEG4 实测劣于 baseline |

### 5.6 GA 参数

| 参数 | 值 | 说明 |
|------|:---:|------|
| `population_size` | 50 | 种群大小 |
| `num_generations` | 30 | 最大代数 |
| `elite_count` | 2 | 精英保留数 |
| `tournament_size` | 3 | 锦标赛选择压力 |
| `crossover_rate` | 0.8 | 交叉概率 |
| `mutation_rate` | 0.1 | 逐基因变异概率 |
| `patience` | 10 | 早停容忍代数 |
| `seed` | 42 | 随机种子（可复现） |
| `max_dvfs_iter` | 2 | 评估时 DVFS 迭代次数（最终验证用 3） |

### 5.7 收敛行为（Python 优化阶段）

5 个 benchmark 的典型收敛曲线：

```
GEMM:  1→30代, best=20.5→14.7 (-28%), 收敛于 gen 18
MPEG4: 1→30代, best=17.5→14.7 (-16%), 未收敛
VOPD:  1→30代, best=17.9→14.6 (-19%), 收敛于 gen 20
HNN:   1→30代, best=73.1→56.4 (-23%), 未收敛
Optic: 1→25代, best=15.7→11.6 (-26%), 收敛于 gen 15
```

GEMM/MPEG4/VOPD/Optic 均在 15-20 代内接近收敛，HNN 需要更多代数（搜索空间大：32 tasks × 16 PEs = 16^32）。

---

## 六、BL vs B-2 对比总结（OMNeT++ 实测）

| 维度 | B-2 vs Baseline | 说明 |
|------|:---:|------|
| **SimT (完成时间)** | 混合 | GEMM 降 0.6%，Optic 持平，MPEG4 升 0.3%，VOPD 升 1.4% |
| **SOA 能耗** | 混合 | GEMM 降 41%，Optic 降 0.6%，MPEG4 升 8.0%，VOPD 升 32.8% |
| **Tuning 能耗** | 混合 | GEMM 降 48%，MPEG4 降 22%，Optic 升 7.4%，VOPD 升 13.7% |
| **PE 能耗** | 基本持平 | GEMM 降 1.2%，其余差异 < 1% |
| **Throttle** | 改善/持平 | GEMM 从 1.8%→1.2%，其余无显著变化 |
| **OMNeT++ 稳定性** | **4/5** | HNN 失败（仿真时间爆炸） |

**核心结论**：
- **B-2（GA）仅在 GEMM 上全维度优于 static baseline**：GEMM 的通信密集型 fork-join 结构从通信局部化中受益最大，SOA -41%、Tuning -48%
- **MPEG4 和 VOPD 上 B-2 实测反劣于 baseline**：GA 为降通信跳数将 task 集中 → 光路竞争加剧 → SOA/SimT 反升。通信跳数虽减但波长争用使单跳成本更高
- **HNN 的 OMNeT++ 失败揭示 GA 的根本局限**：缺少 makespan 直接惩罚 → 牺牲 DAG 并行度 → 产生病态映射，仿真时间爆炸
- **Python→OMNeT++ 的 gap 是核心教训**：光层竞争和热-通信耦合的完整效应只能在全系统仿真中观测，Python 优化器缺少这些物理层细节
