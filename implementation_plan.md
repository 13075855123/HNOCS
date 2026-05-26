# HNOCS 光旁路仿真修复与完善计划

## 当前状态回顾

### 已有（正确运行）
- 纯电 NoC 仿真（`HNOCS_clean`）：PE 能耗 + 路由器能耗 → ThermalModel → 温度
- 光旁路数据面：`sendDirect()` 绕过电路由器发送数据包（功能正确）
- 电层握手建链：SETUP_REQ/ACK 走电路由器 → 光路波长分配 → 数据传输 → 拆链

### 三个核心缺陷

| # | 问题 | 影响 |
|---|------|------|
| 1 | **无光功率分光**：每个 srcId 用同一个 `launchPower_dBm`，等于假设每路独立激光器 | 光功率预算不真实 |
| 2 | **光器件电功耗未入热模型**：调制器驱动、微环热调谐、SOA 泵浦、PD+TIA 的电功耗完全没统计 | 温度仿真偏低于真实值 |
| 3 | **微环热调谐功耗只在建路时算一次**：后续温度变化不更新，且拆链后未清除 | 正反馈闭环未建模 |

---

## 目标架构

单层 4×4 Mesh ONoC，片外激光器 + 片上 5×5 微环路由器 + WDM（8 波长）。

参考论文：*A Novel Optical Mesh Network-on-Chip for Gigascale Systems-on-Chip*，图1（5-port 微环光路由器）+ 图2（Mesh 拓扑）。

```
片外 CW 激光器 (常亮)
  │
  ▼  光栅耦合 → 片上波导
  │
  ▼  1×16 分光器 → 每路送入一个 PE 的调制器链 (共 16 个 PE)
  │
  ▼  PE 调制 → WDM 波导 → 5×5 微环路由器 → ... → 目的 PE 解调 → PD
```

分光路数 = PE 数量 = 16（4×4 Mesh），波长数 = 8（WDM 通道数），两者独立。

**8 波长理由**：4×4 Mesh 双向 bisection 对边数为 4，8 波长在 XY 路由下已可覆盖典型流量模式下的无阻塞通信。16 波长对 4×4 规模偏多，环链更长但损耗更大。

---

## 修改计划

### 一、光功率分光（`LogicalTopologyManager` + `OpticalDeviceModel`）

**物理模型**：

```
片外激光器 P_total (CW, 常亮)
  │
  ▼  光栅耦合损耗: ~3 dB
片上波导
  │
  ▼  1×16 分光器（16 个 PE 各一路）
  │  每路: P_per_branch = P_total - coupling_loss - 10×log₁₀(16) - excess_loss
  ▼
每个 PE 的调制器入口 (P_total=20dBm 时，每路约 20-3-12-1=4 dBm)
```

**代码改动**：

1. `LogicalTopologyManager` 新增 NED 参数：
   - `opticalNumSplitBranches` (default=16，对应 rows×columns)：分光路数 = PE 数量
   - `opticalSplitterExcessLoss_dB` (default=1.0)：分光器额外损耗
   - `opticalCouplingLoss_dB` (default=3.0)：光栅耦合损耗

2. 在 `getDeviceLevelPathMetrics()` 中，budget computation 之前计算分光后功率：
   ```
   perBranchPower_dBm = opticalLaunchPower_dBm
                      - opticalCouplingLoss_dB
                      - 10*log10(opticalNumSplitBranches)
                      - opticalSplitterExcessLoss_dB
   ```
   将 `constraints.launchPower_dBm` 设为此值再传给 `computeDeviceLevelBudget`。

3. 分光损耗恒定，所有路径一致，不需要每路动态计算。

---

### 二、光器件电功耗 → 热模型

**总原则：光器件与 PE/路由器共址，电功耗就近归入已有热节点。**

| 功耗来源 | 触发时机 | 归入热节点 | 改动位置 |
|---------|---------|-----------|---------|
| 调制器驱动 | PE 发送光数据时 (per flit) | **源 PE** `windowDynamicEnergyJ` | `TaskPE.cc` |
| 微环热调谐 | 光路活跃期间（建路→拆链） | 路径上每个**路由器** | `LogicalTopologyManager.cc` |
| SOA 泵浦 | 光路活跃期间（建路→拆链） | 路径上每个**路由器** | `LogicalTopologyManager.cc` |
| PD+TIA | PE 接收光数据时 | **目的 PE** `windowDynamicEnergyJ` | `TaskPE.cc` |
| 激光器(片外) | 固定 | **不计入芯片热模型** | 仅记录能耗标量 |

