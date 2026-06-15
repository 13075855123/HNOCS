# Thermal-SA-TAS-Mapping 上下文交接文档

## 1. 基本约束

工作仓库：

`D:\HNOCS`

后续新对话开始后，必须先阅读：

- `D:\HNOCS\AGENTS.md`
- `D:\HNOCS\out\AGENTS.md`

必须遵守：

- 中文回答。
- 优先读取 `metrics.json` 的结构化字段，不要从 `summary.txt` 手工解析核心指标。
- 不要删除或覆盖：
  - `D:\HNOCS\out\B-2-v3-g60-seed42`
  - `D:\HNOCS\out\B-2-v3-g60-seed43`
- 如果这两个目录在当前机器不存在，也仍然把它们视为受保护路径。
- 生成或修改实验结果时，不要覆盖已有正式结果目录，除非用户明确要求。
- VOPD 和 HNN 的论文叙事必须谨慎：
  - VOPD 当前不能声称热指标改善。
  - HNN 当前是多目标折中，不能声称所有指标同步改善。

## 2. 当前任务背景

目标 baseline：

`Thermal-SA-TAS-Mapping`

定位：

- Mukherjee et al. 2019 TAS 思想的 inspired/reimplementation baseline。
- 不是 exact reproduction。
- 不使用 proposed GA。
- 不使用 proposed full composite cost。
- 不对每个 SA candidate 调用 OMNeT++ full simulation。
- 使用 lightweight thermal-aware allocation/scheduling proxy。
- OMNeT++ 只用于最终 mapping 的一次完整评估并生成 `metrics.json`。

当前 proposed method 是 GA-based simulation-in-the-loop thermal-aware task remapping，优化完整 composite cost。Thermal-SA-TAS-Mapping 必须和它明确区分。

## 3. 已实现代码位置

主要实现目录：

`D:\HNOCS\experiment\thermal_sa_tas_baseline`

关键文件：

- `D:\HNOCS\experiment\thermal_sa_tas_baseline\thermal_sa_tas_proxy.py`
- `D:\HNOCS\experiment\thermal_sa_tas_baseline\thermal_sa_tas_mapper.py`
- `D:\HNOCS\experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py`
- `D:\HNOCS\experiment\thermal_sa_tas_baseline\tests\`

当前已经实现过一版 v2 改进。

### `thermal_sa_tas_proxy.py`

新增或修改点：

- dynamic RC schedule-aware thermal proxy：
  - `thermal_mode="dynamic_rc"`
  - event-driven time overlap
- 新增参数：
  - `thermal_tau_ns`
  - `center_cooling_penalty_K_per_W`
  - `neighborhood_heat_penalty_K_per_W`
  - `dynamic_power_mode`
- 新增 spatial penalty：
  - center closeness penalty
  - neighbor heat penalty
- 新增 load proxy terms：
  - `MaxLoadProxy_ns`
  - `LoadImbalanceProxy`
- 新增函数：
  - `dynamic_temperature_proxy`
  - `apply_spatial_heat_penalties`
  - `pe_closeness_to_center`
  - `load_proxy_terms`

### `thermal_sa_tas_mapper.py`

新增或修改点：

- 新增 `selection_mode`
  - 默认 `"thermal_lexicographic"`
- 新增 thermal lexicographic final selection/ranking。
- 新增 `init_mode="comm_aware"`。
  - deterministic comm-aware initializer。
- thermal rank 包括：
  - Tmax
  - SigmaT
  - HotCount
  - MaxLoad
  - LoadImbalance
  - Makespan
  - Comm
  - score

### `run_thermal_sa_tas.py`

新增 CLI 参数：

```powershell
--thermal-mode {steady_rc,dynamic_rc}
--thermal-tau-ns
--center-cooling-penalty
--neighborhood-heat-penalty
--dynamic-power-mode {compute_power,task_power}
--tas-w-max-load
--tas-w-load-imbalance
--selection-mode {score,thermal_lexicographic}
--init comm_aware
```

当前 v2 默认 objective 权重：

```text
tas-w-tmax = 0.80
tas-w-sigma = 0.18
tas-w-hot = 0.02
tas-w-makespan = 0.0
tas-w-comm = 0.0
tas-w-max-load = 0.0
tas-w-load-imbalance = 0.0
```

当前搜索参数：

```text
max-total-iter = 5000
patience = 800
seed = 42
```

## 4. 当前正式结果目录

正式整合目录：

`D:\HNOCS\out\thermal-sa-tas-v2-integrated-seed42`

目录结构：

```text
D:\HNOCS\out\thermal-sa-tas-v2-integrated-seed42
├── v1
├── v2
├── v2_formal_metrics_summary.csv
├── v2_formal_metrics_summary.json
├── combined_v1_v2_metrics_summary.csv
├── combined_v1_v2_metrics_summary.json
├── v1_vs_v2_comparison.csv
└── v1_vs_v2_comparison.json
```

说明：

- `v1\` 是原 `D:\HNOCS\out\thermal-sa-tas-v1-seed42` 的整合副本。
- 原目录 `D:\HNOCS\out\thermal-sa-tas-v1-seed42` 已删除。
- `v2\` 是当前 dynamic RC thermal-first 改进后的正式结果。

每个 workload 的结构大致为：

```text
v2\<workload>\
├── original\
│   ├── mapping.csv
│   ├── metrics.json
│   └── summary.txt
└── thermal_sa_tas\
    ├── history.csv
    ├── history.json
    ├── mapping.csv
    ├── metrics.json
    ├── power_vector.csv
    ├── proxy_score_breakdown.json
    ├── proxy.json
    ├── rc_matrix.csv
    ├── remapped.csv
    ├── schedule_proxy.csv
    └── summary.txt
