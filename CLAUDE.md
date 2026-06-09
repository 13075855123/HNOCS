# HNOCS — 光电混合 NoC 仿真器 (OMNeT++ 6.3.0)


## 终端测试命令

```bash
# 构建（debug 模式用于开发；release 模式用于实验，快 2-5×）
cd /d/HNOCS
make MODE=release -j8   # 产出 libhnocs.exe (Release, ~2MB)
# make MODE=debug -j8   # 产出 libhnocs_dbg.exe (Debug, ~26MB)

# 运行（从 examples/task_driven 目录执行，CSV 文件在此目录）
cd examples/task_driven
../../libhnocs.exe -u Cmdenv -n "../../src;." -c ONoC_Optic omnetpp.ini
```

---

## B-2 热感知任务映射实验流程

### 概述

实验分为两个阶段：

- **阶段一**：B-2 遗传算法优化任务映射。GA 适应度评估直接调用 OMNeT++ 光-电混合仿真器，代价函数基于 `.sca` / `.vec` 实测数据。产出 `_remapped.csv` 和 `_metrics.json`（8 项论文指标）。
- **阶段二**（可选）：将 `_remapped.csv` 喂入 OMNeT++ 独立验证，产出 `.sca` / `.vec` 结果文件。

两个阶段使用同一套物理参数（RC 热网络、DVFS 阈值、光学预算），通过 `Experiment/mapping/omnet_cost_model.py`
中的 `SimParams` 默认值与 OMNeT++ 侧 `omnetpp.ini` 中的 `[ONoCGeneral]` 配置段保持对齐。

---

### 阶段一：B-2 遗传算法优化

#### 运行命令

```bash
# 单个基准
python Experiment/B-2/run.py --csv examples/task_driven/static/tasks_gemm_static.csv \
    --population 50 --generations 30 --workers 8 -v

# 全部 5 个基准
python Experiment/B-2/run.py --all --workers 8 --generations 30 -v -o out/B-2/
```

#### 参数

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `--omnet-bin` | `D:/HNOCS/libhnocs.exe` | OMNeT++ 可执行文件 |
| `--omnet-ned-paths` | `/d/HNOCS/src;/d/HNOCS/examples/task_driven` | NED 搜索路径 |
| `--omnet-workdir` | `/d/HNOCS/examples/task_driven` | OMNeT++ 工作目录 |
| `--omnet-ini` | `.../examples/task_driven/omnetpp.ini` | 基础 INI 文件 |
| `--omnetpp-root` | `/d/omnetpp/omnetpp-6.3.0` | OMNeT++ 安装根目录（供 opp_scavetool） |
| `--omnet-timeout` | 60.0 | 单个仿真超时 (秒) |

#### 完整工作流程（每个基准）

**步骤 1 — 加载任务图**

- `TaskGraph.from_csv(csv_path)` → DAG
- `baseline_asgn` = 提取静态 peId（基线）
- `_make_mappable(graph)`：全部 peId 置为 -2

**步骤 2 — 基线 OMNeT++ 仿真（1 次）**

`OmnetEvaluator.evaluate(graph, baseline_asgn)`：
1. 写临时 CSV + 临时 INI（`extends=ONoCGeneral`）
2. `subprocess: libhnocs.exe -u Cmdenv -c GA_<uuid>`
   - TaskPE×16 + Router + OpticalCircuitController + ThermalTrace (32节点 RC 热网络, dt=100ns)
   - 产出 `.sca` / `.vec` / `thermal_snapshot.json`
3. `_parse_sca(.sca)` → makespan, `throttlePenaltyRatio[16]`, `totalEnergyJ[16]`, SOA/tuning/laser 能耗
4. `_parse_vec_via_scavetool(.vec)` → `opp_scavetool export -F JSON` → `pe-die-temperature[16]` → **T_max(真峰值)**, **σ_T**, **N_hot**
5. `rmtree(临时目录)` ← 清理所有仿真产物

产出: T_max, σ_T, N_hot, makespan, η_dvfs, E_total（8项指标基线值）

**步骤 3 — GA 优化（50个体 × 30代）**

`GAMapper.run(seed_assignment=baseline_asgn)`：

