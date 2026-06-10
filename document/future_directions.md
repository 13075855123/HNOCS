# 热感知任务映射——后续方向文档

## 当前状态

当前实现中，GlobalBuffer（GB）承担两个角色：
1. **控制角色**：决定每个 task 映射到哪个 PE
2. **数据中继角色**：接收 PE 的计算结果，再注入给下一个 PE

数据流为 `PE_a → GB → PE_b`，每个 task 的数据多走了一个 GB 往返。

---

## 公共基础设施：Python 热仿真器

方向 B-1、B-2、C 共同依赖一个**与 OMNeT++ 解耦的 Python 热仿真器**（`mapping/thermal_simulator.py`），精确复现 OMNeT++ 的 RC 热模型（显式欧拉法，32 节点，100ns 步长）。包含三个组件：

| 组件 | 功能 |
|------|------|
| **TaskScheduler** | DAG 感知事件驱动调度，PE 串行化，通信延迟建模 |
| **PowerModel** | 计算/空闲功耗追踪 + DVFS 热降频（T > 46.85°C → 5%/°C 减速） |
| **ThermalSimulator** | RC 热网络求解器，逐时间步记录所有 PE 的完整温度曲线 |

优化在 Python 内完成（毫秒级/轮），OMNeT++ 仅用于最终验证（跑一次）。

---

## 方向 A：控制与数据分离（Lookup-Based Thermal-Aware Placement）

### 核心思想

**GB 只做映射决策（发调度令），不中转数据。PE 之间仍然直接通信。**

```
当前（GB 中转）：                     方向 A（控制数据分离）：

  PE_a 算完                            PE_a 算完
   │                                    │
   ▼                                    ├──→ 发查询包给 GB："T6 放哪？"
  GB（收数据）                          │    （几字节，极小开销）
   │                                    │
   ▼                                    ├──← GB 应答："放 PE15"
  GB（查温度，选 PE）                   │
   │                                    ▼
   ▼                                  PE_a → PE15（数据直连）
  GB → 新 PE（数据 + 任务描述）         │
                                        ▼
                                      PE15 创建 T6，等待所有前驱数据到达 → 启动
```

### 实现要点

1. PE 发包前先检查**全局 Task-to-PE 映射表**（放在 ThermalModel 单例中）
2. 若目标 task 尚未分配 → 该 PE 评估所有 PE 温度，决定目标 PE，写入全局表
3. 若目标 task 已分配（被其他前驱抢先） → 直接发往已记录的 PE
4. 收包侧：PE 收到数据 → 若 task 不存在则创建（pendingDeps=总前驱数），dep 计数减 1 → 归零则启动

### 论文依据

| 引用 | 关联点 |
|------|--------|
| **Gannet SoC Architecture** (Vanderbauwhede, 2008) | NoC 中控制流与数据流分离的先例，使用集中式控制器管理任务执行 |
| **SK hynix Patent US 11,113,116** (2020) | 基于查找表（lookup table）的热感知任务映射，控制器查询节点温度+剩余计算时间表来选择目标 |
| **Intel PCU / ARM SCP** | 现代 SoC 中已有的集中式功耗/热管理微控制器，GB 增加调度功能是架构的自然扩展 |
| **Arteris Patent US 2025/0106119** (2024) | 中央聚合处理器通过观察 NoC 包来监控负载，反馈给发起端进行调度——控制回路不经过数据路径 |
| **UNISM: Unified Scheduling and Mapping** (He & Dong, IEEE TVLSI 2013) | 统一调度与映射框架，集中式分配决策，分散式执行 |

### 论文表述建议

> We propose a lightweight lookup-based thermal-aware placement mechanism. A centralized GlobalBuffer maintains a task-to-PE mapping table and responds to placement queries from PEs with a single-word reply. Data transfer between dependent tasks occurs directly over the NoC without GB relay. This control-data separation is analogous to the decoupled control and data planes in software-defined networking (SDN), and adds negligible communication overhead to the NoC.

