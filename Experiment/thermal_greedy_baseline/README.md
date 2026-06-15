# ThermalGreedy / TAPP-inspired heuristic

## Current status

Status: exploratory / not recommended as a main thermal-aware baseline method.

The implementation is kept for reproducibility and negative-result tracking.
Across the tested variants, ThermalGreedy does not consistently reduce peak
temperature. In particular, VOPD and HNN remain problematic, so paper text must
not claim that this method is a strong or stable peak-temperature-reduction
baseline method.

Current ACP paper note: this archive is not one of the main method-level
baselines.  The main paper baselines are `Thermal-SA-TAS` and
`CommAware-Heuristic`; `Original` is only an initial/reference mapping.

See `EXPERIMENT_STATUS.md` for the tested output directories, metric summary,
and interpretation.

This directory contains a minimal literature-inspired thermal-aware mapping
heuristic for the HNOCS ONoC experiments.

It is not an exact reproduction of TAPP, Mosayyebzadeh et al., or Shen et al.
It captures the core thermal-aware mapping idea under the same HNOCS/OMNeT++
evaluation pipeline used by B-2.

## Method

ThermalGreedy maps only `graph.mappable_task_ids` and leaves GB tasks untouched.
The default heat proxy is:

```text
heat_weight(task) = compute_time_ns(task)
```

The objective used during search is:

```text
ThermalProxy =
    max_load / ideal_load
  + alpha_sigma  * std_load / ideal_load
  + alpha_center * center_heat_penalty
  + alpha_temp_placement * initial/reference-temperature placement penalty
  + beta_comm    * normalized_comm_proxy
```

Communication is only a weak tie-breaker. The search objective does not use
OMNeT++ final peak temperature, DVFS penalty, optical tuning energy, makespan,
or TR2 composite cost. Those metrics are used only for final evaluation.

The optional `--heat-weight-mode baseline_temp` uses one initial/reference
(`Original`) static mapping observation to build per-PE temperature factors. It is not enabled by
default and is not a simulation-in-the-loop search over candidate mappings.

The optional `--alpha-temp-placement` uses the same one-shot initial/reference
temperature factors as a PE placement penalty. It is also disabled by default.

## Commands

Dry run without writing files or running OMNeT++:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm --dry-run --proxy-only
```

Proxy-only mapping generation without OMNeT++:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm --proxy-only
```

Full evaluation, only when explicitly needed:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm
```

Default output directory:

```text
out/thermal-greedy-baseline-v1
```

The runner refuses to write into `out/B-2*` paths and the protected
`B-2-v3-g60-seed42` / `B-2-v3-g60-seed43` result directories.
