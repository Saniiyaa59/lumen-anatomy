import regionJson from '../../assets/regions/heart/structures.json'

/**
 * The region's structure list, generated from the Z-Anatomy atlas by
 * backend/scripts/export_region.py. Nothing here is written by hand: names,
 * grouping and ids all come from the atlas. Field names match the JSON.
 */

/** A named group in the atlas, e.g. "Aortic valve". Groups have no shape of their own. */
export interface Group {
  id: string
  name: string
  parent: string | null
  /** Key of this group's article in the articles file, if it has one. */
  article: string | null
}

/** One clickable shape. Its mesh in model.glb has the same name as its id. */
export interface Structure {
  id: string
  name: string
  side: 'left' | 'right' | null
  /** A tube is a vessel with a centre line; a surface is everything else. */
  kind: 'surface' | 'tube'
  /** The structure this one is part of (a branch of an artery), or the group it belongs to. */
  parent: string | null
  article: string | null
  z_anatomy_object: string
}

/** A labelled place. On the heart these float beside it; see `distance_to_surface`. */
export interface Landmark {
  id: string
  name: string
  parent: string | null
  point: [number, number, number]
  nearest_structure: string | null
  distance_to_surface: number | null
  article: string | null
}

export interface RegionFile {
  region: string
  name: string
  source: string
  units: string
  groups: Group[]
  structures: Structure[]
  landmarks: Landmark[]
}

export const region = regionJson as RegionFile

export const structures: readonly Structure[] = region.structures

export const groups: readonly Group[] = region.groups

const structuresById = new Map(structures.map((structure) => [structure.id, structure]))

const groupsById = new Map(groups.map((group) => [group.id, group]))

export function getStructure(id: string): Structure | undefined {
  return structuresById.get(id)
}

export function getGroup(id: string): Group | undefined {
  return groupsById.get(id)
}

/** Ids of everything a structure or group sits inside, nearest first. */
export function ancestors(id: string): string[] {
  const chain: string[] = []
  let parent = (structuresById.get(id) ?? groupsById.get(id))?.parent ?? null
  while (parent !== null && !chain.includes(parent)) {
    chain.push(parent)
    parent = (structuresById.get(parent) ?? groupsById.get(parent))?.parent ?? null
  }
  return chain
}

/** Every structure inside a group, at any depth. */
export function structuresUnder(groupId: string): Structure[] {
  return structures.filter((structure) => ancestors(structure.id).includes(groupId))
}

/**
 * Student-facing name. Never show a raw id in the UI.
 *
 * The atlas lost the name of one cardiac vein ("????????"); it is described by what it joins.
 */
export function displayName(id: string): string {
  const entry = structuresById.get(id) ?? groupsById.get(id)
  if (!entry) return id
  if (!/[a-z]/i.test(entry.name)) {
    return entry.parent ? `Unnamed vessel (${displayName(entry.parent)})` : 'Unnamed structure'
  }
  const side = 'side' in entry ? entry.side : null
  return side ? `${entry.name} (${side})` : entry.name
}

/** One block of the structures panel: an atlas group and the structures directly in it. */
export interface Section {
  group: Group
  /** In tree order. `depth` is how many structures a row sits inside, for indenting branches. */
  items: { structure: Structure; depth: number }[]
}

const OTHER: Group = { id: 'other', name: 'Other', parent: null, article: null }

function buildSections(): Section[] {
  const byName = (a: Structure, b: Structure) => displayName(a.id).localeCompare(displayName(b.id))
  const childrenOf = (parent: string) => structures.filter((structure) => structure.parent === parent).sort(byName)
  const built = new Map<string, Section>()
  for (const structure of [...structures].sort(byName)) {
    // A structure whose parent is another structure is listed under that parent instead.
    if (structure.parent !== null && structuresById.has(structure.parent)) continue
    const group = (structure.parent !== null && groupsById.get(structure.parent)) || OTHER
    const section = built.get(group.id) ?? { group, items: [] }
    built.set(group.id, section)
    const add = (item: Structure, depth: number) => {
      section.items.push({ structure: item, depth })
      childrenOf(item.id).forEach((child) => add(child, depth + 1))
    }
    add(structure, 0)
  }
  // The region's own group comes first; the rest follow by name.
  return [...built.values()].sort(
    (a, b) =>
      Number(b.group.id === region.region) - Number(a.group.id === region.region) || a.group.name.localeCompare(b.group.name),
  )
}

export const sections: readonly Section[] = buildSections()
