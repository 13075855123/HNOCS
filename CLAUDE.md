# HNOCS - Hybrid Network-on-Chip Simulator (OMNeT++)

> **行为准则**：每次执行文件操作（删除、修改、创建）后，必须用 `test`/`grep`/`ls` 等独立命令验证结果是否真正生效，不得仅凭命令输出（如 `echo "done"`）判断成功。

> **Git 规则**：每次修改本项目文件后，都必须主动执行 `git add`、`git commit` 和 `git push`，将更改记录到 GitHub。不得跳过此步骤。

## Project Overview

OMNeT++ simulation framework for **Hybrid Electrical-Optical Network-on-Chip (HNOCS)**.

- 4×4 Mesh ONoC，片外激光器 + 片上 5×5 微环路由器 + WDM（8 波长）
- Tasks distributed via CSV task graphs, run on 16 TaskPEs
- Optical bypass: data flits via `sendDirect()` through optical path; SETUP_REQ/ACK handshake via electrical routers
- RC thermal model: 2-layer grid (PE + Router), explicit Euler solver, HotSpot-format trace output

## Build System

- Build tool: OMNeT++ `opp_makemake` (see `Makefile`)
- Executable: `libhnocs.exe` (clang release) / `libhnocs_dbg.exe` (debug)
- Build output: `out/clang-release/` or `out/clang-debug/`
- Include path: `-Isrc`
- To build from OMNeT++ shell: `make MODE=debug -j4` or `make MODE=release -j4`

## OMNeT++ IDE 测试步骤

### 方式一：IDE 内运行

1. 用 OMNeT++ IDE 打开 `D:\HNOCS` 目录（作为 OMNeT++ 项目）
2. 在 Project Explorer 中展开 `examples/task_driven/`
3. 右键 `omnetpp.ini` → **Run As** → **OMNeT++ Simulation**
4. 在弹出的 Run Configuration 对话框中选择想要运行的 **Config name**：

| Config | 网络 | CSV | 特点 |
|--------|------|-----|------|
| `General` | TaskMesh | tasks_mpeg4_static.csv | 纯电基线（4×4 Mesh + XY 路由） |
| `ONoCGeneral` | ONoCMesh | tasks_mpeg4_static.csv | **光电混合完整仿真**（20ms） |
| `ONoC_MPEG4` | extends ONoCGeneral | tasks_mpeg4_static.csv | 光电混合 + MPEG4 任务图 |
| `ONoC_GEMM` | extends ONoCGeneral | tasks_gemm_static.csv | 光电混合 + GEMM 任务图 |
| `ONoC_VOPD` | extends ONoCGeneral | tasks_vopd_static.csv | 光电混合 + VOPD 任务图 |
| `ONoC_Optic` | extends ONoCGeneral | optic_static.csv | 光电混合 + Optic 任务图 |

5. 点击 **Run**，仿真在 IDE 内置 Qtenv 中运行

### 方式二：命令行运行（在 OMNeT++ Shell 中）

```bash
cd D:/HNOCS/examples/task_driven
../../libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini
```

替换 `ONoC_MPEG4` 为其他 config 名即可。

### 注意
- IDE 的 Run Configuration 中 **Additional arguments** 需保持清空

## Source Tree Structure

```
src/
├── cores/           # Processing Elements (PE), Network Interfaces, Sources/Sinks
│   ├── task/        # TaskPE (task-driven PE), PowerTrace (CSV power event logger)
│   ├── sinks/       # InfiniteBWMultiVCSink (packet sinks)
│   └── sources/     # PktFifoSrc (packet sources)
├── routers/hier/    # Hierarchical wormhole routers
│   ├── inPort/      # InPortSync (energy tracking + thermal submission)
│   ├── opCalc/      # Output port calculators (XY routing)
│   ├── sched/       # Schedulers (Sync/Async)
│   └── vcCalc/      # VC allocators
├── onoc/            # Optical Network-on-Chip
│   ├── common/      # OpticalDeviceModel, OpticalParamLoader, OpticalPathMetrics
│   ├── control/     # LogicalTopologyManager (wavelength allocation, topology, optical power)
│   ├── optical/     # OpticalCircuitController (circuit open/close)
│   └── routing/     # ReconfigurableOPCalc (optical-aware routing)
├── thermal/         # ThermalTrace — RC thermal solver (global singleton)
├── topologies/      # Mesh.ned, TaskMesh.ned, ONoCMesh.ned
├── globalbuffer/    # GlobalBuffer (shared memory / DRAM interface)
├── messages/        # TaskMsg definitions
└── utils/           # TaskGraphParser (CSV task graph loader)
```

## 光路架构（4 个 CSV 都适用）

