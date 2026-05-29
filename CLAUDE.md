# HNOCS - Hybrid Network-on-Chip Simulator (OMNeT++)

> **语言**：用中文回答。

> **行为准则**：每次执行文件操作（删除、修改、创建）后，必须用 `test`/`grep`/`ls` 等独立命令验证结果是否真正生效，不得仅凭命令输出（如 `echo "done"`）判断成功。
> 
> **测试文件清理**：如果生成测试文件，在测试完成、确定功能实现正确后删去。

> **Git 规则**：每次修改本项目文件后，都必须主动执行 `git add`、`git commit` 和 `git push`，将更改记录到 GitHub。不得跳过此步骤。

## Project Overview

OMNeT++ simulation framework for **Hybrid Electrical-Optical Network-on-Chip (HNOCS)**.

- 4×4 Mesh ONoC，片外激光器 + 片上 5×5 微环路由器 + WDM（8 波长）
- 任务通过 CSV task graph 分配到 16 个 TaskPE，**静态离线映射**（peId 在 CSV 中固定）
- Optical bypass: data flit 走 `sendDirect()` 光路直传；SETUP_REQ/ACK 握手走电路由器
- 5×5 微环光路由器：20 waveguide 交叉点 × 8 WDM 波长 = **160 微环/路由器**
- 微环静态热调谐：常驻功耗注入 RC thermal model
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

### SOA 电能耗追踪（2026-05-29 新增）

每条光路建立时记录 `setupTime`，拆除时按电路持续时间累计 SOA 电能：
```
energy_J = SOA数量(跳数) × opticalSoaPumpPower_mW × 1e-3 × 持续时间(s)
```

验证命令：
```bash
grep "onoc-soa" results/ONoC_MPEG4-#0.sca
```

输出示例：
```
onoc-soa-pump-power-mW       80
onoc-soa-total-energy-J      6.89e-07      # 全仿真 SOA 总电能
onoc-soa-total-circuit-hops  44            # 所有光路 SOA·跳 累计
onoc-soa-average-power-W     0.00360       # 时间平均功率
onoc-soa-energy-per-hop-J    1.57e-08      # 每 SOA·跳 平均 15.7 nJ
```

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
| `opticalSoaPumpPower_mW` | 80.0 | SOA 电泵浦功耗（256 Gbps PAM4 128 GBaud，13 dB 增益） |

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

## 微环热调谐功耗

### 微环数量

5 端口（0=Local, 1=West, 2=North, 3=East, 4=South），每交叉点 8 个微环（每波长一个）：

> **20 有效交叉点 × 8 波长 = 160 微环/路由器**

各方向路径经过的微环数（through + 1 drop）：

| 方向组 | 公式类型 | through 范围(i=1..8) | 最长(i=8) |
|--------|:---:|:---|:---:|
| L→W, W→S, N→L, E→N | Type 0: i−1 | 0–7 | 8 |
| L→S, N→W, E→L, S→E | Type 1: 2n+i−1 | 16–23 | 24 |
| L→N, L→E, W→L, S→L | Type 2: 3n+i−1 | 24–31 | 32 |
| W→E, N→S, E→W, S→N | Type 3: 4n | 32（恒定） | 33 |
| W→N, E→S | Type 4: 4n+i−1 | 32–39 | 40 |
| **N→E, S→W** | **Type 5: 6n+i−1** | 48–55 | **56** |

（代码位置：`OpticalDeviceModel.cc:70-128`、`buildWavelengthDependentRouterMatrix()`）

### 静态热调谐（已实现）

每个微环需要恒定的加热功率将谐振波长对准目标，这是**常开功耗**，与建链/拆链无关。实现方式：

- **`LogicalTopologyManager::initialize()`** — 计算每路由器调谐功率（`numRings × powerPerRing`），通过 `addRouterOpticalPower()` 注入 RC 热模型（永久，不 remove）
- **`LogicalTopologyManager::finish()`** — 计算累计能耗 `energy = totalPower × simTime`，记录 scalars

### 相关参数（ONoCGeneral / LogicalTopologyManager）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `opticalRingTuningPower_mW_per_ring` | 2.0 | 每微环静态调谐功率（Dong 2010: 21mW/FSR → ~2mW baseline） |
| `opticalNumRingsPerRouter` | 160 | 每路由器微环总数（20 交叉点 × 8 波长） |

### 验证命令

```bash
grep "ring-tuning" results/ONoC_MPEG4-#0.sca
```

输出示例：

```
onoc-ring-tuning-rings-per-router          160
onoc-ring-tuning-power-per-ring-mW         2
onoc-ring-tuning-power-per-router-mW       320
onoc-ring-tuning-total-power-W             5.12
onoc-ring-tuning-total-energy-J            0.000923
```

### 静态 vs 动态热调谐

| | 静态（已实现） | 动态（待实现） |
|------|:---:|:---:|
| 触发条件 | 始终在线 | 温度漂移时动态补偿 |
| 功耗 | 恒定 = numRings × powerPerRing | 随 ΔT 变化 |
| 注入方式 | `initialize()` 一次性加入 | 建链/拆链时 add/remove |
| 代码位置 | `LogicalTopologyManager` | `OpticalDeviceModel` (需 `opticalEnableThermalEffects=true`) |

## 已实现 / 待实现

### 已实现

