# AGENTS.md

Scope: this file applies to `D:\HNOCS\document\paper` and all subdirectories.

## Project Context

- The paper targets ACP 2026 and should follow an IEEE conference-style, double-column LaTeX format.
- The official submission language is English. Chinese drafts are for internal comparison and planning only.
- Keep author information anonymous for double-blind review drafts.
- Target length is 2-6 pages unless the user gives a different page budget.

## Main Paper Narrative

Use this causal chain when editing the paper:

1. ONoC system behavior is determined by task execution and task-to-task communication.
2. Task-to-PE mapping determines the spatial distribution of on-chip heat sources.
3. Heat distribution affects PE hotspots, DVFS throttling, and task execution time.
4. Heat distribution also affects nearby MRR temperature, MRR alignment, and dynamic thermal tuning demand.
5. Task communication changes WDM optical transmission activity, wavelength-channel activity, SOA activation time, and optical-layer energy.
6. ONoC thermal management is therefore a system-level multi-objective tradeoff among task mapping, heat distribution, MRR alignment, photonic-device compensation cost, performance, and energy.

Do not frame the paper as if MRR thermal sensitivity alone causes PE hotspots, DVFS, SOA activation, or application energy. MRR thermal sensitivity is one photonic consequence of the heat distribution, not the root cause of all system effects.

## Terminology

Preferred terms:

- `initial mapping`
- `reference mapping`
- `normalization reference`
- `WDM optical transmission activity`
- `wavelength-channel activity`
- `MRR alignment`
- `dynamic thermal tuning`
- `photonic-device compensation cost`
- `SOA activation time`
- `optical-layer energy`
- `task-to-PE mapping`
- `simulator-in-the-loop thermal-aware task remapping`

Baseline terminology for the ACP paper:

- Treat `Original` as the initial/reference mapping used for normalization and before/after comparison, not as a baseline method.
- Treat `Thermal-SA-TAS` and `CommAware-Heuristic` as the main method-level baseline methods.
- Treat `RandomBest` only as a best-of-random sanity/control comparison if it is used; do not describe it as an average random control or an average random method.
- Historical code, CSV files, and plotting sources may still use `baseline` in column names or implementation terms. Convert that wording to `initial/reference mapping` in manuscript prose unless it names a code-level field.

Avoid these terms in the paper narrative unless the user explicitly asks to discuss the simulator implementation details:

- `handshake`
- `setup`
- `teardown`
- `optical circuit setup`
- `optical circuit duration`
- `connection setup`
- `connection teardown`
- `建链`
- `拆链`
- `握手`
- `光路建立`

## Evidence Boundary

- Current experiments support temperature, DVFS, makespan, communication cost, SOA energy, MRR thermal tuning energy, laser energy, and total energy.
- Do not claim direct validation of BER, optical transmission errors, packet loss, receiver margin, or uncompensated MRR detuning unless new experiments are added.
- It is acceptable to state that MRR thermal tuning energy is used as an observable compensation cost for maintaining MRR alignment.
- If discussing detuning, phrase it as background motivation or physical mechanism, not as a directly measured runtime failure mode.

## LaTeX Editing Rules

- Keep IEEE conference style unless the user asks for a different template.
- Prefer concise ACP/IEEE conference prose over highly editorial or Nature-style prose.
- Keep figures and tables compact; avoid large explanatory blocks that push the paper beyond 6 pages.
- Use `siunitx` for units where practical.
- Keep citations in IEEE style using `\cite{...}`.
- Do not add acknowledgments, author names, affiliations, or self-identifying paths in double-blind drafts.

## Build And Verification

For English drafts:

```powershell
latexmk -pdf -interaction=nonstopmode -halt-on-error <main>.tex
```

For Chinese internal drafts:

```powershell
latexmk -xelatex -interaction=nonstopmode -halt-on-error <main>.tex
```

Before considering edits complete:

- Compile the edited `.tex` file.
- Check that the output PDF is within the ACP page limit.
- Search edited `.tex` files for banned connection-control terminology listed above.
- Report any remaining LaTeX warnings that may affect submission quality.

## Bilingual Policy

When making edits, update both the Chinese (`AGENTS_zh.md`) and English (`AGENTS.md`) versions. If the two versions become inconsistent, the Chinese version takes precedence, as the author manually maintains the Chinese draft.

## File Organization

- `第一版/` contains earlier drafts and generated build artifacts.
- `第二版/` contains the current ACP-oriented draft files.
- Prefer editing the current version unless the user explicitly names another version.
