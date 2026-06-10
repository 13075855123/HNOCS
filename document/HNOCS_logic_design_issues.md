# HNOCS 逻辑与设计错误审查报告

> 审查日期: 2026-06-02
> 最后更新: 2026-06-03 (中危级复查完成: M3/H9 SOA饱和ASE修正, M10/H10 GB injectQ清除, M2 ASE因子修正, M4 BER引用, M6 pendingDeps守卫, M7 拆链重置; M5不修复, M1误报; **低危L1/L2/L3/L10/L11/L12已修复**)
> 审查范围: `LogicalTopologyManager` | `TaskPE` | `ThermalTrace` | `GlobalBuffer` | `OpticalDeviceModel` | 论文设计文档
> 方法: 逐函数代码审查 + 跨模块一致性校验 + 论文设计对照 + 仿真回归验证

---

## 审查模块与源文件

| 模块 | 源文件 |
|------|--------|
| 波长分配与拓扑管理 | `src/onoc/control/LogicalTopologyManager.cc` `.h` |
| PE 核心 (握手+DVFS+能耗) | `src/cores/task/TaskPE.cc` `.h` |
| RC 热求解器 | `src/thermal/ThermalTrace.cc` `.h` |
| 全局缓冲区 (片外 DRAM) | `src/globalbuffer/GlobalBuffer.cc` `.h` |
| 器件级光链路预算 | `src/onoc/common/OpticalDeviceModel.cc` `.h` |
| 论文设计文档 | `paper/20260530.md` |

---

## 严重程度定义

| 等级 | 定义 |
|:----:|------|
| **致命** | 导致死锁、资源泄漏、崩溃、或仿真完全不可信 |
| **高危** | 产生错误物理/逻辑结果，影响论文数据或关键功能 |
| **中危** | 影响精度或在特定边界条件下出错 |
| **低危** | 代码质量/可维护性问题，不影响当前功能 |

---

## 致命级问题修复状态

| 编号 | 问题 | 状态 | 修复日期 | 修改文件 |
|:---:|------|:---:|:---:|------|
| C1 | GB 光路令牌丢失 | ✅ 已修复 | 2026-06-02 | `src/globalbuffer/GlobalBuffer.cc:183` (+1 行) |
| C2 | PE→GB 信用泄漏 | ✅ 已修复 | 2026-06-02 | `src/globalbuffer/GlobalBuffer.cc:197-206` (+9 行) |
| C3 | GB 多包 HoL 阻塞 | ✅ 已修复 | 2026-06-02 | `src/globalbuffer/GlobalBuffer.cc:244-256` (改写 flushPendingData) |
| C4 | 电层路径不可用 | 🔒 不修复 | — | 纯电代码另有版本用于对比 |
| C5 | 热模型停滞风险 | 🔒 暂不修复 | — | 热仿真强制 `enableEnergyWindow=true` |
| C6 | Euler 稳定性 | ✅ 已修复 | 2026-06-02 | `src/thermal/ThermalTrace.cc:260-330` (稳定性检测 + 自动子步进) |

### 致命级修复后基准值变更 (C1–C3, C6)

| Benchmark | 事件数 (旧→新) | SOA 能量 Optic (旧→新) | 调谐能量 Optic (旧→新) |
|-----------|:---:|:---:|:---:|
| Optic | 266,689→266,709 (+20) | 21.21→12.75 μJ (−40%) | 68.45→42.06 nJ (−39%) |
| VOPD | 1,756,660→1,756,666 (+6) | 不变 | 不变 |
| MPEG4 | 2,264,084→2,264,091 (+7) | 不变 | 不变 |
| HNN | 3,869,360→3,869,365 (+5) | 不变 | 不变 |
| GEMM | 2,178,336→2,178,337 (+1) | 不变 | 不变 |

> 事件数微增（+1~+20）是 C2 信用修复后 PE 控制 flit 发送时机提前所致。Optic 的 SOA/调谐能量下降是 C1 修复后 GB→PE 光路不再在仿真全程累计能耗。

### 高危级修复后基准值变更 (H1–H5, H7–H8)

| Benchmark | 事件数 (旧→新) | SOA 能量 Optic (旧→新) | 调谐能量 Optic (旧→新) |
|-----------|:---:|:---:|:---:|
| Optic | 266,709→266,205 (−504) | 12.75→12.75 μJ (不变) | 42.06→42.10 nJ (+0.1%) |
| VOPD | 1,756,666→1,756,666 (0) | 不变 | 不变 |
| MPEG4 | 2,264,091→2,263,683 (−408) | — | — |
| HNN | 3,869,365→3,868,110 (−1,255) | — | — |
| GEMM | 2,178,337→2,178,337 (0) | 不变 | 不变 |

> 事件数微降（−408~−1255）来自 H4（DVFS 末 tick 不超额）和 H5（GB 跳数正确）的时序微调。VOPD/GEMM 完全不变——不触发转弯路径或 GB 通信。Optic 能耗与基线一致。全部 benchmark finish 时刻 `occupied-wavelength-slots=0`, `active-circuits=0`。

---

# 一、致命级 (CRITICAL)

## C1. GB 端光学路径令牌丢失 → 波长资源永不释放

**文件**: `src/globalbuffer/GlobalBuffer.cc`

**位置**: SETUP_ACK 处理 (第 179–185 行) / END_FLIT 拆链 (第 294–299 行)

**描述**: GB 端在收到 SETUP_ACK 并激活电路后，未将令牌保存到 `activeCircuitTokenByDst`。END_FLIT 时 `token==0`，`releaseOpticalPathByToken` 永不调用。

**PE vs GB 对照**:

PE 端 (`TaskPE.cc:1315–1320`) — 正确:
```cpp
circuitReadyByDst[srcIdx] = 1;
setupPendingByDst[srcIdx] = 0;
activeCircuitTokenByDst[srcIdx] = pktId;  // ← 保存令牌
```

GB 端 (`GlobalBuffer.cc:180–185`) — 缺失:
```cpp
circuitReadyByDst[srcPE] = 1;
setupPendingByDst[srcPE] = 0;
pendingSetupTokenByDst[srcPE] = 0;
// ← 缺失: activeCircuitTokenByDst[srcPE] = pktId;
```

