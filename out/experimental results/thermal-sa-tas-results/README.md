# Thermal-SA-TAS Results Organization

整理时间：2026-06-13

## 当前目录口径

当前 `D:\HNOCS\out\thermal-sa-tas-results` 已整理为两层主结构：

- `final`：正式 Thermal-SA-TAS v3 integrated 多 seed 结果，当前论文与图表优先使用。
- `archive`：历史探索与 v1/v2 追溯材料，默认不参与当前论文主结果。

论文写作口径：`Thermal-SA-TAS` 是当前主文的两个 method-level baseline methods 之一，另一个是 `CommAware-Heuristic`。各 seed/workload 下的 `original` 目录表示 initial/reference mapping，用于归一化和前后比较，不应写作 baseline method。

`final` 目录已经采用扁平化多 seed 结构，不再使用额外的 `thermal-sa-tas-v3-integrated-seeds40-49` 子目录：

```text
final\
  aggregate_summary.csv
  aggregate_summary.json
  runs_summary.csv
  validity_report.csv
  thermal_sa_tas_multiseed_analysis.md
  provenance\
  seed_40\
  seed_41\
  ...
  seed_49\
```

每个 `seed_<N>` 目录包含四个 workload：

```text
seed_<N>\
  gemm\
    original\
    thermal_sa_tas\
  mpeg4\
    original\
    thermal_sa_tas\
  vopd\
    original\
    thermal_sa_tas\
  hnn\
    original\
    thermal_sa_tas\
```

每个 workload 的核心数据以 `metrics.json` 为准；搜索轨迹保留 `history.json`。已删除重复的 `history.csv`。

## 当前推荐结果

论文主表、随机种子稳健性、以及与 B-2-v4 seed 40-49 对齐时，优先使用：

`D:\HNOCS\out\thermal-sa-tas-results\final`

关键汇总文件：

- `final\runs_summary.csv`
- `final\aggregate_summary.csv`
- `final\aggregate_summary.json`
- `final\validity_report.csv`
- `final\thermal_sa_tas_multiseed_analysis.md`

运行脚本、聚合脚本和日志已归档到：

`final\provenance`

其中：

- `final\provenance\run_seeds_40_49.ps1`：seed 40-49 运行脚本。
- `final\provenance\aggregate_thermal_sa_tas_multiseed.py`：聚合脚本。
- `final\provenance\_logs\progress.log`：多 seed 运行进度日志。
- `final\provenance\_logs\seed_*.log`：单 seed 运行日志。

## 多 seed 结果口径

seed 40-49 全部使用正式 preset：

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --preset v3_integrated `
  --seed <SEED> `
  --out out\thermal-sa-tas-results\final\seed_<SEED> `
  --omnet-timeout 300 `
  --verbose
```

有效性检查结果：40/40 个 seed-workload 组合通过。未出现 `run_ok=false`、`valid_for_cost=false`、`T_max=-273.1 C`、`makespan=0`、`E_total=0` 或 `history.json` 全代 best 为 Infinity。

| Workload | Thermal-SA-TAS cost mean ± CI95 | vs initial mapping | B-2-v4 GA cost mean | B-2-v4 vs initial mapping |
|---|---:|---:|---:|---:|
| GEMM | 5.0255 ± 0.3716 | -16.24% | 3.7796 | -37.01% |
| MPEG4 | 4.9191 ± 0.2181 | -18.01% | 4.1326 | -31.12% |
| VOPD | 4.5019 ± 0.0509 | -9.96% | 4.4059 | -11.88% |
| HNN | 5.6903 ± 0.1381 | -5.16% | 5.1357 | -14.40% |

## 写作注意

- Thermal-SA-TAS v3 integrated 多 seed 稳定优于 initial/reference mapping，但整体弱于 B-2-v4 GA。
- GEMM：热指标改善明显，但 makespan 和总 PE+optical energy 上升，应写作热稳定 baseline method 的 trade-off。
- MPEG4：cost 和 Tmax/sigma_T 下降，但通信、拥塞和负载均衡存在代价，不要写成所有指标同步改善。
- VOPD：cost、sigma_T、通信、拥塞、makespan 和能耗改善；Tmax 多 seed 平均基本持平，不宜夸大为稳定峰温下降。
- HNN：热点 PE 和温度不均衡下降，但 Tmax 平均上升、makespan 平均变差；只能写成多目标折中，不要声称 Tmax 或 makespan 改善。

## 与旧 seed42 单次结果的关系

之前保留过 `final\thermal-sa-tas-v3-integrated-seed42-final` 作为 seed42 单次正式结果目录。当前目录整理后，该独立目录已合并到扁平化多 seed 结果中：

`final\seed_42`

此前已核对：旧 seed42 单次目录与当前 `final\seed_42` 的四个 workload `metrics.json` 完全一致。因此，后续若需要引用 seed42 单次结果，应使用 `final\seed_42`。

## Archive 内容

`archive` 目录保留历史追溯材料：

- `archive\thermal-sa-tas-v2-integrated-seed42`：v1/v2 对照、handoff 和 v2 正式结果。
- `archive\thermal-sa-tas-v3-exploratory-summary-seed42`：v3 探索轮次汇总，只保留 summary，不保留中间完整运行目录。

这些内容不作为当前主结果口径；需要追溯算法演进或解释 preset 调整时再使用。

## 整理与删除记录

本轮整理后保留：

- 所有 `metrics.json`。
- 所有 `history.json`。
- 所有 `mapping.csv` / `remapped.csv`。
- `final` 根部多 seed 聚合文件。
- `archive` 中历史汇总和必要原始 JSON。

已删除或合并：

- 所有 `history.csv`：与 `history.json` 重复。
- 每个 `seed_*` 根部的 `runs_summary.csv`、`runs_summary.json`、`aggregate_summary.json`：已由 `final` 根部聚合文件覆盖。
- `runner.pid`、空的 `runner.stderr.log` 和冗余 `runner.stdout.log`。
- 原多 seed 外层目录名已取消，内容上移到 `final`。
- 旧 `final\thermal-sa-tas-v3-integrated-seed42-final` 已合并到 `final\seed_42`。

## 已删除的旧中间目录

以下目录为探索、smoke test、被正式结果覆盖的单 workload 结果，或第一次 GEMM preset 错误的 integrated 目录，之前已删除：

- `out\thermal-sa-tas-v3-hnn-dynamic-score-seed42`
- `out\thermal-sa-tas-v3-hnn-random-balanced-smoke-seed42`
- `out\thermal-sa-tas-v3-hnn-tmax-score-seed42`
- `out\thermal-sa-tas-v3-hotspot-seed42`
- `out\thermal-sa-tas-v3-integrated-seed42`
- `out\thermal-sa-tas-v3-proxy-sweep-seed42-a`
- `out\thermal-sa-tas-v3-steady-vopd-comm-score-seed42`
- `out\thermal-sa-tas-v3-steady-vopd-seed42`
- `out\thermal-sa-tas-v3-steady-vopd-sigma-score-seed42`
- `out\thermal-sa-tas-v3-vopd-hnn-seed42`
