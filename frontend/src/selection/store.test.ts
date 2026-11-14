import { describe, expect, it, vi } from 'vitest'
import { SelectionStore } from './store.ts'

/** A store whose clock ticks 1, 2, 3… so click times are predictable. */
function makeStore() {
  let time = 0
  return new SelectionStore(() => ++time)
}

describe('SelectionStore', () => {
  it('selects only the clicked structure on a plain click', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.click('aorta', false)
    expect(store.getState().selected).toEqual(['aorta'])
    expect(store.getState().clickLog).toEqual([{ t: 2, structure_id: 'aorta' }])
  })

  it('keeps Shift-click order, so the first is "here" and the second "there"', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.click('aorta', true)
    store.click('mitral_valve', true)
    expect(store.getState().selected).toEqual(['right_atrium', 'aorta', 'mitral_valve'])
    expect(store.getState().clickLog).toEqual([
      { t: 1, structure_id: 'right_atrium' },
      { t: 2, structure_id: 'aorta' },
      { t: 3, structure_id: 'mitral_valve' },
    ])
  })

  it('removes a selected structure and its click on a second Shift-click', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.click('aorta', true)
    store.click('right_atrium', true)
    expect(store.getState().selected).toEqual(['aorta'])
    expect(store.getState().clickLog).toEqual([{ t: 2, structure_id: 'aorta' }])
  })

  it('puts a re-added structure at the end', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.click('aorta', true)
    store.click('right_atrium', true)
    store.click('right_atrium', true)
    expect(store.getState().selected).toEqual(['aorta', 'right_atrium'])
  })

  it('clears on a plain click on empty space, but not on a Shift-click', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.click(null, true)
    expect(store.getState().selected).toEqual(['right_atrium'])
    store.click(null, false)
    expect(store.getState().selected).toEqual([])
    expect(store.getState().clickLog).toEqual([])
  })

  it('removes one structure by ID, as the chip × does', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.click('aorta', true)
    store.remove('right_atrium')
    expect(store.getState().selected).toEqual(['aorta'])
    expect(store.getState().clickLog).toEqual([{ t: 2, structure_id: 'aorta' }])
  })

  it('sets a selection without clicks, dropping duplicates', () => {
    const store = makeStore()
    store.click('right_atrium', false)
    store.set(['aorta', 'mitral_valve', 'aorta'])
    expect(store.getState().selected).toEqual(['aorta', 'mitral_valve'])
    expect(store.getState().clickLog).toEqual([])
  })

  it('notifies subscribers on change only, and stops after unsubscribe', () => {
    const store = makeStore()
    const listener = vi.fn()
    const unsubscribe = store.subscribe(listener)
    store.clear()
    store.remove('aorta')
    expect(listener).not.toHaveBeenCalled()
    store.click('aorta', false)
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
    store.clear()
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('returns a new state object on each change, as useSyncExternalStore needs', () => {
    const store = makeStore()
    const before = store.getState()
    store.click('aorta', false)
    expect(store.getState()).not.toBe(before)
    expect(store.getState()).toBe(store.getState())
  })
})
