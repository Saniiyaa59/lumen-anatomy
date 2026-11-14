/** One selecting click. Sent to the backend as `click_events`. */
export interface ClickEvent {
  /** Seconds, from a monotonic clock (`performance.now() / 1000`). */
  t: number
  structure_id: string
}

export interface SelectionState {
  /** Selected structure IDs in click order: the first is "here", the second is "there". */
  readonly selected: readonly string[]
  /** The clicks that produced `selected`, oldest first. */
  readonly clickLog: readonly ClickEvent[]
}

const EMPTY: SelectionState = { selected: [], clickLog: [] }

/**
 * The current selection and its click log.
 *
 * Lives outside React so the scene controller can read and change it directly;
 * React components subscribe through `useSelection`.
 */
export class SelectionStore {
  private state: SelectionState = EMPTY
  private readonly listeners = new Set<() => void>()
  private readonly now: () => number

  constructor(now: () => number = () => performance.now() / 1000) {
    this.now = now
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  readonly getState = (): SelectionState => this.state

  /**
   * A click in the 3D view. `structureId` is null when the click hit empty space.
   *
   * Plain click: select only that structure (empty space clears).
   * Additive (Shift) click: add the structure, or remove it if already selected.
   */
  click(structureId: string | null, additive: boolean): void {
    if (structureId === null) {
      if (!additive) this.clear()
      return
    }
    const event: ClickEvent = { t: this.now(), structure_id: structureId }
    if (!additive) {
      this.update({ selected: [structureId], clickLog: [event] })
    } else if (this.state.selected.includes(structureId)) {
      this.remove(structureId)
    } else {
      this.update({
        selected: [...this.state.selected, structureId],
        clickLog: [...this.state.clickLog, event],
      })
    }
  }

  remove(structureId: string): void {
    if (!this.state.selected.includes(structureId)) return
    this.update({
      selected: this.state.selected.filter((id) => id !== structureId),
      clickLog: this.state.clickLog.filter((event) => event.structure_id !== structureId),
    })
  }

  clear(): void {
    if (this.state.selected.length === 0) return
    this.update(EMPTY)
  }

  /** Replace the selection without clicks, e.g. for the agent's `set_selection` action. */
  set(structureIds: readonly string[]): void {
    this.update({ selected: [...new Set(structureIds)], clickLog: [] })
  }

  private update(next: SelectionState): void {
    this.state = next
    this.listeners.forEach((listener) => listener())
  }
}

export const selectionStore = new SelectionStore()
