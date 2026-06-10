# HNOCS 闭环热感知 NoC 仿真 — 实现文档

## 1. 能耗模型

片上网络的总能耗来自两个层面：PE（计算单元）和 Router（路由节点）。每层又分为静态能耗和动态能耗，以 100ns 为窗口统计。

### 1.1 PE 能耗

PE 的静态能耗来自晶体管泄漏电流。泄漏电流随温度指数增长——这是 CMOS 器件的物理特性：温度升高导致亚阈值斜率退化，泄漏电流增大，进而产生更多热量，形成正反馈。

**PE 总能耗**：

$$E_{PE} = E_{static}^{PE} + E_{dynamic}^{PE}$$

**静态能耗**（温度依赖）—— PE 空闲时的全部功耗来自泄漏，计算时功耗 = 动态开关功耗 + 泄漏功耗：

$$E_{static}^{PE} = \int_{t_0}^{t_1} P_{static}(T(t)) \, dt \quad \text{（以窗口离散求和）}$$

$$P_{static}(T) = \begin{cases} P_{leak}(T) & \text{PE 空闲} \\[4pt] P_{leak}(T) + (P_{compute} - P_{idle}) & \text{PE 计算中} \end{cases}$$

其中 $P_{compute} - P_{idle}$ 为动态开关功耗（与温度无关），$P_{leak}(T)$ 为温度依赖的泄漏功耗。

**泄漏功耗的温度依赖**（CMOS 亚阈值泄漏模型，$T_0 = 15\text{K}$ 意味着每升温约 10°C 泄漏翻倍）：

$$P_{leak}(T) = P_{idle} \times \exp\!\left(\frac{T - T_{ambient}}{T_0}\right)$$

此公式是正反馈的核心——温度升高 → 泄漏增大 → 功耗加大 → 温度进一步升高。系统最终收敛于新的热平衡点（因为对流散热也随温差增大而增大）。

**动态能耗**（与温度无关，取决于通信事件计数）：

$$E_{dynamic}^{PE} = N_{send} \cdot E_{send} + N_{recv} \cdot E_{recv}$$

| 参数 | 默认值 | 说明 |
|------|--------|------|
| $P_{idle}$ | 0.5 W | 空闲泄漏功率（$T_{amb}$ 下） |
| $P_{compute}$ | 2.0 W | 计算时总功率 |
| $E_{send}$ | $1\times 10^{-10}$ J | 每发送一个 flit 的能耗 |
| $E_{recv}$ | $5\times 10^{-11}$ J | 每接收一个 flit 的能耗 |
| $T_0$ | 15 K | 泄漏温度特征常数 |

### 1.2 Router 能耗

Router 的能耗来自每个端口的静态泄漏和动态操作（buffer 读写、crossbar 遍历）。

**Router 总能耗**：

$$E_{router} = E_{static}^{router} + E_{dynamic}^{router}$$

**静态能耗**（每个端口的温度依赖泄漏）：

$$E_{static}^{router} = \sum_{port} P_{leak}^{router}(T) \times \Delta t$$

$$P_{leak}^{router}(T) = P_{leak}^{nom} \times \exp\!\left(\frac{T - T_{ambient}}{T_0}\right)$$

一个 Router 有 5 个端口，实际功耗 = 各端口泄漏之和。

**动态能耗**（buffer 读写及 crossbar 遍历，与温度无关）：

$$E_{dynamic}^{router} = N_{buf\_write} \cdot E_{buf\_write} + N_{buf\_read} \cdot E_{buf\_read} + N_{crossbar} \cdot E_{crossbar}$$

| 参数 | 默认值 | 说明 |
|------|--------|------|
| $P_{leak}^{nom}$ | $1\times 10^{-3}$ W | 单端口额定泄漏 |
| $E_{buf\_write}$ | $1\times 10^{-12}$ J | 写 buffer 能耗 |
| $E_{buf\_read}$ | $1\times 10^{-12}$ J | 读 buffer 能耗 |
| $E_{crossbar}$ | $0.5\times 10^{-12}$ J | crossbar 遍历能耗 |

---

## 2. 任务计算时间

### 2.1 名义计算时间（无降频）

任务的**名义计算时间** $t_{nominal}$ 在降频前确定，有两种方式：