- **初始化种群**：个体0 = 基线；个体1~49 = 随机 + 变异
- **每代循环**（支持 `ProcessPoolExecutor` 并行）：

  **适应度评估**（每个个体独立调用）：
  1. `chromosome → assignment = {task_id: pe_id}`
  2. `OmnetEvaluator.evaluate(graph, assignment)` → `OmnetScalars`
  3. `OmnetCostModel.total_cost(assignment, scalars)` → fitness

  **代价函数**（与 Python 模式同权重接口）：

  ```
  fitness = w_T × f_thermal + w_H × f_comm + w_D × f_dvfs + w_L × f_load

  f_thermal = (T_max - 318.15) / (327.15 - 318.15)    ← .vec 真峰值
  f_comm    = Σ(hops × dataSize) / max_possible         ← 解析计算
  f_dvfs    = η_dvfs% / 100 × num_mappable              ← .sca per-PE 平均
  f_load    = var(per-PE负载) / ideal²                   ← 解析计算
  ```

  **遗传操作**：记录最优/平均 fitness → 早停检测 → 精英保留 + 锦标赛选择 + 均匀交叉 + 逐任务变异

- 产出: `GAResult { best_assignment, best_fitness, generation_history }`

**步骤 4 — 最优映射验证（1 次）**

`OmnetEvaluator.evaluate(graph, best_assignment)` → b2_scalars

产出: b2_T_max, b2_σ_T, b2_N_hot, b2_makespan, b2_η_dvfs, b2_E_total

**步骤 5 — 输出文件（写入 `out/B-2/`）**

| 文件 | 内容 |
|------|------|
| `{name}_remapped.csv` | 最优映射（可喂给阶段二独立验证） |
| `{name}_metrics.json` | baseline vs B-2 全 8 项论文指标对比 |
| `{name}_history.json` | 逐代 fitness / T_max 收敛曲线 |
| `{name}_summary.txt` | 人类可读摘要 |

> OMNeT++ 模式总仿真次数 ≈ 2 + 种群×有效代数（早停后更少）。以 pop=50, 8 并行计算，约需 30~60 分钟完成全部 30 代。

#### 新增文件

| 文件 | 职责 |
|------|------|
| `Experiment/mapping/omnet_cost_model.py` | `OmnetScalars` + `OmnetCostModel`：基于 .sca/.vec 聚合标量计算适应度 |
| `Experiment/mapping/omnet_evaluator.py` | `OmnetEvaluator`：管理 OMNeT++ 子进程、临时文件、.sca/.vec 解析 |
| `Experiment/B-2/ga_mapper.py` | + `evaluate_fitness_omnet()`, `OmnetGAConfig`, OMNeT++ 评估路由 |
| `Experiment/B-2/run.py` | CLI 入口, OMNeT++ 模式基线/指标计算 |

---

### 阶段二：OMNeT++ 完整仿真（可选）

#### 5. 部署重映射 CSV

将阶段一产出的 `remapped.csv` 复制到 `examples/task_driven/mapping/` 目录下：

```bash
cp out/B-2/gemm/remapped.csv examples/task_driven/mapping/tasks_gemm_b2.csv
```

#### 6. OMNeT++ 运行命令

```bash
cd examples/task_driven

# 静态基线仿真
opp_run -u Qtenv -c ONoC_GEMM    omnetpp.ini

# B-2 重映射仿真
opp_run -u Qtenv -c ONoC_GEMM_B2 omnetpp.ini

# 批量（5 个基准）
for cfg in ONoC_GEMM ONoC_VOPD ONoC_MPEG4 ONoC_Optic ONoC_HNN \
           ONoC_GEMM_B2 ONoC_VOPD_B2 ONoC_MPEG4_B2 ONoC_Optic_B2 ONoC_HNN_B2; do
    opp_run -u Cmdenv -c $cfg omnetpp.ini
done
```

`omnetpp.ini` 中每个 config 段只覆盖 `**.csvFile`，其余参数继承 `[ONoCGeneral]`：

```ini
[ONoC_GEMM]
extends = ONoCGeneral
**.csvFile = "static/tasks_gemm_static.csv"

[ONoC_GEMM_B2]
extends = ONoCGeneral
**.csvFile = "mapping/tasks_gemm_b2.csv"
```

#### 7. OMNeT++ 仿真器内部做了什么

```
TaskGraphParser 解析 CSV → 构建 DAG
  │
  ├─ TaskPE[0..15]: 执行任务
  │   ├─ 计算功耗: powerCompute × compute_time + 泄漏修正 exp((T-Tamb)/15)
  │   ├─ DVFS 降频: T > Tthrottle(54°C) → compute_time *= (1+0.1×(T-Tthr))
  │   └─ 发包: 按 successorPE 通过 NoC 发给下游 PE 或 GlobalBuffer
  │
  ├─ Router + OpticalCircuitController:
  │   ├─ 电层: XY 路由, Wormhole 交换, FLU VC 分配
  │   ├─ 光层: SETUP 握手 → 波长分配(lowest-available) → 电路建立
  │   │        8λ WDM × 2 空间通道, 256 Gbps/λ
  │   │        微环热调谐, SOA 放大(80mW), 激光器 WPE=20%
  │   └─ 光旁路: 已建立的光路跳过电层路由器
  │
  ├─ GlobalBuffer: 片外 DRAM 读写
  │
  └─ ThermalTrace: 双层 RC 热网络
       32 节点（16 PE + 16 Router）, 显式欧拉 dt=100ns
       Rconv/Rlateral/Rpe2router, Cpe/Crouter
       温度反馈 → 影响泄漏功耗 → 影响 DVFS → 影响调度时序
       → 写入 .sca（标量）/ .vec（向量）文件到 results/
```

