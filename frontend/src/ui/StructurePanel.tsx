import { useState } from 'react'
import { displayName, sections } from '../registry.ts'
import { baseColor } from '../viewer/colors.ts'
import { visibilityStore } from '../visibility/store.ts'
import { useVisibility } from '../visibility/useVisibility.ts'

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="2.8" />
      {!open && <line x1="4" y1="20" x2="20" y2="4" strokeLinecap="round" />}
    </svg>
  )
}

interface EyeButtonProps {
  /** 'some' is a group with part of its structures hidden. */
  state: 'shown' | 'hidden' | 'some'
  /** What the button acts on, e.g. "Left ventricle" or "all valves". */
  target: string
  onToggle: () => void
}

function EyeButton({ state, target, onToggle }: EyeButtonProps) {
  // A fully shown item gets hidden; anything else is shown in full.
  const action = state === 'shown' ? 'Hide' : 'Show'
  return (
    <button type="button" className="eye" data-state={state} aria-label={`${action} ${target}`} title={`${action} ${target}`} onClick={onToggle}>
      <EyeIcon open={state !== 'hidden'} />
    </button>
  )
}

interface StructurePanelProps {
  onClose: () => void
}

/** Lists every structure under its atlas group, with an eye button to hide or show each one or a whole group. */
export default function StructurePanel({ onClose }: StructurePanelProps) {
  const { hidden } = useVisibility()
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())

  const toggleExpanded = (groupId: string) => {
    const next = new Set(collapsed)
    if (!next.delete(groupId)) next.add(groupId)
    setCollapsed(next)
  }

  return (
    <aside className="panel" id="structures" aria-label="Structures">
      <header className="panel-header">
        <h2>Structures</h2>
        <button type="button" className="panel-action" disabled={hidden.size === 0} onClick={() => visibilityStore.showAll()}>
          Show all
        </button>
        <button type="button" className="panel-close" aria-label="Close the structures panel" title="Close" onClick={onClose}>
          ×
        </button>
      </header>
      <ul className="panel-layers">
        {sections.map(({ group, items }) => {
          const ids = items.map((item) => item.structure.id)
          const hiddenCount = ids.filter((id) => hidden.has(id)).length
          const groupState = hiddenCount === 0 ? 'shown' : hiddenCount === ids.length ? 'hidden' : 'some'
          const isExpanded = !collapsed.has(group.id)
          return (
            <li key={group.id}>
              <div className="panel-row panel-layer">
                <button type="button" className="panel-expand" aria-expanded={isExpanded} onClick={() => toggleExpanded(group.id)}>
                  <span className="panel-chevron" aria-hidden="true" />
                  <span className="panel-name">{group.name}</span>
                  <span className="panel-count">{ids.length}</span>
                </button>
                <EyeButton
                  state={groupState}
                  target={`everything in ${group.name}`}
                  onToggle={() => visibilityStore.setVisible(ids, groupState !== 'shown')}
                />
              </div>
              {isExpanded && (
                <ul className="panel-structures">
                  {items.map(({ structure, depth }) => {
                    const isHidden = hidden.has(structure.id)
                    const name = displayName(structure.id)
                    return (
                      // A branch is indented under the vessel it comes off.
                      <li className="panel-row" data-hidden={isHidden} style={{ paddingLeft: 28 + depth * 14 }} key={structure.id}>
                        <span className="panel-swatch" style={{ background: `#${baseColor(structure).toString(16).padStart(6, '0')}` }} aria-hidden="true" />
                        <span className="panel-name" title={name}>
                          {name}
                        </span>
                        <EyeButton state={isHidden ? 'hidden' : 'shown'} target={name} onToggle={() => visibilityStore.toggle(structure.id)} />
                      </li>
                    )
                  })}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