**方式 A**（CSV 直接指定）：CSV 第三列 `computeTime_ns` 直接给出名义计算时间（单位：纳秒）。解析时转换为秒：

$$t_{nominal} = \text{computeTime\_ns} \times 10^{-9} \text{ s}$$

**方式 B**（数据量推导）：当参数 `computeDensity > 0` 时，根据任务的输出数据量计算：

$$t_{nominal} = \text{outputDataSize} \times \text{computeDensity} \times 10^{-9} \text{ s}$$

其中 `computeDensity` 单位为 ns/B，表示每字节输出数据所需的计算时间。例如 2352 B × 21.3 ns/B = 50000 ns = 50 µs。

`computeDensity = 0` 时使用方式 A（向后兼容）。

### 2.2 实际计算时间（降频后）

名义时间经 DVFS 缩放后得到实际时间（见第 3 节）。

---

## 3. DVFS 热降频模型

### 3.1 物理动机

现代芯片都有温度保护机制：当某区域温度超过安全阈值时，硬件自动降低该区域的时钟频率和电压（DVFS），减少发热，避免永久损坏。频率降低 → 同样计算量需要更长时间 → 任务完成延迟。

在我们的仿真中，**PE 执行任务的耗时不是固定值，而是随 PE 当前温度动态变化**。温度越高的 PE 计算越慢。这正是热感知调度要解决的核心问题：通过把任务路由到冷 PE，避免降频惩罚。

### 3.2 降频公式

$$t_{actual} = t_{nominal} \times \alpha(T)$$

$$\alpha(T) = \begin{cases} 1 & T \leq T_{throttle} \\[4pt] 1 + \beta \cdot (T - T_{throttle}) & T > T_{throttle} \end{cases}$$

**参数选取依据**：$\beta = 0.05 \text{ K}^{-1}$ 意味着每超过阈值 10°C，降频 50%。这与工业芯片的 DVFS 曲线数量级一致（如 NVIDIA GPU 每 10°C 掉 50–150 MHz，基准约 1.5 GHz，对应 3–10%/10°C 的降幅）。$T_{throttle} = 320\text{K (47°C)}$ 设为略高于环境温度，使得即使是轻微温升也能触发降频（仿真中温升范围 ~3–8°C，需要低阈值才能观察到效果）。

**降频惩罚比**（论文核心对比指标）：

$$R_{throttle} = \frac{t_{actual} - t_{nominal}}{t_{nominal}} = \alpha(T) - 1$$

| 参数 | 默认值 | 说明 |
|------|--------|------|
| $T_{throttle}$ | 320 K (47°C) | 降频触发温度 |
| $\beta$ | 0.05 K⁻¹ | 降频斜率 |

### 3.3 论文中的意义

降频惩罚比 $R_{throttle}$ 是衡量"热问题有多严重"的直接指标。Baseline（XY 路由固定映射）下，热点 PE 持续承载计算任务，温度高 → 降频多 → $R_{throttle}$ 大。Proposed（温度感知调度）下，GB 自动避开热点 PE，PE 温度低 → $R_{throttle}$ 小。两者对比直接量化了热感知调度的收益。

---

## 4. RC 热网络模型

### 4.1 物理原理与电学类比

芯片上的热传导遵循傅里叶定律。离散化为节点网络后，其数学形式与 RC 电路完全一致：

| 热学量 | 电学类比 |
|--------|---------|
| 温度 $T$ (K) | 电压 $V$ (V) |
| 功率 $P$ (W) | 电流 $I$ (A) |
| 热阻 $R_{th}$ (K/W) | 电阻 $R$ (Ω) |
| 热容 $C_{th}$ (J/K) | 电容 $C$ (F) |
| 时间常数 $\tau = R_{th}C_{th}$ (s) | RC 时间常数 |

热阻反映材料阻碍热流的能力（取决于厚度和热导率），热容反映材料存储热量的能力（取决于体积、密度和比热容）。硅 die 的典型热时间常数在微秒量级。

### 4.2 热网络拓扑

系统包含 $N = N_{PE} + N_{router}$ 个热节点（4×4 mesh 下各 16 个，共 32 节点）。每个节点有三类传热路径：