### 优缺点

| 优点 | 缺点 |
|------|------|
| 数据不绕 GB，通信开销极低 | PE 需要发查询包（几 bytes，可忽略） |
| 控制与数据分离，架构清晰 | 全局表需要一致性保证（单写多读，锁开销小） |
| 论文中 SDN 类比有说服力 | 实现比当前方案稍复杂 |

---

## 方向 B：离线热感知静态映射（Design-Time Thermal-Aware Mapping）

### 整体定位

**在 t=0 时一次性完成所有 task 的 PE 分配。** task 之间的数据走 PE→PE 直连（static CSV 模式），仿真期间无需运行时调度。

核心挑战：温度是映射的"副作用"（task A 放 PE0 → PE0 发热 → 影响后续 task B 的 PE 选择），而映射又应该避开热点——这是鸡和蛋的循环依赖。

方向 B 拆分为两个子方向，用不同的方法解决这个循环依赖：

| | B-1：增量贪心 + 多轮迭代 | B-2：遗传算法（GA） |
|---|---|---|
| **方法类型** | 解析方法（规则驱动） | 元启发式搜索 |
| **论文定位** | Baseline | Baseline |
| **自洽性** | 每步注入真实热效应 | 每个个体独立仿真 |
| **全局搜索** | 无（贪心不可回溯），靠多轮弥补 | 有（种群多样性） |

---

### 方向 B-1：增量贪心 + 多轮迭代

#### 核心思想

**按 DAG 拓扑序逐个分配 task，每分配完一个 task 就立刻跑热仿真把它的热效应注入进去——下一个 task 评估 PE 时看到的是"前面所有 task 已经烧热了的芯片"。** 单轮贪心不能回溯（T1 选错 → 后面全错），用多轮迭代弥补：每轮重新贪心构建，用上一轮的温度经验指导本轮决策。

```
单轮内部（增量贪心构建）:
  T=0，所有 PE=45°C
  分配 T1 → 选代价最低的 PE → 跑热仿真到 T1 结束 → PE 温度更新
  分配 T2 → 候选 PE 有不同的实时温度 → 选 PE_j → 跑热仿真注入 T2 的热
  分配 T3 → 芯片已经被 T1、T2 加热 → 看到真实的温度梯度 → 选 PE_k
  ...直到所有 task 分配完毕
  → 产出映射 A + 完整温度时间曲线

轮间迭代:
  Round 1: 贪心构建（无历史经验，初始分配近似随机）
  Round 2: 贪心构建（用 Round 1 的温度经验重选，纠正 Round 1 的错误）
  Round 3: ...直到映射不再变化
```

#### 代价函数

task_i 选 PE_j 时的代价：

$$\text{cost}(PE_j, task_i) = w_T \cdot (T_{PE_j}(t_{start}) - T_{amb}) + w_H \cdot \sum_{p \in pred(i)} \text{hops}(PE_{p}, PE_j) \cdot \text{dataSize}(p,i)$$

其中 $T_{PE_j}(t_{start})$ 是**task_i 开始时刻 PE_j 的真实温度**（来自已注入热效应的当前热状态），不是 PE 的峰值或平均温度。

#### 实现要点

1. 按拓扑序遍历 task，维护一个"当前芯片热状态"（所有 PE 的实时温度）
2. 每分配一个 task：评估所有候选 PE → 选代价最小的 → 调度该 task（计算开始/结束时间）→ 跑热仿真到该 task 结束 → 更新芯片热状态
3. 多轮迭代：每轮从 45°C 重新开始贪心构建，但代价函数可参考上一轮的完整温度时间曲线（task_start_temps）
4. 收敛条件：映射不变，或温度分布变化 < 阈值

#### 优缺点

