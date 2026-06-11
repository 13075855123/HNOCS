# 2026-06-11 Code Review 修复总结

本文档简要记录本轮 code review 后已经完成的功能修复与指标口径调整。审查范围包括热模型、PE 任务执行、功耗窗口、DVFS 节流、thermal snapshot、Python 指标解析，以及光路由器 device-level 模型、路径构造、光预算统计和相关输出口径。

## 1. DVFS 最后一个 tick 的完成时间修复

已修复 TaskPE 中 DVFS tick 按整窗口完成任务的问题。

原逻辑中，任务即使只剩很少 nominal work，也会等到下一个完整 `energyWindow` tick 才完成，导致 makespan 偏大，而 `totalThrottlePenalty` 又只按实际完成的 nominal work 计算，二者不闭合。

现在 TaskPE 记录 `lastDvfsUpdateTime`，每次 DVFS tick 根据真实 elapsed time 推进 `remainingNominalWork`。下一次事件时间取：

```text
min(dvfsTickInterval, remainingNominalWork * dvfsScale)
```

因此最后一个 partial tick 会在真实完成时间触发，`actual compute time = nominal compute time + throttle penalty` 的统计口径更一致。

涉及文件：

- `src/cores/task/TaskPE.h`
- `src/cores/task/TaskPE.cc`

## 2. Router 功耗窗口聚合修复

已修复 router 功耗聚合依赖同一时间戳事件顺序的问题。

原逻辑中只有 `port[0].inPort` 负责读取其他 port 的 `windowEnergyJ` 并提交 router 总功耗。如果同一窗口内 `port[0]` 比其他 port 更早执行，就可能读取到尚未更新或已清零的窗口能量，导致 router 热注入偏低且非确定。

现在每个 inPort 都向 `ThermalModel` 提交自己的 per-port 平均功率。`ThermalModel` 内部等待同一 router 的所有 port 在同一窗口都提交后，再汇总为 router 平均功率并进入 RC 热网络。

涉及文件：

- `src/routers/hier/inPort/InPortSync.h`
- `src/routers/hier/inPort/InPortSync.cc`
- `src/thermal/ThermalTrace.h`
- `src/thermal/ThermalTrace.cc`

## 3. Makespan 口径改为 traffic-drained

已新增 `allTrafficDrainedAt` 标量。

原来的 `allTasksCompletedAt` 在最后一个 task 计算完成时记录，但此时最终输出 flit 可能仍在发送队列或光直连链路中。现在 `checkStop` 确认所有 PE 的发送队列、pending 队列和 optical sendDirect 传输均排空后，记录：

```text
allTrafficDrainedAt
```

Python 解析中，`P1_makespan_s` 优先使用 `allTrafficDrainedAt`；如果旧结果没有该字段，才 fallback 到 `allTasksCompletedAt`。

涉及文件：

- `src/cores/task/TaskPE.cc`
- `Experiment/mapping/omnet_evaluator.py`

## 4. Thermal snapshot 写出时机修复

已修复第一个 PE finish 过早关闭 `ThermalModel` 的问题。

原逻辑中每个 TaskPE 的 `finish()` 都会调用 `getThermalModel()->close()`。第一个 PE finish 后就可能写出 `thermal_snapshot.json`，其他 PE/router 的最终窗口功耗不再进入热模型。

现在 TaskPE finish 后只调用：

```text
markPEFinished(peId)
```

router 侧每个 inPort 在 finish 时提交 final window。`ThermalModel` 等所有 PE 与所有 router final window 都完成后，才统一关闭并写出 `thermal_snapshot.json`。

涉及文件：

- `src/cores/task/TaskPE.cc`
- `src/routers/hier/inPort/InPortSync.cc`
- `src/thermal/ThermalTrace.h`
- `src/thermal/ThermalTrace.cc`

## 5. Thermal snapshot fallback 指标补齐

已补齐 `.vec` 缺失时的 snapshot fallback 指标。

原逻辑中，如果 `.vec` 解析失败，Python 只读取 `thermal_snapshot.json` 的最终温度数组，但不计算 `sigma_T` 和 `N_hot`，可能让这两个指标错误地保持 0。

现在 fallback 会基于最终 PE 温度计算：

- `T_max`
- `sigma_T`
- `N_hot`

注意：该 fallback 是 final-only 口径，正常论文结果仍优先使用 `.vec` 中的时间序列温度指标。

涉及文件：

- `Experiment/mapping/omnet_evaluator.py`

## 6. E7 能耗口径改名

已将原先容易被理解为完整 system total energy 的 E7 口径改名为：

```text
E7_pe_optical_comm_energy_J
```

当前 E7 表示：

```text
PE total energy + SOA energy + MRR tuning energy + laser energy
```

也就是 PE 与光通信相关能耗。它有意不包含 electronic router buffer/read/crossbar/leakage energy。这样避免论文或结果表中把该项误写为完整系统总能耗。

兼容性方面，代码中保留了旧名 `E7_total_energy_J` 的 fallback，用于读取历史结果。

涉及文件：

- `Experiment/mapping/omnet_cost_model.py`
- `Experiment/B-2/run.py`
- `Experiment/B-2/ga_mapper.py`

## 7. 光路由器多波长预算重复计数修复

已修复 device-level optical budget 中多波长路径被重复计数的问题。

原逻辑中，`computeDeviceLevelBudget()` 会对每个 active wavelength 遍历整条 `devPath.segments`，但 segment 没有按 `wavelengthIndex` 过滤。多波长路径下，每个 wavelength 会重复支付其他 wavelength 的 drop ring、PD、waveguide crossing 和 crosstalk，导致：

