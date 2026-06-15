# Editable SVG Redraw Metadata

## File Set

- `figure1_framework_gpt_image2_alt_editable.svg`
- `figure1_framework_gpt_image2_alt_editable.pdf`
- `figure1_framework_gpt_image2_alt_editable.png`
- `figure1_framework_gpt_image2_alt_editable_qa.json`
- `make_gpt_image2_alt_editable.py`

## Purpose

Editable vector reconstruction of the GPT-image raster alternative for Figure 1.

## Method

The source PNG was used as a design reference. The SVG was manually reconstructed with Python/matplotlib using editable text, rectangles, arrows, circles, and line objects. It is not an automatic bitmap trace, so it is cleaner for subsequent editing in PowerPoint, Illustrator, Inkscape, or similar editors.

## Editable Elements

- Module titles and labels are SVG text nodes.
- Flow arrows, feedback loop, panels, metric blocks, DAG, genome strips, PE array, optical links, MRR rings, SOA and laser blocks are vector objects.
- SVG export uses `svg.fonttype = none` to preserve text editability.

## Caveat

PowerPoint SVG import may still group some paths and text differently depending on the PowerPoint version. If PPT-native editing is required, import the SVG and use ungroup/convert-to-shape, or rebuild directly as a PPTX with native PowerPoint objects.
