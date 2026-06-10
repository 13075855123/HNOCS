# Handoff Context - 2026-06-09

## Scope

This document summarizes the context established in the current conversation so a new thread can continue from the same state without redoing the analysis.

## Environment

- Workspace root: `D:\HNOCS`
- User-provided runtime setup used for the second experiment:
  - `OMNETPP_ROOT=D:\omnetpp\omnetpp-6.3.0`
  - `PATH` prefixed with:
    - `D:\HNOCS`
    - `D:\omnetpp\omnetpp-6.3.0\bin`
    - `D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\clang64\bin`
    - `D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\usr\bin`

## Experiment Runs

Two experiment result sets were analyzed:

1. First experiment:
   - Output directory: `D:\HNOCS\out\B-2`
2. Second experiment:
   - Command used by user:
     - `python experiment\B-2\run.py --all --workers 8 --generations 30 --population 50 --seed 42 -o out\B-2-v2`
   - Output directory: `D:\HNOCS\out\B-2-v2`

Both runs include five workloads:

- `gemm`
- `hnn`
- `mpeg4`
- `optic`
- `vopd`

Each workload directory contains:

- `metrics.json`
- `history.json`
- `remapped.csv`
- `summary.txt`

## Relevant Code Paths

Primary implementation files referenced during analysis:

- [`D:\HNOCS\experiment\B-2\run.py`](</D:/HNOCS/experiment/B-2/run.py>)
- [`D:\HNOCS\experiment\B-2\ga_mapper.py`](</D:/HNOCS/experiment/B-2/ga_mapper.py>)
- [`D:\HNOCS\experiment\mapping\omnet_cost_model.py`](</D:/HNOCS/experiment/mapping/omnet_cost_model.py>)

Background docs mentioned:

- [`D:\HNOCS\CLAUDE.md`](</D:/HNOCS/CLAUDE.md>)
- [`D:\HNOCS\paper\B1_algorithm.md`](</D:/HNOCS/paper/B1_algorithm.md>)

Important interpretation rule:

- Background markdown docs are not the final source of truth.
- The code in `run.py`, `ga_mapper.py`, and `omnet_cost_model.py` is the authoritative source for experiment behavior.

## Objective Function Difference

This is the main reason the two experiment runs must be compared carefully.

### First experiment: `out/B-2`

The first run uses the older objective with these visible weights in `metrics.json`:

- `w_T = 1.0`
- `w_H = 1.0`
- `w_D = 2.0`
- `w_L = 0.5`
- `w_peak = 0.0`

This version is dominated by:

- peak temperature
- communication
- DVFS penalty
- load imbalance

### Second experiment: `out/B-2-v2`

The second run uses `fitness = baseline_normalized_v2` with these visible weights:

- `w_T = 1.0`
- `w_sigma = 1.0`
- `w_hot = 0.6`
- `w_makespan = 1.2`
- `w_H = 0.4`
- `w_congestion = 0.7`
- `w_D = 0.4`
- `w_L = 0.2`
- `w_E = 0.5`
- `w_peak = 0.0`

This version explicitly optimizes:

- peak temperature
- temperature standard deviation `sigma_T`
- hot-PE count
- makespan
- communication cost
- congestion proxy
- DVFS penalty
- load imbalance
- total energy

### Comparison consequence

`TR2_composite_cost` values from `out/B-2` and `out/B-2-v2` are not directly comparable as absolute numbers because the cost function changed.

Directly comparable cross-run quantities are the raw metrics:

- `T_max`
- `sigma_T`
- `N_hot`
- `makespan`
- `DVFS penalty`
- `communication cost`
- `total energy`

## Second Experiment Summary (`out/B-2-v2`)

This table was cleaned up during the conversation and is the preferred summary format.

### Absolute values

| Workload | TR2 Cost | T_max | sigma_T | Hot PE | Makespan | Comm | Energy |
|---|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 6.000 -> 3.978 | 54.9C -> 53.1C | 2.55K -> 1.89K | 6 -> 0 | 119.6us -> 115.9us | 104448 -> 62464 | 1.569mJ -> 1.515mJ |
| HNN | 6.000 -> 5.252 | 55.7C -> 56.0C | 3.05K -> 2.19K | 16 -> 8 | 204.2us -> 243.2us | 2195456 -> 1638400 | 4.661mJ -> 4.517mJ |
| MPEG4 | 6.000 -> 4.035 | 54.4C -> 52.7C | 1.54K -> 1.46K | 2 -> 0 | 121.7us -> 90.9us | 420000 -> 196000 | 1.133mJ -> 0.969mJ |
| Optic | 3.700 -> 3.692 | 48.8C -> 48.8C | 1.02K -> 0.96K | 0 -> 0 | 9.2us -> 9.2us | 0 -> 0 | 0.106mJ -> 0.103mJ |
| VOPD | 5.000 -> 4.063 | 52.2C -> 52.3C | 1.15K -> 1.40K | 0 -> 0 | 87.4us -> 43.3us | 1396000 -> 646000 | 0.747mJ -> 0.510mJ |

