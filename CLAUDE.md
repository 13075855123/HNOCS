# HNOCS - Hybrid Network-on-Chip Simulator (OMNeT++)

> **行为准则**：每次执行文件操作（删除、修改、创建）后，必须用 `test`/`grep`/`ls` 等独立命令验证结果是否真正生效，不得仅凭命令输出（如 `echo "done"`）判断成功。

> **Git 规则**：每次修改本项目文件后，都必须主动执行 `git add`、`git commit` 和 `git push`，将更改记录到 GitHub。不得跳过此步骤。

## Project Overview

OMNeT++ simulation framework for **Hybrid Electrical-Optical Network-on-Chip (HNOCS)**.

- 4×4 Mesh ONoC，片外激光器 + 片上 5×5 微环路由器 + WDM（8 波长）
- 任务通过 CSV task graph 分配到 16 个 TaskPE，**静态离线映射**（peId 在 CSV 中固定）
- Optical bypass: data flit 走 `sendDirect()` 光路直传；SETUP_REQ/ACK 握手走电路由器
- RC thermal model: 2-layer grid (PE + Router), explicit Euler solver, HotSpot-format trace output

### 关键约定

| 项目 | 值/含义 |
|------|--------|
| flitSize | 16B |
| Flit 数计算 | `max(2, ceil(dataSize / 16B))` — 最小 2 flit（START + END） |
| CSV `peId = -1` | GB 预载任务（模拟片外 DRAM 注入初始数据） |
| CSV `successor = -1:-1` | 输出发往 GlobalBuffer（最终结果收集），不是错误 |
| 光路带宽 | 2 波长 × 256Gbps = **512Gbps**，每 flit 传输 0.25ns |
| 电层带宽 | 单链路 16Gbps（光路是电层的 32 倍） |

## Build & Run

### IDE 运行

1. OMNeT++ IDE 打开 `D:\HNOCS` 作为项目
2. `examples/task_driven/omnetpp.ini` → Run As → OMNeT++ Simulation
3. 选择 Config name：

| Config | 网络 | 特点 |
|--------|------|------|
| `General` | TaskMesh | 纯电基线 |
| `ONoCGeneral` | ONoCMesh | 光电混合 |
| `ONoC_MPEG4` | extends ONoCGeneral | MPEG4 任务图 |
| `ONoC_GEMM` | extends ONoCGeneral | GEMM 任务图 |
| `ONoC_VOPD` | extends ONoCGeneral | VOPD 任务图 |
| `ONoC_Optic` | extends ONoCGeneral | Optic 任务图 |

- Run Configuration 中 **Additional arguments** 保持清空
- 如需干净的控制台输出：Run Configuration → User interface 选 **Cmdenv**

### 终端编译与运行

```bash
# 设置 OMNeT++ 工具链 PATH
export TOOLS="/d/omnetpp/omnetpp-6.3.0/tools/win32.x86_64"
export OMNETPP_ROOT="/d/omnetpp/omnetpp-6.3.0"
export PATH="$TOOLS/clang64/bin:$TOOLS/usr/bin:$OMNETPP_ROOT/bin:$PATH"

# 编译
cd /d/HNOCS
make MODE=debug -j4

# 运行（Cmdenv 模式）
cd examples/task_driven
../../out/clang-debug/libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini
```

## Source Tree

```
src/
├── cores/task/      # TaskPE (task-driven PE), PowerTrace
├── cores/sinks/     # InfiniteBWMultiVCSink
├── cores/sources/   # PktFifoSrc
├── routers/hier/    # Wormhole routers: InPort, OPCalc, Sched, VCCalc
├── onoc/control/    # LogicalTopologyManager (波长分配、拓扑管理)
├── onoc/optical/    # OpticalCircuitController (光路建链/拆链)
├── onoc/routing/    # ReconfigurableOPCalc (光路感知路由)
├── onoc/common/     # OpticalDeviceModel, OpticalParamLoader
├── thermal/         # ThermalTrace — RC thermal solver
├── topologies/      # Mesh.ned, TaskMesh.ned, ONoCMesh.ned
├── globalbuffer/    # GlobalBuffer (片外 DRAM 接口，初始数据注入)
└── utils/           # TaskGraphParser (CSV 加载)
```

## 光旁路（Optical Bypass）

### 数据流

```
Task完成 → data flit 全部进 pendingDataQ
  → SETUP_REQ (2 flit, 电路由器) → dst PE
  → SETUP_ACK (2 flit, 电路由器) → src PE
  → circuitReady = true → flushPendingData → opticalDataQ
  → sendDirect(flit, ..., opticalIn)   ← 光路直传
  → END flit 后 TEARDOWN
```

### 验证命令

仿真结束时 `TaskPE::finish()` 通过 `printf` 输出 `[OPTICAL-STATS]`（`printf` 不受 `cmdenv-log-level` 控制）：

```bash
./libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini 2>&1 | grep OPTICAL-STATS
```

输出示例：
```
[OPTICAL-STATS] PE0  optical-flits=30  setup-req-rx=1  setup-ack-rx=8  setup-ack-ok=3
[OPTICAL-STATS] PE7  optical-flits=27  setup-req-rx=2  setup-ack-rx=8  setup-ack-ok=3
...
[OPTICAL-STATS] ===== GRAND TOTAL: 153 optical flits sent via sendDirect =====
```

