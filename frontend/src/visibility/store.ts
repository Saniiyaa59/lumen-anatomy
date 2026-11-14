export interface VisibilityState {
  /** IDs of the structures currently hidden in the 3D view. */
  readonly hidden: ReadonlySet<string>
}

/**
 * Which structures are hidden.
 *
 * Lives outside React, like the selection: the structure panel and the scene
 * controller (and so the agent's `set_visibility` action) all change it, and
 * each stays in step by subscribing.
 */
export class VisibilityStore {
  private state: VisibilityState = { hidden: new Set() }
  private readonly listeners = new Set<() => void>()

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  readonly getState = (): VisibilityState => this.state

  setVisible(structureIds: Iterable<string>, visible: boolean): void {
    const hidden = new Set(this.state.hidden)
    for (const id of structureIds) {
      if (visible) hidden.delete(id)
      else hidden.add(id)
    }
    this.update(hidden)
  }

  toggle(structureId: string): void {
    this.setVisible([structureId], this.state.hidden.has(structureId))
  }

  showAll(): void {
    this.update(new Set())
  }

  private update(hidden: Set<string>): void {
    const current = this.state.hidden
    if (hidden.size === current.size && [...hidden].every((id) => current.has(id))) return
    this.state = { hidden }
    this.listeners.forEach((listener) => listener())
  }
}

export const visibilityStore = new VisibilityStore()
