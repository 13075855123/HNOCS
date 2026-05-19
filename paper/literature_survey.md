# 热感知 NoC 任务映射与路由——文献调研与创新定位

## 1. 我们的创新定位

### 1.1 两层热感知闭环

传统热管理是事后响应——温度超阈值 → 降频/关核。我们做的是**事前预防**，分为两层：

| 层 | 做什么 | 决策依据 | 代码位置 |
|-----|-------|---------|---------|
| **任务映射层** | 选择哪个 PE 执行 task | PE 当前温度 + 跳数代价 | `GlobalBuffer::pickBestIdlePE` |
| **路由层** | 数据包走哪条路径 | Router 当前温度 + 距离 | `XYOPCalc`（待实现） |

两层协同闭环：温度 → 功耗模型 → RC 热求解器 → 温度表 → 映射决策 + 路由决策 → 新温度。

### 1.2 与现有工作的本质区别

**现有热感知工作**大都只做一层：

- **热感知映射**：静态优化（SA/GA/ILP），一次性决定 task-PE 映射，不随温度动态调整
- **热感知路由**：绕过热点 Router，但不管 task 分配在哪
- **DVFS 降频**：温度到了再降，被动应对

**我们同时做两层**：映射层把 task 从热 PE 引到冷 PE + 路由层让数据包绕过热 Router。而且这两层共享同一个 RC 热模型（100ns 更新），形成真正的闭环反馈。

### 1.3 关键差异化

- **闭环** vs 开环：温度实时反馈路由与映射决策（HotSpot 离线做不到）
- **在线** vs 离线：每个 100ns 能量窗更新温度，每个 task 完成触发重新评估
- **依赖感知**：任务图依赖自然控制并行度，不需人工调参
- **泄漏反馈**：温度依赖的漏电功耗正反馈嵌入热求解器

---

## 2. 文献调研（2023–2025）

### 2.1 热感知任务映射

| 论文 | 年份 | 出处 | 方法 | 我们的区别 |
|------|------|------|------|-----------|
| Thermal-aware application mapping using genetic and fuzzy logic for 3D NoC | 2024 | J. Supercomputing 80(8) | GA + 模糊逻辑静态优化映射 | 静态一次性映射，不随温度在线调整 |
| TTNNM: Thermal- and Traffic-Aware NN Mapping on 3D-NoC | 2024 | GLSVLSI '24 | 层次化 NN 映射，温度+流量联合优化 | 针对 NN 推理专用，非通用任务图 |
| BTSAM: Balanced Thermal-State-Aware Mapping | 2024 | IEEE Access | 3D NoC 神经形态系统热均衡映射 | 离线映射，非运行时 |
| Contention and Reliability-Aware Energy Efficiency Task Mapping | 2024 | IEEE Trans. Reliability | MILP 联合优化竞争+可靠性+能耗 | 离线优化，无实时温度反馈 |
| High-performance application mapping in NoC-based multicore | 2024 | J. Supercomputing | MILP + SA/GA 启发式 | 静态优化，非动态 |

**我们的不同**：上述全部是**离线静态映射**（设计时确定），我们是**在线动态映射**（运行时每 task 根据实时温度决定）。论文中没有发现和我们一样在 OMNeT++ 事件驱动仿真器里实现在线温度感知任务映射的工作。

### 2.2 热感知路由算法

| 论文 | 年份 | 出处 | 方法 | 我们的区别 |
|------|------|------|------|-----------|
| AMBTAR: Adaptive Multi-Beltway Thermal-Aware Routing for 3D NoC | 2025 | J. Supercomputing 81 | 三模式非最小化路由 + 概率代价函数 | 复杂的多模式路由；无任务映射层配合 |
| CTWR: Congestion, Temperature and Wear-aware Routing | 2025 | Computers & Electrical Engineering 124 | 温度+拥塞+磨损三目标路由 | 3D NoC；无映射层 |
| Thermal and Congestion-aware Deadlock-free Halted Routing | 2025 | Integration, the VLSI Journal | DPSO + SA 优化 halt router 布局 | 确定性路由，需预先布局 |
| RLARA: RL-Assisted Fault-Tolerant Routing for 3D NoC | 2023 | Electronics 12(23) | 强化学习自适应路由 | RL 训练开销大；无映射协同 |
| Power-Aware 3D NoC using Soft Computing | 2023 | IC-TEA | ANN/SVM 预测 → 动态切换路由算法 | 3D NoC；无映射层 |

**我们的不同**：上述路由算法多是**3D NoC** 场景，且都没有**映射层 + 路由层联合**。我们针对 2D Mesh，路由层直接读同一热模型的温度表，和映射层共用数据源。

### 2.3 闭环热管理

| 论文 | 年份 | 出处 | 方法 | 我们的区别 |
|------|------|------|------|-----------|
| Adaptive ML-based Proactive Thermal Management for NoC (🏆 IEEE TVLSI Best Paper) | 2024 | IEEE TVLSI | ASLP 预测 + RL 决定降频比例 | 只做降频管理，不改映射/路由 |
| ControlPULP: RISC-V On-Chip Parallel Power Controller | 2024 | Int. J. Parallel Prog. | FPGA HIL 闭环功率/热控制 | 硬件控制器，非架构级仿真 |
| RL-driven Task Migration for 3D NoC Temperature Management | 2025 | Scientific Reports | RL 任务迁移降温 | task migration 开销大；3D NoC |
| Enhancing Performance and Thermal Management in WNoC | 2024 | SSRN/TechRxiv | 无线 NoC 动态任务调度 | WNoC 场景不同 |

