import { useCallback, useEffect, useRef, useState } from 'react'
import { getHealth } from './api.ts'
import SelectionChips from './selection/SelectionChips.tsx'
import { selectionStore } from './selection/store.ts'
import { namesHidden as namesGiveAway, usePlayer } from './session/player.ts'
import PositionReadout from './ui/PositionReadout.tsx'
import SessionRail from './ui/SessionRail.tsx'
import SessionThread from './ui/SessionThread.tsx'
import SplitHandle from './ui/SplitHandle.tsx'
import StructurePanel from './ui/StructurePanel.tsx'
import Viewer, { type ViewerHandle } from './viewer/Viewer.tsx'

type BackendState = 'checking' | 'ok' | 'down'

const STATUS_LABEL: Record<BackendState, string> = {
  checking: 'Backend: checking…',
  ok: 'Backend: connected',
  down: 'Backend: unreachable',
}

/** Width of the session column, in pixels: where it starts, and how narrow it may get. */
const THREAD_WIDTH = 400
const THREAD_MIN = 320
/** The session column may take at most this share of the window, so the model always keeps room. */
const THREAD_MAX_SHARE = 0.6

const WIDTH_KEY = 'lumen.threadWidth'
const RAIL_KEY = 'lumen.railCollapsed'

/** A small setting kept in this browser. Falls back quietly when storage is blocked. */
function readSetting(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeSetting(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Not saved; the setting still holds until the page is closed.
  }
}

const threadMax = () => Math.max(THREAD_MIN, Math.round(window.innerWidth * THREAD_MAX_SHARE))

const clampThread = (width: number) => Math.max(THREAD_MIN, Math.min(threadMax(), Math.round(width)))

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA'].includes(target.tagName))
}

export default function App() {
  const [backend, setBackend] = useState<BackendState>('checking')
  const [showLabels, setShowLabels] = useState(true)
  const [structuresOpen, setStructuresOpen] = useState(false)
  const [railCollapsed, setRailCollapsed] = useState(() => readSetting(RAIL_KEY) === 'true')
  const [threadWidth, setThreadWidth] = useState(() => clampThread(Number(readSetting(WIDTH_KEY)) || THREAD_WIDTH))
  const viewerRef = useRef<ViewerHandle>(null)
  const player = usePlayer()
  const inSession = player.session !== null
  // While a case asks for a place, or a question asks what is highlighted, names on the model would give it away.
  const namesHidden = namesGiveAway(player)

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

  // A narrower window can leave the session column wider than its share allows.
  useEffect(() => {
    const onResize = () => setThreadWidth((width) => clampThread(width))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // The 3D view learns its new width a frame or two after the layout changes, so
  // the camera is re-aimed at what the session is showing only after that.
  const reframeSoon = () => requestAnimationFrame(() => requestAnimationFrame(() => viewerRef.current?.reframe()))

  const toggleRail = () => {
    setRailCollapsed((collapsed) => {
      writeSetting(RAIL_KEY, String(!collapsed))
      return !collapsed
    })
    reframeSoon()
  }

  const resizeThread = useCallback((width: number) => setThreadWidth(clampThread(width)), [])

  // When the border stops moving, remember the width and re-aim the camera.
  const resizeDone = () => {
    setThreadWidth((width) => {
      writeSetting(WIDTH_KEY, String(width))
      return width
    })
    reframeSoon()
  }

  return (
    <div className="app">
      <SessionRail collapsed={railCollapsed} onToggle={toggleRail} />
      <main className="stage">
        <Viewer showLabels={showLabels && !namesHidden} showNames={!namesHidden} ref={viewerRef} />
        <div className="stage-corner">
          <button
            type="button"
            className="toggle toggle-plain"
            aria-expanded={structuresOpen}
            aria-controls="structures"
            onClick={() => setStructuresOpen((open) => !open)}
          >
            Structures
          </button>
          <div className="status" data-state={backend}>
            {STATUS_LABEL[backend]}
          </div>
        </div>
        {structuresOpen && <StructurePanel onClose={() => setStructuresOpen(false)} />}
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
        </div>
        <div className="selection-bar">
          <SelectionChips />
        </div>
        {!inSession && <PositionReadout />}
        <footer className="disclaimer">
          Lumen is an educational prototype. It does not give medical advice.
        </footer>
      </main>
      <SplitHandle
        width={threadWidth}
        min={THREAD_MIN}
        max={threadMax()}
        onResize={resizeThread}
        onDone={resizeDone}
        onReset={() => setThreadWidth(clampThread(THREAD_WIDTH))}
      />
      <div className="thread-column" style={{ width: threadWidth }}>
        <SessionThread />
      </div>
    </div>
  )
}
