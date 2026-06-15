# ThermalGreedy exploratory result: default compute-time variant

Status: valid OMNeT++ exploratory result; not recommended as main thermal
baseline.

Variant:

```text
heat_weight = compute_time_ns
alpha_sigma = 0.5
alpha_center = 0.1
alpha_temp_placement = 0.0
beta_comm = 0.05
```

Command shape:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm,mpeg4,vopd,hnn --out out\thermal-greedy-baseline-v1-full
```

Tmax delta vs Original:

| Workload | Delta |
|---|---:|
| GEMM | -0.020 K |
| MPEG4 | -0.296 K |
| VOPD | +1.877 K |
| HNN | +4.315 K |

Interpretation: default ThermalGreedy improves some proxy and communication
metrics, but does not reliably reduce peak temperature.

