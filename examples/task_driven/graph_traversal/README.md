# Graph Traversal Example

## Description
Simulates a Breadth-First Search (BFS) graph traversal distributed across
a 4×4 mesh NoC over 4 levels.

## Task Graph (BFS Tree)
```
Level 0:  PE0  (root)
            ↓ 64 B       ↓ 64 B
Level 1:  PE1           PE2
           ↓ 64B ↓ 64B   ↓ 64B ↓ 64B
Level 2:  PE3   PE4     PE5   PE6
           ↓32B   ↓32B   ↓32B   ↓32B
Level 3:  PE7   PE8     PE9   PE10  (leaf nodes)
```

## Data Flow Summary
| Sender | Receiver | Data Size |
|--------|----------|-----------|
| PE0    | PE1, PE2 | 64 B each |
| PE1    | PE3, PE4 | 64 B each |
| PE2    | PE5, PE6 | 64 B each |
| PE3    | PE7      | 32 B      |
| PE4    | PE8      | 32 B      |
| PE5    | PE9      | 32 B      |
| PE6    | PE10     | 32 B      |

## Running
```bash
cd examples/task_driven/graph_traversal
opp_run -u Cmdenv -f omnetpp.ini -n ../../../src
```

## Expected Results
- PE0 completes first (50 ns)
- PE1 and PE2 complete after receiving PE0's data + 50 ns
- PE3–PE6 complete in the next wave
- PE7–PE10 complete last
- PEs 11–15 are idle (no tasks assigned in this application)

## Power Analysis
```bash
cd results
python3 ../../power_analysis/parse_power.py graph_power.csv
```
