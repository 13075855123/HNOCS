# HNOCS: 异构片上网络模块化开源仿真器

## 📖 项目概述

HNOCS (Heterogeneous Network-on-Chip Simulator) 是一个基于 OMNeT++ 的开源片上网络 (NoC) 仿真框架。该项目由以色列理工学院电气工程系开发，主要用于研究和评估片上网络架构。

### 主要特点

- **模块化设计**：利用 OMNeT++ 的模块接口特性，支持在运行时从参数化组件库中选择仿真模块
- **异构支持**：支持链路容量和虚拟通道(VC)数量不同的异构NoC配置
- **虫洞交换**：实现了虫洞(Wormhole)交换机制
- **多种仲裁策略**：支持轮询(Round-Robin)和胜者通吃(Winner-Takes-All)仲裁方式
- **同步/异步模式**：提供同步和异步两种路由器设计

### 相关论文

> Y. Ben-Itzhak, E. Zahavi, I. Cidon, and A. Kolodny, "HNOCS: Modular Open-Source Simulator for Heterogeneous NoCs", SAMOS XII: International Conference on Embedded Computer Systems: Architectures, Modeling and Simulation, 2012

---

## 🚀 快速开始

### 环境要求

- **OMNeT++** 4.x 或更高版本
- **C++ 编译器** (GCC 或 MSVC)
- **Make 工具**

### 安装步骤

#### 1. 安装 OMNeT++

首先确保已安装 OMNeT++，并将 `<omnet-home-dir>/bin` 添加到系统 PATH 环境变量中。

#### 2. 编译 HNOCS

```bash
# 进入项目根目录
cd HNOCS-master

# 生成 Makefile
make makefiles

# 编译项目
make
```

#### 3. 运行示例仿真

```bash
# 使用图形界面运行示例
./examples/run_nocs

# 或者直接进入示例目录运行
cd examples/async/4x4
./run
```

---

## 📁 项目目录结构

```
HNOCS-master/
├── src/                          # 源代码目录
│   ├── cores/                    # 网络接口模块
│   │   ├── sources/              # 数据包生成器（流量源）
│   │   │   └── PktFifoSrc.*      # 基于FIFO的数据包源
│   │   └── sinks/                # 数据包收集器（流量汇）
│   │       └── InfiniteBWMultiVCSink.*  # 无限带宽多VC接收器
│   │
│   ├── routers/                  # 路由器模块
│   │   └── hier/                 # 层次化路由器
│   │       ├── inPort/           # 输入端口模块
│   │       │   ├── InPortAsync.* # 异步输入端口
│   │       │   └── InPortSync.*  # 同步输入端口
│   │       ├── opCalc/           # 输出端口计算（路由算法）
│   │       │   └── static/       # 静态/确定性路由
│   │       │       └── XYOPCalc.*# XY维序路由
│   │       ├── sched/            # 调度器/仲裁器
│   │       │   └── wormhole/     # 虫洞交换调度
│   │       │       ├── SchedAsync.* # 异步调度器
│   │       │       └── SchedSync.*  # 同步调度器
│   │       └── vcCalc/           # VC分配器
│   │           └── free/         # 空闲VC分配
│   │               └── FLUVCCalc.* # FLU VC分配器
│   │
│   ├── topologies/               # 网络拓扑
│   │   └── Mesh.ned              # Mesh网格拓扑
│   │
│   ├── NoCs.msg                  # 消息类型定义
│   └── package.ned               # 包定义文件
│
├── examples/                     # 示例仿真
│   ├── async/                    # 异步路由器示例
│   │   ├── 4x4/                  # 4x4 Mesh 网络
│   │   ├── 8x8/                  # 8x8 Mesh 网络
│   │   └── uniform_eval/         # 均匀流量评估
│   └── sync/                     # 同步路由器示例
│       ├── 4x4/                  # 4x4 Mesh 网络
│       ├── 8x8/                  # 8x8 Mesh 网络
│       └── uniform_eval/         # 均匀流量评估
│
├── simulations/                  # 自定义仿真配置目录
├── Makefile                      # 项目主 Makefile
└── README.md                     # 原始说明文件
```

