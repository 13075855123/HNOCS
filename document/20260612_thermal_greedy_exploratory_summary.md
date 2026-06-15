# ThermalGreedy / TAPP-inspired baseline exploratory summary

日期：2026-06-12

## 结论

`ThermalGreedy / TAPP-inspired` 已实现并完成多组验证，但当前不建议作为论文主 thermal-aware baseline。它可以保留为可复现实验记录和 negative result：简单 static thermal/load spreading 在当前 HNOCS ONoC OMNeT++ 模型中不能稳定降低峰值温度。

不要在论文中写成 exact reproduction of TAPP / Mosayyebzadeh / Shen，也不要声称它稳定降低 Tmax。

推荐称呼：

```text
TAPP-inspired static thermal/load spreading heuristic
```

## 代码位置

```text
D:\HNOCS\experiment\thermal_greedy_baseline\
```

其中 `EXPERIMENT_STATUS.md` 记录了完整测试目录、变体和结果解释。

## 输出目录

```text
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-gemm-full
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-baseline-temp
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-temp-placement-a1
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-placement-only-a1
```

## Tmax delta vs Original

| Variant | GEMM | MPEG4 | VOPD | HNN |
|---|---:|---:|---:|---:|
| compute_time | -0.020 K | -0.296 K | +1.877 K | +4.315 K |
| baseline_temp | -0.020 K | -0.561 K | +0.932 K | +4.305 K |
| baseline_temp + placement a1 | -0.236 K | +0.270 K | +0.440 K | +4.272 K |
| placement_only a1 | +0.521 K | -1.256 K | +1.124 K | +4.304 K |

## 写作边界

- GEMM/MPEG4 有局部可用变体，但不是统一配置下稳定改善所有 workload。
- VOPD 所有测试变体 Tmax 都升高。
- HNN 所有测试变体 Tmax 都升高约 4.3 K。
- 若保留该 baseline，只能作为 weak heuristic / exploratory baseline，不能作为强 thermal baseline。

## 下一步建议

不要继续只调 greedy proxy 权重。若需要更强 thermal baseline，应重新调研或实现更接近物理热模型的 non-GA 方法，例如 lightweight RC thermal proxy、cooling-resistance-aware mapping、time-overlap-aware heat proxy 或 thermal-aware local search。
