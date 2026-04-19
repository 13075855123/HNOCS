# HNOCS 到 ONoC 改造清单（实施版）

本文件用于指导你在 HNOCS 基础上逐步改造成支持 ONoC 的仿真平台，覆盖以下目标：

1. 在 Torus 基础上实现运行时可重构，支持生成 mesh、ring、star、tree 逻辑拓扑
2. 引入 Lumerical 光器件参数，验证端到端约 30Gbps 传输能力
3. 支持人工或脚本故障注入，实现 10ms 检测与备用节点替换或路径重构自恢复

---

## 0. 总体改造原则

1. 保留 HNOCS 的模块化装配机制（NED 接口 + 可替换模块）
2. 不依赖运行时物理断线重连，采用逻辑链路状态矩阵控制可达性
3. 将电层与光层解耦：
   - 电层负责控制面（重构、探测、恢复）
   - 光层负责数据面（传输、误码、器件状态）
4. 优先实现最小可行版本，再逐步增加精细模型

---

## 1. 工程文件级改造清单

### 1.1 可复用文件（保留为接口或框架）

- src/cores/NI_Ifc.ned
- src/routers/Router_Ifc.ned
- src/routers/Port_Ifc.ned
- src/routers/hier/opCalc/OPCalc_Ifc.ned
- src/routers/hier/vcCalc/VCCalc_Ifc.ned

说明：这些文件定义了模块接口，不强绑定电互连语义，可作为 ONoC 的装配骨架继续使用。

### 1.2 需要重点改造文件（第一优先级）

- src/topologies/Mesh.ned
  - 新增或旁路为 ONoC 拓扑入口
  - 支持 Torus 候选邻接关系定义
- src/NoCs.msg
  - 增加 ONoC 控制与状态消息
- src/routers/hier/opCalc/static/XYOPCalc.cc
  - 改造为拓扑可重构感知路径选择
- src/routers/hier/sched/wormhole/SchedSync.cc
  - 适配光链路可用性与退化状态
- src/cores/sources/PktFifoSrc.cc
  - 增加速率目标和误码注入相关统计

### 1.3 建议新增文件（建议新建目录）

建议新增目录：

- src/onoc/topologies/
- src/onoc/link/
- src/onoc/control/
- src/onoc/routing/
- src/onoc/fault/

建议新增模块：

1. ONoCTorus.ned
   - ONoC 主拓扑网络，持有全网节点、链路和控制子模块
2. OLinkStateManager.cc/.h
   - 维护链路状态矩阵 A(t) 与链路代价矩阵 W(t)
3. OReconfigController.cc/.h
   - 接收脚本或命令，触发拓扑模式切换
4. ORingResonatorModel.cc/.h
   - 微环模型，支持正常、失谐、故障、旁路状态
5. OOpticalLinkModel.cc/.h
   - 光链路模型，按参数计算有效速率、时延、误码
6. OAdaptiveOPCalc.cc/.h
   - 可重构路由器输出端口计算模块
7. OFaultDetector.cc/.h
   - 故障探测（心跳、超时）与告警管理
8. ORecoveryManager.cc/.h
   - 备用节点替换或路径重构恢复执行

---

## 2. 消息与参数扩展清单

## 2.1 在 NoCs.msg 增加消息类型

建议新增类型：

1. NOC_RECONF_CMD_MSG
   - 重构命令（目标拓扑、执行时刻、作用范围）
2. NOC_LINK_STATE_MSG
   - 链路状态上报（up、down、degraded）
3. NOC_RING_STATE_MSG
   - 微环状态上报（ok、detuned、failed、bypass）
4. NOC_HEARTBEAT_MSG
   - 节点心跳
5. NOC_FAULT_ALARM_MSG
   - 故障告警
6. NOC_RECOVERY_CMD_MSG
   - 恢复命令（替换节点或重路由）
7. NOC_RECOVERY_ACK_MSG
   - 恢复完成确认

## 2.2 新增全局参数（omnetpp.ini）

1. onoc.enable = true
2. onoc.baseTopology = torus
3. onoc.reconfigMode = manual 或 script
4. onoc.targetTopology = mesh 或 ring 或 star 或 tree
5. onoc.detector.timeout = 10ms
6. onoc.recovery.strategy = spare_first 或 reroute_first
7. onoc.optics.paramFile = 光器件参数文件路径
8. onoc.optics.targetRate = 30Gbps

---

## 3. 分阶段实施计划（建议按顺序执行）

## 阶段 A：最小可行 ONoC 骨架

目标：先跑通 ONoC 基础网络与可重构控制闭环。

任务：

1. 新建 ONoCTorus.ned，复用现有 Router_Ifc 与 NI_Ifc 装配方式
2. 接入 OLinkStateManager，支持 A(t) 动态更新
3. 用简单控制命令实现 mesh/ring/star/tree 四种模式切换
4. 增加基础统计：重构耗时、切换前后可达率

验收：

1. 不重启仿真可切换拓扑
2. 切换后拓扑连接关系与预期一致
3. 基础流量可继续传输

