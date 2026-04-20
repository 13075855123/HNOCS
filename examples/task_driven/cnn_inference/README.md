# CNN Inference Example

## Description
Simulates a simplified 3-layer Convolutional Neural Network inference pipeline
mapped onto a 4×4 mesh NoC.

## Task Graph
```
Layer 1 (Convolution):
  Task0 @ PE0 → 100 ns, outputs 256 B → PE1, PE2, PE3, PE4

Layer 2 (Convolution):
  Task1 @ PE1 → 200 ns, outputs 128 B → PE5   (waits for Task0)
  Task2 @ PE2 → 200 ns, outputs 128 B → PE5   (waits for Task0)
  Task3 @ PE3 → 200 ns, outputs 128 B → PE5   (waits for Task0)
  Task4 @ PE4 → 200 ns, outputs 128 B → PE5   (waits for Task0)

Layer 3 (Fully-Connected):
  Task5 @ PE5 → 150 ns, no output             (waits for Task1-4)
```

## Data Flow
```
PE0 → (256 B) → PE1, PE2, PE3, PE4
PE1 → (128 B) → PE5
PE2 → (128 B) → PE5
PE3 → (128 B) → PE5
PE4 → (128 B) → PE5
```

## Running
```bash
cd examples/task_driven/cnn_inference
opp_run -u Cmdenv -f omnetpp.ini -n ../../../src
```

## Expected Results
- PE0 completes first (100 ns)
- PE1–PE4 complete after receiving PE0's data + 200 ns compute
- PE5 completes last after receiving all four layer-2 results + 150 ns compute

## Power Analysis
```bash
cd results
python3 ../../power_analysis/parse_power.py cnn_power.csv
```