**影响**: 所有 GB→PE 光路在仿真期间无法释放波长/SOA/调谐功率。Optic benchmark 中 16 条 GB→PE 电路全部泄漏，`occupied-wavelength-slots` 在 finish 时残留 48 槽。`finish()` 兜底统计了能耗但资源在仿真全程被占用。

**修复** (已实施, 2026-06-02):
```diff
     circuitReadyByDst[srcPE] = 1;
     setupPendingByDst[srcPE] = 0;
+    activeCircuitTokenByDst[srcPE] = pktId;
     pendingSetupTokenByDst[srcPE] = 0;
```

**修复后验证**:
| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| `occupied-wavelength-slots` | 48 | **0** |
| `active-circuits` (finish) | 16 | **0** |
| SOA Energy Optic | 21.21 μJ | **12.75 μJ** (−40%) |
| Tuning Energy Optic | 68.45 nJ | **42.06 nJ** (−39%) |
| 5 benchmark 回归 | — | 5/5 PASS |

---

## C2. PE→GB SETUP_REQ 信用泄漏 → 渐进式死锁

**文件**: `src/globalbuffer/GlobalBuffer.cc`

**位置**: `handleMessage` 中 `NOC_FLIT_MSG` 分支 (第 142–197 行)

**描述**: PE→GB SETUP_REQ 包含 2 flit (START + END)。GB 收到 END_FLIT 时正确退还 1 credit（第 153 行），但 START_FLIT 落入第 196–197 行的 `delete; return` 分支，未退还 credit。

**信用流追踪**:

| Flit | 修复前 GB 行为 | 修复前 PE credit 变化 | 修复后 |
|------|---------|:---:|:---:|
| START | 静默 delete | −1 | +1 (新增) |
| END | 触发 ACK，退 1 credit | +1 | +1 |
| **净/握手** | | **−1** | **0** |

PE 初始 credit = 4（`TaskPE.cc:282` 硬编码）。每次 PE→GB 握手净亏 1 credit，多次握手后 PE 信用耗尽 → 无法再发送 → 死锁。

**影响**: 当前 5 benchmark 不触发死锁（每 PE ≤1 次握手，4 credit 余量足够），但信用泄漏确实发生。C1 的波长泄漏会加剧拥塞 → 更多重试 → 加速信用消耗。

**修复** (已实施, 2026-06-02):
```cpp
// 在 delete taskMsg; return; 之前新增：
{
    int gIdS = msg->getArrivalGateId();
    int connIdxS = -1;
    for (int iS = 0; iS < numConnections; iS++) {
        if (gIdS == gateHalf("in", cGate::INPUT, iS)->getId())
            { connIdxS = iS; break; }
    }
    if (connIdxS >= 0) sendCredit(connIdxS, taskMsg->getVC(), 1);
}
delete taskMsg;
return;
```

**修复后验证**: 5 benchmark 事件数微增 +1~+20（信用不泄漏后 PE 控制 flit 发送时机提前），时间/flit/能耗不变。5/5 回归 PASS。

---

## C3. GB 多数据包 HoL 阻塞 → 后续数据包永久丢失

**文件**: `src/globalbuffer/GlobalBuffer.cc`

**位置**: `flushPendingData` (第 244–259 行) / `sendFlitOptical` (第 285–300 行)

**描述**: `flushPendingData` 将 `pendingDataQ[peId]` 中**所有** flit 一次性移入 `opticalDataQ`。若包含多个数据包，第一包 END_FLIT 后电路拆除，后续包因 `circuitReadyByDst==0` 永久卡在 `opticalDataQ`。`sendFlitFromQ` 的重试逻辑只检查 `pendingDataQ`，不检查 `opticalDataQ`。

**触发条件**: GB 向同一 PE 连续两次 `queueFlit()`。当前 5 benchmark 中每 PE 仅 1 次注入，不触发。属潜伏性缺陷。

**专项测试验证** (GB→PE0 两个数据包):

| | 修复前 | 修复后 |
|---|:---:|:---:|
| 任务完成 | 1/2 (task2 未收到数据) | **2/2** |
| 光 flit 数 | 7 | **14** |
| 仿真终止 | 触达 20μs 限 | **正常 endSimulation** |

**修复** (已实施, 2026-06-02):
```cpp
void GlobalBuffer::flushPendingData(int peId) {
    if (pendingDataQ[peId].empty()) return;
    if (circuitReadyByDst[peId]) {
        auto &q = pendingDataQ[peId];
        size_t count = 0;
        for (size_t i = 0; i < q.size(); i++) {
            opticalDataQ.insert(q[i]);
            count++;
            if (q[i]->getType() == NOC_END_FLIT) break;  // 仅移一个完整包
        }
        q.erase(q.begin(), q.begin() + count);
        sendFlitOptical();
    }
}
```

**修复后验证**: 5/5 回归 PASS，各指标不变（当前 benchmark 不触发）。

---

## C4. 电层数据路径完全不可用

**文件**: `src/cores/task/TaskPE.cc`

**位置**: `pendingDataQ` resize (第 337–341 行) / 无条件访问 (第 1194 行) / `injectQ` (第 1214 行)

**描述**: `injectQ` 未被任何代码路径填充，电层 `sendFlitFromQ` 为死代码。`pendingDataQ` 仅在 `enableSetupHandshake=true` 时 resize，但第 1194 行无条件访问——光旁路禁用时越界崩溃。

**判定**: 🔒 **不修复**。纯电 NoC 对比实验有独立代码版本 (`D:\HNOCS_clean`)。当前光层代码仅需光旁路模式运行。

---

## C5. 热求解器永久停滞风险

**文件**: `src/thermal/ThermalTrace.cc`

**位置**: `allReady()` (第 357–364 行) / `tryFlush` (第 218–256 行)

**描述**: `allReady()` 要求全部 PE + Router 均提交功率才推进。任一模块未提交 → 永久停滞。Router 提交链依赖 `InPortSync::finalizeEnergyWindow` → `submitRouterPower`。

