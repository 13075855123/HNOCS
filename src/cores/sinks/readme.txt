# sinks

该目录实现 **流量汇聚端（Sink）**，负责接收从网络返回的数据，并进行统计、吞吐分析、延迟分析等处理，是 NI（Network Interface）中接收端的重要组成部分。

## 目录职责

`sinks` 目录中的模块主要负责：

- 接收从 NoC 输出的数据包/Flit
- 统计报文到达情况
- 记录时延、吞吐量、来源分布等指标
- 作为仿真结果分析的重要观测点

## 主要文件

### `Sink_Ifc.ned`
定义 Sink 模块的统一接口。  
其他具体 Sink 实现都应遵循该接口，以便在 `NI.ned` 中通过参数化方式灵活替换。

### `InfiniteBWMultiVCSink.ned`
Sink 模块的 NED 定义文件。  
从命名看，该模块表示一个**无限带宽、多虚通道（Multi-VC）**的接收端模型。

### `InfiniteBWMultiVCSink.h`
`InfiniteBWMultiVCSink` 的类声明文件。  
定义接收端统计、状态维护及消息处理接口。

### `InfiniteBWMultiVCSink.cc`
`InfiniteBWMultiVCSink` 的实现文件。  
负责接收数据并进行统计分析。

### `InfiniteBWMultiVCSinkperSrc.ned`
另一个 Sink 结构定义文件。  
从命名看，该模块会**按源节点（per source）**分别统计接收信息。

### `InfiniteBWMultiVCSinkperSrc.h`
`InfiniteBWMultiVCSinkperSrc` 的类声明文件。

### `InfiniteBWMultiVCSinkperSrc.cc`
`InfiniteBWMultiVCSinkperSrc` 的实现文件。  
用于实现按源分类的接收统计逻辑。


## 模块定位

在整体结构中，`sinks` 目录下的模块通常作为：

- **NI 的接收子模块**
- **网络出口的数据接收者**
- **仿真性能统计终点**

典型连接关系如下：

`Router/Network -> NI -> Sink`

## 设计特点

- 支持接口化替换不同 Sink 模型
- 适合统计：
  - 平均时延
  - 吞吐率
  - 按源节点统计的接收数据
  - 多 VC 接收行为
- “InfiniteBW” 命名表明该类接收端通常假设接收侧不是瓶颈，不限制带宽

## 备注

如果后续要扩展到 ONoC 或故障恢复场景，`sinks` 目录也可以作为：
- 光链路接收统计端
- 误码/丢包观测端
- 按业务流分类的性能分析端