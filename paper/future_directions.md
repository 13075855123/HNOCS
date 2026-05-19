# 热感知任务映射——后续方向文档

## 当前状态

当前实现中，GlobalBuffer（GB）承担两个角色：
1. **控制角色**：决定每个 task 映射到哪个 PE
2. **数据中继角色**：接收 PE 的计算结果，再注入给下一个 PE

数据流为 `PE_a → GB → PE_b`，每个 task 的数据多走了一个 GB 往返。

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

### 核心思想

**在 t=0 时一次性完成所有 task 的 PE 分配，利用初始温度信息 + 任务图通信模式进行静态优化。** task 之间的数据仍走 PE→PE 直连（static CSV 模式），无需运行时调度。

```
t=0：GB 加载全部 task
    → 扫描任务图（有向无环图 DAG）
    → 用代价函数 cost(PE,T,H) 一次性算出每个 task 的最优 PE
    → 分配完毕后，task 按 static.csv 模式 PE→PE 直连执行
    → GB 不参与后续数据中转
```

这本质上是将 NoC 文献中经典的**静态应用映射（Application Mapping）** 问题用**温度感知代价函数**重新求解。

### 实现要点

1. **t=0 的拓扑排序遍历**：按 DAG 拓扑序依次分配 task
2. 分配 task[i] 时，已知 task[i] 的前驱已分配的 PE 位置 → 可计算通信距离
3. 代价函数增加通信量项：

   $$\text{cost}(PE_j) = w_T \cdot T_j + w_H \cdot \sum_{p \in pred(i)} \text{hops}(PE_{p}, PE_j) \cdot \text{dataSize}(p,i)$$

4. 分配完毕后注入到各自 PE，后续全 static 模式执行

### 论文依据

| 引用 | 关联点 |
|------|--------|
| **Kaur et al., "Survey on mapping and scheduling for 3D NoC"** (J. Systems Architecture, 2024) | 全面综述静态与动态映射技术，其中静态映射使用 ILP/MILP/GA/SA 等优化方法 |
| **TTNNM: Thermal- and Traffic-Aware NN Mapping** (Li & Fan, GLSVLSI 2024) | 热+流量感知的神经网络映射到 3D NoC，层次化映射算法 |
| **Mo et al., "Contention and Reliability-Aware Energy Efficiency Task Mapping"** (IEEE Trans. Reliability, 2024) | 使用 MILP 联合优化竞争、可靠性和能耗的任务映射 |
| **Reza, "High-performance application mapping in NoC-based multicore"** (J. Supercomputing, 2024) | MILP + SA + GA 的静态应用映射对比，SA 和 GA 在 MILP 最优解 10% 以内 |
| **SpecMap: Spectral Partitioning-Based Mapping** (Raj et al., CCPE, 2023) | 基于谱图分割的静态映射，通信密集型任务聚类到 mesh 中心 |
| **Reshadi et al., "Thermal-aware application mapping using GA and fuzzy logic"** (J. Supercomputing, 2024) | 遗传算法 + 模糊逻辑的热感知应用映射 |

### 论文表述建议

> We formulate the thermal-aware task mapping as a design-time optimization problem. Given a task DAG with communication weights and an initial thermal profile, we assign each task to a PE to minimize a weighted cost function of temperature and communication distance. This approach leverages the well-studied static application mapping framework, replacing traditional communication-cost-only objectives with our joint thermal-communication cost metric.

### 优缺点

| 优点 | 缺点 |
|------|------|
| 实现简单（t=0 一次性算完） | 无运行时的温度反馈（初始 T=45°C 全等，温度感知退化为通信感知） |
| PE→PE 直连，零额外通信开销 | 无法应对运行时温度变化 |
| 大量静态映射论文作为理论基础 | 需要**第二次迭代**（先跑一遍获得温度分布，再优化映射，再跑）来体现温度感知 |
| 适合作为 Baseline | 创新性不如方向 A |

---

## 方向 C：GNN + RL 智能映射（RA-Map 复现 + 温度代价）

### 核心思想

**将 task graph 和 mesh 拓扑视为两个图，用图神经网络（GNN）联合编码，强化学习（RL）学习最优 PE 分配策略，代价函数加入温度项。**

