# AGENTS_zh.md

**作用范围**：本文件适用于 `D:\HNOCS\document\paper` 及其所有子目录。

## 项目背景

- 论文目标会议为 ACP 2026，应遵循 IEEE 会议风格、双栏 LaTeX 格式。
- 正式投稿语言为英文。中文草稿仅用于内部对照和规划。
- 双盲审稿阶段需保持作者信息匿名。
- 除非另有说明，目标篇幅为 2–6 页。

## 论文主叙事线

编辑论文时遵循以下因果链：

1. ONoC 系统行为由任务执行和任务间通信共同决定。
2. 任务到 PE 的映射决定片上热源的空间分布。
3. 热分布影响 PE 热点、DVFS 节流和任务执行时间。
4. 热分布同时影响邻近 MRR 的温度、MRR 对准以及动态热调谐需求。
5. 任务通信改变 WDM 光传输活动、波长通道活动、SOA 激活时间和光层能耗。
6. 因此，ONoC 热管理是任务映射、热分布、MRR 对准、光器件补偿成本、性能和能耗之间的系统级多目标权衡。

**不要**将论文叙述为"MRR 热敏感性单独导致 PE 热点、DVFS 节流、SOA 激活或应用能耗"。MRR 热敏感性是热分布在光子层面的一种后果，而非所有系统效应的根源。

## 术语规范

**推荐使用的术语**：

- `WDM optical transmission activity`
- `wavelength-channel activity`
- `MRR alignment`
- `dynamic thermal tuning`
- `photonic-device compensation cost`
- `SOA activation time`
- `optical-layer energy`
- `task-to-PE mapping`
- `simulator-in-the-loop thermal-aware task remapping`

**论文叙述中应避免的术语**（除非明确要求讨论仿真器实现细节）：

- `handshake`
- `setup`
- `teardown`
- `optical circuit setup`
- `optical circuit duration`
- `connection setup`
- `connection teardown`
- `建链`
- `拆链`
- `握手`
- `光路建立`

## 证据边界

- 当前实验支撑的指标：温度、DVFS、makespan、通信代价、SOA 能耗、MRR 热调谐能耗、激光器能耗和总能耗。
- 除非新增实验，否则**不得**声称直接验证了 BER、光传输误码、丢包、接收端裕量或未补偿的 MRR 失谐。
- 可以将 MRR 热调谐能耗作为维持 MRR 对准的可观测补偿成本来陈述。
- 讨论失谐时，应将其作为背景动机或物理机制来表述，而非作为直接测量的运行时故障模式。

## LaTeX 编辑规则

- 除非要求更换模板，保持 IEEE 会议风格。
- 偏向简洁的 ACP/IEEE 会议文风，而非高度社论化或 Nature 式的文风。
- 保持图表紧凑，避免大段说明性文字导致论文超出 6 页。
- 适当时使用 `siunitx` 处理单位。
- 引用使用 IEEE 风格 `\cite{...}`。
- 双盲稿中不得添加致谢、作者姓名、单位或任何能识别身份的文件路径。

## 构建与验证

英文草稿：

```powershell
latexmk -pdf -interaction=nonstopmode -halt-on-error <main>.tex
```

中文内部草稿：

```powershell
latexmk -xelatex -interaction=nonstopmode -halt-on-error <main>.tex
```

编辑完成前需完成以下检查：

- 编译修改后的 `.tex` 文件。
- 确认输出的 PDF 在 ACP 页数限制内。
- 在修改过的 `.tex` 文件中搜索上述禁用术语。
- 报告任何可能影响投稿质量的残留 LaTeX 警告。

## 双语同步规则

在进行修改时，需同步更新中文版（`AGENTS_zh.md`）与英文版（`AGENTS.md`）。若二者出现不一致，以中文版为准，因作者手动维护中文草稿。

## 文件组织

- `第一版/` — 早期草稿及生成的构建产物。
- `第二版/` — 当前面向 ACP 投稿的草稿文件。
- 除非明确指定其他版本，优先编辑当前版本。