```

## 5. 当前 `metrics.json` schema

正式结果的 `metrics.json` 不是简单的 `baseline/candidate` schema，而是：

```json
{
  "name": "...",
  "method": "thermal_sa_tas",
  "method_label": "Thermal-SA-TAS-Mapping",
  "metrics": {
    "thermal": {
      "T1_pe_peak_temp_K": 0,
      "T3_temp_std_K": 0,
      "T5_over_throttle_count": 0
    },
    "performance": {
      "P1_makespan_s": 0,
      "P3_dvfs_penalty_pct": 0,
      "P2_speedup": 0
    },
    "communication": {
      "C1_total_comm_cost": 0
    },
    "energy": {
      "E7_pe_optical_comm_energy_J": 0
    },
    "tradeoff": {
      "TR2_composite_cost": 0,
      "cost_terms": {
        "T_max_K": 0,
        "sigma_T_K": 0,
        "N_hot": 0,
        "makespan_s": 0,
        "pe_optical_comm_energy_J": 0
      }
    },
    "run_status": {
      "run_ok": true,
      "valid_for_cost": true,
      "parsed_pe_count": 16,
      "parsed_temp_timepoints": 0
    }
  },
  "proxy": {},
  "config": {}
}
```

优先读取：

- `metrics.thermal.T1_pe_peak_temp_K`
- `metrics.thermal.T3_temp_std_K`
- `metrics.thermal.T5_over_throttle_count`
- `metrics.performance.P1_makespan_s`
- `metrics.communication.C1_total_comm_cost`
- `metrics.energy.E7_pe_optical_comm_energy_J`
- `metrics.tradeoff.TR2_composite_cost`
- `metrics.run_status.run_ok`
- `metrics.run_status.valid_for_cost`

## 6. 当前 v1 与 v2 结果

### v1 结果

| Workload | Cost | Tmax | SigmaT | Hot PE | Makespan |
|---|---:|---:|---:|---:|---:|
| GEMM | 6.0000 -> 4.8639 | -0.394 K | -29.95% | 6 -> 1 | -1.55% |
| MPEG4 | 6.0000 -> 4.6476 | -1.411 K | -19.03% | 2 -> 0 | -0.66% |
| VOPD | 5.0000 -> 4.9584 | +0.045 K | -6.97% | 0 -> 0 | +0.22% |
| HNN | 6.0000 -> 6.3117 | +3.883 K | -20.76% | 16 -> 16 | -0.04% |

### v2 结果

| Workload | Cost | Tmax | SigmaT | Hot PE | Makespan |
|---|---:|---:|---:|---:|---:|
| GEMM | 6.0000 -> 5.8674 | -2.321 K | -37.17% | 6 -> 0 | +79.60% |
| MPEG4 | 6.0000 -> 4.8938 | -1.649 K | -15.83% | 2 -> 0 | +8.14% |
| VOPD | 5.0000 -> 5.2266 | +0.783 K | -1.71% | 0 -> 0 | +0.73% |
| HNN | 6.0000 -> 6.5374 | +1.783 K | -27.98% | 16 -> 9 | +45.27% |

### v1 vs v2 关键变化

来自：

`D:\HNOCS\out\thermal-sa-tas-v2-integrated-seed42\v1_vs_v2_comparison.csv`

重点：

- GEMM：
  - v2 Tmax 比 v1 额外降低约 `1.927 K`。
  - SigmaT 更好。
  - 但 makespan 和 energy 明显变差。
- MPEG4：
  - v2 Tmax 比 v1 额外降低约 `0.238 K`。
  - SigmaT 略差于 v1。
  - makespan 和 energy 变差。
- VOPD：
  - v2 比 v1 更差。
  - Tmax 从 v1 的 `+0.045 K` 恶化到 v2 的 `+0.783 K`。
  - SigmaT 改善也从 `-6.97%` 降到 `-1.71%`。
- HNN：
  - v2 比 v1 的 Tmax 恶化幅度小一些。
  - SigmaT 和 Hot PE 比 v1 好。
  - 但 makespan 变差严重。

## 7. 当前问题

用户明确指出：

- VOPD 和 HNN 结果仍不理想。
- 尤其是 VOPD。
- 下一步需要继续修改代码，目标是让 Tmax 与 SigmaT 降低更明显，作为更好的 baseline 和 proposed GA 对比。

当前 v2 的问题：

1. Thermal-first proxy 对 GEMM 和 MPEG4 有效，但对 VOPD 和 HNN 失效。
2. VOPD 的真实 OMNeT++ Tmax 上升，说明 proxy 与真实热模型或通信热效应存在偏差。
3. HNN 虽然 SigmaT 降低、Hot PE 下降，但 Tmax 和 makespan 仍变差。
4. v2 牺牲 makespan 和 energy 较多，尤其 GEMM/HNN。
5. 当前 objective 几乎只看 thermal proxy，容易产生真实仿真下通信路径和负载副作用。

## 8. 已运行验证命令

代码语法检查：

```powershell
python -m py_compile experiment\thermal_sa_tas_baseline\thermal_sa_tas_proxy.py experiment\thermal_sa_tas_baseline\thermal_sa_tas_mapper.py experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py
```

单元测试：

```powershell
python -m unittest discover -s experiment\thermal_sa_tas_baseline\tests -p "test_*.py"
```

结果：

```text
Ran 6 tests in 0.292s
OK
```

正式 v2 运行命令：

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --seed 42 `
  --out out\thermal-sa-tas-v2-integrated-seed42\v2 `
  --omnet-timeout 300 `
  --verbose