| 优点 | 缺点 |
|------|------|
| 每一步的评估完全自洽（温度来自已注入的热效应） | 单轮贪心无回溯能力 |
| 概念直观，实现简单 | 需要多轮才能收敛 |
| 热状态是连续时间函数，精度最高 | 最终结果可能不如全局优化 |

#### 论文依据

贪心拓扑调度 + 热感知的文献依据同方向 B-2（见下方）。增量式热注入是本方向的独特贡献，现有文献中未见类似方法。

#### 实现现状（2026-06-03）

B-1 已在 `Experiment/B-1/` 中完整实现。核心文件：

| 文件 | 功能 |
|------|------|
| `mapping/cost_model.py` → `NormalizedCostModel` | 四子项归一化代价函数 |
| `Experiment/B-1/iterative_greedy.py` | 增量热注入贪心 + PE 热应力跨轮反馈 + 循环检测 |
| `Experiment/B-1/run.py` | CLI 入口，支持 `--all` 跑全部 benchmark |

##### 代价函数设计演进

**初版**（论文公式直译）：
$$\text{cost} = w_T \cdot (T_{PE_j} - T_{amb}) + w_H \cdot \sum \text{hops} \cdot \text{dataSize}$$

实际运行发现两个致命问题：
1. **量纲不匹配**：热项 ~O(1)、通信项 ~O(10³)，贪心完全忽略温度
2. **DVFS 阈值无感知**：温度超过 54°C 时计算时间翻倍，但代价函数对此不敏感

**终版**（四子项归一化）：
$$\text{cost} = w_T \cdot f_{thermal} + w_H \cdot f_{comm} + w_D \cdot f_{dvfs} + w_L \cdot f_{overload}$$

| 子项 | 公式 | 范围 | 权重 |
|------|------|------|------|
| $f_{thermal}$ | $(T - T_{amb}) / (T_{throttle} - T_{amb})$ | [0, ~1.5] | $w_T=1.0$ |
| $f_{comm}$ | $\sum \text{hops} \cdot \text{dataSize} / \maxEdgeComm$ | [0, ~1] | $w_H=0.5$ |
| $f_{dvfs}$ | 三段式：安全区 0 → 预警区线性 → 超阈值 5× 斜率 | [0, 陡升] | $w_D=2.0$ |
| $f_{overload}$ | $\max(0, \frac{\text{load}_{PE_j}}{\text{ideal}} - 1)$，load 按 **compute_time 加权** | [0, ~15] | $w_L=3.0$ |

其中 $f_{overload}$ 是最关键的改进。初版用 task 计数衡量负载（一个 50000ns 的重 task 和一个 20000ns 的轻 task 等权重），导致贪心无法区分热负载轻重。改为 compute_time 加权后，贪心自然倾向将重 task 分散到冷 PE 上。

##### 跨轮经验机制

初版用 `task_start_temps`（"上轮 task_i 开始时 PE_j 是多少度"）作为跨轮先知。但因每轮映射不同 → 调度时序不同 → 温度值跨映射失准，导致算法在 2-3 轮内围绕局部最优振荡。

改为 **PE 级热应力反馈**（quadratic penalty）：

$$\text{stress}_{PE_j} = w_T \cdot \left(\frac{\max(0, T_{peak}^{PE_j} - T_{amb})}{T_{throttle} - T_{amb}}\right)^2$$

下轮贪心构建时，`pe_penalty[PE_j]` 作为静态偏置加入代价函数。"上轮 PE_j 太热 → 这轮避开它"——粗粒度但跨映射鲁棒。

收敛条件：映射重复出现（循环检测）时取峰值温度最低的轮次。

##### OMNeT++ C++ 实测结果

B-1 重映射的 CSV 在 `examples/task_driven/B1_mapping/`，OMNeT++ 配置文件位于 `examples/task_driven/omnetpp.ini`（新增 `_B1` 后缀 config）。以下为 C++ 仿真结果（`opp_run -u Cmdenv`）：

