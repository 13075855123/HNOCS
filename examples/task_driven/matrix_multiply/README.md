# Matrix Multiply Example

## Description
Simulates a blocked matrix multiplication on a 4×4 mesh NoC.

Each of the 16 PEs computes one block of the result matrix C = A × B independently.
There are no inter-PE data dependencies in this example, so all 16 tasks start
simultaneously, compute for 100 ns and then finish.

## Task Graph
```
PE0  → C[0][0]  (100 ns, 64 B output)
PE1  → C[0][1]  (100 ns, 64 B output)
...
PE15 → C[3][3]  (100 ns, 64 B output)
```

## Running
```bash
cd examples/task_driven/matrix_multiply
opp_run -u Cmdenv -f omnetpp.ini -n ../../../src
```

## Expected Results
Each PE should complete exactly one task and record:
- `totalTasksCompleted = 1`
- `utilization ≈ 0.0001` (100 ns / 1 ms simulation)
- `avgPower ≈ 0.29 W` (weighted average of compute and idle power)

## Power Analysis
```bash
cd results
python3 ../../power_analysis/parse_power.py matrix_power.csv
```
