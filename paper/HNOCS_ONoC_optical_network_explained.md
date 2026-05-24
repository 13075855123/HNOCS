# HNOCS 光片上网络 (ONoC) 架构详解

> 基于 HNOCS_master，分析光网络部分的搭建方式、数据传输机制、建链拆链流程及波分复用实现。

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [物理层：Torus 网格拓扑](#3-物理层torus-网格拓扑)
4. [逻辑层：可切换的逻辑拓扑](#4-逻辑层可切换的逻辑拓扑)
5. [电控面与光数据面分离](#5-电控面与光数据面分离)
6. [建链与拆链机制（SETUP/ACK 握手）](#6-建链与拆链机制setupack-握手)
7. [光旁路直通（sendDirect）](#7-光旁路直通senddirect)
8. [波分复用 (WDM) 与空分复用 (SDM)](#8-波分复用-wdm-与空分复用-sdm)
9. [器件级光预算建模](#9-器件级光预算建模)
10. [有源器件与无源器件](#10-有源器件与无源器件)
11. [建链失败处理](#11-建链失败处理)
12. [波长数与带宽配置](#12-波长数与带宽配置)
13. [与真实微环架构的对比](#13-与真实微环架构的对比)
14. [当前实现状态与待完成工作](#14-当前实现状态与待完成工作)
15. [关键源码索引](#15-关键源码索引)

---

## 1. 项目概述

ONoC (Optical Network-on-Chip) 是在 HNOCS 电互连仿真器基础上扩展的光片上网络仿真平台。核心目标：

1. **网络可重构**：在固定物理 Torus 互连之上，通过 `LogicalTopologyManager` 维护动态逻辑邻接矩阵 A(t)，支持运行时切换 mesh、ring、star、tree、torus 五种逻辑拓扑。
2. **器件级光传输验证**：引入光学器件参数（插入损耗、串扰、调制/解调损耗等），通过波分复用 (WDM) 与空分复用 (SDM) 实现端到端传输性能验证。
3. **故障检测与自恢复**（待实现）：支持故障注入、10 ms 节点损坏检测及备用节点替换或路径重构。

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────┐
│                    ONoCTorus.ned                      │
│                                                      │
│  ┌──────────────────────────────┐                    │
│  │  LogicalTopologyManager      │  ← 逻辑拓扑 A(t)   │
│  │  - 5种拓扑构建                │                    │
│  │  - BFS路由查询                │                    │
│  │  - 波长/SDM分配与释放         │                    │
│  │  - 光预算计算                 │                    │
│  └──────────────────────────────┘                    │
│                                                      │
│  ┌──────────────────────────────┐                    │
│  │  OpticalCircuitController    │  ← ACK驱动光路跟踪  │
│  └──────────────────────────────┘                    │
│                                                      │
│  ┌──┐ ┌──┐ ┌──┐ ┌──┐                                │
│  │R0│←│R1│←│R2│←│R3│  ← 物理 Torus (4×4)           │
│  └┬─┘ └┬─┘ └┬─┘ └┬─┘                                │
│   │    │    │    │                                   │
│  ┌┴─┐ ┌┴─┐ ┌┴─┐ ┌┴─┐                                │
│  │NI│ │NI│ │NI│ │NI│  ← 网络接口 (core)              │
│  └┬─┘ └┬─┘ └┬─┘ └┬─┘                                │
│   │    │    │    │                                   │
│  Src  Src  Src  Src   ← PktFifoSrc (双队列)         │
│  Sink Sink Sink Sink  ← InfiniteBWMultiVCSink        │
└──────────────────────────────────────────────────────┘
```

- **物理层固定不变**：Torus 网格 + TorusLink 通道
- **逻辑层可重构**：A(t) 控制哪些逻辑边可用
- **路由可替换**：`ReconfigurableOPCalc` 替代 XY 路由，查询 `LogicalTopologyManager` 获取下一跳

---

## 3. 物理层：Torus 网格拓扑

`src/onoc/topologies/ONoCTorus.ned` 定义：

```
router[0] ↔ router[1] ↔ ... ↔ router[columns-1]    东西连接（含 wrap-around）
router[0] ↔ router[columns] ↔ ...                    南北连接（含 wrap-around）
router[i] ↔ core[i]                                    本地连接
```

关键参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `rows` / `columns` | 4 / 4 | Torus 网格规模 |
| `TorusLink.datarate` | 16 Gbps | 物理链路速率 |

每个 core（网络接口 NI）内含一个 `PktFifoSrc`（源端）和一个 Sink（汇端）。

---

## 4. 逻辑层：可切换的逻辑拓扑

`LogicalTopologyManager` (`src/onoc/control/LogicalTopologyManager.cc`) 维护运行时可变的**无向邻接矩阵 A(t)**。

### 4.1 五种逻辑拓扑

| 拓扑 | 构建方式 |
|------|---------|
| **Torus** | 每个节点连东、南邻居 + wrap-around |
| **Mesh** | 同 Torus 但无 wrap-around，边界节点度数低 |
| **Ring** | 蛇形遍历所有节点形成单环（`buildSnakeRingOrder`） |
| **Star** | 中心节点直连所有叶子，支持距离排序和 ID 排序 |
| **Tree** | BFS 生成树，根为 starCenterId，在 Torus 邻居上蔓延 |

### 4.2 运行时拓扑切换

```ini
**.initialTopology = "torus"
**.topologySwitches = "30us:mesh;80us:ring"
```

`scheduleTopologySwitches()` 解析切换脚本，为每个切换时间点创建自消息。到达时间后 `handleMessage()` 调用 `applyTopology()` 清空并重建邻接矩阵。全程不重启仿真。

### 4.3 BFS 路由查询

`getLogicalNextHop(srcId, dstId)` 在当前逻辑邻接矩阵上运行 BFS，返回从 src 到 dst 的最短路径下一跳，供 `ReconfigurableOPCalc` 使用。

---

## 5. 电控面与光数据面分离

核心设计理念：**控制信令走电路由网络（慢），数据走光纤直通（快）**。

`PktFifoSrc` (`src/cores/sources/PktFifoSrc.cc`) 维护两个独立队列：

```
controlQ   → 走电路由器网络        → 用于 SETUP_REQ / SETUP_ACK / 常规数据包
opticalQ   → 走 sendDirect() 直达  → 用于光数据包 (ONOC_PKT_DATA)
```

关键参数：

| 参数 | 说明 |
|------|------|
| `enableSetupHandshake` | 是否启用电控建链握手 |
| `enableOpticalBypass` | 是否启用光旁路直通 |
| `opticalBurstSize` | 建链一次可发送的数据包数 |

---

## 6. 建链与拆链机制（SETUP/ACK 握手）

**"建链"**——发数据前通过电控面握手预留光路（波长 + 空间通道）。

**"拆链"**——数据 burst 发完后释放波长资源，让其他通信对可用。

### 6.1 完整时序

```
源端 (PktFifoSrc)                LogicalTopologyManager          目的端 Sink
      │                                      │                        │
      │  ① tryReserveSetupPath()             │                        │
      │  ───→ reserveOpticalPathForSetup()   │                        │
      │       ├─ 生成 circuitToken           │                        │
      │       ├─ 沿 XY 路径逐边检查波长空闲     │                        │
      │       ├─ first-fit 分配波长            │                        │
      │       └─ 占用 opticalEdgeOccupancy[][] │                       │
      │                                      │                        │
      │  ② enqueuePacket(SETUP_REQ)          │                        │
      │  ───→ controlQ → 电路由网络 ──────→   │                        │
      │                                      │                        │
      │                                      │      ③ 收到 SETUP_REQ   │
      │                                      │      生成 SETUP_ACK     │
      │  ④ 收到 SETUP_ACK                    │  ←── controlQ ← 电网络  │
      │     验证 token 匹配                   │                        │
      │     circuitReadyByDst = 1            │                        │
      │                                      │                        │
      │  ⑤ enqueuePacket(DATA)              │                        │
      │  ──→ opticalQ → sendDirect() ───────────────────────────→ opticalIn
      │                                      │                        │
      │  ⑥ burst 发完                        │                        │
      │     circuitReadyByDst = 0            │                        │
      │     releaseOpticalPath() ← 拆链       │                        │
```

### 6.2 源端状态机

在 `handleGenMsg()` 和 `handleControlEvent()` 中实现，由 `circuitReadyByDst[dstId]` 标志驱动：

```
状态 A: 无光路
  │  circuitReadyByDst = 0, setupPendingByDst = 0
  │  → tryReserveSetupPath() 预留光路资源
  │  → enqueuePacket(SETUP_REQ) 发建链请求
  │  → 进入状态 B
  ↓
状态 B: 等待 ACK
  │  setupPendingByDst = 1
  │  启动 setupPendingTimeout 超时计时器
  │  → 收到 SETUP_ACK 且 token 匹配 → 进入状态 C
  │  → 超时未收到 → 释放预留资源，回到状态 A
  ↓
状态 C: 光路就绪
  │  circuitReadyByDst = 1
  │  → enqueuePacket(DATA) 把数据放入 opticalQ
  │  → sendOpticalFlitFromQ() → sendDirect() 光旁路发数据
  │  → burst 发完后 circuitReadyByDst = 0，回到状态 A
```

### 6.3 三种拆链场景

| 场景 | 触发条件 | 行为 |
|------|---------|------|
| **正常拆链** | burst 发完 `opticalBurstSize` 个数据包 | `circuitReadyByDst = 0`，调用 `releaseOpticalPathByToken()` 清空 `opticalEdgeOccupancy` |
| **超时拆链** | SETUP_REQ 发出后在 `setupPendingTimeout` 内未收到 ACK | `setupPendingTimeoutCount++`，释放资源，允许立即重试 |
| **过时 ACK** | 收到 ACK 但 token 不匹配或不在 pending 状态 | `setupAckStaleCount++`，释放该 token 对应的资源 |

### 6.4 建链握手的本质

握手的根本目的是**波长资源冲突避免**。如果同一波长被两对通信同时用于重叠路径，在波导交叉处会产生冲突。`LogicalTopologyManager` 的 `opticalEdgeOccupancy` 表就是用来确保"同一时刻、同一条边、同一空间通道、同一波长"只被一条光路占用。

---

## 7. 光旁路直通（sendDirect）

光数据包不经过路由器，通过 OMNeT++ 的 `sendDirect()` API 从源端直接投递到目的端 Sink。

```cpp
// PktFifoSrc::sendFlitDirectToSink() (行 372-393)
sendDirect(flit, propDelay, txDuration, sinkModule->gate("opticalIn"));
```

### 7.1 传播时延

```
propDelay = opticalBasePropagationDelay + opticalPerTorusHopDelay × hopCount
```

`hopCount` 是源到目的在 Torus 上的曼哈顿距离（含 wrap-around 最短路径）。

### 7.2 发送时长

```
effectiveRate = opticalWavelengthBitrate × wavelengthCount
txDuration = (8 × flitByteLength) / effectiveRate
```

波长数越多，有效速率越高，发送时间越短。

### 7.3 传输 vs 预算分离

- `sendDirect()` 决定**数据包何时到达**（传输时延模型）
- `OpticalPathMetrics` 决定**光信号还剩多少功率、误码率多少**（光预算模型）

两者解耦：传输一跳直达，但光预算按逐器件、逐 hop、逐微环的真实路径计算。

---

## 8. 波分复用 (WDM) 与空分复用 (SDM)

### 8.1 资源占用表

每条物理无向边上维护二维占用矩阵：

```
opticalEdgeOccupancy[edgeKey][spatialChannel][wavelengthIndex] = pktId
                         ↑            ↑               ↑
                    哪条物理边    哪个空间通道      哪个波长 (1~16)
```

示例 — router[0]↔router[1] 这条边的占用情况：

```
         λ1  λ2  λ3  λ4  ... λ16
  SDM0:   0   0  52   0        0     ← λ3 被 pktId=52 占用
  SDM1:  88   0   0   0        0     ← λ1 被 pktId=88 占用
```

### 8.2 波长分配算法

`tryAllocateOpticalPathForPacket()` 使用 first-fit 策略：

1. 沿 XY 路径确定边的序列
2. 对每个空间通道，扫描波长 1→max：
   - 检查该波长在路径上**所有边**是否都空闲
   - 空闲则选中
3. 累计到 `required` 个波长后，占用所有边的对应槽位
4. 所有空间通道都失败 → `insufficientResources = true` → 建链失败

### 8.3 包标签编码

每个 flit 的 SL 字段携带 32 位标签：

```
[ packetClass:8 | spatialChannel:8 | wavelengthMask:16 ]
                                       ↑
                      bit i=1 表示使用了波长 (i+1)
                      例如 0x0006 = 0b0110 = λ2 + λ3
```

### 8.4 波长索引与器件损耗的关系

微环对不同波长的响应不同。对波长 λ_i：

- **调制器端**：光经过 (i-1) 个微环的 through + 1 个微环的 drop
- **路由器内部**：through 数量取决于转向端口和 λ 索引
- **解调器端**：(i-1) 个 through + 1 个 drop

因此 λ_16 比 λ_1 经过更多微环 through，损耗更大。代码中 `perWavelengthTotalLoss_dB` 和 `perWavelengthReceivedPower_dBm` 会分别记录每个波长的实际损耗。

---

## 9. 器件级光预算建模

### 9.1 器件路径构建

`getDeviceLevelPathMetrics()` (行 961-1234) 构建从激光源到光电探测器的完整器件链：

```
Laser → 波导(source→modulator)
     → 调制器微环链: (λ_i-1)×through + 1×drop
     → 波导(modulator→router)
     → Router 0: 输入端口→输出端口
          through×N + drop×1 + bends×M
     → 波导(router→router)
     → SOA（增益 + ASE 噪声）
     → Router 1: ...
     → ... (逐 hop)
     → 波导(router→demodulator)
     → 解调器微环链: (λ_i-1)×through + 1×drop
     → 波导(demodulator→PD)
     → 光电探测器 (PD)
```

### 9.2 器件类型

| 器件 | 类型 | 损耗/增益 |
|------|------|----------|
| `DEV_WAVEGUIDE` | 无源 | 传播损耗 × 长度 (dB/cm) |
| `DEV_WAVEGUIDE_BEND` | 无源 | 弯曲损耗 (dB) |
| `DEV_RING_THROUGH` | 无源 | 微环直通插入损耗 (dB) |
| `DEV_RING_DROP` | 无源 | 微环下载损耗 (dB) |
| `DEV_MODULATOR` | 有源 | 调制器插入损耗 (dB) |
| `DEV_MUX` / `DEV_DEMUX` | 无源 | 复用/解复用器插入损耗 (dB) |
| `DEV_SOA` | 有源 | 增益 (dB 正值)，同时引入 ASE 噪声 |
| `DEV_PHOTODETECTOR` | 有源 | 光电转换损耗 (dB) |

### 9.3 光预算计算公式

**路径级（legacy，hop 累计）**：

```
L_total = L_mod + N_hop × L_ins + N_hop × L_xtalk + L_demod
P_rx = P_launch - L_total
Margin = P_rx - Sensitivity
```

**器件级（已实现，逐器件累加）**：

```
totalLoss_dB = Σ(modulator + ringThrough + ringDrop + waveguide + bend + mux/demux + detector) - Σ(SOA_gain)
receivedPower_dBm = launchPower_dBm - totalLoss_dB
SNR_dB = receivedPower_dBm - thermalNoiseFloor_dBm - SOA_ASE_accumulated
BER = 0.75 × erfc(√(SNR_linear / 10))    ← PAM4 调制
```

### 9.4 SOA 增益与 ASE 噪声

每个路由器 hop 之后放一个 SOA（`opticalEnableSOA = true` 时）：

```cpp
// LogicalTopologyManager.cc 行 1111-1117
if (opticalEnableSOA) {
    devPath.segments.push_back(DEV_SOA);  // 每个 hop 后一个 SOA
}
```

SOA 在提供正增益的同时引入 ASE 噪声：

```
P_ASE = 10 × log₁₀(h × ν × (G-1) × NF × BW)
```

多次 SOA 放大后 ASE 噪声累积，最终影响 SNR 和 BER。

---

## 10. 有源器件与无源器件

### 10.1 定义

- **无源器件 (Passive)**：不需要外部电能，不能向信号注入能量，只会引起衰减。包括波导、微环谐振器、弯曲波导、MUX/DEMUX。
- **有源器件 (Active)**：需要外部电泵浦/驱动，可以向光信号注入能量或进行光电转换。包括激光源、调制器、SOA、光电探测器。

### 10.2 微环路由是无源过程

微环的 through/drop 是纯物理现象——微环出厂时几何尺寸固定了谐振波长。光走到微环处：
- 波长匹配 → drop（谐振耦合下来）
- 波长不匹配 → through（直通）

全程不需要电信号控制，**物理层自动完成**。这就是"光路由无源"的含义。

### 10.3 仿真中的建链与真实微环的关系

| | 真实微环 | 当前仿真 |
|---|---|---|
| **路由方式** | 波长 = 地址，微环自动 drop | `LogicalTopologyManager` BFS + `sendDirect()` 直达 |
| **建链** | 不需要（波长分配即建链） | SETUP_REQ/ACK 握手预留波长 |
| **拆链** | 不需要（不发即停） | 主动释放 `opticalEdgeOccupancy` |
| **并行传输** | 不同 λ 天然正交 | first-fit 分配到不冲突的 (SDM, WDM) 槽位 |
| **多播** | 天然支持（总线广播） | 不支持（点对点，需多次建链） |
| **冲突解决** | 波长预分配 + 物理隔离 | 占用表检查 + 重试 |

---

## 11. 建链失败处理

建链可能因资源不足（波长/空间通道被占满）而失败，处理机制是**重试而非丢包**：

```
tryReserveSetupPath() 失败:
  ├─ setupReserveFailCount++           ← 记录失败次数
  ├─ nextSetupAttemptByDst = now + setupRetryDelay  ← 推迟重试 (默认 20ns)
  └─ scheduleAt(now + setupRetryDelay, genMsg)      ← 到时间重试
      return;  ← 不产生数据，不丢包
```

三种失败情况及行为：

| 失败原因 | 行为 |
|---------|------|
| **资源不足** | `setupReserveFailCount++`，等 `setupRetryDelay` 后重试 |
| **SETUP_REQ 超时未收到 ACK** | `setupPendingTimeoutCount++`，释放预留资源，立即允许重试 |
| **队列已满** | `FullQueueIndicator = 1`，包被丢弃 |

重试时间线示例：

```
t=0ns:   数据要发给 PE3
t=0ns:   tryReservePath → 失败（所需波长被占）
t=20ns:  retry → 失败
t=40ns:  retry → 成功！enqueue SETUP_REQ
t≈70ns:  SETUP_REQ → 电网络 → 目的端 → SETUP_ACK 返回
t≈100ns: 收到 ACK，circuitReady=1，开始发数据
```

---

## 12. 波长数与带宽配置

### 12.1 参数

波长数和带宽均**不固定**，可通过 INI 完整配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `defaultOpticalWavelengths` | 2 | 每对源-目默认波长数 |
| `maxOpticalWavelengths` | 16 | 波长数量硬上限 |
| `opticalWavelengthBitrate` | 256 Gbps | 单波长比特率 |
| `numOpticalSpatialChannels` | 1 | 空间通道数 |
| `opticalPairWavelengthOverrides` | `""` | 按源-目对定制波长数 |

### 12.2 带宽计算

```
effectiveRate = opticalWavelengthBitrate × wavelengthCount

默认: 2λ × 256 Gbps = 512 Gbps（已达到 >500 Gbps 目标）
最大: 16λ × 256 Gbps = 4 Tbps
```

### 12.3 配置示例

```ini
# 全局 4 波长
**.defaultOpticalWavelengths = 4        # 4 × 256 Gbps = 1 Tbps
**.maxOpticalWavelengths = 16

# 特定通信对定制
**.opticalPairWavelengthOverrides = "0->5:8;1->6:4"
# 源0→目的5 用 8 个波长 = 8 × 256 Gbps = 2 Tbps
# 源1→目的6 用 4 个波长 = 4 × 256 Gbps = 1 Tbps

# 单波长速率
**.source.opticalWavelengthBitrate = 32e9   # 单λ 32 Gbps
```

### 12.4 实际分配约束

实际能分到的波长数受限于：

```
能分配几个波长 = min(
    配置的 requiredWavelengths,
    maxOpticalWavelengths (16),
    路径上所有边的剩余空闲波长数
)
```

路径拥挤时，即使配置了 8 波长，实际分配可能不足，触发 `insufficientResources` 导致建链失败。

---

## 13. 与真实微环架构的对比

### 13.1 真实微环：波长 = 地址

```
        总线波导 (bus waveguide)
    ════════════════════════════════════════
      ↓↑ 微环 @ λ3    ↓↑ 微环 @ λ1
     Node A          Node B
```

- 每个微环被静态调谐到特定波长
- 当总线波导上传来 λ1 的光，只有 Node B 的微环谐振并 drop
- 其他波长的光直通（through），不受影响
- **多播天然支持**：如果 Node A 和 Node B 都装了 @λ1 的微环，两个都能收到

### 13.2 当前仿真与真实架构的差异

| 特性 | 真实微环架构 | 当前仿真 |
|------|------------|---------|
| **拓扑** | 总线/广播 | Torus 网格 + 逻辑邻接矩阵 |
| **路由** | 波长 = 地址，微环无源 drop | `LogicalTopologyManager` BFS + `sendDirect()` 一跳直达 |
| **建链** | 不需要（物理自动完成） | SETUP_REQ/ACK 握手预留资源 |
| **多播** | 天然支持 | 不支持（需多次建链） |
| **光预算** | 真实的逐器件物理损耗 | 器件级损耗累加（已实现），但光传输仍走 `sendDirect()` |
| **冲突避免** | 波长预分配 + 物理隔离 | 占用表 `opticalEdgeOccupancy` + first-fit |

### 13.3 模拟建链的目的

仿真的 SETUP/ACK 握手不是模拟微环的物理行为，而是模拟**控制面（如中央控制器）对波长资源的动态管理**。在真实系统中，波长分配可能是离线预配置的；仿真中通过握手来动态协调，使多对通信可以时分复用或按需分配波长。

---

## 14. 当前实现状态与待完成工作

### 14.1 已完成

| 功能 | 说明 |
|------|------|
| 可重构拓扑 | Torus/Mesh/Ring/Star/Tree，支持按时切换 |
| 电建链握手 + 光旁路 | 源端 controlQ/opticalQ 分离，`sendDirect()` 光直达 |
| WDM/SDM 波长分配 | first-fit 分配，per-edge per-wavelength 占用追踪 |
| 路径级光预算 | hop 级累计损耗 |
| 器件级光预算 | 调制→波导→微环 through/drop→弯曲→SOA→PD 逐器件累加 |
| SOA 增益 + ASE 噪声 | 逐 hop SOA 放大，ASE 噪声累积 |
| PAM4 SNR→BER | `0.75 × erfc(√(SNR/10))` |
| 预算不足检测 + 重路由标志 | margin/SNR/BER 阈值触发 |
| per-wavelength 统计 | 每个波长独立损耗/SNR/BER |

### 14.2 待完成

| 功能 | 说明 |
|------|------|
| 端到端 >500 Gbps 验证 | 需对照仿真结果验证 |
| BER 驱动 flit 错误/丢弃 | 当前仅记录 BER，未触发丢包 |
| 预算不足实际丢包 | 当前仅记录统计和重路由标志 |
| 微环编号与单环故障注入 | 故障隔离粒度 |
| 故障检测与自恢复 | 心跳探测/故障注入/备用替换/路径重构 |
| 真实器件级物理链路 | 当前 `sendDirect()` 直达，未逐器件传输 |
| Lumerical 参数接入 | CSV 加载框架已建，未接入实际参数 |
| 多播支持 | 当前仅支持单播 |

---

## 15. 关键源码索引

| 文件 | 功能 |
|------|------|
| `src/onoc/topologies/ONoCTorus.ned` | 顶层网络：固定物理 Torus + 逻辑拓扑管理器 |
| `src/onoc/control/LogicalTopologyManager.h` | ★ A(t) 邻接矩阵、波长分配、光预算查询接口 |
| `src/onoc/control/LogicalTopologyManager.cc` | ★ 五种拓扑构建、BFS 路由、first-fit 波长分配、器件级预算计算 |
| `src/cores/sources/PktFifoSrc.h` | ★ 双队列、建链状态机、光旁路接口 |
| `src/cores/sources/PktFifoSrc.cc` | ★ 建链握手实现、sendDirect、重试/超时处理、统计收集 |
| `src/onoc/optical/OpticalCircuitController.h/cc` | ACK 驱动的光路 open/close 状态跟踪 |
| `src/onoc/routing/ReconfigurableOPCalc.h/cc` | 查询 `LogicalTopologyManager` 的可重构路由 |
| `src/onoc/common/ControlPlaneEvents.h` | 包标签（SL）编码/解码、控制事件编码 |
| `src/onoc/common/OpticalPathMetrics.h` | 光路径度量对象（损耗/SNR/BER） |
| `src/onoc/common/OpticalDeviceModel.h/cc` | 器件类型枚举、参数结构、预算计算、PAM4 BER、SOA ASE 噪声 |
| `src/onoc/common/OpticalParamLoader.h/cc` | CSV/JSON 器件参数加载器 |
| `src/NoCs.msg` | 消息类型定义（FLIT, CREDIT, REQ, GNT 等） |

---

*文档整理自 HNOCS_master 源码分析，2026年5月。*
