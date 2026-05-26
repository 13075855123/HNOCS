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

### 2026-05-26：NED 文件格式损坏导致 IDE Syntax Error

**现象**：IDE 报 18 个 .ned 文件的 "NED Syntax Problem"，但 `make` 编译通过。

**原因**：多个 .ned 文件中 `gates:` / `submodules:` / `}` 关键字被塞进了 `//` 行注释内部，IDE 解析器找不到这些关键字。行如：
```
bool remapToDynamic = default(false); // deprecated...    gates:
```
`nedtool` 容错性更强所以能编译，IDE 解析器严格所以报错。

**修复**：sed 批量删除损坏行，恢复 `gates:` / `submodules:` 关键字，补回缺失的 `}`。

### 2026-05-26：IDE 缓存旧 INI 导致 "Unknown parameter"

**现象**：运行时报 `Unknown parameter 'wTemperature' / 'remapToDynamic'`。

**原因**：旧 workspace 的 `results/` 目录中有 `.vci` 文件（来自已不存在的 `omnetpp_bench.ini`），其中含 `config **.wTemperature 1.0` 等通配符赋值。OMNeT++ IDE 会将 `.vci` 文件作为可选配置源。

**修复**：删除旧 `.vci` / `.sca` / `.vec` 文件；为所有模块 NED 添加废弃参数声明（`remapToDynamic`, `wTemperature`, `wHopCount`）作为 IDE 兼容占位。

## 终端编译

IDE 外编译需设置 OMNeT++ 工具链 PATH：

```bash
export TOOLS="/d/omnetpp/omnetpp-6.3.0/tools/win32.x86_64"
export OMNETPP_ROOT="/d/omnetpp/omnetpp-6.3.0"
export PATH="$TOOLS/clang64/bin:$TOOLS/usr/bin:$OMNETPP_ROOT/bin:$PATH"
cd /d/HNOCS
make MODE=debug -j4
```

运行仿真：
```bash
cd /d/HNOCS/examples/task_driven
../../out/clang-debug/libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini
```

## 光旁路（Optical Bypass）验证

### 数据流路径

```
Task完成 → 全部 data flit 进 pendingDataQ
  → SETUP_REQ (2 flit, 电路由器)
  → SETUP_ACK (2 flit, 电路由器)
  → circuitReady = true → flushPendingData → opticalDataQ
  → sendDirect(flit, ..., targetMod->gate("opticalIn"))  ← 光路直传
  → END flit 后 TEARDOWN
```

### 关键计数器

| 变量 | 含义 | 位置 |
|------|------|------|
| `totalFlitsSent` | 电层+光层总发送 flit 数 | `sendFlitFromQ()` + `sendOpticalFlitFromQ()` |
| `opticalPacketsSent` | **仅光路** `sendDirect()` 发送的 flit 数 | `TaskPE.cc:768` |
| `opticalModulatorEnergyPerFlit` | 每光路 flit 调制器驱动能耗 (2pJ) | NED 参数 |
| `opticalReceiverEnergyPerFlit` | 每光路 flit PD+TIA 能耗 (1pJ) | NED 参数 |

### 仿真结束时打印光路统计

`TaskPE::finish()` 中通过 `printf` 输出 `[OPTICAL-STATS]`，包括每 PE 的光路 flit 数和全局总计。**`printf` 不受 `cmdenv-log-level` 控制**。

```bash
# 只看光路统计
../../out/clang-debug/libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini 2>&1 | grep OPTICAL-STATS
```

输出示例：
```
[OPTICAL-STATS] PE0  optical-flits=30  setup-req-rx=1  setup-ack-rx=8  setup-ack-ok=3
[OPTICAL-STATS] PE7  optical-flits=27  setup-req-rx=2  setup-ack-rx=8  setup-ack-ok=3
...
[OPTICAL-STATS] ===== GRAND TOTAL: 153 optical flits sent via sendDirect =====
```

### Qtenv 可视化限制

- `sendDirect()` 传送的消息**不会**在 Qtenv 中显示为绿色连线箭头（绿色箭头 = 电路由器 channel 消息）
- 光路握手阶段 SETUP_REQ/ACK 走电路由器，在 Qtenv 中可见为绿色箭头
- `refreshDisplay()` / display string 修改在 Qtenv 中不可靠，不建议依赖模块图标变色来验证光旁路
- **推荐用 Cmdenv + printf/grep 验证**

### 光路带宽

- 2 波长 × 256Gbps = **512Gbps** 有效带宽
- 每 flit (16B) 传输耗时：8×16b / 512Gbps = **0.25ns**
- 电层单链路带宽：16Gbps（光路是电层的 32 倍）

## CSV 任务图约定

| 字段 | 含义 |
|------|------|
| `peId = -1` | GB 预载任务（模拟片外 DRAM 注入初始数据），不在任何 PE 上执行 |
| `successor = -1:-1` | 输出发送到 GlobalBuffer（最终结果收集），不是错误 |

## 废弃代码标记

- `remapToDynamic` / `wTemperature` / `wHopCount` — 三个参数在全部 21 个模块 NED 中有声明（`default(false)` / `default(1.0)`），但 C++ 代码中**零引用**。当初 `remapToDynamic=true` 时 GB 会动态改写 CSV 中的 peId（在线重映射），现已废弃。保留声明仅为防止 IDE 缓存报 "Unknown parameter" 错误。
- `GlobalBuffer::distributeTasks()` — 处理 CSV 中 `peId=-1` 的初始数据注入任务，**不是**在线重映射代码。
- Flit 数计算公式：`max(2, ceil(dataSize / flitSize))`，最小 2 flit（START + END 握手）。

## 控制台日志控制

- `**.cmdenv-log-level = off` — 压制所有 `EV <<` 日志（INFO/WARN/DEBUG/TRACE）
- `printf()` — 不受 log-level 影响，始终输出到控制台
- `[OPTICAL]` 前缀的 printf 覆盖全光路生命周期：SETUP_REQ → ACK → CIRCUIT READY → SEND-OPTICAL → TEARDOWN
