import { useEffect, useState } from 'react'
import { getHealth } from './api.ts'
import Viewer from './viewer/Viewer.tsx'

type BackendState = 'checking' | 'ok' | 'down'

const STATUS_LABEL: Record<BackendState, string> = {
  checking: 'Backend: checking…',
  ok: 'Backend: connected',
  down: 'Backend: unreachable',
}

export default function App() {
  const [backend, setBackend] = useState<BackendState>('checking')

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then(() => !cancelled && setBackend('ok'))
      .catch(() => !cancelled && setBackend('down'))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="app">
      <Viewer />
      <div className="status" data-state={backend}>
        {STATUS_LABEL[backend]}
      </div>
      <footer className="disclaimer">
        Lumen is an educational prototype. It does not give medical advice.
      </footer>
    </div>
  )
}
