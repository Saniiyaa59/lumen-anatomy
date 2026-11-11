import { displayName } from '../registry.ts'
import { selectionStore } from './store.ts'
import { useSelection } from './useSelection.ts'

/** The selected structures as removable chips, in click order. */
export default function SelectionChips() {
  const { selected } = useSelection()

  if (selected.length === 0) {
    return <p className="selection-hint">Click a structure to select it. Shift-click to add more.</p>
  }

  return (
    <ul className="chips" aria-label="Selected structures">
      {selected.map((id, index) => (
        <li className="chip" key={id}>
          <span className="chip-order">{index + 1}</span>
          {displayName(id)}
          <button
            type="button"
            className="chip-remove"
            aria-label={`Remove ${displayName(id)}`}
            onClick={() => selectionStore.remove(id)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  )
}
