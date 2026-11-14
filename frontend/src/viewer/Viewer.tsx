import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { displayName } from '../registry.ts'
import { selectionStore } from '../selection/store.ts'
import { visibilityStore } from '../visibility/store.ts'
import { SceneController } from './controller.ts'

declare global {
  interface Window {
    /** Dev-only handles for driving the scene from the browser console. */
    lumen?: SceneController
    lumenSelection?: typeof selectionStore
  }
}

type LoadState = 'loading' | 'ready' | 'error'

/** What the rest of the app can ask the 3D view to do. */
export interface ViewerHandle {
  /** Glide the camera back to its starting view. */
  resetView(): void
}

interface ViewerProps {
  /** Whether each visible structure is named with a leader-line label. */
  showLabels: boolean
  ref?: Ref<ViewerHandle>
}

export default function Viewer({ showLabels, ref }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<SceneController | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')

  useImperativeHandle(ref, () => ({ resetView: () => controllerRef.current?.resetView() }), [])

  useEffect(() => {
    const controller = new SceneController(containerRef.current!, selectionStore, visibilityStore)
    controllerRef.current = controller
    let active = true

    controller.ready.then(
      () => active && setLoadState('ready'),
      (error: unknown) => {
        console.error('Could not load the heart model', error)
        if (active) setLoadState('error')
      },
    )

    // The tooltip follows the cursor, so it is moved directly instead of through React state.
    controller.onHover = (hover) => {
      const tooltip = tooltipRef.current
      if (!tooltip) return
      tooltip.hidden = hover === null
      if (hover) {
        tooltip.textContent = displayName(hover.structureId)
        tooltip.style.transform = `translate(${hover.clientX + 14}px, ${hover.clientY + 14}px)`
      }
    }

    if (import.meta.env.DEV) {
      window.lumen = controller
      window.lumenSelection = selectionStore
    }
    return () => {
      active = false
      controller.dispose()
      controllerRef.current = null
      if (window.lumen === controller) delete window.lumen
    }
  }, [])

  // Declared after the effect above, so the controller already exists on the first run.
  useEffect(() => {
    controllerRef.current?.setLabelsVisible(showLabels)
  }, [showLabels])

  return (
    <>
      <div className="viewer" ref={containerRef} />
      <div className="tooltip" ref={tooltipRef} hidden />
      {loadState === 'loading' && <div className="viewer-message">Loading the heart…</div>}
      {loadState === 'error' && (
        <div className="viewer-message" role="alert">
          The heart model couldn't be loaded. Check that assets/models/heart.glb exists, then reload.
        </div>
      )}
    </>
  )
}
