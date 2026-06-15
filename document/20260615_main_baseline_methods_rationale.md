# 主文两个 baseline 的实现方法与选择依据

生成日期：2026-06-15

本文档简要整理当前主文使用的两个 method-level baselines：`Thermal-SA-TAS` 和 `CommAware-Heuristic`。两者都不是对某一篇论文的逐行复现，而是面向 HNOCS 当前 4x4 ONoC、静态 DAG workload 和统一 OMNeT++ 评估链路的 literature-inspired baseline。

## 1. Thermal-SA-TAS

### 实现方法

代码位置：`D:\HNOCS\experiment\thermal_sa_tas_baseline`

`Thermal-SA-TAS` 是一个热感知 simulated annealing baseline。它先从初始映射读取 task-to-PE assignment，然后在静态 DAG 上使用轻量 list scheduling 和 RC/dynamic-RC 热代理估计候选映射的热行为。搜索目标不使用本文 Full-GA 的完整 composite objective，也不在搜索阶段调用 OMNeT++，而是使用较窄的热主导代理目标：

```text
J_TAS = 0.60 * Tmax_proxy / Tmax_ref
      + 0.25 * SigmaT_proxy / SigmaT_ref
      + 0.10 * HotCount_proxy / max(1, HotCount_ref)
      + 0.05 * MakespanProxy / Makespan_ref
```

搜索过程采用 simulated annealing，在 hot/cool PE 之间进行交换、局部扰动和多次 restart；最终 mapping 再交给与 B-2/Full-GA 相同的 OMNeT++ 评估链路生成 `metrics.json`。因此它是“热代理搜索 + 统一仿真评估”的 baseline。

### 参考论文依据

该 baseline 参考的是热感知 task allocation and scheduling 方向。Mukherjee 等提出的 thermal-aware TAS 方法把 task allocation 和 scheduling 作为联合优化对象，并用 simulated annealing 降低 NoC/多核平台上的温度相关目标。这与本文“任务映射影响热分布和执行时序”的问题设置相近，因此适合作为热感知 baseline。

### 为什么可以作为 baseline

选择它的原因是：它专门压力测试本文方法的热管理能力。相比简单 ThermalGreedy，它不仅看静态热源分布，还引入 DAG 调度、峰值热窗口和温度不均衡代理，更能形成有竞争力的热侧对照。同时，它不使用本文的 OMNeT++ simulator-in-the-loop GA，也不使用完整九项 objective，因此不会与 proposed method 共享核心优化机制。

写作边界：应称为 `TAS-inspired thermal simulated annealing baseline`，不要写成 Mukherjee et al. 的精确复现。

## 2. CommAware-Heuristic

### 实现方法

代码位置：`D:\HNOCS\experiment\comm_aware_baseline`

`CommAware-Heuristic` 是一个确定性的通信感知启发式 baseline。它只使用静态 task graph 的通信信息，不读取温度、DVFS、makespan、energy、OMNeT++ 结果或 Full-GA composite cost。代理目标为：

```text
CommProxy(M) = raw_comm_cost(M) + lambda_cong * max_edge_load(M)
```

其中 `raw_comm_cost` 为 `producer.output_data_size * Manhattan_hops` 的总和，`max_edge_load` 为确定性 XY routing 下单条物理 mesh edge 上累积的最大通信量，默认 `lambda_cong = 0.25`。算法先选择通信度最高的 seed task，放到中心候选 PE，然后按通信度依次放置其他任务，并进行 deterministic pairwise local swaps；只有通信代理变好时才接受交换。最终 mapping 同样使用统一 OMNeT++ 链路评估。

### 参考论文依据

NoC mapping 文献中，通信量、hop distance、带宽/链路负载和通信能耗是非常经典的 mapping baseline 目标。Murali 和 De Micheli 的 bandwidth-constrained mapping 工作以 mesh NoC 上的带宽约束和通信代价为核心；Hu 和 Marculescu 的 energy-aware mapping 工作则把 IP/core 映射到规则 NoC，使通信能耗最小并满足性能约束。`CommAware-Heuristic` 正是对这一类 communication-aware / bandwidth-aware / hop-energy-aware mapping 思路的 HNOCS 平台适配。

### 为什么可以作为 baseline

选择它的原因是：本文的 ONoC 任务重映射不仅影响温度，也显著影响光通信路径、拥塞和能耗。因此需要一个“只关心通信”的 baseline 来检验 proposed method 是否只是借助通信压缩取得优势，还是能在通信、热、DVFS、性能和能耗之间做系统级折中。

该 baseline 的边界非常清楚：搜索阶段只优化通信代理，不接触热模型、DVFS、makespan 和 optical energy。若它在通信指标上较强但 full-objective score 较差，就能说明单纯通信优化不足以解决本文的系统级热管理问题。

写作边界：应称为 `literature-inspired communication-aware heuristic`，不要写成 Murali、Hu/Marculescu 或其他单一论文的精确复现。

## 3. 简短写作版本

可直接放入论文方法/实验设置中的简短说明：

> We compare Full-GA with two literature-inspired method-level baselines. Thermal-SA-TAS is a thermal simulated-annealing mapper adapted from thermal-aware task allocation and scheduling studies. It optimizes a narrow proxy composed of peak temperature, temperature imbalance, hot-PE count and a weak makespan term, and its final mapping is evaluated by the same OMNeT++ flow as Full-GA. CommAware-Heuristic is a deterministic communication-aware mapper inspired by classical NoC mapping methods that minimize hop-weighted communication cost and bandwidth pressure. It optimizes only a communication proxy based on Manhattan distance and XY-routed edge load. These two baselines isolate the thermal-only and communication-only design philosophies, respectively, while avoiding reuse of the proposed simulator-in-the-loop GA objective.

中文对应：

> 本文选择两个文献启发式 method-level baselines。`Thermal-SA-TAS` 代表热感知 task allocation/scheduling 思路，使用 simulated annealing 优化由峰值温度、温度不均衡、热点 PE 数和弱 makespan 项组成的热代理目标；最终映射仍通过与 Full-GA 相同的 OMNeT++ 流程评估。`CommAware-Heuristic` 代表经典 NoC communication-aware mapping 思路，只优化由 Manhattan-hop 通信代价和 XY-routing 边负载组成的通信代理。二者分别对应热优先和通信优先的设计哲学，且不复用本文 simulator-in-the-loop GA 的完整目标函数，因此适合作为公平、可解释的对照方法。

## 4. 参考文献

1. Priyajit Mukherjee, et al. *Thermal-aware task allocation and scheduling for periodic real-time applications in mesh-based heterogeneous NoCs*. Real-Time Systems, 2019. DOI: `10.1007/s11241-019-09327-x`.  
   官方页面：[ACM DOI page](https://dl.acm.org/doi/abs/10.1007/s11241-019-09327-x)

2. Srinivasan Murali and Giovanni De Micheli. *Bandwidth-Constrained Mapping of Cores onto NoC Architectures*. DATE, 2004. DOI: `10.1109/DATE.2004.1269002`.  
   官方/索引页面：[ACM record](https://dl.acm.org/doi/10.5555/968879.969207), [OpenAIRE DOI record](https://oamonitor.ireland.openaire.eu/rpo/rcsi/search/publication?pid=10.1109%2Fdate.2004.1269002)

3. Jingcao Hu and Radu Marculescu. *Energy-aware mapping for tile-based NoC architectures under performance constraints*. ASP-DAC, 2003. DOI/ACM record: `10.1145/1119772.1119818`.  
   官方页面：[ACM DOI page](https://dl.acm.org/doi/10.1145/1119772.1119818)
