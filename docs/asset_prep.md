# Asset prep — heart model

Status: **model not chosen yet.** Phase 1 needs `assets/models/heart.glb` with one named mesh per structure.

## Requirements

- One separate mesh per structure, with stable names (chambers, four valves, great vessels, coronary arteries)
- Open license that allows modified copies in our public repo and ZIP
- Under ~10 MB as binary glTF after decimation

## Candidate sources

| Source | Format | License | Notes |
| --- | --- | --- | --- |
| **Z-Anatomy** — [github.com/Z-Anatomy/Models-of-human-anatomy](https://github.com/Z-Anatomy/Models-of-human-anatomy) | Blender template (whole body) | CC BY-SA 4.0; derived from BodyParts3D (credit CC BY-SA 2.1 JP). Some parts carry other licenses — check each heart part's credit. | The plan's first choice. Named objects per structure. Needs Blender: install the template, keep only heart objects, decimate, export GLB. |
| **BodyParts3D** — [dbarchive.biosciencedbc.jp/data/bodyparts3d](https://dbarchive.biosciencedbc.jp/data/bodyparts3d/20100816/README_e.html) | One OBJ per structure, named by FMA ID | CC BY-SA 2.1 Japan, with a required credit line | Raw upstream of Z-Anatomy. Must map FMA IDs to names and assemble in Blender. More work. |
| **HuBMAP Human Reference Atlas, 3D reference heart** — [CCF 3D reference library](https://hubmapconsortium.github.io/ccf/pages/ccf-3d-reference-library.html) | GLB, already segmented | Creative Commons (some HRA organs CC BY 4.0) — **verify for the heart** | Built from Visible Human data; already a GLB. Check which structures are separate nodes (valves especially). |
| **Sketchfab** (filter: Downloadable + CC BY) | glTF/GLB | Varies per model | Quality and segmentation vary; many are one mesh or NC/ND licensed, which we can't use. |

## Steps (once chosen)

To be filled in with the exact export steps used, so the model can be rebuilt.