#### 2.1 新增参数

**`TaskPE` 新增 NED 参数**：
```
opticalModulatorEnergyPerFlit  // 每 flit 调制器驱动能耗 (J)
opticalReceiverEnergyPerFlit   // 每 flit PD+TIA 能耗 (J)
```

**`LogicalTopologyManager` 新增 NED 参数**：
```
opticalTuningEfficiency_mW_per_nm  // 已有，微环热调谐效率
opticalSoaPumpPower_mW             // SOA 电泵浦功耗 (mW)
opticalMaxHeaterPower_mW           // 单个加热器饱和上限 (mW)
```

#### 2.2 TaskPE 改动

**`sendOpticalFlitFromQ()`** 中，`sendDirect` 之后累加：
```cpp
windowDynamicEnergyJ += opticalModulatorEnergyPerFlit;
```

**`handleDataArrival()`** 中，光接收路径累加：
```cpp
windowDynamicEnergyJ += opticalReceiverEnergyPerFlit;
```

自动随 `finalizeEnergyWindow()` → `submitPEPower()` 进入热模型。

#### 2.3 LogicalTopologyManager 改动

**建路时**（`tryAllocateOpticalPathForPacket` 成功分配后）：
1. 从 `cachedBudgets[pktId]` 取 `totalTuningPower_mW`，根据路径路由器列表，将调谐功耗分摊到对应路由器的 `routerOpticalPower[]`
2. 如有 SOA，累加 SOA 泵浦功耗到对应路由器

**拆链时**（`releaseOpticalPathForPacket`）：
1. 从对应路由器**减去**该路径的调谐功耗和 SOA 泵浦功耗

#### 2.4 ThermalModel 改动

```cpp
// ThermalTrace.h 新增
std::vector<double> routerOpticalPower;  // 光器件叠加到路由器的功耗 (W)

void addRouterOpticalPower(int routerId, double power_W);
void removeRouterOpticalPower(int routerId, double power_W);

// tryFlush() 中写入 HotSpot trace 前并入:
// for each i: routerPower[i] += routerOpticalPower[i]
// 写入后再还原（或下个窗口重新累加时覆盖）
```

`LogicalTopologyManager` 在建路/拆链时通过 `add/removeRouterOpticalPower` 操作。

---

### 三、微环热调谐的动态更新（闭环正反馈）

**当前问题**：调谐功耗仅在 `getDeviceLevelPathMetrics` 中根据建路时刻温度计算一次。

**物理过程**：
```
温度变化 → 微环波长漂移 (0.1 nm/K) → 加热器出力变化 → 功耗变化 → 温度再变化
```

**修改方案**：

在每个 energyWindow 的温度更新之前，`ThermalModel` 回调重新计算所有活跃光路的调谐功耗：

```cpp
// ThermalModel 新增
std::function<void()> onBeforeTemperatureUpdate;

// updateTemperature() 调用前
if (onBeforeTemperatureUpdate) onBeforeTemperatureUpdate();
```

`LogicalTopologyManager` 注册回调，遍历 `opticalPacketAllocations`，用当前温度重算每条路径的 `totalTuningPower_mW`，更新 `ThermalModel::routerOpticalPower[]`。

**收敛保护**：
```cpp
heater_power = min(tuningEfficiency × |detuning|, maxHeaterPower_mW);
```

---

### 四、波导交叉损耗与串扰（新增器件类型）

**当前问题**：代码的 `OpticalDeviceType` 枚举只有 9 种器件，没有 `DEV_WAVEGUIDE_CROSSING`。单层 Mesh 中 XY 波导在路由器位置物理交叉，交叉点的插入损耗和串扰未建模。

**实际影响**：单次交叉损耗 ~0.05-0.12 dB，4×4 Mesh XY 路径约 3-6 次交叉，累计 0.3-0.7 dB。量级虽不大，但论文若提及交叉损耗而仿真未计，审稿人可指出。

**代码改动**：

1. `OpticalDeviceModel.h` — 枚举新增 `DEV_WAVEGUIDE_CROSSING`：
```cpp
enum OpticalDeviceType {
    // ... 已有的 ...
    DEV_WAVEGUIDE_CROSSING,    // 波导交叉点
    DEV_COUNT
};
```

2. `OpticalDeviceModel.cc` — `opticalDeviceTypeName()` 新增 case：
```cpp
case DEV_WAVEGUIDE_CROSSING: return "waveguide_crossing";
```