这是方向 B（离线静态映射）的 AI 增强版——不再用 GA/SA 穷举搜索，而是训练一个神经网络直接输出映射结果。

```
输入层：
  任务图 G_task（节点=task, 边=依赖+通信量）
      ↓
  GCN 编码（图卷积网络）→每个 task 的 embedding 向量
      ↓
  注意力机制 → 聚焦高通信量的关键 task
      ↓
  RL 策略网络（PPO/A2C）→ 依次输出每个 task 的目标 PE
      ↓
  代价函数 = w_comm × 通信跳数 + w_T × T(PE)
      ↓
  奖励 → 更新策略网络
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

**RA-Map 的代价函数只有通信成本。我们加入温度项：**

```
原始 RA-Map:
  reward = -Σ hops(task_i, task_j) × dataSize_ij

我们的改进:
  reward = -Σ [ w_H × hops + w_T × (T(PE_i) - T_amb) + w_comm × dataSize ]
  即论文的通信+温度联合代价函数，直接嵌入 RL 的 reward 函数
```

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

**Phase 2（温度项融入）**：
- 将温度代价加入 reward 函数
- 从 OMNeT++ 仿真提取 PE 温度分布作为训练数据
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
| **最前沿**：GNN+RL 是 2024-2025 最热门组合 | 实现复杂度高于 GA/SA |
| **可泛化**：训练一次可用不同 task graph | 需要大量训练数据（可从 OMNeT++ 生成） |
| **论文故事强**：复现 + 创新（温度项）+ 对比充分 | PyTorch/OMNeT++ 跨框架集成有工程挑战 |
| **可直接投稿顶会/顶刊** | 训练超参调优需经验 |

---

## 三个方向的定位

| | 方向 A（控制数据分离） | 方向 B（离线静态映射） | 方向 C（GNN+RL 智能映射） |
|---|---|---|---|
| **调度时机** | 运行时 | 设计时（t=0） | 设计时（t=0）+ 可扩展在线 |
| **决策方式** | GB 查温度表 + 代价函数 | 代价函数 + GA/SA 优化 | GCN 编码 + RL 策略网络 |
| **温度信息来源** | 实时 | 离线 | 混合（离线训练 + 在线推理） |
| **论文定位** | **Proposed**（控制创新） | Baseline | **Proposed**（算法创新） |
| **创新程度** | 高（架构创新） | 中 | **最高**（AI+架构交叉） |
| **可投稿会议** | DATE/NoCArc | J. Supercomputing | **DAC/ICCAD/NeurIPS** |
| **实现工作量** | 中 | 低 | 高（PyTorch + OMNeT++） |

## 建议的论文实验设计

1. **Baseline 1**：传统 XY 路由 + **固定映射**（当前 `tasks_*_static.csv`）
2. **Baseline 2**：传统 XY 路由 + **方向 B 离线热感知静态映射**（GA/SA 优化）
3. **Proposed A**：传统 XY 路由 + **方向 A 运行时热感知动态放置**（控制数据分离）
4. **Proposed C**：**方向 C GNN+RL 智能映射** — 离线训练、在线推理，通信+温度联合代价
5. **未来工作**：方向 A + 方向 C 融合（RL 预分配 + 运行时微调 + 热感知路由）

---

## 实验 Benchmark 套件

四个 benchmark 覆盖 NoC 任务图的完整依赖谱——从全并行到长串行流水线。

### 任务图

```
GEMM (fork-join):          MPEG-4 (fork-join+并行分支):
  T1→T2→T6↘                 GB→T1─┬→T2─┬→T3→T5↘
  T1→T3→T7 →T10→GB               ├→T8→GB   T4─→T6─┬→T7→GB
  T1→T4→T8 ↗                     └→T11→GB          ├→T9→GB
  T1→T5→T9↗                                        └→T10→GB

VOPD (长流水线):            Optic Calib (全并行):
  T1→T2→T3→T4→T5→T6→T7      GB→T1(PE0)─→GB
       ↓        ↓  ↓  ↓         T2(PE1)─→GB
      T12→GB  T8 T9 T10→GB       ...
                                T16(PE15)→GB