- `totalLoss_dB` 偏高
- SNR 偏低
- BER 偏高
- `tempAdjustedLoss_dB` 和 tuning power 可能重复累计
- `O2-O8` 光预算输出不再严格对应真实 allocation

现在光路径按 wavelength 构造 signal path，budget 计算时只处理匹配当前 wavelength 的 segment。per-device 汇总也改为按 wavelength 单独统计后取 worst/max，而不是把所有 wavelength 的器件损耗简单相加。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/control/LogicalTopologyManager.cc`
- `src/onoc/common/OpticalPathMetrics.h`

## 8. SOA 温度归属修复

已修复 SOA 温度查表错误映射到 router 0 的问题。

原逻辑中，SOA segment 的 `deviceIndex` 直接使用 router id，而热模型用：

```text
nodeId = deviceIndex / 1000
```

推导温度节点。因此 router id 0-15 都会映射到 0，导致 SOA gain degradation 使用错误温度。

现在 `OpticalDeviceSegment` 新增：

```text
hostNodeId
```

所有光器件 segment 显式记录所属 PE/router。SOA 的 `hostNodeId` 设为驱动该 hop 的 router，与 SOA pump power 热注入位置保持一致。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/control/LogicalTopologyManager.cc`

## 9. MRR thermal detuning 与 tuning power 物理口径修复

已修复 ring detuning loss 与 tuning power 同时完整叠加的问题。

原逻辑中，MRR 在温度偏移时同时：

- 添加 detuning excess insertion loss
- 添加 heater tuning power

这会造成物理解释不自洽：如果 heater 已经用于补偿热漂移，就不应再保留完整未补偿 detuning loss，除非显式建模 residual detuning。

现在口径调整为：

- `tuningEfficiency_mW_per_nm > 0` 时，认为 heater 补偿 detuning，只累计 tuning power 和 max detuning，不再叠加完整 ring detuning loss。
- `tuningEfficiency_mW_per_nm <= 0` 时，认为不进行热调谐补偿，才使用 `ringIL_TempCoeff_dB_per_K × |deltaT|` 作为未补偿 residual loss。
- ring tuning power 按物理 ring 去重，不再因多 wavelength budget loop 重复累计。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.cc`

## 10. Router through-count API 修复

已修复 `RouterTurnMetadata.throughCount` 字段语义混乱的问题。

原逻辑中，`throughCount` 注释表示“through ring 数量”，但实际存储的是 formula type。`LogicalTopologyManager` 里又重复实现一套公式 switch，容易造成公式分叉和维护错误。

现在结构调整为：

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

## 11. Crosstalk 聚合与单位口径修复

已修复 crosstalk 使用 dB/dBm 混合语义的问题。

原逻辑中，`accumulatedCrosstalk_dB` 以 dB sentinel 初始化，但实际更新时存的是单个 segment 的 crosstalk power dBm，并且只保留最大值；与此同时 SNR 使用线性噪声功率求和。这样导出的 `totalCrosstalk_dB` 与 per-wavelength crosstalk 字段语义不清。

现在 crosstalk 计算改为：

```text
各器件 crosstalk noise power 先按 mW 线性求和
最终再转换为 dBm 输出
```

为了兼容历史字段，旧字段仍保留：

- `totalCrosstalk_dB`
- `perWavelengthCrosstalk_dB`

但新增更准确的新字段：

- `totalCrosstalkNoise_dBm`
- `perWavelengthCrosstalkNoise_dBm`

后续论文或结果表述应优先使用 `*_CrosstalkNoise_dBm` 口径。

涉及文件：

- `src/onoc/common/OpticalDeviceModel.h`
- `src/onoc/common/OpticalDeviceModel.cc`
- `src/onoc/common/OpticalPathMetrics.h`
- `src/onoc/control/LogicalTopologyManager.cc`

## 12. Optical budget cache 释放修复

已修复 optical path release 后 cached budget 未同步清理的问题。

原逻辑中 `releaseOpticalPathForPacket()` 只删除 `opticalPacketAllocations`，但 `cachedBudgets[pktId]` 会保留。长仿真或 token 复用时可能读到 stale metrics。

现在 release 时同步执行：

```text
cachedBudgets.erase(pktId)
```

涉及文件：

- `src/onoc/control/LogicalTopologyManager.cc`

## 13. 光路由器修复验证

本轮光路由器修复后已做过以下验证：

- `make MODE=release -j4` 编译通过。
- 临时 C++ 单元测试通过，覆盖：
  - router through-count 公式求值
  - per-wavelength loss 过滤
  - ring tuning power 物理 ring 去重
  - `hostNodeId` 温度归属
  - compensated / uncompensated detuning 分支
- OMNeT++ evaluator smoke 通过，GEMM baseline 可正常生成：
  - `makespan_s`
  - PE 温度向量
  - `optical_budget_count`
  - `optical_min_snr_dB`
  - `optical_max_waveguide_crossing_loss_dB`

临时 C++ 测试源码、测试 exe 和临时测试结果均已删除。

## 14. 热模型与 DVFS 修复验证

本轮修复后已做过以下验证：

- `make -j2` 编译通过。
- VOPD smoke 仿真可正常生成 makespan、温度、sigma、hot count 和能耗指标。
- 强制 DVFS 微测试确认 150 ns nominal task 在 throttling 后约 166 ns 完成，不再被推迟到 200 ns 整 tick。
- 保留结果的临时仿真确认 `allTrafficDrainedAt` 大于 `allTasksCompletedAt`，并且 snapshot 包含 16 个 PE 和 16 个 router 温度。
- snapshot fallback 单独测试确认可计算 `Tmax`、`sigma_T`、`N_hot`。

临时测试目录和临时 `thermal_snapshot.json` 均已删除。
