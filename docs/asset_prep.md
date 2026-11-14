# Asset prep — heart model

`assets/models/heart.glb` is extracted from the **Z-Anatomy** atlas by a script, so anyone can rebuild it. It holds 40 separately named meshes (~155k vertices, 5.6 MB): every heart structure Z-Anatomy has, plus the roots of the great vessels.

## Rebuilding heart.glb

1. Install [Blender](https://www.blender.org/download/) (tested with 5.2 LTS).
2. Download the Z-Anatomy template zip from [github.com/Z-Anatomy/Models-of-human-anatomy](https://github.com/Z-Anatomy/Models-of-human-anatomy) and unzip it. You need `Z-Anatomy/Startup.blend` (~300 MB). You don't need to install it as a Blender template.
3. From the repo root, run Blender without its window. Replace the paths with yours.

   Windows (Git Bash):

   ```bash
   "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --disable-autoexec "C:/Users/<you>/Downloads/Z-Anatomy/Z-Anatomy/Startup.blend" --python backend/scripts/extract_heart.py -- assets/models/heart.glb
   ```

   macOS:

   ```bash
   /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --disable-autoexec ~/Downloads/Z-Anatomy/Z-Anatomy/Startup.blend --python backend/scripts/extract_heart.py -- assets/models/heart.glb
   ```

   `--disable-autoexec` stops the Python script embedded in the `.blend` file from running.

The script ([backend/scripts/extract_heart.py](../backend/scripts/extract_heart.py)) holds the list of GLB mesh names and the Z-Anatomy object(s) each is built from. For each object it applies modifiers (subdivision), turns tube curves (all vessels) into meshes, and applies parent transforms. Then it exports only those meshes as binary glTF. Units are meters; the heart itself is ~11 cm tall, ~23 cm with the vessels (the inferior vena cava reaches down to the diaphragm). The frontend centers and scales it.

## Region export (for study sessions)

Added 2026-11-14. The viewer now loads these files. `heart.glb` and `assets/structures.json` above are still read by the backend and `/api/command`. Study sessions need more than shapes, so a second script exports a whole region with nothing written by hand. It reads everything from the atlas.

```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --disable-autoexec "C:/Users/<you>/Downloads/Z-Anatomy/Z-Anatomy/Startup.blend" --python backend/scripts/export_region.py -- assets/regions/heart/region.json --articles assets/text/z_anatomy_articles.jsonl
```

On macOS, replace the Blender and `.blend` paths as in the command above. `--articles` is optional and only needs running once: it writes the articles for the whole atlas, not for one region.

The only input is `assets/regions/heart/region.json`, which lists Z-Anatomy object names: `roots` (each root and everything under it) and `extra_objects` (that object alone, used for the great vessels so their branches into the lungs and neck stay out). A new region is a new `region.json`.

| Output | What it holds |
| --- | --- |
| `assets/regions/heart/model.glb` | One mesh per structure, named by structure id. Same geometry as `heart.glb`, no materials. |
| `assets/regions/heart/structures.json` | 41 structures, the 17 Z-Anatomy groups above them, and 13 labelled landmarks. Each has an id, the atlas' name, its parent, and the name of its article if it has one. |
| `assets/regions/heart/centerlines.json` | For each of the 23 vessels, the path down its middle as pieces. Each piece has its points, the tube radius at each point, its length, and where it branches off another piece. |
| `assets/text/z_anatomy_articles.jsonl` | 3,821 description articles, one per line: `key`, `text`, `source_url`. Entries with identical text carry `same_as` in place of the text. |

Coordinates in the JSON files match the GLB: metres, +Y up. Structure ids are the atlas' names in lower case with underscores, for example `anterior_interventricular_artery`. A group such as the aortic valve is no longer one structure: it is a group whose members are its three leaflets.

Check the export from `backend/` with the venv active (the test suite runs the same check):

```bash
python -m scripts.validate_region
```

It fails if a mesh has no structure or the reverse, if a vessel has no centre line, if a centre line does not lie inside its own tube, or if a branch joins nothing.

### What the export found

- **Branches join cleanly.** Of 97 centre-line pieces, 84 start on another piece and 13 are starting points (the great vessels, the coronary sinus, and pulmonary vein stubs that fan out from one point). Both coronary arteries start on the wall of the ascending aorta. Tube surfaces sit within 0.01 mm of the exported radius, apart from where branches meet.
- **The heart's landmarks do not touch the heart.** All 13 (apex, coronary sulcus, the surfaces and borders) are labels floating 6 to 44 mm away, so they give a name but not a place. `distance_to_surface` records this for each one.
- **19 of 41 structures have an article under their own name.** The leaflets, papillary muscles, pulmonary veins and smaller branches do not; they fall back to the article of their group or parent. Some articles exist under a different name from the model's (the model's "Anterior interventricular artery" against the article "Left anterior descending artery"), and nothing in the atlas links the two.
- **Some of what is drawn cannot be seen.** The left coronary artery's 17 mm trunk starts inside the aorta's tube and runs under the right ventricle's surface, so it is hidden from every side unless those are hidden too. The first 46 mm of the anterior interventricular artery is covered by the left atrium and the pulmonary trunk; hiding those two and looking from the left shows all of it. The great cardiac vein runs beside that artery closely enough to be clicked by mistake. Found while playing the sample session (2026-11-14).
- **Not in the atlas, so not exported:** short names such as "LAD" or "RA" (they appear only inside article text), which structures are neighbours, and a best camera view. The four layers in the Structures panel are replaced by the atlas' own groups.
- **Atlas quirks kept as they are:** the mitral valve's posterior leaflet is filed under the right atrioventricular valve group; one cardiac vein is named `????????` (exported as `unnamed_coronary_sinus`); the heart's chambers sit under the "Arterial system" group.

## Checking the model against the registry

After re-exporting `heart.glb` or editing `assets/structures.json`, run from `backend/` with the venv active:

```bash
python -m scripts.validate_glb
```

It lists registry mesh names missing from the GLB and GLB meshes no structure claims, and exits with status 1 if there are any. The test suite runs the same check.

## What's in the model

| Group | Meshes in heart.glb |
| --- | --- |
| Chambers | `Right_atrium`, `Right_ventricle`, `Left_atrium`, `Left_ventricle` |
| Tricuspid valve | `Tricuspid_septal_leaflet`, `Tricuspid_inferior_leaflet` |
| Mitral valve | `Mitral_posterior_leaflet` |
| Aortic valve | `Aortic_right_coronary_leaflet`, `Aortic_left_coronary_leaflet`, `Aortic_non_coronary_leaflet` |
| Pulmonary valve | `Pulmonary_anterior_leaflet`, `Pulmonary_left_leaflet`, `Pulmonary_right_leaflet` |
| Papillary muscles | `Anterior_papillary_muscle_RV`, `Inferior_papillary_muscle_RV`, `Septal_papillary_muscle_RV`, `Inferior_papillary_muscle_LV` |
| Aorta | `Ascending_aorta`, `Aortic_arch` |
| Pulmonary arteries | `Pulmonary_trunk`, `Pulmonary_trunk_bifurcation`, `Right_pulmonary_artery`, `Left_pulmonary_artery` |
| Venae cavae | `Superior_vena_cava`, `Inferior_vena_cava` (thoracic part) |
| Pulmonary veins | `Right_superior_pulmonary_vein`, `Right_inferior_pulmonary_vein`, `Left_superior_pulmonary_vein`, `Left_inferior_pulmonary_vein` |
| Coronary arteries | `Right_coronary_artery`, `Right_coronary_inferolateral_branch`, `Left_coronary_artery`, `Anterior_interventricular_artery`, `Septal_branches`, `Circumflex_artery` |
| Cardiac veins | `Coronary_sinus`, `Great_cardiac_vein`, `Middle_cardiac_vein`, `Inferior_vein_of_left_ventricle`, `Unlabeled_cardiac_veins` |

Notes on the cardiac veins:

- `Inferior_vein_of_left_ventricle` merges two Z-Anatomy objects that share that name.
- `Unlabeled_cardiac_veins` is named `????????` in Z-Anatomy (the name was lost). It runs along the right coronary groove next to the right coronary artery and drains toward the coronary sinus, with branches over the front of the right ventricle. That fits the small cardiac vein plus the anterior cardiac veins; confirm before giving it a display name.

## Deliberately left out

Z-Anatomy also has these nearby, but they belong to other organs or systems: the descending (thoracic) aorta, the aortic arch branches (brachiocephalic trunk, common carotid and subclavian arteries), the brachiocephalic and azygos veins, and the lobar and segmental pulmonary vessels inside the lungs. Add them to `HEART_MESHES` in the script if a lesson needs them; the carotid arteries run all the way up the neck.

## Gaps compared with the plan's target structures

- **Interventricular septum:** not a separate mesh; it is part of the ventricle meshes. Either drop it from the registry or split it out of the ventricles in Blender later.
- **Myocardium:** not separate; the chamber meshes are the heart wall.
- **Anterior leaflets of the mitral and tricuspid valves:** missing from Z-Anatomy. The valves still work as clickable structures (one or two leaflets each), but they look incomplete up close.
- **Pericardium, conducting system, fibrous skeleton, chordae tendineae:** Z-Anatomy has empty collections for these but no meshes.
- **Materials:** exported, but the chamber colors come out grey; the viewer assigns its own colors per structure anyway.
- **Smaller coronary branches:** drawn, but not named. See the next section.

## Unnamed coronary branches

Checked in `Startup.blend` on 2026-11-14. Each coronary artery is a curve made of several pieces (splines), so the centre lines and their branching are there. Only six objects carry a name:

| Z-Anatomy object | Curve pieces | Parent object |
| --- | --- | --- |
| Right coronary artery | 14 | — |
| Right inferolateral branch of right coronary artery | 8 | Right coronary artery |
| Left coronary artery | 1 | — |
| Anterior interventricular artery | 6 | Left coronary artery |
| Septal branches of anterior interventricular artery | 6 | Anterior interventricular artery |
| Circumflex artery of heart | 6 | Left coronary artery |

There is no object for the posterior (inferior) interventricular artery, the marginal branches, the diagonal branches, or the branches to the sinoatrial and atrioventricular nodes. Some of them are probably among the unnamed pieces of the six objects above, but nobody has worked out which piece is which.

**Why it matters:** we can measure a click on these arteries (which piece, how far along it), but we can't grade it against a named place. A case such as "inferior infarct with heart block", where the answer is "the right coronary artery before the branch to the atrioventricular node", can't be graded by exact place until those pieces are named. The heart wall has the same problem: no territories and no separate septum, so there is no region to mark as "lost".

**Idea to come back to (Hanna, Nov 14):** use textbook figures and a vision model to grade exact clicks in places the model leaves unnamed. Two ways to do it:

1. **Name the pieces ahead of time.** Render each unnamed piece on the heart, have the vision model compare it with a textbook figure and propose a name, and have a person confirm. Grading then stays plain code against the named piece. This fits two rules we already have: clicks are graded only against facts checked against the model, and vision work is prepared ahead of the session, never live.
2. **Judge each click live.** Send a render of the click and the textbook figure to the vision model during the session. No preparation, but slower, and the same click could be graded differently on two tries.

The same approach could apply to any region where the model draws more than it names.

## Other sources considered

| Source | Why not (for now) |
| --- | --- |
| [BodyParts3D](https://dbarchive.biosciencedbc.jp/data/bodyparts3d/20100816/README_e.html) | Upstream of Z-Anatomy; one OBJ per structure named by FMA ID, much more assembly work. |
| [HuBMAP Human Reference Atlas heart](https://hubmapconsortium.github.io/ccf/pages/ccf-3d-reference-library.html) | Already a GLB, but its license and valve segmentation were unverified. A fallback if we need the missing leaflets. |
| Sketchfab | Most free hearts are a single mesh or carry NC/ND licenses. |
