import { useSyncExternalStore } from 'react'
import { visibilityStore, type VisibilityState } from './store.ts'

export function useVisibility(): VisibilityState {
  return useSyncExternalStore(visibilityStore.subscribe, visibilityStore.getState)
}