**我们的不同**：上述闭环管理都是**被动降频/迁移**（温度高了再动）。我们是**事前引导**（选择冷 PE 避免形成热点）。且我们在标准 2D Mesh NoC 上同时做映射+路由的协同。

### 2.4 与 HotSpot 离线仿真的对比

传统方法：跑 NoC 仿真 → 导出功率 trace → 喂给 HotSpot → 算出温度 → 手动分析 → 改参数重新仿真。这是**开环**。

我们：功耗 → 热求解器（嵌入 OMNeT++）→ 温度 → 映射决策 / 路由决策（同一事件循环）→ 新功耗。这是**闭环**。

| | HotSpot 离线方法 | 我们的方法 |
|---|---|---|
| 温度分辨率 | 取决于 trace 步长 | **100ns**（与能耗窗口同步） |
| 反馈延迟 | 仿真后分析，无反馈 | **实时**（同一步内温度可用） |
| 工具链 | NoC 仿真器 + HotSpot + 脚本 | **单一仿真器（OMNeT++）** |
| 泄漏反馈 | 不支持 | 支持（T 依赖漏电） |

**最接近的工作**：Noxim + McPAT + HotSpot 联合仿真（Samala & Soumya, 2024），但仍然是离线 ML 预测，没有运行时闭环。

---

## 3. 建议的投稿方向

### 3.1 会议

| 会议 | 级别 | 特点 | 截稿（参考） |
|------|------|------|------------|
| **NOCS** (Int'l Symp. on Networks-on-Chip) | 顶会（CORE A） | NoC 领域最权威 | 每年约 5 月 |
| **DAC** (Design Automation Conference) | 顶会（CORE A*） | EDA/架构 | 每年约 11 月 |
| **DATE** (Design, Automation and Test in Europe) | 顶会（CORE A） | 嵌入式/NoC/EDA | 每年约 9 月 |
| **ICCAD** (Int'l Conf. on Computer-Aided Design) | 顶会（CORE A） | EDA/架构 | 每年约 4 月 |
| **GLSVLSI** (Great Lakes Symp. on VLSI) | CORE B | VLSI/NoC/EDA | 每年约 12 月 |
| **NoCArc** (Int'l Workshop on NoC Architectures) | 研讨会 | NoC 架构 workshop | 每年约 7 月 |

### 3.2 期刊

| 期刊 | 级别 | 特点 |
|------|------|------|
| **IEEE TCAD** (Trans. on CAD) | SCI 一区/CCF A | EDA/架构/热分析 |
| **IEEE TVLSI** (Trans. on VLSI) | SCI 二区/CCF B | VLSI 设计（2024 Best Paper 就是热管理） |
| **ACM JETC** (J. on Emerging Technologies in Computing) | SCI 三区 | 新兴计算架构 |
| **J. Supercomputing** | SCI 三区 | 多篇热感知 NoC 论文在此发表 |
| **Integration, the VLSI Journal** | SCI 三区 | VLSI 集成设计 |
| **Microprocessors and Microsystems** | SCI 四区 | 嵌入式/NoC |

### 3.3 推荐投稿策略

1. **首选 DAC/ICCAD**：如果实验充分且有硬件实现讨论（我们做了硬件参数映射）
2. **其次 DATE**：NoC 热管理有收录历史
3. **保底 GLSVLSI + J. Supercomputing**：GLSVLSI 2024 有 TTNNM（热+流量 NN 映射），与我们方向最近

---

## 4. 关键参考文献

1. Liao YH, Chen CT, Wang LC, Chen KC. "Adaptive Machine Learning-Based Proactive Thermal Management for NoC Systems." IEEE TVLSI, 2024 (Best Paper). — 闭环预测+RL 降频

2. Dadmand F, Reshadi M, Asadzadeh M. "Adaptive multi-beltway thermal-aware routing algorithm for 3D NoC system." J. Supercomputing, 2025. — 多模式热感知路由

3. Li Z, Fan H, et al. "TTNNM: Thermal- and Traffic-Aware Neural Network Mapping on 3D-NoC-based Accelerator." GLSVLSI, 2024. — 热+流量感知 NN 映射

4. Asadzadeh M, Reza H, Khademzadeh A. "Thermal-aware application mapping using genetic and fuzzy logic techniques." J. Supercomputing, 2024. — GA+模糊逻辑热感知映射

5. Mo L, Li X, Kritikakou A, Zhai X. "Contention and Reliability-Aware Energy Efficiency Task Mapping on NoC-Based MPSoCs." IEEE Trans. Reliability, 2024. — MILP 联合优化

6. Ishak SA, Wu H, Tariq UU. "Energy-aware task scheduling for streaming applications on NoC-based MPSoCs." J. King Saud Univ., 2024. — DVFS + 任务调度

7. Masdari M, et al. "Towards Task Mapping Approaches in Network on Chips: A Comprehensive Survey." Microprocessors and Microsystems, 2023. — NoC 任务映射综述

8. Samala J, Soumya J. "Enhancing NoC Performance Parameters Evaluation: A Data-Driven Approach with Auto-ML Framework." 2024. — Noxim+McPAT+HotSpot 联合仿真

9. Tang M, Hong X. "Reinforcement learning-driven task migration for effective temperature management in 3D NoC systems." Scientific Reports, 2025. — RL 任务迁移

10. Skadron K, et al. "Temperature-aware microarchitecture." ISCA, 2003. — HotSpot 原始论文