**判定**: 🔒 **暂不修复**。热仿真强制 `**.pe[*].enableEnergyWindow=true` 和 `**.inPort.enableEnergyWindow=true`，所有模块正常提交，热模型正常工作（阶段 1 DVFS 触发已验证）。若需容错可增加超时看门狗。

---

## C6. 显式欧拉求解器无数值稳定性保证

**文件**: `src/thermal/ThermalTrace.cc`

**位置**: `updateTemperature` (第 260–330 行)

**描述**: Forward Euler 条件稳定。当前参数下稳定边界 240ns，`energyWindow=100ns` 恰好安全（裕度 2.4×）。无任何稳定性检查、CFL 条件校验、或子步进机制。

**稳定性推导** (当前参数):

```
G_router = 1/10 + 1/3 + 4/10 = 0.833 K/W⁻¹
τ_router = Crouter / G = 1e-7 / 0.833 = 120 ns
maxStableDt = 2 × 120 = 240 ns
```

**修复** (已实施, 2026-06-02): 在 Euler 步前按实际 RC 参数计算逐节点热时间常数，取最严约束作为稳定步长上限。若 `dt > maxStableDt` 则自动拆为 N 子步。

```cpp
// 计算稳定边界
double G_router = 1.0/RconvRouter + 1.0/Rpe2router + 4.0/RlateralRouter;
double tau_router = Crouter / G_router;
double G_pe = 1.0/RconvPE + 1.0/Rpe2router + 4.0/RlateralPE;
double tau_pe = Cpe / G_pe;
double maxStableDt = 2.0 * std::min(tau_router, tau_pe);

// 必要时子步进
int nSteps = (dt_s > maxStableDt) ?
    (int)std::ceil(dt_s / (maxStableDt * 0.9)) : 1;
double subDt = dt_s / nSteps;
for (int step = 0; step < nSteps; step++) { /* Euler step */ }
```

**修复后验证**:

| 配置 | dt | maxStableDt | nSteps | 结果 |
|------|:---:|:---:|:---:|:---:|
| energyWindow=100ns | 100ns | 240ns | 1 | ✓ 值与修复前完全一致 |
| energyWindow=500ns | 500ns | 240ns | 3 | ✓ 正常完成，温度稳定 |

5/5 回归 PASS，当前参数下无变化（nSteps=1）。

---

# 二、高危级 (HIGH)

## H1. 光链路预算中转弯路径端口方向错误

**文件**: `src/onoc/common/OpticalDeviceModel.cc` (由 `LogicalTopologyManager.cc` 调用)

**位置**: `getDeviceLevelPathMetrics` 第 1288–1308 行

**描述**:

对比两处端口分配逻辑：

**`tryAllocateOpticalPathForPacket`（正确）** — 第 1841–1889 行:
```cpp
// 中间路由器: inPort 从 routers[i-1]→routerId 方向推导 (前一跳到当前)
//             outPort 从 routerId→routers[i+1] 方向推导 (当前到下一跳)
```

**`getDeviceLevelPathMetrics`（错误）** — 第 1296–1309 行:
```cpp
// 中间路由器: inPort 和 outPort 均从 (当前, 下一跳) 方向推导
int dx = nx - px, dy = ny - py;
if (dx == 0 && dy == -1)      { inPort = 4; outPort = 2; } // S→N
else if (dx == 0 && dy == 1)  { inPort = 2; outPort = 4; } // N→S
...
```

对于转弯路径（例如信号从 West 进入，从 South 退出），错误代码推导的 `inPort` 是信号**离开**的方向（而不是信号**到达**的方向），导致查找的 `formulaType` 和 `bendCount` 对应错误的转向类型。

**具体示例** — 路径 `PE0(0,0) → PE5(1,1)`，经过路由器 `(1,0)`：
- 信号从 PE0 到达路由器 `(1,0)` 的西侧端口 → `inPort` 应为 1 (West)
- 信号从路由器 `(1,0)` 向南侧离开 → `outPort` 应为 4 (South)
- 正确查询: West→South 转弯 (formulaType=0, bendCount=5)
- 错误代码查询: North→South 直通 (formulaType=3, bendCount=0)

**影响**: 所有含转弯的光路器件级预算（微环直通计数、波导损耗、SOA 配置）使用错误的转向元数据。per-router 调谐功率计算不受影响（该路径在 `tryAllocateOpticalPathForPacket` 中正确实现）。影响的函数包括 `getDeviceLevelPathMetrics` 和 `getOpticalPathMetrics` 的调用者。

**修复方向**: 将 `getDeviceLevelPathMetrics` 中的中间路由器端口推导逻辑改为与 `tryAllocateOpticalPathForPacket` 一致：`inPort` 从前一跳方向推导，`outPort` 从去往下一跳方向推导。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/onoc/control/LogicalTopologyManager.cc:1287-1325`。`outPort` 仅从方向向量推导，`inPort` 改为从 `prevOutPort` 反方向推导（与目标路由器段逻辑一致）。转弯路径的 `formulaType` 查询现已正确。

---

## H2. `isActiveWl[9]` 硬编码数组限制最大波长为 8

**文件**: `src/onoc/control/LogicalTopologyManager.cc`

**位置**: 第 1237–1240 行

**描述**:

```cpp
bool isActiveWl[9] = {false};  // 仅索引 1–8 可用
for (size_t wi = 0; wi < wavelengths.size(); ++wi)
    if (wavelengths[wi] > 0 && wavelengths[wi] <= 8)
        isActiveWl[wavelengths[wi]] = true;
```

`maxOpticalWavelengths` 默认值为 8，但用户可配置为 16、32 等。当配置超过 8 个波长时：

- 波长 9+ 被静默地视为"非活跃"
- 调制器/解调器微环链中，这些波长对应的微环被标记为 `DEV_RING_THROUGH` 而非 `DEV_RING_DROP`
- 信号未被正确耦合到对应波长的解调器端口

**影响**: 当前 `maxOpticalWavelengths=8` 恰好在边界内，不受影响。一旦升级波长数，问题立现。限制了系统的可扩展性。

**修复方向**: 使用 `std::vector<bool>(maxWl + 1)` 或 `std::set<int>` 动态分配。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/onoc/control/LogicalTopologyManager.cc:1235-1240`。`bool isActiveWl[9]` → `std::vector<bool> isActiveWl(maxWl+1, false)`，上限检查 `<=8` → `<=maxWl`。当前 8 波长配置不受影响，扩容后自动适配。