---

## 🧩 核心组件详解

### 模块接口 (NED Interfaces)

HNOCS 使用 OMNeT++ 的模块接口特性实现灵活的仿真配置。以下是主要接口：

| 接口名称 | 功能描述 | 主要参数 |
|---------|---------|---------|
| `NI_Ifc` | 网络接口 | `id` (地址) |
| `Source_Ifc` | 流量源 | `srcId` |
| `Sink_Ifc` | 流量汇 | `numVCs` |
| `Router_Ifc` | NoC路由器 | `id`, `numPorts` |
| `Port_Ifc` | 层次化路由器端口 | `numPorts` |
| `InPort_Ifc` | 路由器输入端口 | `numVCs` |
| `Sched_Ifc` | 调度器/仲裁器 | `numVCs` |
| `OPCalc_Ifc` | 路由计算 | - |
| `VCCalc_Ifc` | VC分配器 | - |

### 消息类型

在 `NoCs.msg` 中定义的主要消息类型：

| 消息类型 | 用途 |
|---------|------|
| `NOC_FLIT_MSG` | Flit数据传输 |
| `NOC_CREDIT_MSG` | 信用反馈 |
| `NOC_REQ_MSG` | 仲裁请求 |
| `NOC_GNT_MSG` | 仲裁授权 |
| `NOC_ACK_MSG` | 确认消息 |
| `NOC_CLK_MSG` | 时钟消息 |

### Flit 类型

| 类型 | 含义 |
|-----|------|
| `NOC_START_FLIT` | 包头Flit |
| `NOC_MID_FLIT` | 中间Flit |
| `NOC_END_FLIT` | 包尾Flit |

---

## ⚙️ 配置参数说明

### INI 配置文件结构

以下是一个典型配置文件 (`omnetpp.ini`) 的详细说明：

```ini
[General]
network = hnocs.topologies.Mesh    # 使用的网络拓扑
sim-time-limit = 2ms               # 仿真时间限制

# ========== 组件类型选择 ==========
**.routerType = "hnocs.routers.hier.Router"        # 路由器类型
**.coreType   = "hnocs.cores.NI"                   # 网络接口类型
**.sourceType = "hnocs.cores.sources.PktFifoSrc"   # 流量源类型
**.sinkType   = "hnocs.cores.sinks.InfiniteBWMultiVCSink"  # 流量汇类型
**.portType   = "hnocs.routers.hier.Port"          # 端口类型
**.inPortType = "hnocs.routers.hier.inPort.InPortSync"     # 输入端口类型
**.OPCalcType = "hnocs.routers.hier.opCalc.static.XYOPCalc"# 路由算法类型
**.VCCalcType = "hnocs.routers.hier.vcCalc.free.FLUVCCalc" # VC分配器类型
**.schedType  = "hnocs.routers.hier.sched.wormhole.SchedSync" # 调度器类型

# ========== 全局参数 ==========
**.numVCs = 2              # 虚拟通道数量
**.flitSize = 4B           # Flit大小（字节）
**.rows = 4                # Mesh行数
**.columns = 4             # Mesh列数
**.statStartTime = 1us     # 统计开始时间

# ========== 流量源参数 ==========
**.source.pktVC = 0                    # 注入数据包使用的VC
**.source.msgLen = 4                   # 每条消息的数据包数
**.source.pktLen = 8                   # 每个数据包的Flit数
**.source.flitArrivalDelay = 2ns       # Flit到达间隔
**.source.maxQueuedPkts = 16           # 最大队列数据包数
**.source.dstId = (id + intuniform(1, 15)) % 16  # 目的地址（均匀随机）

# ========== 输入端口参数 ==========
**.inPort.flitsPerVC = 4               # 每个VC的缓冲区大小（Flit数）
**.inPort.collectPerHopWait = false    # 是否收集每跳等待时间

# ========== 调度器参数 ==========
**.sched.arbitration_type = 0          # 仲裁类型：0=普通，1=流水线
**.sched.freeRunningClk = false        # 是否使用自由运行时钟
**.tClk = 2ns                          # 时钟周期
```

