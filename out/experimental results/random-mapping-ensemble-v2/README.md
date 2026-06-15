# random-mapping-ensemble-v2

本目录保存用于公平对比 `B-2-v4` GA 的 equal-valid-budget random-search control 结果。核心口径是：每个 workload 的随机搜索统计均基于 **3000 个 valid random mappings**，并且每个 random mapping 都经过与 `B-2-v4` 相同的 OMNeT++ evaluator 和 initial/reference-normalized composite cost 计算。

论文写作口径：本目录不是当前主文的 baseline method。主文 baseline methods 为 `Thermal-SA-TAS` 和 `CommAware-Heuristic`；random 结果只作为 random-search sanity/control，正文若只放一个 random control，优先使用 `RandomBest`，并明确它是 best-of-ensemble selected mapping。

## 统计口径

是的，`D:\HNOCS\out\random-mapping-ensemble-v2` 下用于对比和汇总的统计文件，都是按每个 workload **3000 valid samples** 汇总的：

| Workload | requested samples | valid samples | invalid samples | 说明 |
|---|---:|---:|---:|---|
| GEMM | 3000 | 3000 | 0 | 初始 3000 次全部有效 |
| MPEG4 | 3000 | 3000 | 0 | 初始 3000 次全部有效 |
| VOPD | 3243 | 3000 | 243 | 为补足 3000 valid，额外 top-up；无效样本记录但不进入 cost 分布统计 |
| HNN | 3000 | 3000 | 0 | 初始 3000 次全部有效 |

因此：

- `random_best`、`random_p10`、`random_median`、`random_p90` 均从各 workload 的 3000 个 valid samples 中选出。
- `compare_with_B-2-v4.csv/json/md`、`aggregate_summary.csv/json` 和 `runs_summary.csv/json` 中的 random cost 分布统计均对应 3000 valid samples/workload。
- VOPD 的 `requested_samples=3243` 不是统计样本数，而是为了获得 3000 个有效样本实际尝试过的 random mappings 总数。
- invalid samples 保存在各 workload 的 `invalid_samples.csv/json` 中，并在 `validity_report.csv` 中汇总。

## 有效性判定

用于 cost 统计的样本必须满足：

- `run_ok=true`
- `valid_for_cost=true`
- `T_max` 不是 `-273.1 C`
- `makespan` 不是 `0`
- `total PE+optical energy` 不是 `0`

VOPD 的 invalid samples 已单独保留；主要失败原因是 OMNeT++ 运行超时，另有 1 个样本缺失 makespan。invalid samples 不参与 random best / percentile / median 的 cost 排序。

## 目录结构

每个 workload 使用独立目录：

```text
D:\HNOCS\out\random-mapping-ensemble-v2
├── gemm
├── mpeg4
├── vopd
├── hnn
└── provenance
```

各 workload 目录的主要内容：

```text
<workload>
├── original
│   ├── metrics.json
│   └── remapped.csv
└── random
    ├── samples.csv
    ├── samples.json
    ├── invalid_samples.csv
    ├── invalid_samples.json
    ├── metrics.json
    ├── runs_summary.csv
    ├── runs_summary.json
    ├── mappings
    └── selected
        ├── random_best
        ├── random_p10
        ├── random_median
        └── random_p90
```

`selected/random_best`、`selected/random_p10`、`selected/random_median`、`selected/random_p90` 中保存对应代表样本的：

- `metrics.json`
- `mapping.csv`
- `remapped.csv`

根目录 `provenance` 保存运行日志和 VOPD top-up 批次等追溯材料，不作为论文表格的首选读取入口。

## 根目录汇总文件

建议优先使用以下结构化文件：

- `runs_summary.csv`
- `runs_summary.json`
- `aggregate_summary.csv`
- `aggregate_summary.json`
- `compare_with_B-2-v4.csv`
- `compare_with_B-2-v4.json`
- `compare_with_B-2-v4.md`
- `validity_report.csv`
- `random_v2_analysis.md`

这些文件的聚合指标来自结构化 `metrics.json` 和 `samples.csv/json` 字段，不依赖手工解析 `summary.txt`。

## 与 B-2-v4 的结论口径

当前 equal-valid-budget random-search control 的主要结论是：

- 四个 workload 中，`B-2-v4` 的 GA worst cost 仍低于 random best cost。
- 四个 workload 中，random samples 里 `cost <= GA mean`、`cost <= GA worst`、`cost <= GA best` 的数量均为 0。
- GA mean 相对 random best 的优势约为：
  - GEMM: 6.60%
  - MPEG4: 6.95%
  - VOPD: 6.87%
  - HNN: 7.27%

因此，论文中可以严谨表述为：在每个 workload 3000 个有效 random mappings 的 equal-valid-budget random search 下，random-search control 仍未达到 `B-2-v4` GA 的搜索结果；并且 GA 的最差 seed 仍优于 `RandomBest`。

## 使用注意

- 不要把 VOPD 的 `requested_samples=3243` 误写成 3243 个有效随机样本。
- 不要用 `summary.txt` 手工解析核心指标；论文表格和分析应优先读取 `metrics.json`、`samples.csv/json` 和根目录聚合 CSV/JSON。
- `random-mapping-ensemble-v1` 是早期 50-sample random control；v2 是当前公平对比 `B-2-v4` 时应使用的版本。
