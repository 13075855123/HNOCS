# HNOCS - Hybrid Network-on-Chip Simulator (OMNeT++)

> **语言**：用中文回答。

## Project Overview

OMNeT++ simulation framework for **Hybrid Electrical-Optical Network-on-Chip (HNOCS)**.

- 4×4 Mesh ONoC，片外激光器 + 片上 5×5 微环路由器 + WDM（8 波长）
- 任务通过 CSV task graph 分配到 16 个 TaskPE，**静态离线映射**（peId 在 CSV 中固定）
- Optical bypass: data flit 走 `sendDirect()` 光路直传；SETUP_REQ/ACK 握手走电路由器
- 5×5 微环光路由器：20 waveguide 交叉点 × 8 WDM 波长 = **160 微环/路由器**
- 微环静态热调谐：常驻功耗注入 RC thermal model
- RC thermal model: 2-layer grid (PE + Router), explicit Euler solver, HotSpot-format trace output

### 关键约定

| 项目 | 值 |
|------|----|
| flitSize | 16B |
| Flit 数计算 | `max(2, ceil(dataSize / 16B))` |
| CSV `peId = -1` | GB 预载任务（片外 DRAM 注入初始数据） |
| CSV `successor = -1:-1` / `N:-1` | 输出发往 GlobalBuffer |
| 光路带宽 | 2 波长 × 256Gbps = 512Gbps，每 flit 0.25ns |
| 电层带宽 | 单链路 16Gbps（光路是电层的 32 倍） |

## Build & Run

### IDE

OMNeT++ IDE 打开 `D:\HNOCS`，`examples/task_driven/omnetpp.ini` → Run As → OMNeT++ Simulation，选 Config。推荐 Cmdenv 模式。

### 终端

```bash
export TOOLS="/d/omnetpp/omnetpp-6.3.0/tools/win32.x86_64"
export OMNETPP_ROOT="/d/omnetpp/omnetpp-6.3.0"
export PATH="$TOOLS/clang64/bin:$TOOLS/usr/bin:$OMNETPP_ROOT/bin:$PATH"

cd /d/HNOCS
make MODE=debug -j4

cd examples/task_driven
../../out/clang-debug/libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini
```

### Config 列表

| Config | 说明 |
|--------|------|
| `ONoCGeneral` | 抽象基类（不直接运行） |
| `ONoC_MPEG4` | MPEG4 任务图 |
| `ONoC_GEMM` | GEMM 任务图 |
| `ONoC_VOPD` | VOPD 任务图 |
| `ONoC_Optic` | Optic 任务图 |
| `ONoC_HNN` | HNN 高并发应力测试（33 任务） |

## Source Tree

```
src/
├── cores/task/      # TaskPE, PowerTrace
├── routers/hier/    # Wormhole routers: InPort, OPCalc, Sched, VCCalc
├── onoc/control/    # LogicalTopologyManager (波长分配、拓扑管理)
├── onoc/optical/    # OpticalCircuitController (光路建链/拆链)
├── onoc/routing/    # ReconfigurableOPCalc (光路感知路由)
├── onoc/common/     # OpticalDeviceModel, OpticalParamLoader
├── thermal/         # ThermalTrace — RC thermal solver
├── topologies/      # TaskMesh.ned, ONoCMesh.ned
├── globalbuffer/    # GlobalBuffer (片外 DRAM 接口)
└── utils/           # TaskGraphParser (CSV 加载)
```

## 光旁路（Optical Bypass）

### 数据流

```
Task完成 → data flit 进 pendingDataQ
  → SETUP_REQ (2 flit, 电路由器) → dst PE
  → SETUP_ACK (2 flit, 电路由器) → src PE
  → circuitReady = true → flushPendingData → opticalDataQ
  → sendDirect(flit, ..., opticalIn)   ← 光路直传
  → END flit 后 TEARDOWN
```

### 验证命令

```bash
./libhnocs_dbg.exe -c ONoC_MPEG4 -u Cmdenv -n ../../src omnetpp.ini 2>&1 | grep OPTICAL-STATS
```

### 能耗模型

| 项目 | 值 | 说明 |
|------|----|------|
| 调制器驱动 | 2 pJ/flit | 电→光转换 |
| PD+TIA 接收 | 1 pJ/flit | 光→电转换 |
| 电层发送 | 200 pJ/flit | SETUP_REQ/ACK |
| 电层接收 | 100 pJ/flit | Credit 返回 |
| SOA 泵浦 | 80 mW/器件 | 逐跳放大，按电路持续时间累计 |
| 激光器 WPE | 20% | 片外 CW 常亮，P_elec = 5 mW，不计入热模型 |
| 微环热调谐 | 320 mW/路由器 | 160 环 × 2 mW/环，常驻 |

### 日志控制

- `**.cmdenv-log-level = off` → 压制 `EV <<` 日志
- `printf()` → 不受影响，始终输出
- `[OPTICAL]` 前缀覆盖全生命周期

## 光路架构与参数

```
片外 CW 激光器 (常亮)
  │  光栅耦合损耗: 3 dB
  ▼  1×16 分光器
  ▼
PE 调制 → WDM 波导 → 5×5 微环路由器 (XY) → 目的 PE 解调 → PD
       ↕                                      ↕
  调制器驱动 (2pJ/flit)               PD+TIA (1pJ/flit)
```

### 光层参数

| 参数 | 值 | 说明 |
|------|----|------|
| `opticalNumSplitBranches` | 16 | 1×N 分光器 |
| `opticalCouplingLoss_dB` | 3.0 | 光栅耦合损耗 |
| `opticalSoaPumpPower_mW` | 80.0 | SOA 泵浦功耗 |
| `opticalLaserWPE` | 0.20 | 激光器 wall-plug 效率 |
| `opticalRingTuningPower_mW_per_ring` | 2.0 | 每微环调谐功率 |
| `opticalNumRingsPerRouter` | 160 | 每路由器微环数 |