---

## H3. 全路径损耗跨波长错误累加

**文件**: `src/onoc/common/OpticalDeviceModel.cc`

**位置**: 第 424 行 (声明) / 第 523–525 行 (累加) / 第 602 行 (赋值)

**描述**:

```cpp
double totalInsertionLoss_dB = 0.0;  // ← 第 424 行: 在 per-wavelength for 循环外声明
for (int wl = 1; wl <= totalWavelengths; ++wl) {  // 第 426 行
    // ... 每个波长的独立损耗计算 ...
    totalInsertionLoss_dB += segLoss_dB;  // 第 523–525 行: 未重置，跨波长累加
}
result.totalLoss_dB = std::max(result.totalLoss_dB, totalInsertionLoss_dB);  // 第 602 行
```

每个波长的独立功率追踪变量 (`accumulatedLoss_dB`, 第 431 行) 在循环内正确声明并重置，因此 `perWavelengthTotalLoss_dB[wl]` 不受影响。但汇总变量 `totalInsertionLoss_dB` 从未重置。

**示例**: 4 个有效波长，每波长路径损耗 15 dB (物理正确值) → `totalInsertionLoss_dB = 15 + 15 + 15 + 15 = 60 dB` → `result.totalLoss_dB = 60 dB` (报告值，大 4 倍)。

**影响**: `result.totalLoss_dB` 被严重高估。若此值被论文引用为"全路径光学损耗"，数据错误。

**修复方向**: 方案 A — 将 `totalInsertionLoss_dB` 的声明移入 per-wavelength 循环内（使其在每轮迭代时重置）。方案 B — 将该变量重命名为 `accumulatedAllWavelengthsLoss_dB` 并移除对 `result.totalLoss_dB` 的赋值，仅使用 `perWavelengthTotalLoss_dB` 中的最大值。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/onoc/common/OpticalDeviceModel.cc:423-427`。`totalInsertionLoss_dB` 声明从 per-wavelength 循环外移入循环内。当前 8 波长配置下 `result.totalLoss_dB` 从 120dB（8×累加）修正为 15dB（正确值）。`perWavelengthTotalLoss_dB` 各波长独立值和 SNR/BER 计算不受影响。

---

## H4. DVFS 节流粒度导致短任务完成时间系统性偏大

**文件**: `src/cores/task/TaskPE.cc`

**位置**: 第 161 行 (初始化) / 第 979 行 (调度) / 第 985–1011 行 (`handleDvfsTick`)

**描述**:

`dvfsTickInterval` 被设置为等于 `energyWindow`（默认 100ns）。任务的实际计算推进仅在 `handleDvfsTick` 事件中进行。若 `nominalTime < dvfsTickInterval`：

1. 任务在 `startComputation` 中启动（第 979 行：`scheduleAt(simTime() + dvfsTickInterval, dvfsTickMsg)`）
2. 第一个 DVFS tick 在 `dvfsTickInterval` 后触发
3. 任务的实际完成时间 = 首个 tick 触发时间 + `workDone`，而非 `simTime + nominalTime`

**影响**: 所有 `nominalTime < 100ns` 的短任务（Optic benchmark 中 `nominalTime = 1000ns` 不受影响）表现为至少需要一整窗才能完成。完成时间系统性偏大。

额外效应：`totalThrottlePenalty`（第 1004 行）包含末尾 tick 的量化残差——若 `remainingNominalWork = 10ns` 而 `workDone = 100ns`，罚时包含 90ns 的非节流量化误差，使节流比偏高。

**修复方向**: 在 `startComputation` 中判断若 `nominalTime < dvfsTickInterval`，则用更短的自消息间隔调度首次 DVFS tick。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/cores/task/TaskPE.cc:985-1011`。末 tick 的 `workDone` 上限钳制在 `remainingNominalWork`（避免负剩余量），节流罚时改为 `actualWork×dvfsScale − actualWork`（只计实际消耗的工作量）。短任务在 dvfsScale>1.0 时的 `throttlePenaltyRatio` 不再系统性偏高。

---

## H5. GB 地址下传播延迟计算错误

**文件**: `src/cores/task/TaskPE.cc`

**位置**: 第 818–820 行 (`computeOpticalPropagationDelay`)

**描述**:

```cpp
int hops = meshHopDistance(srcId, dstId);
return opticalBasePropagationDelay + opticalPerHopDelay * hops;
```

`meshHopDistance` 使用 `address / numColumns` 和 `address % numColumns` 推导 mesh 坐标。当 `srcId` 或 `dstId` 为 GB 地址（`bufferBaseId + row`，如 1000–1003）时：

- `1000 / 4 = 250` (非物理行号)
- `1000 % 4 = 0` (非物理列号)

**影响**: PE↔GB 之间的光学传播延迟使用无意义的中间跳数，导致 `sendDirect` 的传播延迟建模不准确。普通 PE→PE 通信不受影响。