3. `OpticalDeviceModel.cc` — `populateDefaultOpticalParams()` 新增默认参数：
```cpp
key.deviceType = DEV_WAVEGUIDE_CROSSING;
{
    DevicePerWavelengthParams p;
    p.insertionLoss_dB = 0.05;          // 典型硅波导交叉损耗
    p.crosstalkToAdjacent_dB = -30.0;   // 交叉点串扰
    p.crosstalkToNonAdjacent_dB = -50.0;
    table[key] = p;
}
```

4. `OpticalDeviceModel.cc` — `computeDeviceLevelBudget()` switch 新增：
```cpp
case DEV_WAVEGUIDE_CROSSING:
    segLoss_dB = params.insertionLoss_dB;
    break;
```

5. `LogicalTopologyManager.cc` — `getDeviceLevelPathMetrics()` 中，在每个路由器遍历时，对每个波导交叉点插入一个 segment。交叉点统计逻辑：XY 路由中每经过一个中间路由器，对应一跳方向变化（X→Y 或直行→转向），产生一次交叉。简化处理：**每个路由器跳插入 1 个 `DEV_WAVEGUIDE_CROSSING` segment**。

---

## 修改顺序

```
第1步: 光功率分光 (LogicalTopologyManager + 新参数)          ← 最独立
第2步: ThermalModel 增 routerOpticalPower 接口               ← 基础设施
第3步: LogicalTopologyManager 建链/拆链时加减光功耗           ← 核心
第4步: TaskPE 加调制器驱动 + PD/TIA 能耗                      ← 补全PE侧
第5步: 微环热调谐动态更新 (回调机制)                          ← 闭环
第6步: 波导交叉损耗 (新增 DEV_WAVEGUIDE_CROSSING)            ← 器件补全
```

## 涉及文件清单

| 文件 | 改动类型 |
|------|---------|
| `src/thermal/ThermalTrace.h` | 新增 `routerOpticalPower[]`、`add/removeRouterOpticalPower()`、`onBeforeTemperatureUpdate` 回调 |
| `src/thermal/ThermalTrace.cc` | 实现上述方法，`tryFlush()` 中并入 optical power，`updateTemperature()` 前调用回调 |
| `src/cores/task/TaskPE.cc` | `sendOpticalFlitFromQ()` 加调制器能耗，`handleDataArrival()` 光路加 PD/TIA 能耗 |
| `src/cores/task/TaskPE.ned` | 新增 `opticalModulatorEnergyPerFlit`、`opticalReceiverEnergyPerFlit` |
| `src/onoc/control/LogicalTopologyManager.h` | 新增方法声明、`add/removeRouterOpticalPower` 调用 |
| `src/onoc/control/LogicalTopologyManager.cc` | 分光计算、建链/拆链调功耗加减、回调注册与重算、交叉点 segment 注入 |
| `src/onoc/control/LogicalTopologyManager.ned` | 新增 `opticalNumSplitBranches`、`opticalCouplingLoss_dB`、`opticalSplitterExcessLoss_dB`、`opticalSoaPumpPower_mW` |
| `src/onoc/common/OpticalDeviceModel.h` | 枚举新增 `DEV_WAVEGUIDE_CROSSING` |
| `src/onoc/common/OpticalDeviceModel.cc` | 新增器件名称、默认参数、`computeDeviceLevelBudget()` switch 分支 |

---

## 实施记录

### 第1步：光功率分光 — 已完成 (2026-05-25)

**修改文件**：
- `src/onoc/control/LogicalTopologyManager.ned` — 新增 NED 参数
- `src/onoc/control/LogicalTopologyManager.h` — 新增成员变量
- `src/onoc/control/LogicalTopologyManager.cc` — 分光计算 + `#include <cmath>`
- `src/onoc/topologies/ONoCMesh.ned` — 新增参数定义及向 `topologyManager` 传递
- `src/cores/task/TaskPE.ned` — 修复缺失的 `@signal[onoc-setup-req-event]` 和 `@signal[onoc-setup-ack-event]`（预存 bug，运行必需）