```

## 9. 下一步建议方向

下一轮重点不是继续盲目提高 `Tmax` 权重，而是修正 VOPD/HNN 的 proxy 偏差。

### 9.1 对 VOPD 增加 communication-aware thermal guard

VOPD 的通信量大，v2 为追求 proxy thermal balance 增加了真实通信成本：

```text
VOPD comm: 1396000 -> 1954000, +39.97%
```

这可能通过 optical/PE activity 间接推高真实 Tmax。

建议：

- 在 SA objective 中恢复弱通信项，不要为 0。
- 对 VOPD/HNN 使用 workload-aware 或 auto-detected high-communication guard。
- 约束形式优先于权重形式：

```text
if CommProxy > CommRef * comm_guard:
    add penalty
```

建议初始参数：

```text
comm_guard = 1.05 或 1.10
comm_penalty_weight = 0.10 ~ 0.20
```

目标：

- 不让 VOPD 的通信成本暴涨。
- 保持 thermal proxy 改善的同时避免 OMNeT++ 真实热恶化。

### 9.2 增加 per-PE peak activity proxy，而不是只看平均功率

VOPD/HNN 可能是短时间峰值或局部并发导致真实 Tmax 上升。当前 dynamic RC 虽然使用 schedule，但仍可能不够敏感。

建议新增：

```text
PEPeakPowerProxy
PEPeakWindowEnergyProxy
ConcurrentNeighborPowerProxy
```

实现思路：

- 根据 `schedule_proxy.csv` 或内存 schedule，滑动窗口统计每个 PE 在窗口内的活动能量。
- thermal objective 中加入 peak window term。
- 对邻居 PE 同窗口并发计算 heat penalty。

窗口建议：

```text
window_ns = 1000 / 2000 / 5000 作为 sweep 参数
```

### 9.3 对 HNN 增加 makespan/load guard

HNN v2：

```text
makespan +45.27%
```

说明纯热 spreading 破坏了关键路径或负载。

建议：

- 对 HNN 启用 makespan guard。
- 不必作为强优化目标，但超过 baseline 后加 penalty：

```text
if MakespanProxy > MakespanRef * 1.05:
    add penalty