```
片外 CW 激光器 (常亮)
  │  光栅耦合损耗: 3 dB
  ▼  1×16 分光器: 10×log10(16) + 1dB excess
  │  每路 PE 调制器入口 ≈ 4 dBm (@ 20dBm 激光器)
  ▼
PE 调制 → WDM 波导 → 5×5 微环路由器 (XY) → ... → 目的 PE 解调 → PD
       ↕                                                      ↕
  调制器驱动能耗 (2pJ/flit)                          PD+TIA 能耗 (1pJ/flit)
```

## 已实现功能状态

### 纯电 NoC（已有，未改动）
- PE 能耗（静态 + 动态）→ `submitPEPower()` → ThermalModel → 温度
- 路由器能耗（静态 + 动态）→ `submitRouterPower()` → ThermalModel → 温度
- RC 热求解器：energyWindow (100ns) 粒度

### 光旁路（已实现）
- `sendDirect()` 绕过电路由器发送数据 flit（功能正确）
- 电层握手建链：SETUP_REQ/ACK 走电路由器 → 光路波长分配 → 光数据传输 → 拆链

### 光功率分光（第1步，已实现）
- NED 参数：`opticalNumSplitBranches`(16), `opticalCouplingLoss_dB`(3.0), `opticalSplitterExcessLoss_dB`(1.0)
- `getDeviceLevelPathMetrics()` 中 budget 计算前自动扣除分光/耦合损耗

### 光器件电功耗入热模型（第2-4步，已实现）

| 功耗来源 | 触发时机 | 归入热节点 | 改动位置 |
|---------|---------|-----------|---------|
| 调制器驱动 | PE 发送光数据时 (per flit) | 源 PE | `TaskPE.cc` `sendOpticalFlitFromQ()` |
| 微环热调谐 | 光路活跃期间（建链→拆链） | 路径上每个 Router | `LogicalTopologyManager.cc` + `ThermalTrace.cc` |
| SOA 泵浦 | 光路活跃期间（建链→拆链） | 路径上每个 Router | `LogicalTopologyManager.cc` + `ThermalTrace.cc` |
| PD+TIA | PE 接收光数据时 | 目的 PE | `TaskPE.cc` `handleDataArrival()` |
| 激光器(片外) | 固定 | 不计入芯片热模型 | 仅记录能耗标量 |

### 待实现

- 微环热调谐动态更新（implementation_plan.md 第5步：温度变化→波长漂移→加热器重算，闭环正反馈）
- 波导交叉损耗（implementation_plan.md 第6步：`DEV_WAVEGUIDE_CROSSING`）
- 链路预算驱动的丢包/重路由（当前 budget 只统计，不阻断建链）
- 激光器电功耗模型（当前仅有光域 `launchPower_dBm`，无电→光 WPE 模型）

## 新增 NED 参数速查

### LogicalTopologyManager / ONoCMesh 网络级

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opticalNumSplitBranches` | 16 | 1×N 分光器路数 |
| `opticalCouplingLoss_dB` | 3.0 | 光栅耦合损耗 |
| `opticalSplitterExcessLoss_dB` | 1.0 | 分光器额外损耗 |
| `opticalSoaPumpPower_mW` | 15.0 | SOA 电泵浦功耗 |

### TaskPE

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opticalModulatorEnergyPerFlit` | 2e-12 J | 每 flit 调制器驱动能耗 |
| `opticalReceiverEnergyPerFlit` | 1e-12 J | 每 flit PD+TIA 能耗 |

### ThermalModel 新增接口

```cpp
void addRouterOpticalPower(int routerId, double power_W);    // 建链时调用
void removeRouterOpticalPower(int routerId, double power_W); // 拆链时调用
```

## 能耗统计说明

- **握手阶段**（SETUP_REQ/ACK）：走电路由器，使用已有 `powerSendPerFlit` / `powerRecvPerFlit` 统计
- **光数据面**（`sendDirect`）：使用 `opticalModulatorEnergyPerFlit` / `opticalReceiverEnergyPerFlit` 单独统计
- `finalizeEnergyWindow()` 中两者叠加：`windowDynamicEnergyJ（光逐 flit 累加）+ windowSendFlits × powerSendPerFlit + windowRecvFlits × powerRecvPerFlit（电）`
- 论文可包装为"纯光路模型"，不体现电层握手开销

## 已知问题与修复记录

### 2026-05-26：`powerTraceFile` 默认路径无目录

**现象**：`Cannot open power trace file: results/power_trace.csv`

**原因**：`TaskPE.ned` 中 `powerTraceFile` 默认路径 `results/power_trace.csv`，但 `results/` 目录不存在，C++ `ofstream::open()` 不自动创建目录。

**修复**：在 `omnetpp.ini` 的 `[General]` 和 `[ONoCGeneral]` 中显式设置 `**.pe[*].powerTraceFile = "power_trace.csv"`，输出到当前目录。`[ONoC_*]` 子配置通过 extends 继承。
