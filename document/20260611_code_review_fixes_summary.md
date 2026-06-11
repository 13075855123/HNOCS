# 2026-06-11 Code Review 修改内容整理

本文档整理本轮 code review 后已经完成的代码修复、指标口径调整和数据语义收敛。复现实验和运行命令请参考 `D:\HNOCS\out\AGENTS.md`。

## 1. 指标输出与论文口径调整

### 1.1 `.vec` 输出收敛

`examples/task_driven/omnetpp.ini` 已将 vector 输出收敛为论文主热指标需要的 PE 温度时间序列：

```text
pe[*] pe-die-temperature
```

该时间序列用于计算：

- `T_max`
- `sigma_T`
- `N_hot`

其他核心指标继续来自 `.sca` 标量或 Python evaluator 计算，包括 makespan、DVFS penalty、能耗、optical budget、communication cost、congestion cost 和 load imbalance。

修改后不再记录 router 温度、queue length、PE/router energy window、latency、source queue 或 optical path 的逐时序 vector，从而减少仿真输出体积。

涉及文件：

- `examples/task_driven/omnetpp.ini`

### 1.2 Makespan 改为 traffic-drained 口径

新增 `allTrafficDrainedAt` 标量，用于表示所有任务计算完成且所有 PE 发送队列、pending 队列和 optical sendDirect 传输均排空后的时间。

Python 解析中，`P1_makespan_s` 优先使用：

```text
allTrafficDrainedAt
```

若历史结果没有该字段，才 fallback 到旧字段：

```text
allTasksCompletedAt
```

这使 makespan 覆盖最后输出 flit 的传输时间，不再只停留在最后一个 task 计算完成时刻。

涉及文件：

- `src/cores/task/TaskPE.cc`
- `Experiment/mapping/omnet_evaluator.py`

### 1.3 E7 能耗口径改名

原 `E7_total_energy_J` 容易被误解为完整 system total energy，现改名为：

```text
E7_pe_optical_comm_energy_J
```

当前 E7 表示：

```text
PE total energy + SOA energy + MRR tuning energy + laser energy
```

即 PE 与光通信相关能耗，不包含 electronic router buffer/read/crossbar/leakage energy。代码保留旧字段 fallback，以便读取历史结果。

涉及文件：

- `Experiment/mapping/omnet_cost_model.py`
- `Experiment/B-2/run.py`
- `Experiment/B-2/ga_mapper.py`

### 1.4 当前 static baseline 口径独立记录

当前修复后的 static baseline 数值已整理到：

```text
document/20260612_static_current_values_from_chat.md
```

后续若比较“当前代码口径下的 static baseline”和新 rerun 结果，应优先使用该文件中的数值。旧 `out\B-2-v3-g60-seed42` 与 `out\B-2-v3-g60-seed43` 中的 baseline 仍作为历史论文结果保留，不应与当前修复后的 static baseline 混用。

涉及文件：

- `document/20260612_static_current_values_from_chat.md`

## 2. 热模型、DVFS 与 snapshot 修复

### 2.1 DVFS 最后 partial tick 完成时间修复

`TaskPE` 现在记录 `lastDvfsUpdateTime`，每次 DVFS tick 按真实 elapsed time 推进 `remainingNominalWork`。

下一次事件时间取：

```text
min(dvfsTickInterval, remainingNominalWork * dvfsScale)
```