| 路径 | 热阻参数 | 物理含义 |
|------|---------|---------|
| 垂直对流（到环境） | $R_{conv}^{PE}$、$R_{conv}^{router}$ | 芯片 → TIM → 散热盖 → 散热器 → 空气 |
| 水平耦合（相邻同层节点） | $R_{lateral}^{PE}$、$R_{lateral}^{router}$ | 硅 die 面内导热（$R \propto \frac{\text{pitch}}{k_{Si} \cdot A_{cross}}$） |
| 层间耦合（同位置 PE ↔ Router） | $R_{pe2router}$ | PE 和 Router 在同一 die 上紧密相邻的垂直导热 |

### 4.3 控制方程

对 PE 节点 $i$，温度变化率由净热流决定：

$$C_{PE} \frac{dT_i^{PE}}{dt} = \underbrace{P_i^{PE}}_{\text{功耗输入}} - \underbrace{\frac{T_i^{PE} - T_{ambient}}{R_{conv}^{PE}}}_{\text{向环境散热}} - \underbrace{\frac{T_i^{PE} - T_i^{router}}{R_{pe2router}}}_{\text{向本地Router导热}} - \underbrace{\sum_{j \in \mathcal{N}(i)} \frac{T_i^{PE} - T_j^{PE}}{R_{lateral}^{PE}}}_{\text{向相邻PE导热}}$$

$\mathcal{N}(i)$ 为 PE $i$ 在网格中的 2–4 个相邻 PE（角节点 2 邻，边节点 3 邻，内部节点 4 邻）。

对 Router 节点同理，功耗为 $P_i^{router}$，散热项对称。水平耦合和层间耦合的热流方向由温差决定：热量总是从高温流向低温。

### 4.4 数值求解

采用**显式欧拉法**，步长与能耗窗口同步（$\Delta t = 100\text{ns}$）：

$$T(t + \Delta t) = T(t) + \Delta t \cdot \frac{dT}{dt}\biggr|_{t}$$

所有节点**同步更新**（先遍历全部节点计算 $dT$，再统一施加 $T \leftarrow T + dT$），保证热流守恒——从节点 $i$ 流向节点 $j$ 的热量等于从节点 $j$ 获得的冷量。

**稳定性条件**：对单节点模型，欧拉法稳定要求 $\Delta t < 2\tau$（$\tau = R_{eff} \cdot C$）。系统有效时间常数 $\tau_{eff} \approx 1.4\,\mu\text{s}$，$\Delta t/\tau \approx 0.07 \ll 2$，远在稳定域内。

### 4.5 封装热阻的物理估算

$R_{conv}$ 封装了从 die 到环境的三段热阻串联：TIM（导热界面材料）+ IHS（散热盖）+ 散热器。各段热阻可用下式估算：

$$R = \frac{d}{k \cdot A}$$

其中 $d$ 为厚度，$k$ 为材料热导率，$A$ 为截面积。4×4 mesh 假设 die 面积 10×10 mm²，每 PE 面积 2.5×2.5 mm²：

| 材料 | 厚度 | $k$ (W/m·K) | $R$ (K/W) |
|------|------|------------|-----------|
| Si die（水平） | 0.5 mm | 148 | ~13.5 |
| TIM | 0.1 mm | 3 | ~0.5 |
| Cu IHS | 2 mm | 401 | ~1.0 |
| 散热器 | — | — | ~5.0 |
| **合计（垂直）** | — | — | **~6.5** |

我们的默认参数 $R_{conv}^{PE} = 8\text{ K/W}$ 包含了上述三段垂直热阻加一定裕量。

### 4.6 默认参数

| 参数 | 值 | 单位 | 说明 |
|------|-----|------|------|
| $R_{conv}^{PE}$ | 8 | K/W | PE 垂直封装热阻 |
| $R_{conv}^{router}$ | 10 | K/W | Router 垂直封装热阻 |
| $R_{lateral}^{PE}$ | 15 | K/W | PE 间水平热阻 |
| $R_{lateral}^{router}$ | 15 | K/W | Router 间水平热阻 |
| $R_{pe2router}$ | 3 | K/W | PE-Router 耦合热阻 |
| $C_{PE}$ | $1\times 10^{-6}$ | J/K | PE 热容 |
| $C_{router}$ | $2\times 10^{-7}$ | J/K | Router 热容 |
| $T_{ambient}$ | 318.15 (45°C) | K | 环境温度 |

