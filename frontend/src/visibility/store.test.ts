import { describe, expect, it, vi } from 'vitest'
import { VisibilityStore } from './store.ts'

const hidden = (store: VisibilityStore) => [...store.getState().hidden].sort()

describe('VisibilityStore', () => {
  it('starts with everything visible', () => {
    expect(hidden(new VisibilityStore())).toEqual([])
  })

  it('hides and shows several structures at once', () => {
    const store = new VisibilityStore()
    store.setVisible(['right_atrium', 'left_atrium', 'aorta'], false)
    store.setVisible(['left_atrium'], true)
    expect(hidden(store)).toEqual(['aorta', 'right_atrium'])
  })

  it('toggles one structure', () => {
    const store = new VisibilityStore()
    store.toggle('aorta')
    expect(hidden(store)).toEqual(['aorta'])
    store.toggle('aorta')
    expect(hidden(store)).toEqual([])
  })

  it('shows everything again', () => {
    const store = new VisibilityStore()
    store.setVisible(['right_atrium', 'aorta'], false)
    store.showAll()
    expect(hidden(store)).toEqual([])
  })

  it('notifies subscribers only when something changes', () => {
    const store = new VisibilityStore()
    const listener = vi.fn()
    store.subscribe(listener)
    store.showAll()
    store.setVisible(['aorta'], true)
    expect(listener).not.toHaveBeenCalled()
    store.setVisible(['aorta'], false)
    store.setVisible(['aorta'], false)
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('returns a new state object on each change, as useSyncExternalStore needs', () => {
    const store = new VisibilityStore()
    const before = store.getState()
    store.toggle('aorta')
    expect(store.getState()).not.toBe(before)
    expect(store.getState()).toBe(store.getState())
  })
})
