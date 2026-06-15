# ThermalGreedy exploratory result: baseline-temperature heat weights

Status: valid OMNeT++ exploratory result; not recommended as main thermal
baseline.

Variant:

```text
heat_weight = compute_time_ns * Original_PE_temperature_factor(original_pe)
alpha_sigma = 0.5
alpha_center = 0.1
alpha_temp_placement = 0.0
beta_comm = 0.05
```

The Original PE temperature factor comes from one Original static mapping
observation. It is not simulation-in-the-loop candidate evaluation.

Command shape:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm,mpeg4,vopd,hnn --heat-weight-mode baseline_temp --out out\thermal-greedy-baseline-v1-full-baseline-temp
```

Tmax delta vs Original:

| Workload | Delta |
|---|---:|
| GEMM | -0.020 K |
| MPEG4 | -0.561 K |
| VOPD | +0.932 K |
| HNN | +4.305 K |

Interpretation: this improves MPEG4 and reduces the VOPD penalty, but HNN
still fails as a peak-temperature baseline.

