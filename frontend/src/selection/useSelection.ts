import { useSyncExternalStore } from 'react'
import { selectionStore, type SelectionState } from './store.ts'

export function useSelection(): SelectionState {
  return useSyncExternalStore(selectionStore.subscribe, selectionStore.getState)
}