因此任务最后只剩少量 nominal work 时，会在真实完成时间结束，而不是被强制推迟到下一个完整 `energyWindow` tick。这使 `actual compute time = nominal compute time + throttle penalty` 的统计口径更一致。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`

### 2.2 Router 功耗窗口聚合修复

原逻辑由 `port[0].inPort` 读取同一 router 其他 port 的 `windowEnergyJ` 并提交总功耗，容易受到同一时间戳事件执行顺序影响。

现在每个 inPort 都向 `ThermalModel` 提交自己的 per-port 平均功率。`ThermalModel` 等待同一 router 的所有 port 在同一窗口都提交后，再汇总为 router 平均功率并进入 RC 热网络。

涉及文件：

- `src/routers/hier/inPort/InPortSync.h`
- `src/routers/hier/inPort/InPortSync.cc`
- `src/thermal/ThermalTrace.h`
- `src/thermal/ThermalTrace.cc`

### 2.3 Thermal snapshot 写出时机修复

原逻辑中每个 `TaskPE::finish()` 都会调用 `ThermalModel::close()`，可能导致第一个 PE finish 后过早写出 `thermal_snapshot.json`。

现在 TaskPE finish 后只标记 PE 完成：

```text
markPEFinished(peId)
```

router 侧每个 inPort 在 finish 时提交 final window。`ThermalModel` 等所有 PE 和所有 router final window 都完成后，才统一关闭并写出 `thermal_snapshot.json`。

涉及文件：

- `src/cores/task/TaskPE.cc`
- `src/routers/hier/inPort/InPortSync.cc`
- `src/thermal/ThermalTrace.h`
- `src/thermal/ThermalTrace.cc`

### 2.4 Thermal snapshot fallback 指标补齐

当 `.vec` 缺失或解析失败时，Python evaluator 现在会基于 `thermal_snapshot.json` 的最终 PE 温度数组计算：

- `T_max`
- `sigma_T`
- `N_hot`

该 fallback 是 final-only 口径。正常论文结果仍优先使用 `.vec` 中的时间序列温度指标。

涉及文件：

- `Experiment/mapping/omnet_evaluator.py`

## 3. 光路由器 device-level 模型修复

### 3.1 多波长 optical budget 重复计数修复

`computeDeviceLevelBudget()` 原先会对每个 active wavelength 遍历整条 `devPath.segments`，但 segment 没有按 `wavelengthIndex` 过滤，导致多波长路径下重复计算其他 wavelength 的 drop ring、PD、waveguide crossing 和 crosstalk。

现在光路径按 wavelength 构造 signal path，budget 计算时只处理匹配当前 wavelength 的 segment。per-device 汇总也改为按 wavelength 单独统计后取 worst/max，而不是把所有 wavelength 的器件损耗简单相加。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/control/LogicalTopologyManager.cc`
- `src/onoc/common/OpticalPathMetrics.h`

### 3.2 SOA 温度归属修复

原逻辑中 SOA segment 的 `deviceIndex` 直接使用 router id，而热模型通过：

```text
nodeId = deviceIndex / 1000
```

推导温度节点，导致 router id 0-15 都映射到节点 0。

现在 `OpticalDeviceSegment` 新增：

```text
hostNodeId
```

所有光器件 segment 显式记录所属 PE/router。SOA 的 `hostNodeId` 设为驱动该 hop 的 router，与 SOA pump power 热注入位置保持一致。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/control/LogicalTopologyManager.cc`

### 3.3 MRR detuning 与 tuning power 口径修复

原逻辑在温度偏移时同时叠加完整 ring detuning loss 和 heater tuning power，物理解释不自洽。

现调整为：

- `tuningEfficiency_mW_per_nm > 0` 时，认为 heater 补偿 detuning，只累计 tuning power 和 max detuning，不再叠加完整 ring detuning loss。
- `tuningEfficiency_mW_per_nm <= 0` 时，认为不进行热调谐补偿，使用 `ringIL_TempCoeff_dB_per_K * |deltaT|` 作为未补偿 residual loss。
- ring tuning power 按物理 ring 去重，不再因多 wavelength budget loop 重复累计。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.cc`

### 3.4 Router through-count API 修复

`RouterTurnMetadata.throughCount` 原先注释表示 through ring 数量，但实际存储 formula type。现在结构调整为：

```text
throughFormulaType  # 公式编号
throughCount        # 已求值的 through ring 数量，默认 0
```

并新增统一求值入口：

```text
evaluateRouterThroughCount(meta, wavelengthIndex, totalWavelengths)
```