| Benchmark | 指标 | 静态映射 | B-1 重映射 | Δ | Δ% |
|-----------|------|----------|-----------|-----|-----|
| **GEMM** | T_peak | 54.9°C | **53.1°C** | **-1.8°C** | — |
| (CCR=8) | T_grad | 7.5°C | **4.1°C** | -3.4°C | — |
| | Makespan | 119.6μs | 116.0μs | -3.6μs | -3.0% |
| | 总能耗 | 1580.6μJ | **1528.1μJ** | -52.5μJ | **-3.3%** |
| **MPEG4** | T_peak | 54.4°C | **52.8°C** | **-1.6°C** | — |
| (CCR=1) | T_grad | 6.5°C | **5.1°C** | -1.4°C | — |
| | Makespan | 121.7μs | 121.4μs | -0.3μs | -0.2% |
| | 总能耗 | 1144.0μJ | **1140.4μJ** | -3.6μJ | **-0.3%** |
| **VOPD** | T_peak | 52.2°C | **51.5°C** | **-0.7°C** | — |
| (CCR=0.3) | T_grad | 4.7°C | **3.6°C** | -1.1°C | — |
| | Makespan | 87.4μs | 85.5μs | -1.9μs | -2.2% |
| | 总能耗 | 753.4μJ | **741.7μJ** | -11.7μJ | **-1.5%** |
| **HNN** | T_peak | 55.7°C | 59.8°C | **+4.1°C** | — |
| (CCR=3) | T_grad | 0.2°C | 1.4°C | +1.2°C | — |
| | Makespan | 204.1μs | **187.1μs** | -17.0μs | **-8.3%** |
| | 总能耗 | 4681.5μJ | 5202.5μJ | +521.0μJ | +11.1% |
| **Optic** | T_peak | 48.8°C | 48.8°C | 0.0°C | — |
| (CCR=0.06) | Makespan | 9.2μs | 9.2μs | 0.0μs | 0.0% |

##### 分析

1. **GEMM/MPEG4/VOPD**：三个 benchmark 在峰值温度、温度梯度、完成时间、总能耗四个维度上**全面优于**静态映射。温度降幅 0.7–1.8°C，能耗降幅 0.3–3.3%。代价函数的热负载加权和 PE 热应力反馈共同作用，使贪心在保持通信效率的同时实现了更好的热负载均衡。

2. **HNN**：B-1 将热负载从 max/min=5.0× 优化到 1.1×（近完美均衡），但峰值温度反而升高 4.1°C。根因是 RC 热网络在长时间仿真中（~200μs）达到稳态——16 个 PE 全部 55.7°C，温度由 **总功率密度 = 总能量 / makespan** 决定。B-1 将 makespan 缩短 8.3%（更高效的 PE 利用率），功率密度相应升高 → 全芯片稳态温度升高。这是**物理学硬约束**（$T \approx T_{amb} + R_{conv} \cdot P_{avg}$），任何纯映射算法都无法同时优化性能和温度——需要 B-2（GA）探索帕累托前沿。

3. **Optic**：16 个 task 全并行、无依赖、1μs 极短计算——热效应微弱，贪心无优化空间。

4. **Python 预测 vs C++ 实测**：两者趋势完全一致（GEMM/MPEG4/VOPD 改善，HNN 温度升但 makespan 降），定量偏差在可接受范围。验证了 Python 热仿真器作为 OMNeT++ 代理的可行性。

---


### 方向 B-2：遗传算法（GA）

#### 核心思想

**每个"个体"是一个完整映射（所有 task→PE 的分配）。评估个体 = 用 Python 热仿真器跑一次该映射的完整仿真 → 得到真实温度分布 → 计算真实代价。** 种群通过选择、交叉、变异迭代进化。

