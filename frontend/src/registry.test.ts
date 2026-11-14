import { describe, expect, it } from 'vitest'
import { displayName, getStructure, LAYERS, structureIdForMesh, structures } from './registry.ts'

describe('registry', () => {
  it('maps every mesh of a structure to that structure', () => {
    expect(structureIdForMesh('Left_ventricle')).toBe('left_ventricle')
    for (const leaflet of ['Aortic_right_coronary_leaflet', 'Aortic_left_coronary_leaflet', 'Aortic_non_coronary_leaflet']) {
      expect(structureIdForMesh(leaflet)).toBe('aortic_valve')
    }
    expect(structureIdForMesh('placeholder_cube')).toBeUndefined()
  })

  it('assigns each mesh to exactly one structure', () => {
    const meshes = structures.flatMap((structure) => structure.mesh_names)
    expect(new Set(meshes).size).toBe(meshes.length)
  })

  it('only uses layers the frontend knows about', () => {
    for (const structure of structures) {
      expect(LAYERS).toContain(structure.layer)
    }
  })

  it('gives display names, falling back to the ID for unknown structures', () => {
    expect(displayName('left_ventricle')).toBe('Left ventricle')
    expect(displayName('not_a_structure')).toBe('not_a_structure')
    expect(getStructure('not_a_structure')).toBeUndefined()
  })
})
