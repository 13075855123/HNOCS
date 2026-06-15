# ThermalGreedy exploratory result: GEMM full sanity run

Status: valid OMNeT++ sanity check; not the final all-workload result.

This directory contains one full GEMM run for Original and ThermalGreedy. It
was used to confirm that the runner, mapping CSV, metrics schema, and
`run_status.valid_for_cost` path worked before batch runs.

Command shape:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm --out out\thermal-greedy-baseline-v1-gemm-full
```

Main observed result:

```text
TR2 cost: 6.0000 -> 5.2711
Tmax:     328.084 K -> 328.065 K
sigma_T:  2.143 K -> 2.069 K
```

Use `thermal-greedy-baseline-v1-full` for the corresponding all-workload
default-variant result.

