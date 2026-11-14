import { describe, expect, it } from 'vitest'
import { ancestors, displayName, getGroup, getStructure, region, sections, structures, structuresUnder } from './registry.ts'

describe('registry', () => {
  it('uses ids taken from the atlas names', () => {
    expect(getStructure('left_ventricle')?.name).toBe('Left ventricle')
    expect(getStructure('anterior_interventricular_artery')?.kind).toBe('tube')
    expect(getStructure('not_a_structure')).toBeUndefined()
  })

  it('gives every structure a unique id and a parent that exists', () => {
    const ids = structures.map((structure) => structure.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const structure of structures) {
      const parent = structure.parent
      expect(parent === null || getStructure(parent) !== undefined || getGroup(parent) !== undefined).toBe(true)
    }
  })

  it('lists what a structure sits inside, nearest first', () => {
    expect(ancestors('septal_branches_of_anterior_interventricular_artery')).toEqual([
      'anterior_interventricular_artery',
      'left_coronary_artery',
      'arteries_of_heart',
      'arterial_system',
    ])
  })

  it('finds every structure inside a group, at any depth', () => {
    const valves = structuresUnder('valvular_complex_of_heart').map((structure) => structure.id)
    expect(valves).toContain('left_coronary_leaflet')
    expect(valves).toContain('anterior_semilunar_leaflet_of_pulmonary_valve')
    expect(valves).not.toContain('left_ventricle')
  })

  it('gives display names for structures and groups, falling back to the id for unknown ones', () => {
    expect(displayName('left_ventricle')).toBe('Left ventricle')
    expect(displayName('aortic_valve')).toBe('Aortic valve')
    expect(displayName('not_a_structure')).toBe('not_a_structure')
  })

  it('describes the vein whose name the atlas lost by what it joins', () => {
    expect(displayName('unnamed_coronary_sinus')).toBe('Unnamed vessel (Coronary sinus)')
  })
})

describe('sections', () => {
  it('puts the region itself first', () => {
    expect(sections[0].group.id).toBe(region.region)
  })

  it('lists every structure exactly once', () => {
    const listed = sections.flatMap((section) => section.items.map((item) => item.structure.id))
    expect([...listed].sort()).toEqual(structures.map((structure) => structure.id).sort())
  })

  it('nests a branch right after the vessel it comes off, one level deeper', () => {
    const arteries = sections.find((section) => section.group.id === 'arteries_of_heart')!
    const rows = arteries.items.map((item) => [item.structure.id, item.depth])
    expect(rows).toEqual([
      ['left_coronary_artery', 0],
      ['anterior_interventricular_artery', 1],
      ['septal_branches_of_anterior_interventricular_artery', 2],
      ['circumflex_artery_of_heart', 1],
      ['right_coronary_artery', 0],
      ['right_inferolateral_branch_of_right_coronary_artery', 1],
    ])
  })
})