**修复方向**: 在 `meshHopDistance` 调用前判断目标是否为 GB 地址，若是则使用 GB 的实际物理位置（`dstPE - bufferBaseId = row`, col = 0）。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/cores/task/TaskPE.cc:811-830` + `src/globalbuffer/GlobalBuffer.cc:280`。`meshHopDistance` 增加 GB 地址→物理坐标映射（`bufferBaseId+row` 和 `numPEs+row` 均映射到 `(row, col=0)`）。GlobalBuffer 端 `sendFlitDirectToPE` 同步修复。PE↔GB 跳数从 ~250 修正为 0–6。

---

## H6. 波长掩码 31 位限制

**文件**: `src/onoc/control/LogicalTopologyManager.cc`

**位置**: 第 1680–1686 行 (`reserveOpticalPathForSetup`)

**描述**:

```cpp
int mask = 0;
for (int wl : wls) {
    if (wl <= 0 || wl > 31) continue;  // ← 波长 32+ 被静默丢弃
    mask |= (1 << (wl - 1));
}
```

`mask` 为 `int` 型（signed 32-bit）。第 31 位（对应波长 32）为符号位，位移操作结果未定义（C++ 标准）。波长 33+ 被 `continue` 跳过。调用者基于此掩码做判断时将缺失这些波长。

**影响**: 当前 `maxOpticalWavelengths=8` 不受影响。超过 31 个波长的配置下掩码信息不完整。

**修复方向**: 改为 `uint64_t mask` 并将上限调整为 63，或使用 `std::bitset<64>`。

**修复状态**: 🔒 不修复 — 当前 `maxOpticalWavelengths=8` 远低于 31 位限制，不影响运行。

---

## H7. 热模型初始化竞态 → 基线光调谐功率丢失

**文件**: `src/thermal/ThermalTrace.cc` (第 200–205 行) / `src/cores/task/TaskPE.cc` (第 232 行) / `src/onoc/control/LogicalTopologyManager.cc` (第 928 行)

**描述**:

1. `ThermalModel::open()` 由 `TaskPE[0]::initialize()` 调用（第 232 行），设置 `numRouters` 并清零 `routerOpticalPower`。
2. `LogicalTopologyManager::initialize()` 在第 928–929 行调用 `addRouterOpticalPower` 注入基线静态调谐功率。
3. 若 OMNeT++ 以 `LogicalTopologyManager` 先于 `TaskPE[0]` 的顺序初始化模块，此时 `numRouters == 0`（尚未调用 `open()`），`addRouterOpticalPower` 在第 202 行因 `routerId >= numRouters` 而静默返回。

**影响**: 基线光调谐功率永久丢失 → Router 初始温度偏低 → 光器件温度效应偏差。当前仿真中热效应已通过 DVFS 触发验证证明 `open()` 被正确调用，但**初始化顺序依赖 OMNeT++ 内部决策，不可靠**。

**修复方向**: 将基线功率注入从 `initialize()` 移至一个显式的初始化阶段（如 `handleMessage` 的第一个自消息），确保在 `ThermalModel::open()` 被调用后执行。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/thermal/ThermalTrace.cc/.h`。增加 `pendingOpticalPower` 缓冲区：`addRouterOpticalPower` 在 `numRouters==0` 时缓存功率，`open()` 完成后自动回填。消除了对 OMNeT++ 模块初始化顺序的依赖。

---

## H8. 热窗口跳过时功率数据静默丢失

**文件**: `src/thermal/ThermalTrace.cc`

**位置**: 第 164–167 行 / 第 218–256 行

**描述**:

当 `tryFlush` 因 `allReady()` 返回 false 而跳过时：

1. `currentWindowTime` 被更新到新窗口时间戳（第 167 行）
2. 上一窗口积累的 `pePower[]` / `routerPower[]` 被新窗口的 `submit*Power` 覆盖
3. 跳过窗口的热量从未被计入学时，且被永久丢失

如果遗漏组件在后续窗口恢复提交，`tryFlush` 最终执行，但：
- `dt = currentTime - lastTempTime` 跨越了所有跳过窗口
- 功率数据仅来自最近一个窗口
- 产生一个跨越长时间的大 Euler 步长，数值不准确且可能不稳定

**修复方向**: 为跳过的窗口累积 dt，窗口恢复后在单步中正确分配。

**修复状态**: ✅ 已修复 (2026-06-02) — `src/thermal/ThermalTrace.cc/.h`。增加 `pendingDt` 累加器：`tryFlush` 在 `allReady()=false` 时主动记录 `pendingDt += t − lastTempTime` 并推进 `lastTempTime`，成功时将累积 dt 回填 `dt = (t−lastTempTime) + pendingDt`。原有的隐式 dt 累积（不更新 `lastTempTime`）被显式化，防止未来改动意外破坏。

---

## H9. SOA 饱和状态下 ASE 噪声使用小信号增益 → 高危

**文件**: `src/onoc/common/OpticalDeviceModel.cc:453-472`

**描述**:

SOA 增益饱和: 当输入功率较高、要求输出超过饱和功率 P_sat（12 dBm）时，载流子耗尽导致实际增益 G_actual 被压缩（远小于小信号增益 G₀=10 dB）。ASE 噪声功率 ∝ (G_actual − 1)，但代码在饱和检查之前已用 G₀ 计算 ASE，饱和削波仅修正输出功率而 ASE 保持不变。

| 饱和深度 | G₀ | G_actual | 代码 ASE / 正确 ASE | 高估 |
|:---:|:---:|:---:|:---:|:---:|
| 未饱和 | 10 dB | 10 dB | 1× | 0 dB |
| 中度饱和（削波 3 dB） | 10 dB | 7 dB | 2.25× | **3.5 dB** |
| 深度饱和（削波 6 dB） | 10 dB | 4 dB | 6× | **7.8 dB** |

**修复** (✅ 2026-06-03): 在 ASE 计算前判断饱和，使用实际增益 `actualGain_dB = P_sat − P_in`（削波后）。若 `actualGain_dB ≤ 0`（输入功率已超 P_sat），`computeSOAASENoisePower_dBm` 自动返回 −199 dBm。

**验证**: Optic 266,205 事件、HNN 3,868,110 事件，标量值完全一致（ASE 仅影响 SNR/BER 内部计算）。

---

## H10. GB 陈旧 SETUP_REQ 消息未被清除 → 高危

**文件**: `src/globalbuffer/GlobalBuffer.cc:501-519`

**描述**:

`sendFlitFromQ` 在同一函数调用中依次执行超时处理→新建链检查→发送，形成竞态：

```
Step 1: 超时处理 → setupPendingByDst[d] = 0, nextSetupAttempt = now + retry
Step 2: 新建链检查 → 若 retryDelay 已过期, setupPendingByDst[d] = 1,
        新 SETUP flit → injectQ[dstConn].push() 【追加到队尾】
Step 3: 从 injectQ 队首 pop → 陈旧 flit 先出队!
```

Step 1 清除的 `setupPendingByDst` 在 Step 2 立即被重设为 1。陈旧 END flit 先发出，PE 响应 ACK(旧token)，而 GB 在 Step2 刚设 `setupPendingByDst=1` → 接受 ACK → circuit 以旧（已释放的）token 建立。新 token 的 ACK 随后被忽略。