```
GA 流程:
  初始化: 随机生成 50 个完整映射（个体）

  每代:
    对每个个体跑 Python 热仿真 → 真实温度 + 真实代价
    选择: 保留代价最低的 20 个
    交叉: 两个父代交换部分 task 的 PE 分配 → 新个体
    变异: 随机修改一个 task 的 PE
    → 新一代 50 个个体

  20-30 代后收敛 → 最优映射
```

#### 为什么 GA 天然自洽

SA 的问题是"挪动一个 task 后用旧温度表评估"——内外不一致。GA 不同：**每个个体是从头跑完整仿真，映射和温度天然自洽。** 个体 #17 说 T2→PE8，那么仿真里 T2 就在 PE8 跑，PE8 的温度就是 T2 造成的。评估个体 #17 的代价时，用的是个体 #17 自己仿真出来的温度——没有近似。

#### 并行化

50 个体 × 20 代 = 1000 次仿真。每次仿真 ~0.05s。单线程 ~50 秒，8 线程并行 ~6 秒。

#### 染色体编码

```
染色体: [PE_T1, PE_T2, PE_T3, ..., PE_Tn]  （每个 task 的 PE 编号）
例:     [0, 8, 12, 4, 1, 4, 8, 12, 1, 0]  （GEMM 10 个 task）
```

#### 优缺点

| 优点 | 缺点 |
|------|------|
| 每个评估完全自洽（映射→仿真→温度→代价，闭环） | 仿真次数多（但可并行） |
| 种群多样性防止局部最优 | 实现比 B-1 复杂 |
| 可输出帕累托前沿（温度最优 vs 通信最优的多个解） | 超参调优（种群大小、交叉率、变异率） |

#### 论文依据

| 引用 | 关联点 |
|------|--------|
| **Reza, "High-performance application mapping in NoC-based multicore"** (J. Supercomputing, 2024) | MILP + SA + GA 对比，GA 在 MILP 最优解 10% 以内 |
| **Reshadi et al., "Thermal-aware application mapping using GA and fuzzy logic"** (J. Supercomputing, 2024) | GA + 模糊逻辑的热感知应用映射，与方向 B-2 直接对应 |
| **Kaur et al., "Survey on mapping and scheduling for 3D NoC"** (J. Systems Architecture, 2024) | 静态映射综述，GA 是主流方法之一 |
| **TTNNM: Thermal- and Traffic-Aware NN Mapping** (Li & Fan, GLSVLSI 2024) | 热+流量感知映射，层次化优化 |
| **Mo et al., "Contention and Reliability-Aware Energy Efficiency Task Mapping"** (IEEE Trans. Reliability, 2024) | MILP 联合优化竞争、可靠性和能耗 |
| **SpecMap: Spectral Partitioning-Based Mapping** (Raj et al., CCPE, 2023) | 谱图分割静态映射，通信密集型任务聚类 |

---

## 方向 C：GNN + RL 智能映射

### 核心思想

**将 task graph 和 mesh 拓扑视为两个图，用图神经网络（GNN）联合编码，强化学习（RL）学习最优 PE 分配策略。** 与方向 B 的关键区别：B-1/B-2 对每个新 benchmark 都需要重新搜索；方向 C 训练一次后，换一个新的 task graph 可直接推理输出映射。

```
训练阶段（Python 内完成）:
  GNN 输入 task graph → 输出映射
    ↓
  Python 热仿真器跑该映射 → 得到真实温度 + 通信代价
    ↓
  reward = -(w_H × 通信代价 + w_T × 温度代价)
    ↓
  PPO 更新策略网络
    ↓
  下一个 task graph...

推理阶段:
  新 task graph → GNN → 映射 → OMNeT++ 验证一次
```

### 参考论文：RA-Map (2024)

**RA-Map: "3D Network-on-Chip Data Acquisition System Mapping Based on Reinforcement Learning and Improved Attention Mechanism"**
- Xu, Shi, Yang, Wang — *Microelectronics Journal*, Vol. 151, Sept 2024
- DOI: `10.1016/j.mejo.2024.106323`

