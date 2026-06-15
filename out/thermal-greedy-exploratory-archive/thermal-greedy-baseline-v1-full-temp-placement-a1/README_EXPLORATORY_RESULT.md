# ThermalGreedy exploratory result: baseline-temperature heat plus placement

Status: valid OMNeT++ exploratory result; not recommended as main thermal
baseline.

Variant:

```text
heat_weight = compute_time_ns * Original_PE_temperature_factor(original_pe)
alpha_sigma = 0.5
alpha_center = 0.1
alpha_temp_placement = 1.0
beta_comm = 0.05
```

Both temperature uses come from one Original static mapping observation. This
is not simulation-in-the-loop candidate evaluation.

Command shape:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm,mpeg4,vopd,hnn --heat-weight-mode baseline_temp --alpha-temp-placement 1.0 --out out\thermal-greedy-baseline-v1-full-temp-placement-a1
```

Tmax delta vs Original:

| Workload | Delta |
|---|---:|
| GEMM | -0.236 K |
| MPEG4 | +0.270 K |
| VOPD | +0.440 K |
| HNN | +4.272 K |

Interpretation: this gives the best GEMM thermal result among tested variants,
but it is not stable across workloads.

