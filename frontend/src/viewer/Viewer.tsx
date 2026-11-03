import { useEffect, useRef } from 'react'
import { SceneController } from './controller.ts'

declare global {
  interface Window {
    /** Dev-only handle for driving the scene from the browser console. */
    lumen?: SceneController
  }
}

export default function Viewer() {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const controller = new SceneController(containerRef.current!)
    if (import.meta.env.DEV) window.lumen = controller
    return () => {
      controller.dispose()
      if (window.lumen === controller) delete window.lumen
    }
  }, [])

  return <div className="viewer" ref={containerRef} />
}