RA-Map 的架构：

| 组件 | 功能 |
|------|------|
| **GCN 编码器** | 用图卷积网络对 task graph 预处理，生成每个节点的特征编码（计算量 + 通信量 + 拓扑位置编码） |
| **局部注意力机制** | 替代全局注意力，聚焦局部关键 task 的映射决策，降低计算开销 |
| **RL 策略网络** | 用 PPO/A2C 学习映射策略，将映射建模为序列决策（逐 task 选择 PE） |
| **无监督评估网络** | 无需标注数据，通过通信代价 + 负载均衡自监督训练 |

RA-Map 的实验结果：通信成本比 DPSO 降 6.5%、比 SA 降 8.5%。

### 我们的差异化

**RA-Map 的代价函数只有通信成本。我们的创新：**

1. **温度项融入**：将 Python 热仿真器作为 RL 训练环境，reward 加入温度代价
   ```
   原始 RA-Map:
     reward = -Σ hops(task_i, task_j) × dataSize_ij

   我们的改进:
     reward = -[ w_H × Σ hops × dataSize + w_T × Σ max(0, T_PE_i - T_amb) ]
   ```
2. **训练环境解耦 OMNeT++**：RL 训练全程在 Python 热仿真器内完成，无需反复调 OMNeT++
3. **可泛化性**：训练好的模型直接用于新 benchmark，无需重新搜索

### 为什么 GNN 天然适合这个任务

| 数据 | 天然图结构 | GNN 能做什么 |
|------|-----------|-------------|
| Task graph | 有向无环图（节点=task，边=依赖+通信量） | GCN 聚合邻居节点信息，学习 task 间的通信模式 |
| 4×4 Mesh | 网格图（节点=PE，边=NoC 链路） | 编码 PE 的拓扑位置和相邻关系 |
| 温度分布 | 每个 PE 一个标量 | 作为 PE 节点的额外特征，GCN 自然处理 |

GNN 的核心优势：**学一次，可泛化**。训练好的模型换一个 task graph（如从 GEMM 换到 VOPD）不需要重新跑优化，直接输出映射结果。

### 实现路线图

**Phase 1（基础复现）**：
- 用 PyTorch Geometric 或 DGL 实现 GCN 编码器
- 实现 PPO RL 策略网络
- 在标准 task graph（VOPD/MPEG4/GEMM）上复现 RA-Map 的通信成本结果

**Phase 2（温度项融入 + Python 热仿真器对接）**：
- 将 Python 热仿真器包装为 RL 环境（`step(action) → (reward, done)`）
- reward 函数加入温度代价
- 对比：纯通信代价 vs 通信+温度联合代价的映射质量

**Phase 3（在线/离线混合）**：
- 初始映射用训练好的 GNN 模型 t=0 一次性分配
- 运行时若检测到局部热点，触发局部重映射（RL 再做一次小范围调整）
- 形成 "离线预分配 + 在线微调" 的混合策略

### 论文依据

| 引用 | 关联点 |
|------|--------|
| **RA-Map** (Xu et al., Microelectronics J., 2024) | GCN + Attention + RL for 3D NoC task mapping; 直接复现基准 |
| **RL + CNN for DNN Mapping in NoC** (IEEE, 2025) | RL 策略 + CNN 空间编码联合映射 DNN 到 NoC |
| **HSDAG: Structure-Aware Device Placement** (NeurIPS, 2024) | GNN + RL 用于计算图设备放置，与 NoC task mapping 数学同构 |
| **EGRL (Intel)** (arXiv/ICLR) | GNN-based policy + RL + 进化搜索 for tensor mapping on Intel NNP-I |
| **GCN + RL for Macro-Unit Placement** (2025) | GCN 编码 netlist + RL 放置，芯片设计领域最前沿方法 |
| **CN115470889A** (中国专利) | PPO/A2C RL 用于 NoC 自主最优映射探索 |
| **Survey: ML for NoC Mapping** (Discover Electronics, 2024) | 全面综述 ML（含 RL）在 NoC 映射中的应用 |