#### 8. 结果提取

OMNeT++ 产出文件位于 `examples/task_driven/results/`：

| 文件 | 内容 |
|------|------|
| `ONoC_GEMM_B2-#0.sca` | 标量：各 PE 温度峰值/均值、总能耗、SOA 能耗、DVFS 事件数、完成时间 |
| `ONoC_GEMM_B2-#0.vec` | 向量：PE/Router 温度时间序列、flit 延迟、光路建立/拆除事件 |
| `ONoC_GEMM_B2-#0.vci` | 索引文件 |

从 `.sca` / `.vec` 提取 8 个论文指标，与阶段一的 `_metrics.json` 交叉验证。

---

### 完整数据流

**阶段一：GA 优化**

```
tasks_gemm_static.csv → TaskGraph → run_benchmark()
                                       │
                          OmnetEvaluator.evaluate()
                            → subprocess: OMNeT++ 仿真
                            → _parse_sca(.sca)
                            → _parse_vec_via_scavetool(.vec)
                            → OmnetCostModel.total_cost()
                                       │
                          数据源:
                            .vec → T_max, σ_T, N_hot
                            .sca → makespan, η_dvfs, E_*
                                       │
                          50个体×30代 → 选择/交叉/变异
                                       │
                              {name}_remapped.csv
                              {name}_metrics.json  (8项论文指标)
                              {name}_history.json
                              {name}_summary.txt
```

> 指标已直接产出，阶段二可选（独立验证）

**阶段二：OMNeT++ 完整仿真**（可选）

```
omnetpp.ini → ONoC_GEMM_B2 config
  ├─ TaskGraphParser 解析 tasks_gemm_b2.csv
  ├─ TaskPE×16: 事件驱动任务执行 + 发包
  ├─ LogicalTopologyManager: 波长分配 + 热调谐
  ├─ OpticalCircuitController: SETUP/ACK 光路管理
  ├─ ReconfigurableOPCalc: 光路感知路由
  ├─ GlobalBuffer: 片外 DRAM
  └─ ThermalTrace: RC 热网络 (32节点, 100ns步长)

  产出: results/ONoC_GEMM_B2-#0.sca, .vec, .vci

  提取 8 论文指标，与阶段一 _metrics.json 交叉验证:
  T_max, σ_T, N_hot, t_makespan, η_dvfs, E_SOA, E_tune, E_total
```

### 参数一致性保证

Python 侧 `SimParams`（`Experiment/mapping/thermal_simulator.py`）与 OMNeT++ 侧 `[ONoCGeneral]`（`omnetpp.ini`）逐项对应：

| 参数 | Python | OMNeT++ | 含义 |
|------|--------|---------|------|
| 网格 | `rows=4, cols=4` | `**.rows=4, **.columns=4` | 4×4 Mesh |
| RC热阻 | `RconvPE=8, RconvRouter=10, RlateralPE=10, RlateralRouter=10, Rpe2router=3` | 同 | 热网络 |
| 热容 | `Cpe=1e-6, Crouter=1e-7` | 同 | 热网络 |
| 温度 | `Tambient=318.15, Tthrottle=327.15` | 同 | 环境 45°C, 降频 54°C |
| 功耗 | `powerIdle=0.3, powerCompute=2.5` | 同 (W) | PE 功耗模型 |
| DVFS | `throttleBeta=0.1` | 同 | 10%/°C 降频系数 |
| 光层 | Python GA 不使用 | 8λ, 2 空间通道, 256Gbps/λ | OMNeT++ 专属 |

Python GA 阶段不使用光层仿真，因为 GA 适应度评估只需温度+时序信息。
光层行为（波长分配、微环调谐、SOA 能耗、激光器效率）仅在 OMNeT++ 阶段完整模拟。

---

## 论文对比指标定义

全部方向 ↓（越小越好）。覆盖**热 → 性能 → 能耗**三条因果链。

