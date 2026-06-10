# Handoff Context - 2026-06-10

## Scope

This file summarizes the work completed after `HANDOFF_CONTEXT_2026-06-09.md`.
It covers:

- analysis of the third B-2 experiment in `out/B-2-v3-g60`
- generation of tables/figures for that experiment
- interpretation of GA / fitness / TR2 cost in discussion
- updates to the paper draft `paper/acp2026_draft.tex`

This is the preferred starting point for a new conversation if the goal is to continue paper writing, figure polishing, or additional B-2 analysis.

## Environment

- Workspace root: `D:\HNOCS`
- Current paper file:
  - `D:\HNOCS\paper\acp2026_draft.tex`
- Current compiled PDF:
  - `D:\HNOCS\paper\acp2026_draft.pdf`
- Latest paper figure directory:
  - `D:\HNOCS\paper\figures`

## Third Experiment: B-2-v3-g60

### User command actually used on host

```powershell
python experiment\B-2\run.py `
  --all `
  --workers 8 `
  --generations 60 `
  --population 50 `
  --seed 42 `
  --omnet-timeout 300 `
  -o out\B-2-v3-g60 `
  --omnet-bin "E:\mzj\HNOCS_mzj\libhnocs.exe" `
  --omnet-ned-paths "E:\mzj\HNOCS_mzj\src;E:\mzj\HNOCS_mzj\examples\task_driven" `
  --omnet-workdir "E:\mzj\HNOCS_mzj\examples\task_driven" `
  --omnet-ini "E:\mzj\HNOCS_mzj\examples\task_driven\omnetpp.ini" `
  --omnetpp-root "S:\omnetpp-6.3.0"
```

### Important structural observation

`out/B-2-v3-g60` contains only four workloads:

- `gemm`
- `hnn`
- `mpeg4`
- `vopd`

There is no `optic`.

Reason:
- current `experiment/B-2/run.py` defines `BENCHMARKS` as only `GEMM/MPEG4/VOPD/HNN`
- therefore `--all` now runs four workloads, not five

This must be kept consistent in the paper. Do not accidentally mix in old `optic` discussion from earlier result sets.

## Authoritative Code Paths

Use code, not background markdown, as the source of truth:

- `D:\HNOCS\experiment\B-2\run.py`
- `D:\HNOCS\experiment\B-2\ga_mapper.py`
- `D:\HNOCS\experiment\mapping\omnet_cost_model.py`

## B-2 Algorithm / Objective Used in v3

### GA settings

- population size = 50
- generation cap = 60
- crossover rate = 0.8
- mutation rate = 0.1
- elite count = 2
- tournament size = 3
- patience = 10 generations
- workers = 8
- seed = 42
- OMNeT++ timeout = 300 s

### Fitness / TR2 cost

The GA minimizes fitness, and in this experiment:

- `fitness == TR2 composite cost`

TR2 is a baseline-normalized weighted sum:

```text
TR2 =
  w_T          * f_thermal
+ w_sigma      * f_sigma
+ w_hot        * f_hot
+ w_makespan   * f_makespan
+ w_H          * f_comm
+ w_congestion * f_congestion
+ w_D          * f_dvfs
+ w_L          * f_load
+ w_E          * f_energy
```

Weights in v3:

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

### Important clarification already established

`w_peak = 0.0` does **not** mean DVFS is disabled.

Correct interpretation:

- OMNeT++ thermal throttling / DVFS is active in simulation
- `w_D = 0.4`, so DVFS penalty enters the objective
- `w_peak = 0.0` only disables an extra peak-over-threshold penalty term

Over-throttle behavior still influences optimization through:

- `f_hot`
- `f_dvfs`
- makespan changes caused by throttling
- energy changes caused by throttling

## Third Experiment Main Results

### Relative to baseline

| Workload | Cost | T_max | sigma_T | Hot PE | Makespan | DVFS | Comm | Energy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 6.000 -> 3.925 (-34.59%) | 54.91C -> 52.87C (-2.04C) | 2.554K -> 1.840K (-27.96%) | 6 -> 0 | 119.64us -> 115.97us (-3.06%) | 1.77% -> 0.00% | 104448 -> 70656 (-32.35%) | 1.569mJ -> 1.515mJ (-3.45%) |
| HNN | 6.000 -> 5.116 (-14.74%) | 55.70C -> 55.13C (-0.57C) | 3.054K -> 2.062K (-32.49%) | 16 -> 4 | 204.22us -> 264.69us (+29.61%) | 11.01% -> 0.63% | 2195456 -> 1761280 (-19.78%) | 4.661mJ -> 4.583mJ (-1.68%) |
| MPEG4 | 6.000 -> 4.035 (-32.75%) | 54.43C -> 52.73C (-1.69C) | 1.540K -> 1.459K (-5.28%) | 2 -> 0 | 121.73us -> 90.92us (-25.31%) | 0.06% -> 0.00% | 420000 -> 196000 (-53.33%) | 1.133mJ -> 0.969mJ (-14.48%) |
| VOPD | 5.000 -> 4.094 (-18.12%) | 52.19C -> 52.31C (+0.12C) | 1.151K -> 1.367K (+18.78%) | 0 -> 0 | 87.43us -> 42.35us (-51.56%) | 0.00% -> 0.00% | 1396000 -> 796000 (-42.98%) | 0.747mJ -> 0.500mJ (-33.05%) |

### Main interpretation

