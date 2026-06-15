# CommAware-Heuristic Baseline

This directory implements only the `CommAware-Heuristic` baseline for the HNOCS
task-mapping experiments.  It is a literature-inspired communication-aware /
bandwidth-aware / hop-energy-aware baseline, not an exact reproduction of
Murali, Hu, Tosun, or any other prior implementation.

## Scope

The search objective is strictly communication-only:

```text
CommProxy(M) = raw_comm_cost(M) + lambda_cong * max_edge_load(M)
```

- `raw_comm_cost`: `sum producer.output_data_size * Manhattan_hops`
- `max_edge_load`: maximum bytes accumulated on one physical mesh edge using
  deterministic XY routing
- default `lambda_cong`: `0.25`

The mapper does not use peak temperature, temperature standard deviation, hot
PE count, DVFS penalty, makespan, optical metrics, energy, OMNeT++ results, or
`TR2_composite_cost` during search.  Those metrics are produced only by final
evaluation in `run_comm_aware.py`.

## Files

- `common.py`: B-2-compatible initial/reference mapping extraction, mappable conversion,
  assignment validation, OMNeT++ evaluator setup, grouped metrics, and summary
  helpers.
- `comm_proxy.py`: communication edge extraction, Manhattan hop distance, XY
  physical edge load, max edge load, and `CommProxy`.
- `comm_aware_mapper.py`: deterministic greedy construction plus optional local
  pairwise swaps.
- `run_comm_aware.py`: CLI runner for the initial/reference mapping (`Original` in output folder names) plus `comm_aware` only.
- `README.md`: this implementation note.

## Algorithm

1. Load the task graph from the same static CSV as B-2.
2. Extract the initial/reference static mapping (`Original`) from non-GB tasks with `peId >= 0`.
3. Convert those tasks to `peId = -2`, matching B-2 mappable-task semantics.
4. Build task communication edges.  Each edge uses the producer task's
   `output_data_size`.
5. Select the seed task with maximum incoming + outgoing traffic.
6. Place the seed on one of `[5, 6, 9, 10]`, choosing the lowest proxy score and
   then the lower PE id by deterministic tie-break.
7. Place remaining tasks by descending communication degree; each task may map
   to any PE in `0..15`.
8. Optionally perform deterministic pairwise local swaps.  A swap is accepted
   only when the communication proxy improves.  Static load imbalance is used
   only as a tie-breaker.
9. Final evaluation, when not using `--proxy-only`, runs the same
   `OmnetEvaluator` and `OmnetCostModel` schema as B-2.

## Commands

Proxy-only GEMM validation without OMNeT++:

```powershell
python experiment\comm_aware_baseline\run_comm_aware.py `
  --csv examples\task_driven\static\tasks_gemm_static.csv `
  --proxy-only `
  --out out\comm-aware-baseline-v1
```

In-memory proxy-only validation without persistent output:

```powershell
python experiment\comm_aware_baseline\run_comm_aware.py `
  --csv examples\task_driven\static\tasks_gemm_static.csv `
  --proxy-only `
  --no-write-proxy-outputs
```

Single workload OMNeT++ validation:

```powershell
python experiment\comm_aware_baseline\run_comm_aware.py `
  --csv examples\task_driven\static\tasks_gemm_static.csv `
  --out out\comm-aware-baseline-v1
```

All-workload batch:

```powershell
python experiment\comm_aware_baseline\run_comm_aware.py `
  --all `
  --out out\comm-aware-baseline-v1
```

## Output

```text
out/comm-aware-baseline-v1/
  runs_summary.csv
  aggregate_summary.json
  gemm/
    original/        # initial/reference mapping, not a baseline method
      metrics.json
      mapping.csv
      summary.txt
    comm_aware/
      metrics.json
      mapping.csv
      proxy.json
      summary.txt
```

With `--proxy-only`, `metrics.json` is intentionally omitted because OMNeT++ was
not run.