### 第一梯队 — 论文核心叙事，缺一不可

| 符号 | 中文名称 | 单位 | 定义 | 为什么重要 |
|:---:|------|:---:|------|------|
| **$T_{\max}$** | 芯片峰值温度 | °C | $\max_{i,t} T_{\text{PE}_i}(t) - 273.15$ | **热安全**：峰值温度不降，热重映射就失败了 |
| **$\sigma_T$** | 温度标准差 | K | $\sqrt{\frac{1}{N_t N_{\text{PE}}} \sum_t \sum_i (T_i(t) - \bar{T})^2}$ | **热均衡的核心量化** |
| **$t_{\text{makespan}}$** | 任务完成时间 | μs | $\text{simTime()} \times 10^6$ | **性能**：证明热均衡不损害甚至提升性能 |
| **$E_{\text{total}}$** | 系统总能耗 | mJ | $(E_{\text{PE}} + E_{\text{SOA}} + E_{\text{tune}} + E_{\text{laser}}) \times 10^{3}$ | **综合代价**：降温付出了多少能耗代价 |

### 第二梯队 — 强化论证

| 符号 | 中文名称 | 单位 | 定义 | 为什么重要 |
|:---:|------|:---:|------|------|
| **$N_{\text{hot}}$** | 过热PE数 | 个 | $\mid\{i \mid \max_t T_i(t) > 327.15\text{K}\}\mid$ | **过热范围**：DVFS 触发面有多大 |
| **$\eta_{\text{dvfs}}$** | 平均DVFS节流比 | % | $\frac{1}{16}\sum_{i} \frac{t_{\text{actual},i} - t_{\text{nominal},i}}{t_{\text{nominal},i}} \times 100\%$ | **热→性能传导**：过热导致百分之多少性能损失 |
| **$E_{\text{SOA}}$** | SOA泵浦能耗 | μJ | $\sum_{\text{circuits}} n_{\text{SOA}} \cdot 80\text{mW} \cdot t_{\text{circuit}}$ | **光层能耗主力**：占光通信能耗 40-60% |

### 第三梯队 — 支撑性

| 符号 | 中文名称 | 单位 | 定义 | 为什么重要 |
|:---:|------|:---:|------|------|
| **$E_{\text{tune}}$** | 微环动态调谐能耗 | nJ | $\sum_c \sum_{r \in \text{path}(c)} \text{ringCount}_r \cdot 0.5\frac{\text{mW}}{\text{nm}} \cdot 0.10\frac{\text{nm}}{\text{K}} \cdot \mid T_r - T_{\text{amb}}\mid \cdot t_c$ | **光层能耗次要项**：间接反映热均衡效果 |

> **注意**：$E_{\text{PE}}$ 已包含光收发器（调制器 25pJ + 接收器 15pJ），$E_{\text{total}}$ 中不再另加 $E_{\text{TRX}}$。路由器端口能耗因 <5% 且 Python 仿真器未跨窗口累加，统一排除。

### 指标数据来源

| 指标 | OMNeT++ 来源 | 解析方法 |
|------|-------------|---------|
| $T_{\max}$ | `.vec` 矢量 `pe-die-temperature` | `opp_scavetool export -F JSON` → 取所有 PE 所有时刻最大值 |
| $\sigma_T$ | `.vec` 矢量 `pe-die-temperature` | 同上，所有 PE 所有时刻展平求标准差 |
| $N_{\text{hot}}$ | `.vec` 矢量 `pe-die-temperature` | 同上，per-PE 峰值超 327.15K 计数 |
| $t_{\text{makespan}}$ | `.sca` 标量 `allTasksCompletedAt` | 直接读取（取 max） |
| $\eta_{\text{dvfs}}$ | `.sca` 标量 `throttlePenaltyRatio`（16 PE 均值） | 收集每个 PE 的 ratio，求平均 × 100% |
| $E_{\text{PE}}$ | `.sca` 标量 `TaskPE.totalEnergyJ`（16 PE 求和，排除 InPortSync） | 直接求和 |
| $E_{\text{SOA}}$ | `.sca` 标量 `onoc-soa-total-energy-J`（LTM 全局） | 直接读取 |
| $E_{\text{tune}}$ | `.sca` 标量 `onoc-dynamic-tuning-total-energy-J`（LTM 全局） | 直接读取 |
| $E_{\text{laser}}$ | `.sca` 标量 `onoc-laser-total-energy-J`（LTM 全局） | 直接读取 |
| $E_{\text{total}}$ | 求和 × 1e3 (J→mJ) | $E_{\text{PE}} + E_{\text{SOA}} + E_{\text{tune}} + E_{\text{laser}}$ |

