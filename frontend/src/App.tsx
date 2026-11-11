import { useEffect, useRef, useState } from 'react'
import { getHealth } from './api.ts'
import SelectionChips from './selection/SelectionChips.tsx'
import { selectionStore } from './selection/store.ts'
import StructurePanel from './ui/StructurePanel.tsx'
import Viewer, { type ViewerHandle } from './viewer/Viewer.tsx'

type BackendState = 'checking' | 'ok' | 'down'

const STATUS_LABEL: Record<BackendState, string> = {
  checking: 'Backend: checking…',
  ok: 'Backend: connected',
  down: 'Backend: unreachable',
}

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA'].includes(target.tagName))
}

export default function App() {
  const [backend, setBackend] = useState<BackendState>('checking')
  const [showLabels, setShowLabels] = useState(true)
  const [panelOpen, setPanelOpen] = useState(true)
  const viewerRef = useRef<ViewerHandle>(null)

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then(() => !cancelled && setBackend('ok'))
      .catch(() => !cancelled && setBackend('down'))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isTyping(event.target)) selectionStore.clear()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <div className="app">
      <main className="stage">
        <Viewer showLabels={showLabels} ref={viewerRef} />
        <div className="stage-corner">
          <div className="status" data-state={backend}>
            {STATUS_LABEL[backend]}
          </div>
        </div>
        <div className="view-options">
          <button
            type="button"
            className="toggle toggle-plain"
            title="Return to the starting view"
            onClick={() => viewerRef.current?.resetView()}
          >
            Recenter
          </button>
          <button
            type="button"
            className="toggle"
            aria-pressed={showLabels}
            onClick={() => setShowLabels((shown) => !shown)}
          >
            <span className="toggle-track" aria-hidden="true" />
            Labels
          </button>
          {!panelOpen && (
            <button type="button" className="toggle toggle-plain" onClick={() => setPanelOpen(true)}>
              Structures
            </button>
          )}
        </div>
        <div className="selection-bar">
          <SelectionChips />
        </div>
        <footer className="disclaimer">
          Lumen is an educational prototype. It does not give medical advice.
        </footer>
      </main>
      {panelOpen && <StructurePanel onClose={() => setPanelOpen(false)} />}
    </div>
  )
}
