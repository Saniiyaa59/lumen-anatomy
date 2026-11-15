import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { displayName } from '../registry.ts'
import { selectionStore } from '../selection/store.ts'
import { playerStore } from '../session/player.ts'
import { Stage } from '../session/stage.ts'
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
  /** Aim the camera again at what the session part on screen is showing, e.g. after the view changes width. */
  reframe(): void
}

interface ViewerProps {
  /** Whether each visible structure is named with a leader-line label. */
  showLabels: boolean
  /** Whether hovering a structure shows its name. Off while a case is asking for a place. */
  showNames: boolean
  ref?: Ref<ViewerHandle>
}

export default function Viewer({ showLabels, showNames, ref }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<SceneController | null>(null)
  const stageRef = useRef<Stage | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')
  // Read by the hover callback below, which is set up once.
  const showNamesRef = useRef(showNames)
  useEffect(() => {
    showNamesRef.current = showNames
    if (!showNames && tooltipRef.current) tooltipRef.current.hidden = true
  }, [showNames])

  useImperativeHandle(
    ref,
    () => ({
      resetView: () => controllerRef.current?.resetView(),
      reframe: () => stageRef.current?.reframe(),
    }),
    [],
  )

  useEffect(() => {
    const controller = new SceneController(containerRef.current!, selectionStore, visibilityStore)
    controllerRef.current = controller
    // Shows whatever part of a study session is playing on the model.
    const stage = new Stage(controller, playerStore, visibilityStore)
    stageRef.current = stage
    let active = true

    controller.ready.then(
      () => active && setLoadState('ready'),
      (error: unknown) => {
        console.error('Could not load the model', error)
        if (active) setLoadState('error')
      },
    )

    // The tooltip follows the cursor, so it is moved directly instead of through React state.
    controller.onHover = (hover) => {
      const tooltip = tooltipRef.current
      if (!tooltip) return
      tooltip.hidden = hover === null || !showNamesRef.current
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
      stage.dispose()
      stageRef.current = null
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
      {loadState === 'loading' && <div className="viewer-message">Loading the model…</div>}
      {loadState === 'error' && (
        <div className="viewer-message" role="alert">
          The model couldn't be loaded. Check that assets/regions/heart/model.glb exists, then reload.
        </div>
      )}
    </>
  )
}
