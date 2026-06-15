# Random Mapping Ensemble v2 与 B-2-v4 对比

数据来源：`D:\HNOCS\out\random-mapping-ensemble-v2` 和 `D:\HNOCS\out\B-2-v4`。Random v2 对 GEMM、MPEG4、HNN 请求 3000 个 random mappings；VOPD 因原始 3000 attempts 中存在 timeout invalid samples，已按 seed 顺序追加至 3000 个有效样本。每个 mapping 均经过 OMNeT++ evaluator 和 baseline-normalized composite cost 计算。所有指标均从 `metrics.json` / `samples.csv` 的结构化字段读取，未解析 `summary.txt`。

## 1. 预算口径

- B-2-v4 配置为 population=50、generations=60，即常用配置预算 3000 candidate slots/seed。
- 按 GA 代码实际新个体评估计算，精英保留使满 60 代为 50 + 48*(60-1) = 2882 次 candidate evaluation；early stopping 会进一步降低实际评估次数。
- Random v2 以 3000 个有效 random mappings/workload 作为公平对比口径。VOPD 为补足 timeout invalid samples，正式合并后的 requested attempts 高于 3000，但 valid samples 为 3000。

## 2. 运行耗时与有效性

| Workload | Requested | Valid | Invalid | Workers | Elapsed(min) |
|---|---:|---:|---:|---:|---:|
| GEMM | 3000 | 3000 | 0 | 8 | 8.6792 |
| MPEG4 | 3000 | 3000 | 0 | 8 | 8.3958 |
| VOPD | 3243 | 3000 | 243 | 8 | 38.9059 |
| HNN | 3000 | 3000 | 0 | 8 | 11.2603 |

总墙钟耗时约 67.2412 min。按 random v1 串行耗时外推，3000 samples/workload 约为 362 min；本次用 8 workers 执行。VOPD 的 invalid samples 均记录在 `vopd/random/invalid_samples.csv`，失败原因主要为 `timeout after 60.0s`，另有少量解析后仍缺失必要字段的无效样本。

## 3. Cost 对比

| Workload | Random valid/total | Random best | Random p10 | Random median | Random p90 | GA mean±std | 95% CI half | GA best/worst | GA mean advantage vs random best | GA worst better? | Random <= GA mean/worst/best |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 3000/3000 | 4.0466 | 4.6600 | 5.2266 | 5.9130 | 3.7796±0.0366 | 0.0262 | 3.7260/3.8446 | 6.5985% | True | 0/0/0 |
| MPEG4 | 3000/3000 | 4.4412 | 4.8339 | 5.2568 | 5.9705 | 4.1326±0.0746 | 0.0533 | 4.0163/4.2428 | 6.9481% | True | 0/0/0 |
| VOPD | 3000/3243 | 4.7311 | 5.1488 | 5.5282 | 6.0291 | 4.4059±0.0860 | 0.0615 | 4.2210/4.5359 | 6.8732% | True | 0/0/0 |
| HNN | 3000/3000 | 5.5382 | 6.1277 | 6.5107 | 6.9967 | 5.1357±0.1923 | 0.1375 | 4.8786/5.4626 | 7.2672% | True | 0/0/0 |

## 4. 九项指标代表样本