---

## 项目概述

4×4 Mesh ONoC，16 TaskPE + 16 光路由器 + 1 GlobalBuffer。控制面走电路由器（SETUP_REQ→SETUP_ACK），数据面走 `sendDirect()` 光旁路直传。5×5 微环光路由器：20 交叉点 × 8 WDM 波长 = 160 微环/路由器。C-band 8λ: 1544.53–1555.75 nm (ITU-T 200GHz grid)。

### 动态热调谐（Per-Router 独立计算）

各路由器独立查询自身温度计算调谐功率，不依赖 budget 汇总值：

```
ringCount_i = throughCount(formulaType, maxWl, totalWL) + numActiveWL   (路由器转向)
if src: ringCount_i += maxWl     (NI 调制器，共享链 ring 1..maxWl)
if dst: ringCount_i += maxWl     (NI 解调器)
P_i = ringCount_i × 0.5mW/nm × 0.10nm/K × abs(T_i − 318.15K)
```

`throughCount` 从 6 种 formula type 推导（见 `routerTurnMatrices[inPort][outPort]`），静态基线已关闭。

---

## 关键参数

| 参数 | 值 | 参数 | 值 |
|------|----|------|----|
| flitSize | 16B | 光路带宽 | 2λ×256Gbps=512Gbps |
| PE 空闲/计算 | 0.3W / 2.5W | 电层带宽 | 16Gbps |
| T_throttle | 327.15K (54°C) | DVFS | 1+0.1×(T−54°C) @ T>54°C |
| T_ambient | 318.15K (45°C) | SOA 泵浦 | 80mW/器件 |
| 微环/路由器 | 160 (20×8) | 全芯片 | 2560 微环 |
| 热光系数 | 0.10 nm/K | 调谐效率 | 0.5 mW/nm |
| C_pe / C_router | 1e-6 / 1e-7 J/K | R_pe2router | 3 K/W |

---

## 源文件结构

```
src/
├── cores/task/       TaskPE, PowerTrace         — PE 核心（握手+DVFS+能耗）
├── routers/hier/     InPort, OPCalc, Sched      — Wormhole 电路由器
├── onoc/control/     LogicalTopologyManager     — 波长分配、拓扑管理、热调谐
├── onoc/optical/     OpticalCircuitController   — 光路建链/拆链
├── onoc/routing/     ReconfigurableOPCalc       — 光路感知路由
├── onoc/common/      OpticalDeviceModel         — 器件级光链路预算（微环/SOA/PD）
├── thermal/          ThermalTrace               — 双层 RC 热求解器
├── globalbuffer/     GlobalBuffer               — 片外 DRAM 接口
└── utils/            TaskGraphParser             — CSV 任务图解析
```

---

## 关键文件

| 组件 | 文件 |
|------|------|
| 波长分配 + 热调谐 | `src/onoc/control/LogicalTopologyManager.cc` |
| 器件级预算模型 | `src/onoc/common/OpticalDeviceModel.cc` `.h` |
| PE 核心 | `src/cores/task/TaskPE.cc` |
| RC 热模型 | `src/thermal/ThermalTrace.cc` |
| 光路由矩阵 | `src/onoc/common/OpticalDeviceModel.cc:89-128` (formulaType/bendCount) |
| 路由器能耗 | `src/routers/hier/inPort/InPortSync.cc` |
| 配置文件 | `examples/task_driven/omnetpp.ini` |
| 设计文档 | `paper/20260530.md` |

---

## 光旁路数据流

```
Task完成 → data flit 进 pendingDataQ
  → SETUP_REQ (电路由器) → dst PE
  → SETUP_ACK (电路由器) → src PE
  → circuitReady → flushPendingData → opticalDataQ
  → sendDirect(flit, opticalIn)   ← 光路直传
  → END flit → TEARDOWN → 释放波长 + 累计 SOA/调谐能耗
```

---

## 微环转向 through-count 公式

端口：0=Local, 1=West, 2=North, 3=East, 4=South。n=8 波长, i 为波长索引：

| 方向组 | Formula | 最长(i=8) |
|--------|:---:|:---:|
| L→W, W→S, N→L, E→N | Type 0: i−1 | 8 |
| L→S, N→W, E→L, S→E | Type 1: 2n+i−1 | 24 |
| L→N, L→E, W→L, S→L | Type 2: 3n+i−1 | 32 |
| W→E, N→S, E→W, S→N | Type 3: 4n | 33 |
| W→N, E→S | Type 4: 4n+i−1 | 40 |
| N→E, S→W | Type 5: 6n+i−1 | **56** |
