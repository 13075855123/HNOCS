# ThermalGreedy exploratory result: proxy-only smoke output

Status: keep for reproducibility; not a paper result.

This directory was produced by the proxy-only GEMM check. It does not contain
full OMNeT++ final metrics and should not be used in paper tables.

Command shape:

```powershell
python experiment\thermal_greedy_baseline\run_thermal_greedy.py --benchmarks gemm --proxy-only
```

Purpose:

- verify mapping generation
- verify `successorPE` rewriting
- verify GB tasks remain unmapped
- verify proxy output schema

Use the full-run directories for evaluated metrics.

