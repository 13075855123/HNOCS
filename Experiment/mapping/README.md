# mapping/ — Shared Infrastructure for Thermal-Aware Task Mapping

Common library used by B-1, B-2, and C experiment folders.

## Modules

| File | Purpose |
|------|---------|
| `task_graph.py` | CSV parsing, DAG representation, topological sort (Kahn's algorithm) |
| `cost_model.py` | Joint thermal+communication cost function with load balance penalty |
| `thermal_simulator.py` | Python replica of OMNeT++ RC thermal solver (TaskScheduler + PowerModel + ThermalSimulator) |
| `temperature_reader.py` | Load thermal snapshot JSON or OMNeT++ .sca, fallback to Tambient |
| `csv_writer.py` | Write optimized task-to-PE mapping as static CSV with successorPE |

## Thermal Simulator

`thermal_simulator.py` replicates the OMNeT++ RC thermal model exactly (explicit-Euler, 32-node, 100ns step). Three components:

- **TaskScheduler**: DAG-aware event-driven scheduling with PE serialization and communication delay
- **PowerModel**: compute/idle power per PE with DVFS thermal throttling (T > 46.85°C → 5%/°C slowdown)
- **ThermalSimulator**: RC thermal network solver, records per-PE temperature traces over time

## Input CSV Format

```
taskId, peId, compTime_ns, outSize_B, [succId:succPE, ...]
```

- `peId = -1`: GB injection task (preserved as-is)
- `peId = -2`: dynamic task (target for optimization)
- `peId >= 0`: static assignment (treated as fixed)

## Output CSV Format

Same format as input, with `peId` and `successorPE` filled by the optimizer for PE→PE direct routing.

## Benchmarks

| Benchmark | File | Tasks | Pattern |
|-----------|------|-------|---------|
| GEMM | `tasks_gemm.csv` | 10 | fork-join |
| MPEG-4 | `tasks_mpeg4.csv` | 11 | fork-join + branches |
| VOPD | `tasks_vopd.csv` | 12 | long pipeline |
| Optic Calib | `tasks_optic_calib.csv` | 16 | fully parallel (static only) |

## Experiment Folders

Current ACP paper terminology:

- `Original` is the initial/reference mapping used for normalization and
  before/after comparison.  It is not a baseline method in manuscript prose.
- The proposed method is the B-2 simulator-in-the-loop GA flow.
- The main method-level baselines are `Thermal-SA-TAS` and
  `CommAware-Heuristic`.

| Folder | Description | Current Paper Position |
|--------|-------------|---------------|
| `../B-1/` | Incremental greedy + multi-round iteration | Legacy/auxiliary analytical method |
| `../B-2/` | Simulator-in-the-loop genetic algorithm (GA) | Proposed method |
| `../comm_aware_baseline/` | Communication-aware heuristic | Main baseline method |
| `../thermal_sa_tas_baseline/` | TAS-inspired thermal simulated annealing | Main baseline method |
| `../thermal_rc_ls_baseline/` | RC-proxy local search | Auxiliary/archival comparison |
| `../thermal_greedy_baseline/` | TAPP-inspired greedy mapping | Exploratory negative-result archive |
| `../C/` | GNN + RL | Legacy/future learning-based path |

## Testing

```bash
python -m mapping.tests.test_task_graph
python -m mapping.tests.test_cost_model
```