---

## 5. 温度感知任务调度

### 5.1 任务模型

任务通过 CSV 文件定义。每行格式：

```
taskId, peId, computeTime_ns, outputDataSize_B, succTaskId1:succPE1, succTaskId2:succPE2, ...
```

| 列 | 含义 | 示例 |
|----|------|------|
| `taskId` | 任务唯一标识 | 1 |
| `peId` | 目标 PE（见下） | -2 |
| `computeTime_ns` | 名义计算时间（纳秒） | 50000 |
| `outputDataSize_B` | 输出数据量（字节） | 2352 |
| `succ:succPE` | 后继任务及所在 PE；`-1:-1` 表示结果发回 GB | -1:-1 |

`peId` 的三种取值：

| peId | 含义 | 行为 |
|------|------|------|
| $-1$ | GB 注入标记（非计算任务） | 仅作 CSV 结构标记 |
| $-2$ | 动态分配 | GB 在运行时根据温度决定目标 PE |
| $\geq 0$ | 静态分配 | PE 自己从 CSV 加载并自启动 |

**`remapToDynamic` 参数**：当设为 `true` 时，GB 自动将 CSV 中所有 `peId ≥ 0` 的任务在运行时转换为 `peId = -2`，即全部走动态调度。**同一 CSV 文件无需任何修改即可在静/动态两套方案间切换。**

### 5.2 代价函数

GB 为每个待注入任务在所有空闲 PE 中计算代价，选代价最小的：

$$\text{cost}(PE_i) = w_T \cdot (T_i - T_{ambient}) + w_H \cdot \text{hops}(GB, PE_i)$$

- **温度项** $w_T \cdot (T_i - T_{ambient})$：惩罚高温 PE。$w_T = 1.0$，温度每高 1K 代价 +1。
- **跳数项** $w_H \cdot \text{hops}(GB, PE_i)$：惩罚远距离 PE。$w_H = 0.5$，GB 连接到 mesh 左边界，$\text{hops} = \text{PE 列索引}$（列 0 → 0 跳，列 3 → 3 跳）。

代价函数的设计使得 t=0 时（所有 PE 温度相等 = $T_{ambient}$），调度退化为最小跳数优先（负载均衡）。随着仿真运行、温度分化，温度项逐渐主导调度决策。

### 5.3 依赖驱动的调度

任务间的依赖关系由 CSV 的 successor 列定义，TaskGraphParser 自动反推 predecessor，并计算 `pendingDependencies`（未完成的前驱数量）：

- `pendingDependencies == 0` → 任务就绪，GB 立即寻找最优空闲 PE 注入
- `pendingDependencies > 0` → 任务等待，不占用任何 PE

当任务 $A$ 完成（其 START flit 到达 GB），遍历 $A$ 的所有后继任务，将其 `pendingDependencies` 减 1。若减至 0，则该后继就绪，参与下一轮调度。

**这是 CSV 自然控制并行度的机制**：无依赖的全并行，有依赖的自然串行。不需要人工设置 `maxConcurrent` 等参数。

### 5.4 任务完成检测（统一标准）

仿真何时结束？标准：**所有需要发回 GB 的结果数据全部到达 GB。**

具体实现：GB 在初始化时统计 `resultPacketsExpected`（CSV 中 successor 为 $-1$ 的任务总数）。运行时每收到一个 END flit（结果包的最后一个 flit），计数器 `resultPacketsReceived` 加 1。当 `resultPacketsReceived == resultPacketsExpected` 时，记录 `allResultsArrivedAt` 并调用 `endSimulation()`。

**该标准对静态（General）和动态（Dynamic）配置均适用。**

---

## 6. 仿真框架

### 6.1 实验配置

同一 CSV 文件 `tasks_optic_output.csv`，通过两个 INI 配置段实现对比实验：