### 异步 vs 同步模式

| 特性 | 异步模式 (Async) | 同步模式 (Sync) |
|-----|-----------------|-----------------|
| 路由器类型 | `idealRouter` | `Router` |
| 输入端口 | `InPortAsync` | `InPortSync` |
| 调度器 | `SchedAsync` | `SchedSync` |
| 延迟建模 | 无内部延迟 | 有时钟同步延迟 |
| 适用场景 | 快速验证 | 精确建模 |

---

## 📊 性能评估实验

### 运行延迟-吞吐量评估

`uniform_eval` 目录下的配置可用于生成延迟-吞吐量曲线：

```ini
# 参数化扫描配置
**.source.flitArrivalDelay = exponential(${D=3,3.5,3.75,4,4.25,4.5,5,6,7,8}ns)
repeat=10  # 每个配置重复运行10次
```

运行方式：
```bash
cd examples/async/uniform_eval
./run -u Cmdenv  # 命令行模式批量运行
```

### 主要统计指标

| 指标名称 | 含义 |
|---------|------|
| `end-to-end-latency-ns` | 端到端延迟（ns） |
| `network-latency-ns` | 网络延迟（ns） |
| `packet-network-latency-ns` | 数据包网络延迟 |
| `link-utilization` | 链路利用率 |
| `number-sent-packets` | 发送数据包数 |
| `number-received-packets` | 接收数据包数 |

---

## 📚 学习路线建议

### 第一阶段：基础准备（1-2周）

1. **学习 OMNeT++ 基础**
   - 完成官方 TicToc 教程：http://www.omnetpp.org/doc/omnetpp/tictoc-tutorial/
   - 理解 NED 语言和模块概念
   - 熟悉 OMNeT++ IDE 操作

2. **阅读 HNOCS 论文**
   - 理解 NoC 基本概念
   - 了解 HNOCS 架构设计思想

### 第二阶段：运行示例（1周）

1. **运行基础示例**

   **方法一：使用 OMNeT++ IDE（推荐）**
   
   在 OMNeT++ IDE 中：
   1. 导入 HNOCS 项目：`File → Import → Existing Projects into Workspace`
   2. 打开示例配置文件，如 `examples/async/4x4/omnetpp.ini`
   3. 右键点击 `omnetpp.ini` → `Run As` → `OMNeT++ Simulation`
   4. 在运行配置中确保：
      - **Executable**: 选择 `Other`，填写 `hnocs` 或浏览到 `src/libhnocs.dll`
      - 不要使用默认的 `opp_run`

   **方法二：命令行运行（Windows）**
   ```cmd
   cd D:\omnet_project\Project\HNOCS-master\examples\async\4x4
   opp_run -l ../../../src/hnocs -n ../../../src;../.. omnetpp.ini
   ```
   
   **方法三：命令行运行（Linux/macOS）**
   ```bash
   cd examples/async/4x4
   ./run
   ```

2. **观察仿真过程**
   - 使用 OMNeT++ 图形界面观察消息传递
   - 查看统计数据输出

3. **对比不同配置**
   - 比较异步和同步模式
   - 比较 4x4 和 8x8 网络

### 第三阶段：深入理解（2-3周）

1. **阅读核心源代码**
   - 从 [Mesh.ned](src/topologies/Mesh.ned) 开始理解拓扑结构
   - 研究 [PktFifoSrc.cc](src/cores/sources/PktFifoSrc.cc) 理解流量生成
   - 学习 [XYOPCalc.cc](src/routers/hier/opCalc/static/XYOPCalc.cc) 理解 XY 路由算法

2. **理解消息流程**
   ```
   Source → Router(InPort → OPCalc → VCCalc → Sched) → ... → Sink
   ```

3. **修改配置参数**
   - 尝试不同的网络大小
   - 调整流量模式
   - 改变 VC 数量

### 第四阶段：扩展开发（持续）

1. **添加新的路由算法**
   - 在 `src/routers/hier/opCalc/` 下创建新模块
   - 实现 `OPCalc_Ifc` 接口

