import registryJson from '../../assets/structures.json'

export type Layer = 'chambers' | 'valves' | 'great_vessels' | 'coronary_vessels'

export const LAYERS: readonly Layer[] = ['chambers', 'valves', 'great_vessels', 'coronary_vessels']

/** Student-facing layer names. */
export const LAYER_NAMES: Record<Layer, string> = {
  chambers: 'Chambers',
  valves: 'Valves',
  great_vessels: 'Great vessels',
  coronary_vessels: 'Coronary vessels',
}

/** One entry of assets/structures.json. Field names stay snake_case to match the JSON. */
export interface Structure {
  id: string
  display_name: string
  mesh_names: string[]
  aliases: string[]
  group: string
  layer: Layer
  size_class: 'small' | 'medium' | 'large'
  best_view: string | null
  neighbors: string[]
  short_description: string
  notes?: string
}

export interface Registry {
  organ: string
  structures: Structure[]
  views: Record<string, unknown>
  cross_sections: Record<string, unknown>
  paths: Record<string, unknown>
}

export const registry = registryJson as Registry

export const structures: readonly Structure[] = registry.structures

const structuresById = new Map(structures.map((structure) => [structure.id, structure]))

const structureIdByMesh = new Map(
  structures.flatMap((structure) => structure.mesh_names.map((mesh) => [mesh, structure.id] as const)),
)

export function getStructure(id: string): Structure | undefined {
  return structuresById.get(id)
}

/** The structure a GLB mesh belongs to. Clicking any mesh of a structure selects the whole structure. */
export function structureIdForMesh(meshName: string): string | undefined {
  return structureIdByMesh.get(meshName)
}

/** Student-facing name. Never show a raw structure ID in the UI. */
export function displayName(id: string): string {
  return structuresById.get(id)?.display_name ?? id
}
