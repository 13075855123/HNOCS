# B-2-v3-g60 seed42 / seed43 / baseline comparison

Source directories:

- `D:\HNOCS\out\B-2-v3-g60-seed42`
- `D:\HNOCS\out\B-2-v3-g60-seed43`

Both runs use `population=50`, `generations=60`, `workers=8`, `omnet-timeout=300`, and `fitness=baseline_normalized_v2`. Baseline values are identical across seed42 and seed43 metrics.

## Baseline

| Workload | Cost | Tmax (C) | Sigma (K) | Hot PE | Makespan (us) | DVFS (%) | Comm | Congestion | Load imbalance | Energy (mJ) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 6.0000 | 54.91 | 2.554 | 6 | 119.635 | 1.768 | 104448 | 22528 | 0.9203 | 1.568842 |
| MPEG4 | 6.0000 | 54.43 | 1.540 | 2 | 121.728 | 0.065 | 420000 | 88000 | 0.5671 | 1.133477 |
| VOPD | 5.0000 | 52.19 | 1.151 | 0 | 87.427 | 0.000 | 1396000 | 252000 | 0.3580 | 0.747293 |
| HNN | 6.0000 | 55.70 | 3.054 | 16 | 204.219 | 11.014 | 2195456 | 163840 | 0.3028 | 4.661220 |

## Per-seed B-2 results versus baseline

Positive improvement means lower is better relative to baseline. For `T_drop_C`, positive means B-2 reduced peak temperature.

| Workload | Seed | Cost | Cost improvement | Tmax (C) | T_drop (C) | Sigma (K) | Sigma improvement | Hot PE | Makespan (us) | Makespan improvement | DVFS (%) | Comm | Comm improvement | Congestion | Congestion improvement | Energy (mJ) | Energy improvement | Generations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 42 | 3.9245 | 34.59% | 52.87 | 2.04 | 1.840 | 27.96% | 0 | 115.971 | 3.06% | 0.000 | 70656 | 32.35% | 10240 | 54.55% | 1.514744 | 3.45% | 52 |
| GEMM | 43 | 3.8490 | 35.85% | 52.98 | 1.93 | 1.881 | 26.36% | 0 | 115.939 | 3.09% | 0.000 | 60416 | 42.16% | 8192 | 63.64% | 1.515632 | 3.39% | 20 |
| MPEG4 | 42 | 4.0350 | 32.75% | 52.73 | 1.69 | 1.459 | 5.28% | 0 | 90.921 | 25.31% | 0.000 | 196000 | 53.33% | 36000 | 59.09% | 0.969304 | 14.48% | 23 |
| MPEG4 | 43 | 3.8743 | 35.43% | 52.65 | 1.78 | 1.530 | 0.65% | 0 | 79.226 | 34.92% | 0.000 | 192000 | 54.29% | 24000 | 72.73% | 0.904710 | 20.18% | 27 |
| VOPD | 42 | 4.0940 | 18.12% | 52.31 | -0.12 | 1.367 | -18.78% | 0 | 42.347 | 51.56% | 0.000 | 796000 | 42.98% | 86000 | 65.87% | 0.500339 | 33.05% | 34 |
| VOPD | 43 | 4.0851 | 18.30% | 52.03 | 0.16 | 1.372 | -19.21% | 0 | 42.363 | 51.55% | 0.000 | 634000 | 54.58% | 72000 | 71.43% | 0.505658 | 32.33% | 43 |
| HNN | 42 | 5.1158 | 14.74% | 55.13 | 0.57 | 2.062 | 32.49% | 4 | 264.691 | -29.61% | 0.627 | 1761280 | 19.78% | 131072 | 20.00% | 4.582881 | 1.68% | 47 |
| HNN | 43 | 5.2112 | 13.15% | 55.21 | 0.49 | 2.239 | 26.69% | 8 | 261.859 | -28.22% | 1.088 | 1835008 | 16.42% | 122880 | 25.00% | 4.596656 | 1.39% | 46 |

## Seed43 relative to seed42

Negative percentage means seed43 is lower than seed42.

| Workload | Cost change | Tmax change | Sigma change | Hot PE | Makespan change | Comm change | Congestion change | Energy change | Generations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | -1.92% | +0.113 C | +0.041 K | 0 -> 0 | -0.03% | -14.49% | -20.00% | +0.06% | 52 -> 20 |
| MPEG4 | -3.98% | -0.083 C | +0.071 K | 0 -> 0 | -12.86% | -2.04% | -33.33% | -6.66% | 23 -> 27 |
| VOPD | -0.22% | -0.280 C | +0.005 K | 0 -> 0 | +0.04% | -20.35% | -16.28% | +1.06% | 34 -> 43 |
| HNN | +1.86% | +0.083 C | +0.177 K | 4 -> 8 | -1.07% | +4.19% | -6.25% | +0.30% | 47 -> 46 |

## Two-seed average

| Workload | Avg cost | Cost SD | Avg cost improvement | Avg T_drop | Avg sigma improvement | Avg hot PE | Avg makespan improvement | Avg comm improvement | Avg energy improvement |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GEMM | 3.8868 | 0.0377 | 35.22% | 1.98 C | 27.16% | 0.0 | 3.08% | 37.25% | 3.42% |
| MPEG4 | 3.9546 | 0.0803 | 34.09% | 1.74 C | 2.97% | 0.0 | 30.11% | 53.81% | 17.33% |
| VOPD | 4.0895 | 0.0044 | 18.21% | 0.02 C | -18.99% | 0.0 | 51.55% | 48.78% | 32.69% |
| HNN | 5.1635 | 0.0477 | 13.94% | 0.53 C | 29.59% | 6.0 | -28.92% | 18.10% | 1.53% |

## Interpretation for paper writing

- GEMM: seed43 improves composite cost slightly over seed42. It lowers communication and congestion further, with essentially unchanged makespan and energy. Both seeds remove all hotspot PEs.
- MPEG4: seed43 is clearly stronger than seed42, especially on makespan, congestion and total energy. Both seeds remove all hotspot PEs.
- VOPD: seed42 and seed43 are nearly tied in composite cost. Both strongly improve makespan, communication, congestion and total energy. Temperature spread worsens, so VOPD should be described as a tradeoff rather than a thermal-only win.
- HNN: seed43 is weaker than seed42 in composite cost and hotspot count. Both seeds still reduce cost and hotspots relative to baseline, but HNN makespan degrades relative to baseline. Use HNN as evidence for multi-objective thermal management tradeoff, not uniform metric improvement.
