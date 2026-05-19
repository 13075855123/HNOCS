# Direction B: Offline Static Thermal-Aware Task Mapping

Design-time optimization of task-to-PE mapping for the HNOCS 2D Mesh NoC simulator. Uses Simulated Annealing (SA) to minimize a joint cost of temperature and communication distance.

## Quick Start

### Single-round optimization (no thermal data)
```bash
python -m mapping.run_mapping \
    --input examples/task_driven/tasks_gemm.csv \
    --output examples/task_driven/tasks_gemm_optimized.csv \
    --rows 4 --cols 4 --wT 1.0 --wH 0.5
```

### Multi-round iterative optimization (recommended)
```bash
python -m mapping.iterative_mapping \
    --input examples/task_driven/tasks_gemm.csv \
    --output examples/task_driven/tasks_gemm_iterative.csv \
    --rows 4 --cols 4 --wT 1.0 --wH 0.5 \
    --max-rounds 20 --ema-alpha 0.5 --verbose
```

The iterative mapper runs a **Python-native thermal simulator** (RC network + task scheduler + power model) inside the optimization loop. It alternates between SA optimization and thermal simulation until the mapping converges (cycle detected) or max rounds reached. No OMNeT++ required during optimization.

## How It Works

```
Task Graph (CSV)  →  SA initial mapping (uniform temp)
                           ↓
                    Python Thermal Simulator
                    (schedule tasks → power trace → RC thermal solver)
                           ↓
                    PE temperature distribution
                           ↓
                    SA re-optimize (avoid hotspots)
                           ↓
                    Repeat until convergence
                           ↓
                    Final optimized static CSV
                           ↓
                    OMNeT++ verification (one run)
```

### Python Thermal Simulator (`thermal_simulator.py`)
- **TaskScheduler**: DAG-aware event-driven scheduling with PE serialization and communication delay
- **PowerModel**: compute/idle power per PE with DVFS thermal throttling (T > 46.85°C → slowdown)
- **ThermalSimulator**: explicit-Euler RC thermal network solver (replicates `ThermalModel::updateTemperature()` from OMNeT++ exactly)

### Convergence Criteria
1. **Cycle detection**: assignment hash repeats → converged
2. **Temperature stability**: all PE temps change < 1 K vs previous round
3. **Max rounds**: stops at 20 by default

### EMA Temperature Smoothing
The `--ema-alpha` parameter (default 0.5) applies exponential moving average to PE temperatures between rounds. This damps oscillation caused by the temperature→mapping→temperature feedback loop. Alpha=1.0 disables smoothing.

## OMNeT++ Verification (optional)
```bash
cd examples/task_driven
opp_run_dbg -l ..\..\src\libhnocs_dbg.dll -n ..\..\src;. \
    omnetpp.ini -u Cmdenv -c General \
    --**.csvFile=tasks_gemm_iterative.csv --**.remapToDynamic=false
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