```

或：

```text
tas-w-max-load = 0.05 ~ 0.10
tas-w-load-imbalance = 0.05
```

### 9.4 改进 final selection：从 accepted states 中选 Pareto-safe 解

当前 `thermal_lexicographic` 可能选到真实性能或通信风险较大的 mapping。

建议保留 SA history 的 candidate archive，最终选择时先过滤：

```text
CommProxy <= 1.05 * CommRef
MakespanProxy <= 1.10 * MakespanRef
MaxLoadProxy <= 1.10 * MaxLoadRef
```

然后在可行集合中按 thermal lexicographic 选：

```text
Tmax_proxy, SigmaT_proxy, HotCount_proxy, PeakWindowProxy
```

如果无可行解，再放宽 guard。

### 9.5 VOPD 可尝试 workload-specific init

VOPD 当前 v1 比 v2 更接近可用：

- v1 cost 更好。
- v1 Tmax 几乎持平，仅 `+0.045 K`。
- v1 SigmaT 改善 `-6.97%`。

建议新增：

```text
--init v1_like
--init thermal_greedy
--init comm_preserving
```

或者让 SA 从 original 与 v1-style initializer 多 restart：

```text
restart 0: original
restart 1: comm_aware
restart 2: balanced
restart 3: thermal_greedy
```

最后用 constrained thermal selection 选解。

## 10. 下一轮实验建议

不要覆盖已有目录。建议新目录：

`D:\HNOCS\out\thermal-sa-tas-v3-vopd-hnn-seed42`

先只跑 VOPD/HNN，节约时间：

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --workload VOPD `
  --seed 42 `
  --out out\thermal-sa-tas-v3-vopd-hnn-seed42 `
  --thermal-mode dynamic_rc `
  --selection-mode thermal_lexicographic `
  --init comm_aware `
  --omnet-timeout 300 `
  --verbose
```

以及：

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --workload HNN `
  --seed 42 `
  --out out\thermal-sa-tas-v3-vopd-hnn-seed42 `
  --thermal-mode dynamic_rc `
  --selection-mode thermal_lexicographic `
  --init comm_aware `
  --omnet-timeout 300 `
  --verbose
```

如果当前 CLI 不支持单 workload 参数，先检查 `run_thermal_sa_tas.py` 的已有参数，再按现有入口扩展。

## 11. 下一轮成功标准

VOPD 优先级最高。

理想目标：

- VOPD：
  - Tmax 不上升，最好下降至少 `0.3 K`。
  - SigmaT 下降至少 `5%`。
  - Comm 不显著恶化，最好不超过 baseline `+5%`。
  - Composite cost 不高于 baseline。
- HNN：
  - SigmaT 继续下降。
  - Hot PE 降低。
  - Tmax 至少不要明显上升。
  - Makespan 恶化控制在可解释范围内。

如果 VOPD Tmax 仍上升，论文中必须写成 trade-off 或 proxy limitation，不能称为热改善 baseline。

## 12. 后续新对话启动提示

可以把下面这段直接给新对话：

```text
你在 D:\HNOCS 仓库工作，请用中文回答。先阅读 D:\HNOCS\AGENTS.md 和 D:\HNOCS\out\AGENTS.md，并遵守其中关于 metrics.json、实验运行、输出目录、以及不要删除/覆盖 B-2 seed42/seed43 结果的约束。

当前已经实现 Thermal-SA-TAS-Mapping baseline，代码在 D:\HNOCS\experiment\thermal_sa_tas_baseline。已有 v2 结果整合在 D:\HNOCS\out\thermal-sa-tas-v2-integrated-seed42。v2 对 GEMM/MPEG4 降温明显，但 VOPD/HNN 仍不理想，尤其 VOPD：Tmax 上升 +0.783 K、SigmaT 仅下降 -1.71%、comm 增加 +39.97%、cost 变差。HNN SigmaT 和 Hot PE 改善，但 Tmax、makespan、cost 变差。

请继续修改 Thermal-SA-TAS-Mapping，使 VOPD 和 HNN 的 Tmax 与 SigmaT 降低更明显。优先考虑 communication-aware thermal guard、peak-window activity thermal proxy、Pareto-safe final selection、makespan/load guard、多 initializer/restart。不要覆盖已有 v2 结果，新结果放到新的 out 目录，先跑 VOPD/HNN 验证，再决定是否全 workload 正式运行。
```