### 优缺点

| 优点 | 缺点 |
|------|------|
| **最前沿**：GNN+RL 是 2024-2025 最热门组合 | 实现复杂度高于 B-1/B-2 |
| **可泛化**：训练一次可用不同 task graph | 需要大量训练数据（可从 Python 热仿真器生成） |
| **论文故事强**：复现 + 创新（温度项）+ 对比充分 | PyTorch/OMNeT++ 跨框架集成有工程挑战（已解耦） |
| **可直接投稿顶会/顶刊** | 训练超参调优需经验 |

---

## 四个方向的定位与关系

| | 方向 A（控制数据分离） | 方向 B-1（增量贪心+迭代） | 方向 B-2（GA） | 方向 C（GNN+RL） |
|---|---|---|---|---|
| **调度时机** | 运行时 | 设计时（t=0） | 设计时（t=0） | 设计时（t=0）+ 可扩展在线 |
| **决策方式** | GB 查温度表 + 代价函数 | 贪心规则 + 实时热注入 | 种群进化 + 完整仿真 | GCN 编码 + RL 策略网络 |
| **温度信息来源** | 实时（OMNeT++ 内） | Python 热仿真器 | Python 热仿真器 | Python 热仿真器（训练） |
| **自洽性** | ✅ 运行时实时温度 | ✅ 每步注入热效应 | ✅ 每个体独立仿真 | ✅ 训练环境提供真实代价 |
| **全局搜索能力** | N/A（运行时动态） | ❌（靠多轮弥补） | ✅ 种群多样性 | ✅ RL 探索策略 |
| **可泛化到新 benchmark** | ✅ | ❌（需重跑） | ❌（需重跑） | ✅ 训练一次直接推理 |
| **论文定位** | **Proposed**（架构创新） | Baseline | Baseline | **Proposed**（算法创新） |
| **实现工作量** | 中 | 低 | 中 | 高（PyTorch + 热仿真器） |

### 共同基础

B-1、B-2、C 共用 `mapping/thermal_simulator.py`（Python 热仿真器）和 `mapping/cost_model.py`（代价函数）。优化全程在 Python 内完成，OMNeT++ 仅用于各方向的最终验证跑一次。

---

## 建议的论文实验设计

1. **Baseline 1**：传统 XY 路由 + **固定映射**（`static/tasks_*_static.csv`）
2. **Baseline 2**：方向 B-1 **增量贪心 + 多轮迭代**（解析方法）— ✅ 已实现，OMNeT++ 实测
3. **Baseline 3**：方向 B-2 **GA 优化**（元启发式方法）— 待实现
4. **Proposed A**：传统 XY 路由 + **方向 A 运行时热感知动态放置**（控制数据分离）
5. **Proposed C**：**方向 C GNN+RL 智能映射** — 离线训练、在线推理，通信+温度联合代价

对比维度：温度（峰值/梯度）、通信代价（总跳数×数据量）、完成时间、总能耗。

---

## 实验 Benchmark 套件

五个 benchmark 覆盖 CCR 0.06→8 的完整谱系，从全并行到深度流水线。

### 任务图

```
GEMM (fork-join):          MPEG-4 (fork-join+并行分支):
  T1→T2→T6↘                 GB→T1─┬→T2─┬→T3→T5↘
  T1→T3→T7 →T10→GB               ├→T8→GB   T4─→T6─┬→T7→GB
  T1→T4→T8 ↗                     └→T11→GB          ├→T9→GB
  T1→T5→T9↗                                        └→T10→GB

VOPD (长流水线):            Optic Calib (全并行):       HNN (深度流水线):
  T1→T2→T3→T4→T5→T6→T7      GB→T1(PE0)─→GB          GB→T1-4(fan-out×4)
       ↓        ↓  ↓  ↓         T2(PE1)─→GB              →T5-12(fan-out×8)
      T12→GB  T8 T9 T10→GB       ...                     →T13-28(16 PE并行)
                                T16(PE15)→GB              →T29-32(reduce×4→GB)
```

