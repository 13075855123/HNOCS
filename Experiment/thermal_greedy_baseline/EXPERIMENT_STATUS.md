# ThermalGreedy exploratory status

Date: 2026-06-12

## Decision

ThermalGreedy is preserved as an exploratory literature-inspired heuristic, but
it is not recommended as the main thermal-aware baseline for the paper.

The method is useful as a reproducible negative result: simple static
thermal/load spreading does not reliably reduce OMNeT++ peak temperature in
this HNOCS ONoC setup.

## Scope

This code only implements ThermalGreedy / TAPP-inspired mapping. It does not
implement Random, CommAware, SA, NSGA-II, or any other baseline.

The search objective does not use candidate OMNeT++ final metrics:

- no final peak temperature
- no DVFS penalty
- no makespan
- no optical tuning energy
- no TR2 composite cost

Optional temperature factors are built only from one Original static mapping
observation. They are not simulation-in-the-loop candidate evaluations.

## Tested result directories

```text
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-gemm-full
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-baseline-temp
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-temp-placement-a1
D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-placement-only-a1
```

## Variants tested

| Variant | Meaning |
|---|---|
| `compute_time` | Default heat proxy: `heat_weight = compute_time_ns` |
| `baseline_temp` | Task heat weight multiplied by Original per-PE temperature factor |
| `baseline_temp + placement a1` | `baseline_temp` plus `--alpha-temp-placement 1.0` |
| `placement_only a1` | compute-time heat weight plus `--alpha-temp-placement 1.0` |

## Key result: Tmax delta vs Original

| Variant | GEMM | MPEG4 | VOPD | HNN |
|---|---:|---:|---:|---:|
| `compute_time` | -0.020 K | -0.296 K | +1.877 K | +4.315 K |
| `baseline_temp` | -0.020 K | -0.561 K | +0.932 K | +4.305 K |
| `baseline_temp + placement a1` | -0.236 K | +0.270 K | +0.440 K | +4.272 K |
| `placement_only a1` | +0.521 K | -1.256 K | +1.124 K | +4.304 K |

## Interpretation

- GEMM can be improved by the enhanced temperature-placement variant.
- MPEG4 can be improved by placement-only temperature penalty.
- VOPD remains weak: all tested variants increase peak temperature.
- HNN fails as a peak-temperature baseline: all tested variants increase peak
  temperature by about 4.3 K, although several variants reduce temperature
  standard deviation and communication cost.

Therefore, ThermalGreedy should not be described as a robust
peak-temperature-reduction baseline. If used at all, describe it as:

```text
TAPP-inspired static thermal/load spreading heuristic
```

and explicitly report its workload-dependent tradeoffs.

## Recommended next direction

Do not continue tuning only `alpha` weights for this greedy proxy. A stronger
thermal baseline likely needs a better non-GA thermal model, such as:

- lightweight RC thermal proxy
- power-density / cooling-resistance-aware placement
- thermal-aware local search with a physical thermal proxy
- thermal-aware list scheduling or time-overlap-aware heat proxy
