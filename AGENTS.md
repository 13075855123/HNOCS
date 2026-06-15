# HNOCS Project Agent Guide

本文档是 `D:\HNOCS` 工程的项目级上下文，重点记录论文叙事、当前有效结果口径和协作注意事项。实验运行手册已单独放在 `D:\HNOCS\out\AGENTS.md`。

## 1. 论文任务与当前叙事

论文关注硅光片上网络（ONoC）的系统级热管理。核心观点不是单独降低芯片温度或补偿 MRR 热漂移，而是把任务到处理单元（PE）的映射作为系统级控制变量，联合优化热稳定性、性能、通信、拥塞、DVFS、负载均衡和总能耗。

当前摘要主张如下：

- 任务级负载映射会同时影响热源分布、DVFS 节流、光传输路径、波长活动、SOA 激活时间和 MRR 热调谐需求。
- 方法为基于遗传算法的仿真在环热感知任务重映射。
- 每个候选映射由全系统 OMNeT++ 模型评估，模型包含 8 波长 WDM 光层、MRR 动态热调谐、SOA 和激光器能耗、紧凑 RC 热网络以及 DVFS 反馈。
- 优化目标为 initial-mapping-normalized composite cost（代码和部分历史文件中仍称 `baseline_normalized_v2`），联合考虑峰值温度、温度不均衡、热点 PE 数、makespan、通信代价、拥塞、DVFS 惩罚、负载不均衡和总能耗。
- GEMM 与 MPEG4 可表述为热、性能、通信和能耗同步改善。
- VOPD 的主要优势是 makespan、通信、拥塞和总能耗显著改善；不要声称 VOPD 的峰值温度和温度标准差也同步改善。
- HNN 是典型多目标折中：热点 PE 数显著下降，但 makespan 相对 initial mapping 变差；写作时强调系统级折中，不要写成所有指标都改善。

论文写作口径：

- `Original` 不作为 baseline method 表述，而应称为 `initial mapping`、`reference mapping` 或 `normalization reference`。
- 当前主文方法级 baselines 为 `Thermal-SA-TAS` 与 `CommAware-Heuristic`。
- `RandomBest` 只作为 best-of-random sanity/control 使用，不作为普通随机 baseline 的平均水平。
- 历史脚本、CSV 列名或代码中出现的 `baseline` 多数表示归一化 reference；写作时需要转换成 `initial/reference mapping`。

## 2. 实验运行手册位置

本地/实验室主机路径、环境检查、已验证运行命令、dry run、进度显示、输出文件结构和无效结果判定，统一维护在 `D:\HNOCS\out\AGENTS.md`。

后续 agent 需要重跑实验或核对环境时，先阅读 `D:\HNOCS\out\AGENTS.md`，不要在根目录 `AGENTS.md` 中重复维护同一批路径和命令。

## 3. 当前已整理结果

本地 `D:\HNOCS\out` 当前包含：

- `B-2-v3-g60-seed42`
- `B-2-v3-g60-seed43`

initial/reference mapping 在两个 seed 的 `metrics.json` 中一致。seed42 可作为主结果；seed43 可作为随机种子稳健性补充。

| Workload | Initial/reference cost | Seed42 cost | Seed43 cost | Seed42 improvement | Seed43 improvement |
|---|---:|---:|---:|---:|---:|
| GEMM | 6.0000 | 3.9245 | 3.8490 | 34.59% | 35.85% |
| MPEG4 | 6.0000 | 4.0350 | 3.8743 | 32.75% | 35.43% |
| VOPD | 5.0000 | 4.0940 | 4.0851 | 18.12% | 18.30% |
| HNN | 6.0000 | 5.1158 | 5.2112 | 14.74% | 13.15% |

Seed43 相对 seed42：

| Workload | Cost change | Tmax change | Hot PE | Makespan change | Comm change | Energy change |
|---|---:|---:|---:|---:|---:|---:|
| GEMM | -1.92% | +0.113 C | 0 -> 0 | -0.03% | -14.49% | +0.06% |
| MPEG4 | -3.98% | -0.083 C | 0 -> 0 | -12.86% | -2.04% | -6.66% |
| VOPD | -0.22% | -0.280 C | 0 -> 0 | +0.04% | -20.35% | +1.06% |
| HNN | +1.86% | +0.083 C | 4 -> 8 | -1.07% | +4.19% | +0.30% |

写作建议：

- GEMM、MPEG4：两个 seed 都支持复合代价下降，并且热、性能、通信、能耗整体改善。
- VOPD：两个 seed 都支持复合代价下降和 makespan 约 51.6% 改善，总能耗约 32-33% 改善；但温度均匀性变差，不要夸大热指标。
- HNN：两个 seed 都支持复合代价下降和热点 PE 减少；seed42 从 16 降至 4，seed43 从 16 降至 8。HNN 的 makespan 变差，应表述为多目标折中。

## 4. 仓库协作注意事项

- 中文回答。
- 优先读取 `metrics.json` 的结构化字段，不要从 `summary.txt` 手工解析核心数据。
- 路径检查优先于重跑实验。发现无效结果时，先按 `D:\HNOCS\out\AGENTS.md` 核对运行环境和路径参数。
- 不要删除或覆盖 `out\B-2-v3-g60-seed42`、`out\B-2-v3-g60-seed43` 及其中的 `history.json`、`metrics.json`、`remapped.csv`。
- 生成论文图表时保留脚本、CSV 中间表和最终图片，便于追溯。
- 修改实验脚本前，先确认是否会改变 initial/reference mapping、external baseline method 或 fitness 定义；如果会改变，旧结果不能和新结果直接合并。
