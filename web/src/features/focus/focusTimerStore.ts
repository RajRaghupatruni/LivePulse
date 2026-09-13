import { useSyncExternalStore } from 'react'
import { getPreference, removePreference, setPreference } from '../../lib/platform'

export type FocusTimerSnapshot = {
  status: 'idle' | 'running' | 'paused' | 'complete'
  durationMinutes: 25 | 50 | 90 | null
  deadline: number | null
  remainingMs: number | null
}

const STORAGE_KEY = 'livepulse.focus-timer.v1'
const idle: FocusTimerSnapshot = { status: 'idle', durationMinutes: null, deadline: null, remainingMs: null }
let snapshot = restore()
const listeners = new Set<() => void>()

function restore(): FocusTimerSnapshot {
  if (typeof window === 'undefined') return idle
  try {
    const raw = getPreference(STORAGE_KEY)
    if (!raw) return idle
    const saved = JSON.parse(raw) as { durationMinutes?: number; deadline?: number; remainingMs?: number; status?: string }
    if (![25, 50, 90].includes(saved.durationMinutes ?? 0)) return idle
    if (saved.status === 'paused' && Number.isFinite(saved.remainingMs) && (saved.remainingMs ?? 0) > 0) {
      return { status: 'paused', durationMinutes: saved.durationMinutes as 25 | 50 | 90, deadline: null, remainingMs: saved.remainingMs! }
    }
    if (saved.status === 'running' && Number.isFinite(saved.deadline)) {
      if ((saved.deadline ?? 0) <= Date.now()) return { status: 'complete', durationMinutes: saved.durationMinutes as 25 | 50 | 90, deadline: null, remainingMs: 0 }
      return { status: 'running', durationMinutes: saved.durationMinutes as 25 | 50 | 90, deadline: saved.deadline!, remainingMs: null }
    }
  } catch {
    removePreference(STORAGE_KEY)
  }
  return idle
}

function publish(next: FocusTimerSnapshot) {
  snapshot = next
  for (const listener of listeners) listener()
}

function persist(next: FocusTimerSnapshot) {
  if (next.status === 'running' || next.status === 'paused') setPreference(STORAGE_KEY, JSON.stringify(next))
  else removePreference(STORAGE_KEY)
}

export const focusTimerStore = {
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  getSnapshot: () => snapshot,
  start(minutes: 25 | 50 | 90) {
    const next: FocusTimerSnapshot = { status: 'running', durationMinutes: minutes, deadline: Date.now() + minutes * 60_000, remainingMs: null }
    persist(next)
    publish(next)
  },
  pause(now = Date.now()) {
    if (snapshot.status !== 'running' || snapshot.deadline === null) return
    const remainingMs = Math.max(0, snapshot.deadline - now)
    if (remainingMs === 0) return this.complete()
    const next: FocusTimerSnapshot = { ...snapshot, status: 'paused', deadline: null, remainingMs }
    persist(next)
    publish(next)
  },
  resume() {
    if (snapshot.status !== 'paused' || snapshot.remainingMs === null) return
    const next: FocusTimerSnapshot = { ...snapshot, status: 'running', deadline: Date.now() + snapshot.remainingMs, remainingMs: null }
    persist(next)
    publish(next)
  },
  complete() {
    const next: FocusTimerSnapshot = { ...snapshot, status: 'complete', deadline: null, remainingMs: 0 }
    persist(next)
    publish(next)
  },
  cancel() {
    persist(idle)
    publish(idle)
  },
}

export function useFocusTimerSnapshot() {
  return useSyncExternalStore(focusTimerStore.subscribe, focusTimerStore.getSnapshot, () => idle)
}