```

### 四个 Benchmark 特征

| | GEMM | MPEG-4 | VOPD | Optic Calib |
|---|---|---|---|---|
| **文件** | `tasks_gemm_static.csv` | `tasks_mpeg4_static.csv` | `tasks_vopd_static.csv` | `tasks_optic_calib.csv` |
| **Task 数** | 10 | 11 PE + 1 GB | 12 PE | 16 PE |
| **依赖模式** | fork-join | fork-join + 分支 | 长流水线 + 分叉 | **全并行（无依赖）** |
| **最长串行链** | 4 级 | 6 级 | 7 级 | 0 级 |
| **最大并行度** | 4 | 3 | 4 | **16** |
| **计算量/task** | 15-50µs | 15-35µs | 20-30µs | 62.5µs |
| **通信量/task** | 32-512B | 32-500B | 27-500B | 4B |
| **数据流方向** | PE→PE + →GB | PE→PE + →GB | PE→PE + →GB | **PE→GB 单向** |
| **类比场景** | HPC 矩阵计算 | 手机视频解码 | 视频对象解码 | Chiplet 标定 |
| **热感知挑战** | 4 路并行热点集中 | 6 级串行累积 + 多路汇聚 | 7 级最长串行累加热 | 全分散，无热点 |

### 覆盖谱

```
依赖复杂度
    ↑
    │  VOPD        ← 最长串行链，温度累积效应最强
    │  MPEG-4      ← 串行+分支，NoC 论文最高频引用
    │  GEMM        ← 结构最规整，并行度最高
    │  Optic Calib ← 全并行，对比组（无热累积）
    └──────────────────────────→ 并行度
```

四个 benchmark 覆盖从 "完全串行" 到 "完全并行" 的完整范围，可证明热感知方法**不依赖任务图特征**。

---

## 关键参考文献

1. Vanderbauwhede W. "A Formal Semantics for Control and Data flow in the Gannet Service-based System-on-Chip Architecture." 2008.
2. SK hynix. "Task mapping method of network-on-chip semiconductor device." US Patent 11,113,116, 2020.
3. Kaur S, et al. "A survey on mapping and scheduling techniques for 3D Network-on-chip." Journal of Systems Architecture, 2024.
4. Li Z, Fan H, et al. "TTNNM: Thermal- and Traffic-Aware Neural Network Mapping on 3D-NoC-based Accelerator." GLSVLSI, 2024.
5. Mo L, Li X, et al. "Contention and Reliability-Aware Energy Efficiency Task Mapping on NoC-Based MPSoCs." IEEE Trans. Reliability, 2024.
6. Reza MF. "High-performance application mapping in network-on-chip-based multicore systems." J. Supercomputing, 2024.
7. He O, Dong Y. "UNISM: Unified Scheduling and Mapping for General Networks on Chip." IEEE TVLSI, 2013.
8. Reshadi M, et al. "Thermal-aware application mapping using genetic and fuzzy logic for 3D NoC." J. Supercomputing, 2024.

**方向 C 专用参考文献**：
9. Xu C, Shi X, Yang H, Wang Y. "RA-Map: 3D Network-on-Chip Data Acquisition System Mapping Based on Reinforcement Learning and Improved Attention Mechanism." Microelectronics Journal, Vol. 151, 2024. — 直接复现基准
10. Duan S, Ping Y, et al. "HSDAG: A Structure-Aware Framework for Learning Device Placements on Computation Graphs." NeurIPS, 2024. — GNN+RL 设备放置，数学同构
11. "Reinforcement Learning and CNN for Generalized Multi-Objective Mapping of DNN Workloads in NoCs." IEEE, 2025. — RL+CNN 映射 DNN 到 NoC
12. "RL-Based NoC Autonomous Optimal Mapping Exploration System and Method." CN115470889A, 中国专利. — PPO/A2C 用于 NoC 映射
13. Yasin AS, et al. "A comprehensive study and holistic review of empowering network-on-chip application mapping through machine learning techniques." Discover Electronics, Vol. 1, 2024. — ML+NoC 映射综述