| | `[General]`（Baseline） | `[Dynamic]`（Proposed） |
|---|---|---|
| 任务映射 | CSV 写死 PE 0, 4, 8, 12 | GB 温度感知动态分配 |
| `remapToDynamic` | false | true |
| 调度策略 | PE 自启动（无调度） | GB 依赖驱动调度 |
| 温度感知 | 无 | 有（代价函数含 ΔT 项） |
| 特色 | 传统 XY 路由 + 固定映射 | 闭环热感知映射 |

### 6.2 输出指标

**能耗指标**：

| Scalar | 含义 | 记录位置 |
|--------|------|---------|
| `totalStaticEnergyJ` | PE/Router 静态能耗（含 T 反馈） | TaskPE / InPortSync |
| `totalDynamicEnergyJ` | PE/Router 动态能耗（flit 事件） | 同上 |
| `totalEnergyJ` | 总能耗（= 静态 + 动态） | 同上 |

**性能指标**：

| Scalar | 含义 | 记录位置 |
|--------|------|---------|
| `totalComputeTimeNominal` | 无降频总计算时间 | TaskPE |
| `totalThrottlePenalty` | 因降频多花的时间 | TaskPE |
| `throttlePenaltyRatio` | 降频惩罚比例 | TaskPE |
| `allTasksCompletedAt` | 最后计算完成时刻 | TaskPE |
| `allResultsArrivedAt` | 全部结果到达 GB 时刻 | GlobalBuffer |

**温度指标**（时序向量）：

| Vector | 含义 |
|--------|------|
| `pe-die-temperature` | 每个 PE 的温度（每 100ns） |
| `router-die-temperature` | 每个 Router 的温度（每 100ns） |
| HotSpot `.trace` | 可离线验证的功率 trace 文件 |

**论文推荐对比**：Baseline vs Proposed 的 `throttlePenaltyRatio` 和 `allResultsArrivedAt`。

### 6.3 可视化

Qtenv 中 PE 和 Router 旁显示实时温度文字（如 `48.5C`），无需额外操作。

---

## 7. 关键公式速查汇总

**PE 能耗**：
$$E_{PE} = \underbrace{\int P_{static}(T)\,dt}_{\text{温度依赖泄漏}} + \underbrace{N_{send}E_{send} + N_{recv}E_{recv}}_{\text{通信事件}}$$

$$P_{static}(T) = \begin{cases} P_{idle} \cdot e^{(T-T_{amb})/T_0} & \text{idle} \\ (P_{compute}-P_{idle}) + P_{idle} \cdot e^{(T-T_{amb})/T_0} & \text{computing} \end{cases}$$

**Router 能耗**：
$$E_{router} = \sum_{ports}\!\left(P_{leak}^{nom} e^{(T-T_{amb})/T_0}\!\cdot\!\Delta t + N_wE_w + N_rE_r\right) + N_{xbar}E_{xbar}$$

**RC 热网络**：
$$C\frac{dT_i}{dt} = P_i - \frac{T_i\!-\!T_{amb}}{R_{conv}} - \frac{T_i\!-\!T_{router(i)}}{R_{couple}} - \sum_{j\in\mathcal{N}(i)}\!\frac{T_i\!-\!T_j}{R_{lateral}}$$

**欧拉离散化**（$\Delta t = 100\text{ns}$，同步更新）：
$$T_i(t+\Delta t) = T_i(t) + \frac{\Delta t}{C}\!\left[P_i - \frac{T_i\!-\!T_{amb}}{R_{conv}} - \frac{T_i\!-\!T_{router(i)}}{R_{couple}} - \sum_{j}\frac{T_i\!-\!T_j}{R_{lateral}}\right]$$

**计算时间**（名义 → DVFS → 实际）：
$$t_{nom} = \text{computeTime\_ns}\!\times\!10^{-9} \quad\text{或}\quad \text{dataSize}\!\times\!\text{computeDensity}\!\times\!10^{-9}$$

$$t_{actual} = t_{nom} \cdot \max\!\big(1,\; 1 + \beta(T - T_{throttle})\big)$$

**调度代价**：
$$\text{cost}(PE_i) = w_T(T_i - T_{amb}) + w_H\cdot\text{hops}(GB, PE_i)$$

**任务完成时间**：
$$T_{complete} = \min\!\big\{\,t \;\big|\; N_{END\_flits}(t) = N_{expected}\,\big\}$$