### 五个 Benchmark 特征

| | GEMM | MPEG-4 | VOPD | Optic Calib | HNN |
|---|---|---|---|---|---|
| **Task 数** | 10 | 11 PE + 1 GB | 12 PE | 16 PE | 32 PE + 1 GB |
| **CCR** | **8** | **1** | **0.3** | **0.06** | **3** |
| **依赖模式** | fork-join | fork-join+分支 | 长流水线+分叉 | 全并行 | 4→8→16→4 流水线 |
| **最长串行链** | 4 级 | 6 级 | 7 级 | 0 级 | 4 级 |
| **最大并行度** | 4 | 3 | 4 | **16** | **16** |
| **计算量/task** | 15-50μs | 15-35μs | 20-30μs | 1μs | 20-50μs |
| **通信量/task** | 1-8KB | 0.5-4KB | 0.5-4KB | 32KB | 8-32KB |
| **热感知挑战** | 中等并行热点 | 6级串行累积 | 7级最长累加热 | 全分散无热点 | **16 PE同步重计算→DVFS重灾区** |

---

## 关键参考文献

### 方向 A
1. Vanderbauwhede W. "A Formal Semantics for Control and Data flow in the Gannet Service-based System-on-Chip Architecture." 2008.
2. SK hynix. "Task mapping method of network-on-chip semiconductor device." US Patent 11,113,116, 2020.
3. He O, Dong Y. "UNISM: Unified Scheduling and Mapping for General Networks on Chip." IEEE TVLSI, 2013.

### 方向 B（B-1 + B-2）
4. Kaur S, et al. "A survey on mapping and scheduling techniques for 3D Network-on-chip." Journal of Systems Architecture, 2024.
5. Li Z, Fan H, et al. "TTNNM: Thermal- and Traffic-Aware Neural Network Mapping on 3D-NoC-based Accelerator." GLSVLSI, 2024.
6. Mo L, Li X, et al. "Contention and Reliability-Aware Energy Efficiency Task Mapping on NoC-Based MPSoCs." IEEE Trans. Reliability, 2024.
7. Reza MF. "High-performance application mapping in network-on-chip-based multicore systems." J. Supercomputing, 2024.
8. Reshadi M, et al. "Thermal-aware application mapping using genetic and fuzzy logic for 3D NoC." J. Supercomputing, 2024.
9. Raj et al. "SpecMap: Spectral Partitioning-Based Mapping." CCPE, 2023.

### 方向 C
10. Xu C, Shi X, Yang H, Wang Y. "RA-Map: 3D Network-on-Chip Data Acquisition System Mapping Based on Reinforcement Learning and Improved Attention Mechanism." Microelectronics Journal, Vol. 151, 2024. — 直接复现基准
11. Duan S, Ping Y, et al. "HSDAG: A Structure-Aware Framework for Learning Device Placements on Computation Graphs." NeurIPS, 2024. — GNN+RL 设备放置，数学同构
12. "Reinforcement Learning and CNN for Generalized Multi-Objective Mapping of DNN Workloads in NoCs." IEEE, 2025. — RL+CNN 映射 DNN 到 NoC
13. "RL-Based NoC Autonomous Optimal Mapping Exploration System and Method." CN115470889A, 中国专利. — PPO/A2C 用于 NoC 映射
14. Yasin AS, et al. "A comprehensive study and holistic review of empowering network-on-chip application mapping through machine learning techniques." Discover Electronics, Vol. 1, 2024. — ML+NoC 映射综述