- all four workloads reduce composite cost
- `gemm` and `mpeg4` are the cleanest positive cases
- `hnn` is a heat-safety / DVFS improvement with a significant makespan regression
- `vopd` is a strong performance / communication / energy win with degraded thermal uniformity

This wording is important:

- do **not** claim that B-2 improves every metric on every workload
- do **not** claim HNN performance improved
- do **not** claim VOPD thermal uniformity improved

## Convergence / Run Quality

### Actual generations before early stopping

- GEMM: 52
- HNN: 47
- MPEG4: 23
- VOPD: 34

### Convergence observations

- all four workloads triggered early stopping before the 60-generation cap
- last improvement generations:
  - GEMM: 42
  - HNN: 37
  - MPEG4: 13
  - VOPD: 24
- unlike the earlier 30-generation run, this result set did **not** show `avg_fitness = Infinity` or `worst_fitness = Infinity` in `history.json`
- therefore the convergence curves for v3 are cleaner and more defensible than the v2 ones

## Comparison with Second Experiment (`out/B-2-v2`)

The second and third experiments use the same objective family, but the third run used a different explicit OMNeT++ invocation environment and 300s timeout. `metrics.json` does not record those path settings, so v3 should not be described as a strict continuation of v2.

Direct v3 minus v2 summary:

- GEMM:
  - composite slightly better
  - thermal slightly better
  - communication worse
- HNN:
  - composite better
  - thermal and hot-PE count better
  - makespan, communication, and energy worse than v2
- MPEG4:
  - identical to v2
  - because v2 had already converged at generation 23
- VOPD:
  - makespan and energy slightly better
  - communication worse
  - composite slightly worse than v2

Key consequence:

- do **not** claim “60 generations is uniformly better than 30 generations”

## Output Files Created for v3

These files were generated in `D:\HNOCS\out\B-2-v3-g60`:

- `analysis_report.md`
- `TODO_1_TO_8_COMPLETED.md`
- `make_figures_and_tables.py`
- `metrics_summary_table.csv`
- `metrics_relative_changes.csv`
- `cost_breakdown_weighted.csv`
- `convergence_history_flat.csv`
- `convergence_best_fitness.png`
- `convergence_population_fitness.png`
- `main_metrics_baseline_vs_b2.png`
- `cost_breakdown.png`

These are paper-ready or paper-supporting artifacts.

## Explanation Established in Conversation

### What “load” means in `f_load`

This was clarified explicitly:

- `f_load` is **not** CPU utilization
- it is a static mapping-side load imbalance metric
- per PE load = sum of assigned tasks’ nominal `compute_time_ns`
- `load_imbalance` is the normalized variance of those PE loads

Important case:

- `mpeg4` has high weighted `f_load`
- meaning GA accepted a more uneven static task distribution
- because that unevenness bought much better communication, makespan, and energy

### What fitness means

- in this experiment, fitness is the scalar GA optimizes
- lower is better
- numerically it is the same as the final `TR2 composite cost`

## Paper Work Completed

### Modified files

- updated:
  - `D:\HNOCS\paper\acp2026_draft.tex`
  - `D:\HNOCS\paper\acp2026_draft.pdf`
- added figures for the paper:
  - `D:\HNOCS\paper\figures\b2_v3_convergence_best_fitness.png`
  - `D:\HNOCS\paper\figures\b2_v3_cost_breakdown.png`
  - `D:\HNOCS\paper\figures\b2_v3_main_metrics.png`

### Paper changes made

The draft was updated to align with `B-2-v3-g60`:

- abstract numbers updated to v3
- GA settings updated from 30 generations / 60s timeout to 60 generations / 300s timeout
- OMNeT++ binary reference changed to `libhnocs.exe`
- GEMM detailed result table updated
- all-workload summary table updated
- convergence section updated to v3 actual-generation early-stop results
- cost breakdown figure and discussion added
- HNN and VOPD tradeoff wording tightened
- discussion, limitations, and conclusions updated to v3 numbers

### Compilation status

The paper was compiled successfully with:

```powershell
latexmk -xelatex -interaction=nonstopmode -halt-on-error acp2026_draft.tex
```

Observed compile status:

- no LaTeX errors
- no undefined references after rerun
- remaining warnings are only layout/font warnings:
  - font shape substitution
  - underfull hbox
  - one float placement adjustment

These are not logic blockers, but may still be worth polishing before submission.

## Current Paper Position

The paper now argues the following, and this framing should be preserved unless new data changes it:

1. B-2 reduces the composite objective on all four workloads.
2. GEMM and MPEG4 are the strongest “clean” wins.
3. VOPD is a performance / communication / energy win with worse thermal uniformity.
4. HNN is a thermal / DVFS win with worse makespan.
5. Therefore B-2 should be described as a multi-objective tradeoff optimizer, not a universal per-metric improver.

## Recommended Next Starting Prompts

Good starting prompts for a new conversation:

- `Please continue from HANDOFF_CONTEXT_2026-06-10_B2_V3_AND_PAPER.md and polish the paper wording for submission quality.`
- `Please continue from HANDOFF_CONTEXT_2026-06-10_B2_V3_AND_PAPER.md and help me add/adjust figures and captions in acp2026_draft.tex.`
- `Please continue from HANDOFF_CONTEXT_2026-06-10_B2_V3_AND_PAPER.md and help me prepare reviewer-safe statements about HNN and VOPD tradeoffs.`
- `Please continue from HANDOFF_CONTEXT_2026-06-10_B2_V3_AND_PAPER.md and help me design follow-up experiments with multiple seeds.`