路径构造、动态 tuning ring count 和 router turn expansion 均使用同一个 helper，避免公式重复实现。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/control/LogicalTopologyManager.cc`

### 3.5 Crosstalk 聚合与单位口径修复

原逻辑中 `accumulatedCrosstalk_dB` 混用了 dB sentinel 和 dBm power 语义，且只保留单个 segment 最大值。

现在 crosstalk noise 先按 mW 线性求和，再转换为 dBm 输出。为兼容历史结果，旧字段仍保留：

- `totalCrosstalk_dB`
- `perWavelengthCrosstalk_dB`

新增推荐字段：

- `totalCrosstalkNoise_dBm`
- `perWavelengthCrosstalkNoise_dBm`

后续论文或结果表述应优先使用 `*_CrosstalkNoise_dBm` 口径。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/common/OpticalPathMetrics.h`
- `src/onoc/control/LogicalTopologyManager.cc`

### 3.6 Optical budget cache 释放修复

`releaseOpticalPathForPacket()` 现在释放 optical allocation 时同步清理：

```text
cachedBudgets.erase(pktId)
```

避免 packet release 后仍保留 stale budget metrics。

涉及文件：

- `src/onoc/control/LogicalTopologyManager.cc`

## 4. TaskPE、packet/flit 生命周期与控制面修复

### 4.1 Optical direct flit credit 修复

Optical direct 到达的 flit 不再返还 electrical credit，避免 optical bypass 流量虚增 router/VC credit 并低估拥塞。

涉及文件：

- `src/cores/task/TaskPE.cc`
- `src/cores/sinks/InfiniteBWMultiVCSink.cc`

### 4.2 Packet reassembly 严格化

packet reassembly 不再只依赖 EoP。现在按 `pktId` 检查：

- SoP
- flit 顺序
- EoP 位置
- 总 flit 数

缺 flit、乱序或重复 flit 会直接报错，避免静默拼出错误 packet。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`

### 4.3 Same-PE dependency 语义修复

same-PE dependency 不再在 CSV 加载阶段提前扣除。本地依赖和远程依赖统一在 producer task 完成后递减，避免同 PE successor 因 CSV 行顺序提前执行。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`

### 4.4 Optical setup ACK/token 与 timeout 修复

控制面 setup handshake 做了以下调整：

- `SETUP_ACK` 必须匹配当前 `pendingSetupTokenByDst`，不再接受 stale ACK 建立错误 circuit。
- setup timeout 后清理同 token 的未发送 `SETUP_REQ` control flit。
- timeout 后下一次 setup 尝试延后到 `setupRetryDelay`。
- `SETUP_ACK` 只在 END flit 上计数和判定，避免一个两 flit ACK 被重复统计。
- `setupPendingTimeout` 从 `200ns` 调整为 `2us`。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`
- `src/globalbuffer/GlobalBuffer.h`
- `src/globalbuffer/GlobalBuffer.cc`
- `src/cores/sources/PktFifoSrc.h`
- `src/cores/sources/PktFifoSrc.cc`
- `examples/task_driven/omnetpp.ini`

### 4.5 Optical circuit release 时机修复

Optical bypass 不再在发送端 EoP 发出后立即释放 circuit。

现在 TaskPE、GlobalBuffer 和 PktFifoSrc 在 EoP optical direct 发送后，按传播延迟与发送时长调度延迟释放，避免最后一个 flit 仍在传输时提前释放 token 或复用光路资源。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`
- `src/globalbuffer/GlobalBuffer.h`
- `src/globalbuffer/GlobalBuffer.cc`
- `src/cores/sources/PktFifoSrc.h`
- `src/cores/sources/PktFifoSrc.cc`

### 4.6 Optical control polling 风暴修复

`controlPopMsg` 不再按 1ns 永久轮询。控制面改为按需调度：

- controlQ 非空时继续调度发送。
- 有 setup pending 时调度到 pending timeout。
- 有 pending data 且无 circuit/setup 时调度到下一次 setup retry。
- 完全没有控制工作时不再调度 control self-message。