### 电层与热参数（当前设计值）

| 参数 | 值 | 说明 |
|------|----|------|
| `powerIdle` | 0.3 W | 空闲功耗 |
| `powerCompute` | 2.5 W | 计算功耗 |
| `powerSendPerFlit` | 2e-10 J | 电层发送 |
| `powerRecvPerFlit` | 1e-10 J | 电层接收 |
| `RconvPE` / `RconvRouter` | 8 / 10 K/W | 垂直热阻 |
| `RlateralPE` / `RlateralRouter` | 10 / 10 K/W | 横向热阻 |
| `Rpe2router` | 3 K/W | PE-Router 热阻 |
| `Cpe` / `Crouter` | 1e-6 / 1e-7 J/K | 热容 |
| `Tambient` | 318.15 K (45°C) | 环境温度 |
| `Tthrottle` | **327.15 K (54°C)** | DVFS 节流阈值 |
| `throttleBeta` | 0.1 | DVFS 减速系数 (10%/°C) |

## 微环热调谐

5 端口路由器（0=Local, 1=West, 2=North, 3=East, 4=South）：**20 有效交叉点 × 8 波长 = 160 微环/路由器**。全芯片 16 路由器共 2560 微环。

各路径微环数（through + 1 drop）：

| 方向组 | 最长(i=8) |
|--------|:---:|
| L→W, W→S, N→L, E→N | 8 |
| L→S, N→W, E→L, S→E | 24 |
| L→N, L→E, W→L, S→L | 32 |
| W→E, N→S, E→W, S→N | 33 |
| W→N, E→S | 40 |
| **N→E, S→W** | **56** |

- **静态热调谐**（已实现）：每环 2mW 常驻加热，320mW/路由器，`initialize()` 注入 RC 热模型
- **动态热调谐**（待实现）：温度漂移补偿，需 `opticalEnableThermalEffects=true`

## 已实现功能

- 纯电 NoC + PE/路由器能耗 + RC 热求解器（100ns 粒度）
- 光旁路：`sendDirect()` 直传 + SETUP_REQ/ACK 握手 + 建链/拆链
- 光功率预算（耦合损耗、分光器、SOA ASE、PAM4 BER）
- 微环静态热调谐（160 环/路由器，5.12W 全芯片）
- SOA 逐跳放大 + 电能耗追踪（5 个 scalar）
- 激光器 WPE 电功耗（片外常亮，4 个 scalar）
- 周期性 DVFS 热节流（每 100ns 重检温度，`1 + 0.1×(T-54°C)` @ T>54°C）
- 可重构波长分配（lowest 优先策略）
- HNN 高并发应力测试 benchmark（33 任务，16 PE 全激活）

### 待实现

- 微环动态热调谐
- 波导交叉损耗
- 链路预算驱动丢包/重路由

## Python 仿真器 (mapping/)

事件驱动 Python 版 NoC 仿真器，支持离线任务重映射优化。与 OMNeT++ 交叉验证：

| 功能 | 偏差 |
|------|:---:|
| 任务调度 + DAG 依赖 | 完成时间 <0.2% |
| 光握手 + 波长分配 + sendDirect | 光 flit 精确匹配 |
| 双层 RC 热模型 | PE 峰值 <0.3K |
| DVFS 热节流 | 因子精确匹配 |
| 能量窗口 100ns | 能耗 <2% |

```bash
python -m mapping.compare_omnet --all    # 对比全部任务图
```

## 最终仿真结果（Tthrottle=54°C, powerCompute=2.5W）

| Config | t_end | PE Tmax | 光 flit | Ring Tuning | SOA | Laser |
|--------|-------|---------|---------|-------------|------|-------|
| ONoC_MPEG4 | 167.66μs | 56.1°C | 1,475 | 0.86mJ | 0.69μJ | 0.84μJ |
| ONoC_GEMM | 130.23μs | 56.4°C | 1,920 | 0.67mJ | 1.18μJ | 0.65μJ |
| ONoC_VOPD | 237.70μs | 54.4°C | 2,774 | 1.22mJ | 0.86μJ | 1.19μJ |
| ONoC_HNN | 228.12μs | 57.1°C | 26,624 | 1.26mJ | 3.28μJ | 1.23μJ |

### DVFS 行为

周期性 DVFS 在所有 benchmark 中生效。MPEG4/GEMM/VOPD 在任务 START 时 dvfs=1.0（PE 尚未升温），`handleDvfsTick` 在任务执行中逐 tick 减速（GEMM 最强 +15-30%）。HNN 因 16 PE 同时计算，START 时温度已达 57°C，dvfs=1.30。

## 关键文件索引

| 组件 | 文件 |
|------|------|
| 波长分配 | `src/onoc/control/LogicalTopologyManager.cc` |
| 光路由触发 | `src/onoc/routing/ReconfigurableOPCalc.cc` |
| PE 能耗 + 握手 | `src/cores/task/TaskPE.cc` |
| Router 能耗 | `src/routers/hier/inPort/InPortSync.cc` |
| RC 热模型 | `src/thermal/ThermalTrace.cc` |
| 微环损耗模型 | `src/onoc/common/OpticalDeviceModel.cc` |
| 配置文件 | `examples/task_driven/omnetpp.ini` |
| Python 仿真器 | `mapping/noc_simulator.py` |
| 自动对比工具 | `mapping/compare_omnet.py` |
| 设计文档 | `paper/20260529.md` |
