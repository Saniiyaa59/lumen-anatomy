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

## Other sources considered

| Source | Why not (for now) |
| --- | --- |
| [BodyParts3D](https://dbarchive.biosciencedbc.jp/data/bodyparts3d/20100816/README_e.html) | Upstream of Z-Anatomy; one OBJ per structure named by FMA ID, much more assembly work. |
| [HuBMAP Human Reference Atlas heart](https://hubmapconsortium.github.io/ccf/pages/ccf-3d-reference-library.html) | Already a GLB, but its license and valve segmentation were unverified. A fallback if we need the missing leaflets. |
| Sketchfab | Most free hearts are a single mesh or carry NC/ND licenses. |