## 阶段 B：光层参数接入与 30Gbps 验证

目标：将 Lumerical 数据接入传输模型并完成吞吐验证。

任务：

1. 定义参数文件格式（CSV 或 JSON）
2. 在 OOpticalLinkModel 中读取参数并映射到链路行为
3. 建立 BER 驱动的 flit 错误或丢弃机制
4. 增加端到端吞吐、时延、误码统计

验收：

1. 目标业务流下端到端吞吐接近 30Gbps
2. 统计输出中可区分理论速率与有效吞吐
3. 参数变化可影响性能指标，趋势合理

## 阶段 C：故障检测与自恢复

目标：实现节点或微环故障后的 10ms 检测与恢复。

任务：

1. 实现 OFaultDetector 心跳探测
2. 支持手动与脚本故障注入（节点故障、微环故障）
3. 实现 ORecoveryManager 两类策略：
   - 备用节点替换
   - 路径重构
4. 记录检测时延与恢复时延

验收：

1. 故障可在 10ms 内触发告警
2. 恢复后业务恢复并可持续运行
3. 恢复失败有明确事件日志与原因

## 阶段 D：联合场景与论文级实验

目标：可重构、光参数扰动、故障恢复并发场景下稳定评估。

任务：

1. 设计联合实验矩阵（规模、负载、故障类型、重构策略）
2. 固化脚本与随机种子，保证可复现实验
3. 导出关键图表：吞吐、时延、恢复率、检测时延、丢包率

验收：

1. 实验可复现
2. 指标齐全，可支撑论文或报告结论

---

## 4. 路由与调度改造建议

1. 路由从固定 XY 升级为代价感知路径选择
2. 代价项建议包括：
   - 链路时延
   - 光损耗
   - 误码风险
   - 故障风险
3. 调度器在下发 grant 前检查链路状态，避免向故障路径发包
4. 对 degraded 链路引入降权机制而非立即禁用

---

## 5. 故障注入与恢复脚本建议

1. 提供手动注入参数：
   - 节点 ID
   - 微环 ID
   - 注入时间
   - 故障持续时间
2. 提供脚本批量注入：
   - 周期注入
   - 泊松注入
   - 指定场景注入
3. 恢复策略选择：
   - spare_first：先启用备用节点
   - reroute_first：先路径重构
4. 记录事件链：故障发生时间、检测时间、恢复触发时间、恢复完成时间

---

## 6. 统计指标清单（必须实现）

1. end_to_end_throughput_gbps
2. end_to_end_latency_ns
3. bit_error_rate
4. packet_loss_rate
5. reconfiguration_time_us
6. fault_detection_time_ms
7. recovery_time_ms
8. post_recovery_throughput_ratio
9. topology_reachability_ratio

---

## 7. 第一轮最小实验建议

实验 1：基础可重构

1. 4x4 Torus 初始
2. 0.5ms 切到 ring
3. 1.0ms 切到 tree
4. 验证可达性与吞吐连续性

实验 2：30Gbps 验证

1. 固定拓扑，读取一组 Lumerical 参数
2. 扫描注入负载
3. 输出吞吐和时延曲线

实验 3：故障与恢复

1. 0.8ms 注入节点故障
2. 要求 10ms 内检测
3. 启动备用节点或重路由
4. 统计恢复时延与恢复后吞吐

---

## 8. 开发执行顺序（可直接照做）

1. 先完成阶段 A，保证框架跑通
2. 再接阶段 B，完成光参数闭环
3. 然后做阶段 C，实现故障检测与恢复
4. 最后阶段 D，批量实验与结果固化

---

## 9. 每周推进检查表

第 1 周：

1. ONoC 目录骨架搭建完成
2. ONoCTorus 可运行
3. 拓扑切换命令可触发

第 2 周：

1. 光参数文件格式确定
2. OOpticalLinkModel 接入并生效
3. 30Gbps 验证场景可跑通

第 3 周：

1. 故障注入与告警链路打通
2. 10ms 检测可观测
3. 恢复策略可执行

第 4 周：

1. 联合实验自动化
2. 指标导出与图表脚本完成
3. 输出阶段总结与下一轮优化点

---

## 10. 注意事项

1. 若 OMNeT++ 版本较新，注意旧 NED 参数自引用写法兼容性
2. 先做逻辑重构，再考虑精细物理层效应，避免过早复杂化
3. 先把统计口径定义清晰，再跑大规模实验
4. 每新增机制都要有最小可复现实验

---

## 11. 里程碑定义

M1：可重构 ONoC 骨架可运行
M2：完成光参数接入并实现接近 30Gbps 的端到端验证
M3：实现 10ms 故障检测与自动恢复
M4：联合场景实验稳定并可复现

---

如需继续推进，下一步建议先落地阶段 A 的三项最小改动：

1. 新建 ONoCTorus.ned
2. 新建 OLinkStateManager
3. 将现有 OP 计算替换为可读取链路状态的模块
