# ThermalRC-LS auxiliary baseline

ThermalRC-LS is a lightweight thermal-aware baseline for the HNOCS task
mapping experiments.

Current ACP paper note: this is an auxiliary/archival comparison, not one of
the two main method-level baselines.  The main paper baselines are
`Thermal-SA-TAS` and `CommAware-Heuristic`; `Original` is only an
initial/reference mapping.

It is intentionally different from the proposed B-2 GA:

- candidate mappings are not evaluated by OMNeT++;
- the search objective is not the B-2 full composite cost;
- makespan, congestion, DVFS penalty, and PE plus optical communication energy
  are not optimized during search;
- communication is only a weak Manhattan-distance tie-breaker;
- one initial/reference (`Original`) static OMNeT++ observation may be used only to calibrate the
  thermal proxy.

The proxy is:

```text
P_k(m) = leakage_base_k + sum task_power_i
T_proxy(m) = Tamb + R * P(m)

J_RC = 0.55 * Tmax_proxy / Tmax_orig
     + 0.30 * SigmaT_proxy / SigmaT_orig
     + 0.10 * HotCount_proxy / max(1, HotCount_orig)
     + 0.05 * CommProxy / Comm_orig
```

`R` is calibrated as low-dimensional Manhattan-distance bins when an
initial/reference temperature vector is available.  Otherwise the runner falls back to a
distance-decay synthetic matrix.

## Commands

Dry run:

```powershell
python experiment\thermal_rc_ls_baseline\run_thermal_rc_ls.py `
  --workload gemm `
  --proxy-only `
  --dry-run
```

Proxy-only mapping generation:

```powershell
python experiment\thermal_rc_ls_baseline\run_thermal_rc_ls.py `
  --workload gemm `
  --seed 42 `
  --init original `
  --proxy-only `
  --out out\thermal-rc-ls-v1-smoke-proxy
```

Full evaluation for one workload:

```powershell
python experiment\thermal_rc_ls_baseline\run_thermal_rc_ls.py `
  --workload gemm `
  --seed 42 `
  --init original `
  --out out\thermal-rc-ls-v1-smoke-full `
  --omnet-timeout 300 `
  --verbose
```

Default output:

```text
out/thermal-rc-ls-v1/<workload>/thermal_rc_ls/
```

The runner refuses to write into `out/B-2*` paths and protected paper result
directories.
