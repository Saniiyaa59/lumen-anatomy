import type { Structure } from '../registry.ts'

const OXYGEN_RICH = 0xc8323a
const OXYGEN_POOR = 0x3f63b8

const GROUP_COLORS: Record<string, number> = {
  chamber: 0xc98a80,
  valve: 0xeadfc6,
  muscle: 0xa85c55,
  great_vessel: OXYGEN_RICH,
  coronary_artery: 0xe0453f,
  cardiac_vein: 0x4f74c9,
}

// Atlas convention: red carries oxygen-rich blood, blue oxygen-poor. That makes
// the pulmonary arteries blue and the pulmonary veins red.
const STRUCTURE_COLORS: Record<string, number> = {
  right_atrium: 0xd49c92,
  left_atrium: 0xd9a59a,
  pulmonary_trunk: OXYGEN_POOR,
  pulmonary_arteries: OXYGEN_POOR,
  superior_vena_cava: OXYGEN_POOR,
  inferior_vena_cava: OXYGEN_POOR,
}

const FALLBACK_COLOR = 0x9aa0a6

export const SELECTED_COLOR = 0xffc93c

export function baseColor(structure: Structure): number {
  return STRUCTURE_COLORS[structure.id] ?? GROUP_COLORS[structure.group] ?? FALLBACK_COLOR
}