**修复** (✅ 2026-06-03): 超时处理中遍历 `injectQ[dstConn]`，删除目标为该 dst 且 `taskId==-1`（SETUP_REQ flit）的陈旧消息。数据 flit（taskId≥0）走 `pendingDataQ` 不受影响。

**验证**: Optic 266,205 事件 / HNN 3,868,110 事件，`occupied-wavelength-slots=0`, `active-circuits=0`，标量值完全一致。

**关联发现**: PE 侧 `sendControlFlitFromQ` 超时后设 `nextSetupAttemptByDst = simTime()`（立即重试），controlQ 存在同类陈旧 flit 交织风险。建议后续统一处理。

---

# 三、中危级 (MEDIUM) — 复查与修复

> 以下 10 个中危问题于 2026-06-03 逐一复查。M3 和 M10 升级为高危（见第二节 H9–H10），M1 确认为误报。其余均已修复或确认不修改。

---

## M1. formulaType=3 微环计数公式 → 最终结论: 误报

**文件**: `src/onoc/common/OpticalDeviceModel.cc:70-128` / `src/onoc/control/LogicalTopologyManager.cc:1327-1365`

**判定**: ❌ **误报**。`4n` 公式和 `+ numActiveWL` 均正确，代码与串联耦合微环路由器架构完全一致。

**证据**: 代码自带架构规格文档（`OpticalDeviceModel.cc:70-88`）逐条声明了全部 20 条路径的 through-count 公式，`W→E:4n` 等为有意设计。架构采用**串联耦合**（"all wavelengths share the same waveguide"），所有微环（路由环 + drop 环）置于同一根总线波导上，信号串行经过每一个环。Type 3 直通路径不 drop，但 drop 环 inline 在总线上，信号必须经过它们。bendCount=0 表示无波导弯曲，而非"不经过 drop 环"。

**无需修改**。

---

## M2. SOA ASE 噪声公式缺少因子 1/2 → 高估约 3 dB

**文件**: `src/onoc/common/OpticalDeviceModel.h:303-320`

**问题**: 标准 ASE 公式 `P_ASE = hν · n_sp · (G−1) · B_o`，其中 `n_sp = NF_linear / 2`。代码使用 `P_ASE = hν · NF_linear · (G−1) · B_o`，缺少因子 1/2。默认值 `soaNoiseFigure_dB=7.0` 是标准 NF 定义（NF_dB=7→NF_lin=5.01→n_sp=2.505），代码用 NF_linear 替代 n_sp，高估 2 倍（+3 dB）。

**修复**（✅ 2026-06-03）: 公式中加入 `nfLinear / 2.0`，注释更新为标准公式。ASE 降低 3 dB，论文 SNR/BER 数据需重算。

---

## M3→H9. SOA 饱和状态下 ASE 噪声使用小信号增益 → 高危

