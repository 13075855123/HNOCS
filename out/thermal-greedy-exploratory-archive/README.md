# ThermalGreedy exploratory output index

Date: 2026-06-12

This archive groups all exploratory / negative-result records for the
ThermalGreedy / TAPP-inspired heuristic. These results are not part of the
current ACP paper's two main method-level baseline methods
(`Thermal-SA-TAS` and `CommAware-Heuristic`), because the tested variants do
not consistently reduce OMNeT++ peak temperature.

Project-level summary:

```text
D:\HNOCS\document\20260612_thermal_greedy_exploratory_summary.md
```

Implementation summary:

```text
D:\HNOCS\experiment\thermal_greedy_baseline\EXPERIMENT_STATUS.md
```

## Directories

| Directory | Scope | Status |
|---|---|---|
| `D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1` | GEMM proxy-only smoke output | No OMNeT++ final metrics; keep only as mapping/proxy check |
| `D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-gemm-full` | GEMM full sanity run | Valid OMNeT++; sanity check only |
| `D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full` | All workloads, default compute-time heat proxy | Valid OMNeT++; exploratory result |
| `D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-baseline-temp` | All workloads, baseline-temperature heat weight | Valid OMNeT++; exploratory result |
| `D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-temp-placement-a1` | All workloads, baseline-temperature heat weight plus placement penalty | Valid OMNeT++; exploratory result |
| `D:\HNOCS\out\thermal-greedy-exploratory-archive\thermal-greedy-baseline-v1-full-placement-only-a1` | All workloads, compute-time heat weight plus placement penalty | Valid OMNeT++; exploratory result |

## Key conclusion

Tmax delta vs initial/reference mapping (`Original`):

| Variant | GEMM | MPEG4 | VOPD | HNN |
|---|---:|---:|---:|---:|
| compute_time | -0.020 K | -0.296 K | +1.877 K | +4.315 K |
| baseline_temp | -0.020 K | -0.561 K | +0.932 K | +4.305 K |
| baseline_temp + placement a1 | -0.236 K | +0.270 K | +0.440 K | +4.272 K |
| placement_only a1 | +0.521 K | -1.256 K | +1.124 K | +4.304 K |

ThermalGreedy can remain as a weak exploratory heuristic, but it is not
recommended as a main thermal-aware baseline method.
