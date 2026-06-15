# Thermal-SA-TAS-Mapping baseline

Thermal-SA-TAS-Mapping is a TAS-inspired thermal simulated annealing baseline
for HNOCS task mapping experiments.  It is not an exact reproduction of
Mukherjee et al. 2019 because HNOCS uses static DAG CSV workloads on a 4x4
ONoC mesh, while the paper targets allocation plus scheduling for periodic
real-time applications on homogeneous/heterogeneous NoCs.

Current ACP paper note: this is one of the two main method-level baseline
methods, together with `CommAware-Heuristic`.  `Original` is not a baseline
method in the paper narrative; it is the initial/reference mapping used for
normalization and before/after comparison.

Search-stage boundaries:

- no proposed GA;
- no OMNeT++ candidate simulation;
- no B-2 full composite objective;
- no congestion, DVFS, PE plus optical communication energy, SOA, laser, or
  MRR tuning energy in the SA objective;
- communication and makespan are weak proxy terms only.

Proxy objective:

```text
J_TAS = 0.60 * Tmax_proxy / Tmax_ref
      + 0.25 * SigmaT_proxy / SigmaT_ref
      + 0.10 * HotCount_proxy / max(1, HotCount_ref)
      + 0.05 * MakespanProxy / Makespan_ref
```

Dry run:

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --workload gemm `
  --proxy-only `
  --dry-run
```

Proxy-only smoke:

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --workload gemm `
  --seed 42 `
  --proxy-only `
  --out out\thermal-sa-tas-v1-smoke-proxy
```

Full final evaluation:

```powershell
python experiment\thermal_sa_tas_baseline\run_thermal_sa_tas.py `
  --workload gemm `
  --seed 42 `
  --out out\thermal-sa-tas-v1-seed42 `
  --omnet-timeout 300 `
  --verbose
```

Default output:

```text
out/thermal-sa-tas-v1/<workload>/thermal_sa_tas/
```

The runner refuses to write into `out/B-2*` paths and protected paper result
directories.