**提升为高危**，见 [第二节 H9](#h9-soa-饱和状态下-ase-噪声使用小信号增益--高危)。

---

## M4. PAM4 BER 公式需外部验证

**文件**: `src/onoc/common/OpticalDeviceModel.h:280-294`

**问题**: 代码 `BER_PAM4 = 0.75 × erfc(√(SNR/10))` 与 ITU-T G.Sup39 一致，但与 Griffin 2005 等 per-bit 定义差 2×。公式本身正确但 SNR 定义需明确。

**修复**（✅ 2026-06-03）: 添加 ITU-T G.Sup39 (2016) 引用注释，说明 3/4 vs 3/8 前因子差异源于 optical-SNR vs per-bit-SNR 定义。公式不修改。

---

## M5. `checkStop` 在动态任务存在时可能过早触停

**文件**: `src/cores/task/TaskPE.cc:263, 1070-1077, 422-439`

**问题**: `systemTotalTasks` 仅统计 CSV 加载的静态任务，动态任务（GB 运行时创建）未计入。所有静态任务完成后 `checkStop` 触发 `endSimulation()`，动态任务可能未完成即终止。`isAllDataSent()` 也不检查 `currentTask` 和 `readyQueue`。

**判定**: 🔒 **不修复**。动态任务分配场景已不再使用。

---

## M6. `pendingDependencies` 无下溢保护

**文件**: `src/cores/task/TaskPE.cc:1474`

**问题**: `task->pendingDependencies--` 无守卫，重复依赖通知可导致下溢为负值，使后续 `<= 0` 检查导致任务重复入队 readyQueue。

**修复**（✅ 2026-06-03）: 递减前增加 `if (task->pendingDependencies > 0)` 守卫。

---

## M7. `nextSetupAttemptByDst` 未在拆链后重置

**文件**: `src/cores/task/TaskPE.cc:787` / `src/globalbuffer/GlobalBuffer.cc:307`

**问题**: SETUP_REQ 发出时 `nextSetupAttemptByDst = simTime() + 50ns`。ACK→电路建立→END_FLIT 拆链后该时间戳残留。若电路持续 < 50ns，下次同 dst 建链被阻塞 ≤ 50ns。

**修复**（✅ 2026-06-03）: 拆链时重置 `nextSetupAttemptByDst = SIMTIME_ZERO`（PE + GB 两侧）。Optic/HNN 回归通过。

---

## M8. 默认热容值偏低约 100–500 倍 → 热动态时间尺度压缩

**文件**: `src/thermal/ThermalTrace.cc:39-40`

**问题**: Cpe=1×10⁻⁶ J/K 比物理硅 tile 值低 ~500×，Crouter=1×10⁻⁷ J/K 低 ~700×。热时间常数 τ=RC 从物理 ms 级压缩到仿真 μs 级。

**判定**: 🔒 **不修改**。论文 `20260530.md` 明确记录了当前值。若论文不讨论绝对热时间尺度，可作为仿真加速简化在论文中声明。不影响稳态温度。

---

## M9. `evalThroughCount` 已实现但从未被调用

**文件**: `src/onoc/common/OpticalDeviceModel.cc:133-143`

**问题**: `static int evalThroughCount()` 正确实现了 6 种公式类型，但 `LogicalTopologyManager.cc` 中 3 处独立重复了相同的 switch 逻辑。维护风险：修改公式时需同步 4 处。

**判定**: 低优先级。当前不影响功能，建议后续代码清理时统一。

---

## M10→H10. GB 陈旧 SETUP_REQ 消息未被清除 → 高危

**提升为高危**，见 [第二节 H10](#h10-gb-陈旧-setup_req-消息未被清除--高危)。

---

# 四、低危级 (LOW) — 6/12 已修复 (2026-06-03)

| # | 位置 | 描述 | 状态 |
|---|------|------|:---:|
| L1 | `TaskPE.cc:250, 359` | `computeCompleteMsg` 死代码 — 旧定时器残留，已移除 | ✅ |
| L2 | `TaskPE.cc:169, 1176` | `pktIdCounter` 溢出冲突 — 加 ASSERT 守卫 | ✅ |
| L3 | `TaskPE.cc:699 vs 1134` | `consumerPE` 内部索引/网络地址不一致 — 统一为 netDst | ✅ |
| L4 | `TaskPE.cc:958` | `outputDataSize * computeDensity` C++ 自动提升为 double，不溢出 | ⬜ |
| L5 | `TaskPE.cc:1525` | `samplePower` 事件标签误导 — 建议论文中声明 | ⬜ |
| L6 | `OpticalDeviceModel.cc:66` | 默认参数全零静默返回 — 建议加 EV_WARN | ⬜ |
| L7 | `OpticalDeviceModel.cc:164,222` | `deviceIndex` 编码限制远低于实际值 | ⬜ |
| L8 | `OpticalDeviceModel.cc:434` | 噪声模型缺失散粒/暗电流 — 建议论文中声明 | ⬜ |
| L9 | `GlobalBuffer.cc:293` | 控制 flit 扫描起点 — 流量稀疏无实际饥饿 | ⬜ |
| L10 | `GlobalBuffer.cc:224-226` | `tasksCompleted` 改为检查 `TASK_COMPLETED` 状态 | ✅ |
| L11 | `ThermalTrace.cc:89` | `ThermalModel::close()` 在 `TaskPE::finish()` 显式调用 | ✅ |
| L12 | `ThermalTrace.cc:310-313` | Euler 更新后温度钳位 `max(T, Tambient)` | ✅ |

### L1–L3, L10–L12 修复详情

**L1 — `computeCompleteMsg` 死代码** (`TaskPE.cc:250, 359, 581` / `TaskPE.h:73`): 该消息从未被 `scheduleAt` 调度（全仓库仅 `dvfsTickMsg` 被调度），`handleMessage` 中对应分支永不可达。已移除创建、检查、析构清理共 5 行。

**L2 — `pktIdCounter` 溢出** (`TaskPE.cc:1177`): `pktIdCounter = peId << 16` 每 PE 仅 65536 ID 空间。加 `ASSERT((pktId >> 16) == peId)` 零开销检测。

**L3 — `consumerPE` 不一致** (`TaskPE.cc:700`): `sendControlFlitFromQ` 使用内部索引 `d`，`sendTaskData` 使用网络地址 `dstPE`。改为 `setConsumerPE(netDst)` 统一。注：`getConsumerPE` 当前无任何业务代码调用，无功能影响。

**L10 — `tasksCompleted` 指标修正** (`GlobalBuffer.cc:236`): `assignedPE >= 0` → `state == TASK_COMPLETED`。修复前 GB 的 `tasksCompleted` 始终等于 `totalTasks`（误导），修复后正确反映实际完成状态。

**L11 — 热快照写入** (`TaskPE.cc:574`): `ThermalModel` 为全局裸指针单例，析构函数永不执行。在 `TaskPE::finish()` 末尾加 `getThermalModel()->close()`，`thermal_snapshot.json` 现在正常生成（16 PE + 16 Router 温度，均高于 Tambient=318.15K）。

**L12 — 温度下限钳位** (`ThermalTrace.cc:354-357`): Forward Euler 更新后加 `if (peTemp[i] < Tambient) peTemp[i] = Tambient`（PE + Router 两侧各 1 行）。

### L4–L9 不修复原因

| # | 判定 |
|---|------|
| L4 | `int * double` 按 C++ 规则自动提升为 double，不溢出。数据量远低于 int 上限 |
| L5 | `samplePower` 周期性采样时 `isIdle=false` 标记为 `PE_COMPUTE_START` 不准确，建议论文声明 |
| L6 | 参数表由 NED 完整填充，不漏配。建议加 `EV_WARN` 但非紧急 |
| L7 | 节点数 ≤19、端口固定 5，远低于编码上限。`deviceIndex` 非功能字段 |
| L8 | 散粒噪声/暗电流 <1 dB 影响，建议论文声明模型假设 |
| L9 | 控制 flit 流量极稀疏（每握手 2 flit），无实际饥饿风险 |

### 低危修复回归测试 (2026-06-03)

| Benchmark | 事件数 | Δ vs 基线 | 终止方式 | occupied-slots |
|-----------|:---:|:---:|------|:---:|
| Optic | 266,205 | 0 | endSimulation | 0 |
| VOPD | 1,756,666 | 0 | endSimulation | 0 |
| MPEG4 | 2,263,683 | 0 | endSimulation | 0 |
| HNN | 3,868,110 | 0 | endSimulation | 0 |
| GEMM | 2,178,337 | 0 | endSimulation | 0 |

---

# 五、设计层面问题

## D1. 脆弱的 SETUP_REQ/ACK 协议复用

**文件**: `TaskPE.cc:1274, 1306` / `GlobalBuffer.cc:147, 179`

协议通过 `producerPE` 字段的符号区分 REQ 和 ACK：`>=0` 表示 REQ，`<0` 表示 ACK。这不是显式的消息类型字段，而是对业务字段语义的重载。任何中间处理代码若不正确保留此约定，将导致控制消息被误分类。

**建议**: 引入显式的消息类型枚举（`SETUP_REQ_START`, `SETUP_REQ_END`, `SETUP_ACK_START`, `SETUP_ACK_END`），避免依赖字段符号。

---

## D2. 单一点对点电路假设限制并发

当前 `circuitReadyByDst` / `setupPendingByDst` 均按**目的地**索引（一维数组），意味着每个 PE 与每个 dst 之间最多一��活跃电路。在需要多电路到同一 dst 的场景中（如不同优先级的流量类），此设计将形成瓶颈。

---

## D3. 热求解器的同步屏障设计脆弱

`allReady()` 屏障要求所有 16PE + 16Router×5Port = 大量模块在每窗口内同步提交。任一模块的瞬态偏离（如初始化延迟、自消息丢失）都可导致全局停顿。更适合仿真的设计是容忍个别缺失并以上一窗口值/零值填充。

---

## D4. OMNeT++ 模块初始化顺序敏感性

多个模块依赖 `ThermalModel::open()` 完成后的状态。但 OMNeT++ 模块初始化顺序不受应用代码控制。至少两处依赖此顺序（C5 初始化竞态中的基线调谐功率，以及 `pendingDataQ` 的 resize）。应解耦为显式的两阶段初始化。

---

# 六、审查统计

| 严重程度 | 数量 | 描述 |
|:--------:|:----:|------|
| 致命 (CRITICAL) | 6 (4✅ 2🔒) | 死锁、资源泄漏、崩溃、仿真不可信 |
| 高危 (HIGH) | 10 (9✅ 1🔒) | 错误物理/逻辑结果 (含 H9 M3→H, H10 M10→H) |
| 中危 (MEDIUM) | 10 (4✅ 2🔒 2⬜) | 精度或边界条件错误 (含 M1 误报) |
| 低危 (LOW) | 12 (6✅ 6⬜) | 代码质量/可维护性 |
| 设计层面 | 4 | 架构与协议级问题 |
| **总计** | **42** (23✅ 5🔒 8⬜) | |

---

# 附录 A: 各模块问题分布

| 模块 | 致命 | 高危 | 中危 | 低危 | 设计 |
|------|:---:|:---:|:---:|:---:|:---:|
| `GlobalBuffer` | 3✅ | 2✅(H5,H10) | 0 | 3 | — |
| `TaskPE` | 1🔒 | 3✅(H4,H5) | 2✅(M6,M7) | 5 | — |
| `ThermalTrace` | 2✅🔒 | 2✅(H7,H8) | 1 | 2 | 1 |
| `LogicalTopologyManager` | — | 2✅(H1,H2) | 1⬜(M1误报) | — | — |
| `OpticalDeviceModel` | — | 3✅(H3,H6,H9) | 3 (M2✅, M4✅, M9⬜) | 2 | — |
| 跨模块/设计 | — | — | — | — | 3 |

---

# 附录 B: 修复优先级与状态

```
✅ 已修复 — 致命级 (2026-06-02):
  C1  光路径令牌丢失          — GlobalBuffer.cc +1 行
  C2  信用泄漏死锁            — GlobalBuffer.cc +9 行
  C3  GB 多包 HoL 阻塞        — GlobalBuffer.cc 改写 flushPendingData
  C6  欧拉稳定性保护          — ThermalTrace.cc 稳定性检测 + 子步进

✅ 已修复 — 高危级 (2026-06-02):
  H1  转弯端口方向错误        — LogicalTopologyManager.cc (~30 行)
  H2  isActiveWl 数组限制     — LogicalTopologyManager.cc (3 行)
  H3  全路径损耗累加错误      — OpticalDeviceModel.cc (2 行)
  H4  DVFS 粒度过大           — TaskPE.cc (8 行)
  H5  GB 跳数计算错误         — TaskPE.cc + GlobalBuffer.cc (~20 行)
  H7  热模型初始化竞态        — ThermalTrace.cc/.h (15 行)
  H8  热窗口 dt 丢失          — ThermalTrace.cc/.h (10 行)

✅ 已修复 — 高危级 (2026-06-03, 中危复查升级):
  H9  SOA 饱和 ASE 噪声修正   — OpticalDeviceModel.cc (~20 行)
  H10 GB 陈旧 SETUP_REQ 清除  — GlobalBuffer.cc (~15 行)

✅ 已修复 — 中危级 (2026-06-03):
  M2  ASE 噪声因子 1/2 修正    — OpticalDeviceModel.h (3 行)
  M4  PAM4 BER 引用注释       — OpticalDeviceModel.h (8 行)
  M6  pendingDeps 下溢守卫    — TaskPE.cc (1 行)
  M7  拆链 nextSetup 重置     — TaskPE.cc + GlobalBuffer.cc (2 行)

🔒 不修复:
  C4  电层路径不可用          — 纯电对比有独立代码版本
  C5  热模型停滞风险          — 热仿真强制 enableEnergyWindow=true
  H6  波长掩码 31 位限制      — 当前 maxWavelengths=8 远低于限制
  M5  checkStop 过早          — 动态任务场景不再使用
  M8  热容值偏低              — 论文声明仿真加速缩放

✅ 已修复 — 低危级 (2026-06-03):
  L1   computeCompleteMsg 死代码     — TaskPE.cc/.h (删除 ~5 行)
  L2   pktIdCounter 溢出断言        — TaskPE.cc (加 1 行 ASSERT)
  L3   consumerPE 一致性            — TaskPE.cc (改 1 行)
  L10  tasksCompleted 统计修正      — GlobalBuffer.cc (改 1 行)
  L11  ThermalModel 快照写入        — TaskPE.cc (加 1 行 close())
  L12  温度下限钳位                  — ThermalTrace.cc (加 2 行)

⬜ 待定 — 低优先级:
  M9  evalThroughCount 去重   — OpticalDeviceModel (代码质量)
  L4   outputDataSize int 溢出 — C++ 自动类型提升，不溢出
  L5   samplePower 事件标签   — 建议论文声明
  L6   默认器件参数全零       — 建议加 EV_WARN
  L7   deviceIndex 编码限制   — 远低于实际值
  L8   散粒噪声/暗电流缺失   — 建议论文声明
  L9   控制 flit 扫描起点     — 无实际饥饿风险

待修复 — 设计改进:
  D1-D4 架构与协议级改进

❌ 误报:
  M1  formulaType=3 微环计数  — 串联耦合架构, 代码正确
```