### Relative changes

| Workload | TR2 Cost | T_max | sigma_T | Makespan | Comm | Energy | Converged |
|---|---:|---:|---:|---:|---:|---:|---|
| GEMM | -33.70% | -1.79C | -26.02% | -3.13% | -40.20% | -3.45% | No |
| HNN | -12.47% | +0.34C | -28.39% | +19.10% | -25.37% | -3.10% | No |
| MPEG4 | -32.75% | -1.70C | -5.28% | -25.31% | -53.33% | -14.48% | Yes |
| Optic | -0.23% | -0.02C | -6.13% | ~0% | 0% | -3.32% | Yes |
| VOPD | -18.74% | +0.08C | +21.67% | -50.47% | -53.72% | -31.75% | No |

### Main conclusions for `B-2-v2`

- `gemm` and `mpeg4` are the cleanest positive results.
- `hnn` improves composite tradeoff but still regresses in makespan and slightly in peak temperature.
- `vopd` gains strongly in makespan, communication, and energy, but `sigma_T` becomes worse.
- `optic` has very limited headroom and shows only marginal gains.

### Convergence / quality caveats

- `gemm`, `hnn`, and `vopd` did not converge within 30 generations.
- In those cases, best fitness still improved near generations 27-28, so the generation cap may be truncating further gains.
- `history.json` often contains `avg_fitness = Infinity` and `worst_fitness = Infinity` for several workloads, indicating invalid or failed individuals in the population.
- This does not invalidate the final best mapping, but it limits how confidently the population-average history can be interpreted.

## First vs Second Experiment

### Shared patterns

- Both runs substantially reduce communication cost on most workloads.
- Both runs reduce or eliminate hot PEs for `gemm`, `mpeg4`, and partially for `hnn`.
- `optic` shows only weak gains in both runs.
- `vopd` shows better performance and communication but worsened `sigma_T` in both runs.

### Main differences

- The first run is more aggressive on communication and DVFS reduction.
- The second run is more balanced and generally better on makespan and energy.
- The second run fixes the especially bad `mpeg4` behavior seen in the first run.
- The second run still leaves `hnn` as a difficult tradeoff case, but it is less bad on makespan than the first run.

### Direct final-state comparison: second minus first

| Workload | T_max | sigma_T | Hot PE | Makespan | Comm | Energy | Short read |
|---|---:|---:|---:|---:|---:|---:|---|
| GEMM | -0.61C | -0.08K | 0 | +0.10us | +20480 | -0.011mJ | second is thermally better, communication worse |
| HNN | +1.49C | +0.16K | +5 | -118.55us | +581632 | -0.597mJ | second is faster and lower-energy, but hotter and worse on communication |
| MPEG4 | -0.23C | +0.14K | 0 | -44.17us | -4000 | -0.246mJ | second is clearly better overall except slightly worse `sigma_T` |
| Optic | -0.02C | -0.03K | 0 | -0.02us | 0 | -0.001mJ | nearly identical; second is marginally better |
| VOPD | +0.20C | +0.07K | 0 | -11.12us | +80000 | -0.064mJ | second is faster and lower-energy, but thermally worse |

### Direct interpretation

The second experiment should not be described as uniformly better than the first.

A precise description is:

- the second experiment sacrifices some communication / thermal extremeness
- in exchange for better balance on makespan and energy
- with `mpeg4` showing the clearest improvement from that redesign
- and `hnn` remaining the hardest workload

## User-Facing Conclusions Already Established in Conversation

These were the main narrative points already agreed during the discussion:

- Do not claim that B-2 improves every metric on every benchmark.
- For the second experiment, the strongest statement is that it consistently lowers the new composite objective, but individual metrics still trade off.
- `hnn` must be treated as a tradeoff case, not a clean performance win.
- `vopd` must be treated as a performance/energy win with degraded thermal uniformity.
- If these results are used in a report or paper, the cost-function change between the two runs must be stated explicitly.

## Recommended Next Thread Starting Point

If a new conversation continues this work, a good opening prompt is:

`Please continue from HANDOFF_CONTEXT_2026-06-09.md. I want to turn these experiment results into [paper text / report tables / new parameter tuning / rerun plan].`

