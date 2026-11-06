"""Extract the heart from the Z-Anatomy atlas and export it as assets/models/heart.glb.

Runs inside Blender, not the backend venv. See docs/asset_prep.md:

    blender --background --factory-startup --disable-autoexec <path>/Z-Anatomy/Startup.blend \
        --python backend/scripts/extract_heart.py -- assets/models/heart.glb

Each listed Blender object is baked into a plain mesh (modifiers applied, curves
turned into tubes, parent transforms applied) and exported under a stable name
with no spaces, so the names survive Three.js' node-name sanitizing unchanged.
"""

import sys
from pathlib import Path

import bmesh
import bpy

# Mesh name in heart.glb -> Z-Anatomy object(s) baked into it.
# structures.json refers to the left-hand names.
HEART_MESHES = {
    # Chambers (the interventricular septum is part of the ventricle meshes)
    "Right_atrium": ("Right atrium",),
    "Right_ventricle": ("Right ventricle",),
    "Left_atrium": ("Left atrium",),
    "Left_ventricle": ("Left ventricle",),
    # Papillary muscles
    "Anterior_papillary_muscle_RV": ("Anterior papillary muscle of right ventricle",),
    "Inferior_papillary_muscle_RV": ("Inferior papillary muscle of right ventricle",),
    "Septal_papillary_muscle_RV": ("Septal papillary muscle of right ventricle",),
    "Inferior_papillary_muscle_LV": ("Inferior papillary muscle of left ventricle",),
    # Tricuspid valve (Z-Anatomy has no anterior leaflet)
    "Tricuspid_septal_leaflet": ("Septal leaflet of right atrioventricular valve",),
    "Tricuspid_inferior_leaflet": ("Inferior leaflet of right atrioventricular valve",),
    # Mitral valve (Z-Anatomy has no anterior leaflet)
    "Mitral_posterior_leaflet": ("Posterior leaflet of left atrioventricular valve",),
    # Aortic valve
    "Aortic_right_coronary_leaflet": ("Right coronary leaflet",),
    "Aortic_left_coronary_leaflet": ("Left coronary leaflet",),
    "Aortic_non_coronary_leaflet": ("Non-coronary leaflet",),
    # Pulmonary valve
    "Pulmonary_anterior_leaflet": ("Anterior semilunar leaflet of pulmonary valve",),
    "Pulmonary_left_leaflet": ("Left semilunar leaflet of pulmonary valve",),
    "Pulmonary_right_leaflet": ("Right semilunar leaflet of pulmonary valve",),
    # Great vessels
    "Ascending_aorta": ("Ascending aorta",),
    "Aortic_arch": ("Aortic arch",),
    "Pulmonary_trunk": ("Pulmonary trunk",),
    "Pulmonary_trunk_bifurcation": ("Bifurcation of pulmonary trunk",),
    "Right_pulmonary_artery": ("Right pulmonary artery",),
    "Left_pulmonary_artery": ("Left pulmonary artery",),
    "Superior_vena_cava": ("Superior vena cava",),
    "Inferior_vena_cava": ("Inferior vena cava (thoracic part)",),
    "Right_superior_pulmonary_vein": ("Right superior pulmonary vein",),
    "Right_inferior_pulmonary_vein": ("Right inferior pulmonary vein",),
    "Left_superior_pulmonary_vein": ("Left superior pulmonary vein",),
    "Left_inferior_pulmonary_vein": ("Left inferior pulmonary vein",),
    # Coronary arteries
    "Right_coronary_artery": ("Right coronary artery",),
    "Right_coronary_inferolateral_branch": ("Right inferolateral branch of right coronary artery",),
    "Left_coronary_artery": ("Left coronary artery",),
    "Anterior_interventricular_artery": ("Anterior interventricular artery",),
    "Septal_branches": ("Septal branches of anterior interventricular artery",),
    "Circumflex_artery": ("Circumflex artery of heart",),
    # Cardiac veins
    "Coronary_sinus": ("Coronary sinus",),
    "Great_cardiac_vein": ("Great cardiac vein",),
    "Middle_cardiac_vein": ("Middle cardiac vein",),
    # Z-Anatomy has two objects with this name; they are merged.
    "Inferior_vein_of_left_ventricle": (
        "Inferior vein of left ventricle",
        "Inferior vein of left ventricle (//Posterior '')",
    ),
    # Z-Anatomy's name for this object is lost ("????????"). It runs over the
    # anterior right ventricle toward the right atrium, so it is probably the
    # anterior cardiac veins; confirm visually before naming it in the registry.
    "Unlabeled_cardiac_veins": ("????????",),
}


def bake(sources: list[bpy.types.Object], name: str, depsgraph) -> bpy.types.Mesh:
    """Merge the evaluated, world-space geometry of `sources` into one new mesh."""
    combined = bmesh.new()
    materials = []
    for source in sources:
        mesh = bpy.data.meshes.new_from_object(source.evaluated_get(depsgraph), depsgraph=depsgraph)
        mesh.transform(source.matrix_world)
        combined.from_mesh(mesh)
        materials = materials or list(mesh.materials)
        bpy.data.meshes.remove(mesh)
    baked = bpy.data.meshes.new(name)
    combined.to_mesh(baked)
    combined.free()
    for material in materials:
        baked.materials.append(material)
    return baked


def main() -> None:
    out_path = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    missing = [n for names in HEART_MESHES.values() for n in names if n not in bpy.data.objects]
    if missing:
        sys.exit(f"Objects not found in the .blend file: {missing}")

    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    export_collection = bpy.data.collections.new("Lumen heart export")
    bpy.context.scene.collection.children.link(export_collection)

    total_vertices = 0
    for export_name, source_names in HEART_MESHES.items():
        mesh = bake([bpy.data.objects[n] for n in source_names], export_name, depsgraph)
        baked = bpy.data.objects.new(export_name, mesh)
        export_collection.objects.link(baked)
        baked.select_set(True)
        total_vertices += len(mesh.vertices)

    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_texcoords=False,
        export_materials="EXPORT",
        export_animations=False,
        export_extras=False,
    )
    size_mb = out_path.stat().st_size / 1_000_000
    print(f"Exported {len(HEART_MESHES)} meshes, {total_vertices} vertices, {size_mb:.1f} MB -> {out_path}")


main()
