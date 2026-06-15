# GPT-Image Alternative Metadata

## File

- `figure1_framework_gpt_image2_alt.png`

## Purpose

AI-generated raster alternative for Figure 1. This version is intended as a visual design reference or manuscript-draft illustration, not as the primary editable/vector source.

## Generator Path

- Generated with Codex built-in image generation.
- Saved into the project after generation from the default Codex generated-image directory.
- The explicit CLI/API `gpt-image-2` fallback was not used because `OPENAI_API_KEY` was not set in the current shell environment.

## Source Data

This is a conceptual pipeline schematic. It uses no experimental numerical data and no source-data table.

## Prompt

Use case: infographic-diagram

Asset type: ACP 2026 paper Figure 1 alternative raster concept image

Primary request: Create a clean scientific workflow schematic titled exactly: "Simulation-in-the-loop thermal-aware task remapping framework for ONoC." The figure should show a left-to-right closed-loop framework for a simulation-in-the-loop thermal-aware task remapping method.

Style/medium: restrained high-impact scientific paper infographic, white background, vector-like flat design, crisp thin outlines, no 3D, no cartoon decoration, no gradients, no stock imagery.

Composition/framing: wide landscape academic figure, double-column paper aspect ratio. Five main modules arranged left to right with the OMNeT++ panel largest in the center. Use clear arrows between modules and an orange feedback loop returning from the final cost/selection module to the GA module.

Color palette: neutral gray + deep scientific blue as the primary color + small orange accents for feedback and cost; minimal teal only for communication metrics. Avoid purple, rainbow colors, dark backgrounds, decorative blobs.

Required module labels and content, use English only:

1. "Workload and Initial Mapping" with small DAG icon, "GEMM / MPEG4 / VOPD / HNN", "Original task-to-PE mapping", and output label "task graph + mapping vector".
2. "GA Candidate Mapping" with population/genome strips and labels "population", "crossover", "mutation", "individual = complete task-to-PE assignment", and output label "candidate remapped mapping".
3. Large central hero panel titled "OMNeT++ Full-system Evaluation" with subtitle "8-wavelength WDM ONoC | 4x4 / 16 PE". Include a simplified 4x4 PE array, blue optical links, orange MRR rings, and small blocks labeled "SOA" and "laser". Mechanism-level framework only, not a realistic circuit diagram.
4. "Coupled Feedback Metrics" as five stacked compact blocks: "thermal safety: T_max, sigma_T, N_hot"; "performance: makespan, DVFS penalty"; "communication pressure: comm cost, congestion proxy"; "mapping balance: load imbalance"; "energy: total PE + optical energy".
5. "Normalized Composite Cost and Selection" with prominent formula label "F(M)", text "baseline-normalized objective", and "selection / next generation" returning to the GA module.

Constraints: The text must be legible and should not overlap. Arrows must point clearly from Workload to GA to OMNeT++ to Metrics to Cost, then loop back to GA. Keep the OMNeT++ module visually largest. Use ample whitespace, IEEE-style compact typography, and a professional manuscript-figure feel. No watermark, no author names, no extra logos, no fake numerical data.

## QA Notes

- The project copy is a nonempty RGB PNG.
- The generated image is visually coherent and legible at desktop preview size.
- Because it is generated raster artwork, in-image text is not editable and should be rechecked manually before submission.