2. **实现新的流量模式**
   - 在 `src/cores/sources/` 下添加新的源模块
   - 支持不同的流量分布

3. **设计新的拓扑**
   - 在 `src/topologies/` 下创建新的 NED 文件
   - 如 Torus、Fat-Tree 等

---

## 🔧 常用命令

```bash
# 编译（调试模式）
make MODE=debug

# 编译（发布模式）
make MODE=release

# 清理编译文件
make clean

# 完全清理
make cleanall

# 命令行模式运行
./src/run_nocs -u Cmdenv -c General omnetpp.ini

# 图形界面运行
./src/run_nocs -u Qtenv -c General omnetpp.ini
```

---

## 🐛 常见问题解决

### Q1: 编译时找不到 OMNeT++

**解决方案**：确保已正确设置 OMNeT++ 环境变量
```bash
source <omnetpp-root>/setenv
```

### Q2: 找不到 Makefile

**解决方案**：先生成 Makefile
```bash
make makefiles
```

### Q3: 运行时找不到模块

**解决方案**：检查 NED 路径配置，确保包含所有必要目录
```bash
./run_nocs -n src:examples
```

### Q4: 报错 "Class '<../>' not found"

**问题描述**：
```
Class "<../>" not found -- perhaps its code was not linked in, or the
class wasn't registered with Register_Class(), or in the case of modules
and channels, with Define_Module()/Define_Channel().
```

**解决方案**：
这是因为使用了 `opp_run` 而不是 HNOCS 编译的库。在 OMNeT++ IDE 中：

1. 右键 `omnetpp.ini` → `Run As` → `Run Configurations...`
2. 在 `Main` 标签页的 `Simulation` → `Executable` 中：
   - 选择 `Other` 单选按钮
   - 填写 HNOCS 库路径，如 `/trunk/src/hnocs` 或 `hnocs`
3. 点击 `Apply` 然后 `Run`

或者使用命令行：
```cmd
# Windows
opp_run -l ..\..\..\src\hnocs -n ..\..\..\src;..\.. omnetpp.ini

# Linux/macOS  
opp_run -l ../../../src/libhnocs.so -n ../../../src:../.. omnetpp.ini
```

### Q5: 报错 "Cannot assign parameter 'numPorts': Parameter refers to itself"

**问题描述**：
```
Cannot assign parameter 'numPorts': Parameter refers to itself in its assignment 
(did you mean 'parent.numPorts'?)
```

**原因**：这是 OMNeT++ 新版本（5.x/6.x）的兼容性问题。旧代码中 `numPorts = numPorts` 在新版本中被检测为自引用错误。

**解决方案**：
修改以下两个文件：

1. `src/routers/hier/idealRouter.ned` 第49行
2. `src/routers/hier/Router.ned` 第50行

将：
```ned
numPorts = numPorts;
```
改为：
```ned
numPorts = parent.numPorts;
```

### Q6: Windows 上 `./run` 无法执行

**原因**：`run` 是 Linux shell 脚本，Windows 不能直接执行。

**解决方案**：使用以下方式之一：

1. **使用 OMNeT++ IDE**（推荐）
2. **使用命令行**：
   ```cmd
   cd D:\omnet_project\Project\HNOCS-master\examples\async\4x4
   opp_run -l ..\..\..\src\hnocs -n ..\..\..\src;..\.. omnetpp.ini
   ```
3. **创建 Windows 批处理文件** `run.bat`：
   ```batch
   @echo off
   opp_run -l ..\..\..\src\hnocs -n ..\..\..\src;..\.. omnetpp.ini %*
   ```

---

## 📞 获取帮助

- **Google 讨论组**: https://groups.google.com/forum/#!forum/hnocs-simulator
- **官方文档**: 参见项目中的 `FAQ.pdf` 和 `How to Add HNOCS to OMNeT Workspace.pdf`

---

## 📜 许可证

本项目采用 GNU Lesser General Public License v3.0 (LGPL-3.0) 许可证。

---

## 🙏 致谢

- 以色列理工学院 (Technion) 电气工程系
- OMNeT++ 开发团队

---

*最后更新：2026年1月*