该修改避免异常 pending data 或 stale ACK 导致仿真跑满 `sim-time-limit` 并产生巨大 `.vec` 文件。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`

### 4.7 Setup/control flit 类型标记修复

`TaskPE` 与 `GlobalBuffer` 构造 optical setup/control flit 时，现在显式设置：

```text
SL = onocEncodePacketTag(...)
```

分别标记为：

- `ONOC_PKT_SETUP_REQ`
- `ONOC_PKT_SETUP_ACK`

避免默认 `SL=0` 被 `ReconfigurableOPCalc` 当作 data packet，从而提前触发 optical allocation/release。

覆盖路径包括 TaskPE 初始 setup、retry setup、ACK 生成，以及 GlobalBuffer 的 GB->PE setup、retry setup、GB ACK 生成。

涉及文件：

- `src/cores/task/TaskPE.cc`
- `src/globalbuffer/GlobalBuffer.cc`

### 4.8 PE 控制面电 flit 能耗漏计修复

`TaskPE` 发送 `SETUP_REQ/SETUP_ACK` control flit 时，现在计入：

- `totalFlitsSent`
- `windowSendFlits`

接收 `taskId == -1` 的 control flit 时，现在计入：

- `totalFlitsReceived`
- `windowRecvFlits`

然后再进入 ACK/token 处理逻辑。控制面正常产生的 PE send/receive 动态能耗因此会进入 `TaskPE.totalEnergyJ` 和最终 PE + optical communication energy。

涉及文件：

- `src/cores/task/TaskPE.cc`

## 5. Task graph、CSV 与 GlobalBuffer 语义修复

### 5.1 Static CSV 写出顺序修复

`TaskGraph` 现在记录 CSV 原始 task 行序。`write_static_csv()` 写 remapped CSV 时保持原始行序，避免把 task-to-PE remap 与同 PE ready-queue 顺序变化混在一起。

涉及文件：

- `Experiment/mapping/task_graph.py`
- `Experiment/mapping/csv_writer.py`

### 5.2 Static CSV 完整性校验增强

`write_static_csv()` 增加严格完整性校验。以下情况会直接报错：

- 缺失 mappable task assignment
- 未知 task
- 非法 PE
- 负 compute time
- 负 data size
- 未知 successor

不再静默写出 `-2` task，也不再把未知 successor 降级成 GB sink。

涉及文件：

- `Experiment/mapping/csv_writer.py`
- `Experiment/mapping/task_graph.py`

### 5.3 GlobalBuffer 空 marker 语义修复

`GlobalBuffer` 修复空 `peId=-1` GB marker 的语义。空 GB 行只作为 metadata，不再阻断 legacy implicit 初始任务分发；有 successor 的 GB task 才触发 explicit GB injection。

涉及文件：

- `src/globalbuffer/GlobalBuffer.h`
- `src/globalbuffer/GlobalBuffer.cc`

### 5.4 GB 输入依赖处理修复

GB flit 到达 TaskPE 时，现在通过：

```text
markDependencySatisfied(..., "gb", true)
```

处理依赖，不会在存在 GB + PE 混合前驱时提前把 consumer task 置为 READY。

涉及文件：

- `src/cores/task/TaskPE.cc`

### 5.5 C++ TaskGraphParser 严格解析

`TaskGraphParser.cc` 替换原有 `atoi/atof` 静默解析。非法 task id、PE id、successor、compute time 或 data size 现在会抛出 `cRuntimeError`，使 C++ 侧与 Python parser 的错误处理更一致。

涉及文件：

- `src/utils/TaskGraphParser.cc`

## 6. 后续仍需注意的风险

当前正常 GEMM 路径已不再出现 setup retry storm，但后续仍建议补充两类保护：

- 为 optical setup 增加最大重试次数或最大等待时间，超过阈值后 fallback 到 electrical path 或直接报错，避免异常 workload 静默跑满 `sim-time-limit`。
- 为 setup handshake 增加 retry/timeout by-dst scalar，实验脚本若发现 timeout 或 retry 超阈值，应标记该 run 无效。

## 7. 写作和结果使用提示

- 论文表述中，E7 应写作 PE + optical communication energy，不应写作完整系统总能耗。
- 当前代码口径下的新 static/remapped 对比，应使用 `document/20260612_static_current_values_from_chat.md` 中的 static baseline。
- 旧 `B-2-v3-g60-seed42/seed43` 结果仍可用于历史论文结果叙事，但不要和当前修复后的 static baseline 直接混合比较。
- 生成新图表或表格时，应从 `metrics.json` 读取结构化字段，不要从 `summary.txt` 手工解析核心数据。