| Workload | Mapping | Cost | T_max(C) | sigma_T(K) | N_hot | makespan(us) | DVFS(%) | comm | congestion | load imbalance | PE+opt energy(mJ) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | Original | 6.0000 | 54.9342 | 2.1435 | 6 | 120.4050 | 1.8351 | 104448 | 22528 | 0.9203 | 1.5709 |
| GEMM | RandomBest | 4.0466 | 53.2922 | 1.4975 | 0 | 116.7810 | 0.0000 | 75776 | 10240 | 1.1869 | 1.5175 |
| GEMM | RandomP10 | 4.6600 | 54.0596 | 1.6068 | 1 | 116.6827 | 0.0158 | 76800 | 18432 | 1.7582 | 1.5179 |
| GEMM | RandomMedian | 5.2266 | 53.5151 | 1.3834 | 0 | 146.7629 | 0.0000 | 113664 | 24576 | 2.4311 | 1.6779 |
| GEMM | RandomP90 | 5.9130 | 54.1495 | 1.4556 | 1 | 196.2928 | 0.0350 | 67584 | 20480 | 3.3833 | 1.9431 |
| MPEG4 | Original | 6.0000 | 54.4466 | 1.3004 | 2 | 122.0699 | 0.0717 | 420000 | 88000 | 0.5671 | 1.1329 |
| MPEG4 | RandomBest | 4.4412 | 52.6922 | 1.0519 | 0 | 122.4139 | 0.0000 | 472000 | 40000 | 0.9837 | 1.1328 |
| MPEG4 | RandomP10 | 4.8339 | 52.7163 | 1.1018 | 0 | 122.4437 | 0.0000 | 452000 | 72000 | 1.3127 | 1.1327 |
| MPEG4 | RandomMedian | 5.2568 | 54.1294 | 1.2539 | 1 | 122.4427 | 0.0176 | 428000 | 60000 | 0.9618 | 1.1338 |
| MPEG4 | RandomP90 | 5.9705 | 54.1487 | 1.3318 | 1 | 132.8456 | 0.0221 | 300000 | 68000 | 2.5407 | 1.1912 |
| VOPD | Original | 5.0000 | 52.2227 | 0.9871 | 0 | 89.3329 | 0.0000 | 1396000 | 252000 | 0.3580 | 0.7507 |
| VOPD | RandomBest | 4.7311 | 52.6488 | 0.9609 | 0 | 90.9347 | 0.0000 | 1374000 | 136000 | 0.3580 | 0.7592 |
| VOPD | RandomP10 | 5.1488 | 52.8615 | 0.9831 | 0 | 87.5287 | 0.0000 | 1144000 | 144000 | 1.1975 | 0.7386 |
| VOPD | RandomMedian | 5.5282 | 53.5930 | 1.0290 | 0 | 87.7870 | 0.0000 | 1838000 | 192000 | 1.0055 | 0.7435 |
| VOPD | RandomP90 | 6.0291 | 53.6043 | 0.9936 | 0 | 89.6050 | 0.0000 | 2418000 | 256000 | 1.2908 | 0.7546 |
| HNN | Original | 6.0000 | 55.6676 | 2.4544 | 16 | 203.1775 | 11.1420 | 2195456 | 163840 | 0.3028 | 4.6513 |
| HNN | RandomBest | 5.5382 | 57.8425 | 1.9979 | 11 | 218.4950 | 8.8873 | 1638400 | 114688 | 0.3070 | 4.7165 |
| HNN | RandomP10 | 6.1277 | 57.1463 | 2.0899 | 12 | 258.3568 | 5.5799 | 2170880 | 163840 | 0.5276 | 4.8127 |
| HNN | RandomMedian | 6.5107 | 56.8167 | 1.8480 | 10 | 296.6229 | 3.7078 | 2252800 | 229376 | 0.7128 | 4.9186 |
| HNN | RandomP90 | 6.9967 | 58.1060 | 1.5724 | 11 | 330.0264 | 10.8585 | 1957888 | 229376 | 0.7066 | 5.3260 |

## 5. 论文可用结论

- GEMM：10 个 GA seed 的最差结果仍优于 random best，支持 GA 不是随机重映射偶然收益。
- MPEG4：10 个 GA seed 的最差结果仍优于 random best，支持 GA 不是随机重映射偶然收益。
- VOPD：10 个 GA seed 的最差结果仍优于 random best，支持 GA 不是随机重映射偶然收益。
- HNN：10 个 GA seed 的最差结果仍优于 random best，支持 GA 不是随机重映射偶然收益。

解释口径：若某 workload 的 random best 接近 GA，优先从搜索空间偶然命中、目标权重偏向通信/拥塞项、以及 workload 负载/通信结构是否容易由纯随机打散热点来解释；不要把 random 结果解释为具备稳定优化能力，除非分布统计也支持。
