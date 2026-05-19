# OMNeT++ vs Python 热仿真器 — 四 Benchmark 时序对比

## 总时间

| Benchmark | OMNeT++ | Python | 差异 | 误差% |
|-----------|---------|--------|------|-------|
| GEMM | 116.658 µs | 115.72 µs | 0.94 µs | **0.81%** |
| MPEG-4 | 165.858 µs | 165.59 µs | 0.27 µs | **0.16%** |
| VOPD | 237.042 µs | 236.42 µs | 0.62 µs | **0.26%** |
| Optic Calib | 62.778 µs | 62.50 µs | 0.28 µs | **0.44%** |

全部 < 1%。

## 通信延迟参数（两者共用）

| 参数 | 值 | OMNeT++ 来源 |
|------|-----|-------------|
| 链路带宽 | 16 Gbps | TaskMesh.ned TaskLink |
| Flit 大小 | 16 B (128 bit) | omnetpp.ini |
| Flit 传输 | 8 ns | 128b ÷ 16Gbps |
| Router 流水线 | 20 ns | SchedSync tClk_s + SwCtrlLink |
| 单跳 head | 28 ns | 流水线 + 链路 |
| Wormhole body | 8 ns/flit | 每拍一个 |
| 包总延迟 | H×28 + N×8 ns | 直接量测 |

## GEMM 逐 Task 对比

| Task | OMNeT++ Start | Python Start | 差异 |
|------|-------------|-------------|------|
| T1 | 0.000 µs | 0.000 µs | 0 |
| T2 | 15.306 µs | 15.284 µs | 22 ns |
| T3 | 15.586 µs | 15.312 µs | 274 ns |
| T4 | 15.842 µs | 15.312 µs | 530 ns |
| T5 | 16.122 µs | 15.340 µs | 782 ns |
| T6 | 65.418 µs | 65.376 µs | 42 ns |
| T7 | 65.698 µs | 65.404 µs | 294 ns |
| T8 | 66.026 µs | 65.488 µs | 538 ns |
| T9 | 66.306 µs | 65.516 µs | 790 ns |
| T10 | 96.506 µs | 95.716 µs | 790 ns |

差异来自 GB 注入串行化——T3/T4 共享 row1 连接，T4 必须等 T3 的 32 flits 注完。

## 差异来源分析

三个 OMNeT++ 独有的因素，Python 没有模拟：

1. **GB 注入串行化**（~200-800 ns）：GB 每个 row 连接一次只能发一个 flit（8ns），同 row 的多个 task 排队
2. **Credit 流控反压**（~50-200 ns）：初始 4 credit，发完 4 flit 后等 Router 返还 credit
3. **SchedSync 时钟对齐**（0-8 ns）：Grant 信号等下一个 8ns 调度时钟跳变

三项合计 < 1 µs，相对于 15-62.5 µs 的 task 计算时间可忽略。
