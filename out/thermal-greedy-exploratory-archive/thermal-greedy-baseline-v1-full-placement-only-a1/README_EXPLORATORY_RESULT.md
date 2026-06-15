# ThermalGreedy exploratory result: placement-only temperature penalty

Status: valid OMNeT++ exploratory result; not recommended as main thermal
baseline.

Variant:

```text
heat_weight = compute_time_ns
alpha_sigma = 0.5
alpha_center = 0.1
alpha_temp_placement = 1.0
beta_comm = 0.05
```

The placement penalty uses one Original static mapping temperature observation.
This is not simulation-in-the-loop candidate evaluation.

Command shape:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm,mpeg4,vopd,hnn --alpha-temp-placement 1.0 --out out\thermal-greedy-baseline-v1-full-placement-only-a1
```

Tmax delta vs Original:

| Workload | Delta |
|---|---:|
| GEMM | +0.521 K |
| MPEG4 | -1.256 K |
| VOPD | +1.124 K |
| HNN | +4.304 K |

Interpretation: this gives the best MPEG4 thermal result among tested
variants, but it worsens peak temperature on GEMM, VOPD, and HNN.