- 纯电 NoC + PE/路由器能耗 + RC 热求解器（100ns 粒度）
- 光旁路：`sendDirect()` 数据直传 + 电层 SETUP_REQ/ACK 握手 + 建链/拆链
- 光功率分光（耦合损耗 + 分光器损耗计入链路预算）
- 光器件电功耗入热模型（调制器、微环热调谐、SOA、PD+TIA；激光器不计入芯片热模型）
- 微环静态热调谐功耗（160 环/路由器，常驻 320mW/路由器，16 路由器共 5.12W）
- SOA 电能耗追踪（按电路持续时间累计，5 个 scalar：pump-power / total-energy / circuit-hops / average-power / energy-per-hop）

### 待实现

- 微环动态热调谐（温度漂移补偿、谐振波长 detuning → 额外插入损耗）
- 波导交叉损耗
- 链路预算驱动丢包/重路由（当前 budget 只统计不阻断）
- 激光器电功耗模型（WPE）

## Python mapping 仿真器 (mapping/)

### 本次对话（2026-05-28）实现/修改

| 文件 | 改动 | 说明 |
|------|------|------|
| `mapping/noc_simulator.py` | **重大重写** | 事件驱动 NoC 仿真器，完整移植 OMNeT++ TaskPE + ThermalTrace |
| `mapping/thermal_simulator.py` | 更新 | 温度修正漏电功率、DVFS、路由器光器件功耗 |
| `mapping/optical_budget.py` | 更新 | 分光器功率、波导交叉损耗、温度感知效应 |
| `mapping/cost_model.py` | 更新 | 温度修正有效温度（漏电模型） |
| `mapping/compare_omnet.py` | **新建** | OMNeT++ vs Python 自动对比工具 |
| `mapping/__init__.py` | 更新 | 包导出符号 |
| `mapping/tests/test_cost_model.py` | 修复 | 适配新的漏电模型 |
| `src/onoc/topologies/ONoCMesh.ned` | **Bug 修复** | pe[] 移到 topologyManager 前，修复 ring tuning 初始化顺序 |

### Python 仿真器能力对照

| 功能 | OMNeT++ 对应 | 验证状态 |
|------|-------------|:---:|
| 事件驱动任务调度 + DAG 依赖 | TaskPE | 完成时间偏差 <0.2% |
| 光握手建链 (SETUP_REQ/ACK) + 波长分配 + 光路直传 + 拆链 | TaskPE + LTM | 光 flit 数精确匹配 |
| 双层 RC 热模型（PE + Router，邻居耦合） | ThermalTrace | PE 温度峰值偏差 <0.3K |
| 温度修正漏电功率 exp((T-Tamb)/15) | TaskPE::getTemperatureCorrectedPower | 路由器温度峰值偏差 <0.3K |
| DVFS 热节流 1+beta*(T-Tthrottle) | TaskPE::getDvfsScaleFactor | DVFS 因子精确匹配 |
| 能量窗口追踪 100ns（静态+动态分离） | TaskPE::finalizeEnergyWindow | 能耗偏差 <2% |
| 路由器 InPort 电功耗 (pLeak + buffer + crossbar) | InPortSync | 已实现 |
| 路由器光器件功耗 (ring tuning 320mW/router) | LTM + ThermalModel | 已实现 |
| 光功率预算（分光器、SOA ASE、PAM4 BER） | OpticalDeviceModel | 已实现 |
| Wormhole 切换电气 flit 延迟 | InPortSync + SchedSync | 已实现 |

### 关键参数（匹配 omnetpp.ini [ONoCGeneral]）

| 参数 | 值 | 说明 |
|------|-----|------|
| `energy_window` | 100e-9 | 能量窗口周期 |
| `pend_to` | 200e-9 | SETUP 超时 |
| `retry_dt` | 50e-9 | SETUP 重试间隔 |
| `router_pipeline` | 2e-9 | 路由器内部流水线延迟 |
| `inport_pLeak` | 1e-3 | 每 InPort 漏电功率 |
| `inport_eBufferWrite` | 1e-12 | Buffer 写能耗 |
| `inport_eBufferRead` | 1e-12 | Buffer 读能耗 |
| `inport_eCrossbar` | 0.5e-12 | Crossbar 能耗 |
| `inport_num_per_router` | 5 | 每路由器 InPort 数 |
| `optical_ring_tuning_mW_per_ring` | 2.0 | 每微环调谐功率 |
| `optical_num_rings_per_router` | 160 | 每路由器微环数 |

### OMNeT++ Ring Tuning Bug（已修复）

**问题**：`LogicalTopologyManager::initialize()` 在 `ThermalModel::open()` 之前调用 `addRouterOpticalPower()`，此时 `numRouters==0`（构造器默认值），`addRouterOpticalPower` 中 `routerId >= numRouters` 检查（0>=0）为 true，静默返回，ring tuning 功率从未注入热模型。

**修复**：`ONoCMesh.ned` 中将 `pe[]` 子模块移到 `topologyManager` 之前，确保 `pe[0].initialize()` → `ThermalModel::open()` → `numRouters=16` 先于 `addRouterOpticalPower()` 执行。

**影响**：修复前 OMNeT++ 的 ring tuning 仅有 scalar 报告（参数×时间），无实际热效应。修复后路由器温度提升 ~2.4°C，PE 温度提升 ~1.5°C，DVFS 因子从 1.108 升至 1.182，完成时间从 179.7μs 增至 191.5μs（MPEG4）。

### compare_omnet.py 用法

```bash
python -m mapping.compare_omnet --all          # 对比全部四个任务图
python -m mapping.compare_omnet --csv tasks_gemm_static.csv --config ONoC_GEMM
```

自动提取 OMNeT++ `.sca/.vec` 结果 → 运行 Python 仿真 → 对比完成时间/PE温度/路由器温度/光flit数 → 输出 PASS/FAIL 报告。

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
