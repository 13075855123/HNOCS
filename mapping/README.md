# Direction B: Offline Static Thermal-Aware Task Mapping

Design-time optimization of task-to-PE mapping for the HNOCS 2D Mesh NoC simulator. Uses Simulated Annealing (SA) to minimize a joint cost of temperature and communication distance.

## Quick Start

```bash
# First-pass: communication-only optimization (uniform temperature)
python -m mapping.run_mapping \
    --input examples/task_driven/tasks_gemm.csv \
    --output examples/task_driven/tasks_gemm_optimized.csv \
    --rows 4 --cols 4 --wT 1.0 --wH 0.5

# Two-pass workflow:
# 1. Run OMNeT++ simulation to get thermal profile
#    → produces thermal_snapshot.json
# 2. Re-optimize with thermal data
python -m mapping.run_mapping \
    --input examples/task_driven/tasks_gemm.csv \
    --output examples/task_driven/tasks_gemm_optimized.csv \
    --temperature thermal_snapshot.json \
    --wT 1.0 --wH 0.5 --verbose
# 3. Re-run OMNeT++ with the optimized static CSV
```

## Cost Function

```
cost(PE_j, task_i) = w_T * (T_j - Tambient)
                   + w_H * Σ hops(PE_pred, PE_j) * dataSize(pred, i)
                   + λ_load * variance(PE loads)
```

- **Thermal term**: penalizes hot PEs
- **Communication term**: penalizes long-distance data transfers weighted by data size
- **Load balance term**: prevents packing all tasks onto a single PE

Tasks are processed in topological order, so predecessors are always assigned before dependents.

## Simulated Annealing Algorithm

| Parameter | Default | Description |
|-----------|---------|-------------|
| `T_init` | 1000 | Initial temperature |
| `T_min` | 0.01 | Stopping temperature |
| `alpha` | 0.95 | Cooling rate per outer step |
| `iters_per_T` | 100 | Inner-loop iterations per temperature |
| `max_idle` | 30 | Early-stop idle steps |
| `max_tasks_per_pe` | auto | Hard load cap (auto: ceil(N/P)×2) |
| `restarts` | 1 | Number of independent SA runs |

Initial solution is generated greedily in topological order. Each perturbation moves one random task to a different PE (respecting the load cap). Metropolis criterion accepts uphill moves with probability `exp(-Δcost / T)`.

## Two-Pass Workflow

### Pass 1 — Get thermal profile
```
cd examples/task_driven
opp_run_dbg -l ..\..\src\libhnocs_dbg.dll -n ..\..\src;. \
    omnetpp.ini -u Cmdenv -c Dynamic
# Produces: thermal_snapshot.json (via ThermalModel::writeThermalSnapshot)
```

### Between passes — Optimize
```
cd D:\HNOCS
python -m mapping.run_mapping \
    --input examples/task_driven/tasks_gemm.csv \
    --output examples/task_driven/tasks_gemm_optimized.csv \
    --temperature examples/task_driven/thermal_snapshot.json \
    --wT 1.0 --wH 0.5
```

### Pass 2 — Run with optimized mapping
```
cd examples/task_driven
opp_run_dbg -l ..\..\src\libhnocs_dbg.dll -n ..\..\src;. \
    omnetpp.ini -u Cmdenv -c General \
    --**.csvFile=tasks_gemm_optimized.csv --**.remapToDynamic=false
```

## Input CSV Format

```
taskId, peId, compTime_ns, outSize_B, [succId:succPE, ...]
```

- `peId = -1`: GB injection task (preserved as-is)
- `peId = -2`: dynamic task (target for optimization)
- `peId >= 0`: static assignment (treated as fixed)

## Output CSV Format

Same format as input, with:
- `peId`: optimized PE assignment for each mappable task
- `successorPE`: set to the successor task's assigned PE for direct PE→PE routing
- GB tasks preserved unchanged

## Benchmarks

| Benchmark | File | Tasks | Pattern |
|-----------|------|-------|---------|
| GEMM | `tasks_gemm.csv` | 10 | fork-join |
| MPEG-4 | `tasks_mpeg4.csv` | 11 | fork-join + branches |
| VOPD | `tasks_vopd.csv` | 12 | long pipeline |
| Optic Calib | `tasks_optic_calib.csv` | 16 | fully parallel (static only) |

## OMNeT++ Integration

The `ThermalModel::writeThermalSnapshot()` method (in `src/thermal/ThermalTrace.cc`) writes final PE temperatures to `thermal_snapshot.json` at simulation end. This file is read by `temperature_reader.py` for the second optimization pass.

## Testing

```bash
python -m mapping.tests.test_task_graph
python -m mapping.tests.test_cost_model
python -m mapping.tests.test_sa_optimizer
python -m mapping.tests.test_integration
```