**新增参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opticalNumSplitBranches` | 16 | 1×N 分光器路数（= PE 数量） |
| `opticalSplitterExcessLoss_dB` | 1.0 | 分光器额外损耗 |
| `opticalCouplingLoss_dB` | 3.0 | 光栅耦合损耗 |

**核心代码**（`getDeviceLevelPathMetrics()`，budget 计算前）：
```cpp
double perBranchPower_dBm = opticalLaunchPower_dBm;
if (opticalNumSplitBranches > 1) {
    perBranchPower_dBm = opticalLaunchPower_dBm
                       - opticalCouplingLoss_dB
                       - 10.0 * std::log10(static_cast<double>(opticalNumSplitBranches))
                       - opticalSplitterExcessLoss_dB;
}
constraints.launchPower_dBm = perBranchPower_dBm;
```

验证方法：`opticalNumSplitBranches=1` 且 `opticalCouplingLoss_dB=0`、`opticalSplitterExcessLoss_dB=0` 时行为与修改前一致。

---

### 第2步：ThermalModel 增 routerOpticalPower 接口 — 已完成 (2026-05-26)

**修改文件**：
- `src/thermal/ThermalTrace.h` — 新增 `routerOpticalPower[]` 数组 + `add/removeRouterOpticalPower()` 方法声明
- `src/thermal/ThermalTrace.cc` — 实现方法 + `open()` 中初始化 + `tryFlush()` 中并入光学功耗

**新增接口**：
```cpp
void addRouterOpticalPower(int routerId, double power_W);
void removeRouterOpticalPower(int routerId, double power_W);
```

**`tryFlush()` 改动**：在温度更新和 trace 写入前，将 `routerOpticalPower` 并入 `routerPower`：
```cpp
for (int i = 0; i < numRouters; i++)
    routerPower[i] += routerOpticalPower[i];
```

`routerOpticalPower[]` 是**持久数组**——建链/拆链时增删，跨 energyWindow 保持，直到下次显式修改。

---

### 第3步：建链/拆链时加减光功耗 — 已完成 (2026-05-26)

**修改文件**：
- `src/onoc/control/LogicalTopologyManager.ned` — 新增 `opticalSoaPumpPower_mW`（默认 15 mW）
- `src/onoc/control/LogicalTopologyManager.h` — 新增成员变量 + `OpticalPacketAllocation` 扩展三个字段
- `src/onoc/control/LogicalTopologyManager.cc` — 建链/拆链时调用 ThermalModel 接口

**建链时**（`tryAllocateOpticalPathForPacket()` 成功分配后）：
1. 从 `pathEdges` 提取有序路由器列表 `[src, R1, R2, ..., dst]`（数量 = edges + 1）
2. 调谐功耗分摊：`totalTuningPower_mW / numRouters`
3. SOA 泵浦功耗分摊：`opticalSoaPumpPower_mW × edges / numRouters`
4. 调用 `ThermalModel::addRouterOpticalPower(routerId, power_W)`，mW → W 转换

**拆链时**（`releaseOpticalPathForPacket()` 中）：
1. 从 `OpticalPacketAllocation.pathRouters` / `tuningPowerPerRouter_mW` / `soaPowerPerRouter_mW` 读取
2. 调用 `ThermalModel::removeRouterOpticalPower(routerId, power_W)` 减去对应功耗

---

### 第4步：TaskPE 光器件能耗 — 已完成 (2026-05-26)

**修改文件**：
- `src/cores/task/TaskPE.ned` — 新增 `opticalModulatorEnergyPerFlit`（默认 2pJ）、`opticalReceiverEnergyPerFlit`（默认 1pJ）
- `src/cores/task/TaskPE.h` — 新增 2 个成员变量
- `src/cores/task/TaskPE.cc` — 三处改动

**`sendOpticalFlitFromQ()`**：
```cpp
// 改为:
windowDynamicEnergyJ += opticalModulatorEnergyPerFlit;  // 替代 windowSendFlits++
```

**`handleDataArrival()`**（数据 flit 路径）：
```cpp
if (!msg->getFirstNet())          // 光路（sendDirect 到达，firstNet=false）
    windowDynamicEnergyJ += opticalReceiverEnergyPerFlit;
else                               // 电路（握手 SETUP_REQ/ACK 等）
    windowRecvFlits++;
```

**`finalizeEnergyWindow()`**：
```cpp
// = 改为 +=，电气能耗叠加到已累积的光能耗上
windowDynamicEnergyJ +=
    windowSendFlits * powerSendPerFlit +
    windowRecvFlits * powerRecvPerFlit;
```

**设计要点**：握手阶段的 SETUP_REQ/ACK 走 `send()` + `handleDataArrival()` 已有逻辑（`firstNet=true`），不计光学能耗。只有光数据面（`sendDirect`，`firstNet=false`）才计入调制器驱动 + PD/TIA 能耗。论文可包装为"纯光路模型"。