### 关键计数器

| 变量 | 含义 | 代码位置 |
|------|------|---------|
| `opticalPacketsSent` | **仅光路** `sendDirect()` flit 数 | `TaskPE.cc:768` |
| `totalFlitsSent` | 电层+光层 flit 总数 | `sendFlitFromQ()` + `sendOpticalFlitFromQ()` |
| `opticalModulatorEnergyPerFlit` | 调制器驱动能耗 (2pJ/flit) | NED 参数 |
| `opticalReceiverEnergyPerFlit` | PD+TIA 能耗 (1pJ/flit) | NED 参数 |

### 日志控制

- `**.cmdenv-log-level = off` → 压制所有 `EV <<` 日志
- `printf()` → 不受 log-level 影响，始终输出
- `[OPTICAL]` 前缀 printf 覆盖全生命周期：SETUP_REQ → ACK → CIRCUIT READY → SEND-OPTICAL → TEARDOWN
- 在 `omnetpp.ini` 的 `[ONoCGeneral]` 段中已设置 `**.cmdenv-log-level = off`

## 光路架构与 NED 参数

```
片外 CW 激光器 (常亮)
  │  光栅耦合损耗: 3 dB
  ▼  1×16 分光器: 10×log10(16) + 1dB excess
  ▼
PE 调制 → WDM 波导 → 5×5 微环路由器 (XY) → 目的 PE 解调 → PD
       ↕                                      ↕
  调制器驱动 (2pJ/flit)               PD+TIA (1pJ/flit)
```

### 网络级参数（ONoCMesh / LogicalTopologyManager）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opticalNumSplitBranches` | 16 | 1×N 分光器路数 |
| `opticalCouplingLoss_dB` | 3.0 | 光栅耦合损耗 |
| `opticalSplitterExcessLoss_dB` | 1.0 | 分光器额外损耗 |
| `opticalSoaPumpPower_mW` | 15.0 | SOA 电泵浦功耗 |

### TaskPE 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opticalModulatorEnergyPerFlit` | 2e-12 J | 调制器驱动能耗 |
| `opticalReceiverEnergyPerFlit` | 1e-12 J | PD+TIA 能耗 |

### ThermalModel 新增接口

```cpp
void addRouterOpticalPower(int routerId, double power_W);    // 建链时调用
void removeRouterOpticalPower(int routerId, double power_W); // 拆链时调用
```

## 已实现 / 待实现

### 已实现

- 纯电 NoC + PE/路由器能耗 + RC 热求解器（100ns 粒度）
- 光旁路：`sendDirect()` 数据直传 + 电层 SETUP_REQ/ACK 握手 + 建链/拆链
- 光功率分光（耦合损耗 + 分光器损耗计入链路预算）
- 光器件电功耗入热模型（调制器、微环热调谐、SOA、PD+TIA；激光器不计入芯片热模型）

### 待实现

- 微环热调谐动态更新 → `implementation_plan.md` 第5步
- 波导交叉损耗 → `implementation_plan.md` 第6步
- 链路预算驱动丢包/重路由（当前 budget 只统计不阻断）
- 激光器电功耗模型（WPE）

## 能耗统计

- 握手阶段（SETUP_REQ/ACK）：电路由器，使用 `powerSendPerFlit` / `powerRecvPerFlit`
- 光数据面（`sendDirect`）：使用 `opticalModulatorEnergyPerFlit` / `opticalReceiverEnergyPerFlit`
- `finalizeEnergyWindow()` 叠加两者：光路动态能耗 + 电层 flit 能耗

## 已知问题与修复记录

### 2026-05-26：`powerTraceFile` 默认路径无目录

**现象**：`Cannot open power trace file: results/power_trace.csv`

**修复**：`omnetpp.ini` 中设置 `**.pe[*].powerTraceFile = "power_trace.csv"`（输出到当前目录）。

### 2026-05-26：NED 文件格式损坏导致 IDE Syntax Error

**现象**：IDE 报 18 个 .ned "NED Syntax Problem"，但 `make` 编译通过。

**原因**：`gates:` / `submodules:` / `}` 关键字被塞进 `//` 注释，IDE 解析器找不到。

### 2026-05-26：IDE 缓存旧 INI 导致 "Unknown parameter"

**现象**：运行时报 `Unknown parameter 'wTemperature' / 'remapToDynamic'`。

**原因**：旧 `.vci` 文件（来自不存在的 `omnetpp_bench.ini`）含 `config **.wTemperature 1.0` 等通配符。IDE 会读取 `.vci` 作为可选配置源。

**修复**：删除旧 `.vci`/`.sca`/`.vec`；为全部 21 个模块 NED 添加废弃参数声明作为 IDE 兼容占位。

### 废弃参数

`remapToDynamic` / `wTemperature` / `wHopCount` → 21 个 NED 中有声明，C++ 中**零引用**。当初 `remapToDynamic=true` 时 GB 动态改写 CSV peId（在线重映射），现已不用。保留只为防 IDE 报错。

`GlobalBuffer::distributeTasks()` → 处理 CSV `peId=-1` 的初始数据注入，不是在线重映射。
