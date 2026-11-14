import { ancestors, getStructure, type Structure } from '../registry.ts'

const OXYGEN_RICH = 0xc8323a
const OXYGEN_POOR = 0x3f63b8
const CHAMBER = 0xc98a80

// Colors by atlas group; a structure takes the color of the nearest group above
// it that has one. Atlas convention: red carries oxygen-rich blood, blue
// oxygen-poor. That makes the pulmonary arteries blue and the pulmonary veins red.
const GROUP_COLORS: Record<string, number> = {
  heart: CHAMBER,
  valvular_complex_of_heart: 0xeadfc6,
  arteries_of_heart: 0xe0453f,
  cardiac_veins: 0x4f74c9,
  pulmonary_arteries: OXYGEN_POOR,
  pulmonary_veins: OXYGEN_RICH,
  arterial_system: OXYGEN_RICH,
  venous_system: OXYGEN_POOR,
}

const FALLBACK_COLOR = 0x9aa0a6

/** How much darker a surface inside another surface is drawn, e.g. a papillary muscle in its ventricle. */
const INNER_SHADE = 0.82

export const SELECTED_COLOR = 0xffc93c

/** Tint for structures a session points out. */
export const HIGHLIGHT_COLOR = 0x39e6ff

// Colors painted along vessels during a session.
/** What lies beyond a damage point, and the point itself. */
export const LOST_COLOR = 0x5a6068
export const DAMAGE_COLOR = 0xfff3b0
export const PULSE_COLOR = 0x8ff5ff
/** The right place once a case is answered, and a wrong click. */
export const CORRECT_COLOR = 0x4ade80
export const WRONG_COLOR = 0xff5a5a

export function baseColor(structure: Structure): number {
  const group = ancestors(structure.id).find((id) => id in GROUP_COLORS)
  const color = group === undefined ? FALLBACK_COLOR : GROUP_COLORS[group]
  const inside = structure.parent !== null && getStructure(structure.parent)?.kind === 'surface'
  if (structure.kind !== 'surface' || !inside) return color
  const shade = (shift: number) => Math.round(((color >> shift) & 0xff) * INNER_SHADE) << shift
  return shade(16) | shade(8) | shade(0)
}
