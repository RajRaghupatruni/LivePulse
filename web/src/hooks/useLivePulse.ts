import { useCallback, useEffect, useRef, useState } from 'react'
import { getLiveState, getTimeline, resetDemo, startDemo } from '../lib/api'
import type { FocusState, LiveState, Match, RealtimeMessage, TimelineItem } from '../types/livepulse'

export type ConnectionState = 'CONNECTING' | 'LIVE' | 'RECONNECTING' | 'RESYNCING' | 'DEGRADED'

export function mergeLiveState(current: LiveState, next: LiveState): LiveState {
  const sameMatch = current.match?.match_id === next.match?.match_id
  if (sameMatch && current.match && next.match && next.match.version < current.match.version) {
    return current
  }
  return next
}

export function mergeRealtimeState(
  current: LiveState,
  nextMatch: Match,
  focus?: FocusState,
  attention?: number,
): LiveState {
  if (!current.match || current.match.match_id !== nextMatch.match_id) {
    return current
  }
  if (nextMatch.version < current.match.version) {
    return current
  }
  return {
    ...current,
    match: nextMatch,
    focus: focus ?? current.focus,
    attention: focus?.score ?? attention ?? current.attention,
    updated_at: nextMatch.updated_at,
  }
}

function upsertTimeline(items: TimelineItem[], item: TimelineItem): TimelineItem[] {
  if (items.some((entry) => entry.event_id === item.event_id)) return items
  return [item, ...items].sort((a, b) => b.cursor - a.cursor).slice(0, 100)
}

export function useLivePulse() {
  const [live, setLive] = useState<LiveState>({
    match: null,
    attention: 10,
    focus: {
      score: 10,
      severity: 'low',
      reason: 'no_active_match',
      transient: false,
      expires_at: null,
      source: 'system',
      subject_id: null,
      match_mode: 'idle',
    },
    updated_at: null,
  })
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [connection, setConnection] = useState<ConnectionState>('CONNECTING')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cursor = useRef(0)
  const snapshotGeneration = useRef(0)
  const liveRef = useRef(live)
  const commitLive = useCallback((next: LiveState) => {
    const merged = mergeLiveState(liveRef.current, next)
    liveRef.current = merged
    setLive(merged)
  }, [])
  const refreshState = useCallback(async () => {
    const generation = ++snapshotGeneration.current
    const state = await getLiveState()
    if (generation === snapshotGeneration.current) commitLive(state)
  }, [commitLive])
  const refresh = useCallback(async () => {
    const generation = ++snapshotGeneration.current
    const [state, history] = await Promise.all([getLiveState(), getTimeline()])
    if (generation !== snapshotGeneration.current) return
    commitLive(state)
    setTimeline(history.items)
    cursor.current = Math.max(cursor.current, history.latest_cursor)
  }, [commitLive])

  useEffect(() => {
    const expiresAt = live.focus.expires_at
    if (!live.focus.transient || !expiresAt) return
    const delay = Math.max(0, Date.parse(expiresAt) - Date.now() + 75)
    const timer = window.setTimeout(() => {
      void refreshState().catch(() => setConnection('DEGRADED'))
    }, delay)
    return () => window.clearTimeout(timer)
  }, [live.focus.expires_at, live.focus.transient, refreshState])

  useEffect(() => {
    let disposed = false
    let socket: WebSocket | null = null
    let reconnectTimer = 0
    let attempt = 0
    let socketGeneration = 0

    const connect = async () => {
      const generation = ++socketGeneration
      if (attempt > 0) setConnection('RESYNCING')
      try {
        await refresh()
      } catch {
        if (!disposed) setConnection('DEGRADED')
      }
      if (disposed) return
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const nextSocket = new WebSocket(`${protocol}//${window.location.host}/ws?last_cursor=${cursor.current}`)
      socket = nextSocket
      nextSocket.onopen = () => {
        if (generation !== socketGeneration) return
        attempt = 0
        setConnection('LIVE')
        void refresh().catch(() => setConnection('DEGRADED'))
      }
      nextSocket.onmessage = (event) => {
        if (generation !== socketGeneration) return
        const message = JSON.parse(event.data) as RealtimeMessage
        if (message.type === 'heartbeat') return
        if (message.type === 'resync_required') {
          setConnection('RESYNCING')
          void refresh()
            .then(() => {
              if (generation === socketGeneration && nextSocket.readyState === WebSocket.OPEN) {
                setConnection('LIVE')
              }
            })
            .catch(() => setConnection('DEGRADED'))
          return
        }
        if (message.type !== 'timeline.item' || !message.event_id || !message.cursor) return
        if (message.cursor <= cursor.current) return
        cursor.current = message.cursor
        snapshotGeneration.current += 1
        const item: TimelineItem = {
          cursor: message.cursor,
          event_id: message.event_id,
          event_type: message.event_type ?? 'unknown',
          source: message.source ?? 'unknown',
          subject_id: message.state?.match_id ?? message.focus?.subject_id ?? '',
          timestamp: message.timestamp ?? new Date().toISOString(),
          payload: message.payload ?? {},
        }
        setTimeline((current) => upsertTimeline(current, item))
        if (message.state) {
          const previous = liveRef.current
          if (previous.match?.match_id !== message.state.match_id) {
            // A different match can be an inactive projection. Only REST knows
            // which match is currently active, so use the event as a resync cue.
            void refreshState().catch(() => setConnection('DEGRADED'))
          } else {
            commitLive(mergeRealtimeState(previous, message.state, message.focus, message.attention))
          }
        } else {
          void refreshState().catch(() => setConnection('DEGRADED'))
        }
      }
      nextSocket.onclose = () => {
        if (generation !== socketGeneration) return
        if (disposed) return
        setConnection('RECONNECTING')
        const delay = Math.min(1000 * 2 ** attempt, 12000)
        attempt += 1
        reconnectTimer = window.setTimeout(() => void connect(), delay)
      }
      nextSocket.onerror = () => nextSocket.close()
    }

    void connect()
    return () => {
      disposed = true
      socketGeneration += 1
      window.clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [commitLive, refresh, refreshState])

  const runDemo = async (): Promise<boolean> => {
    setBusy(true)
    setError(null)
    try {
      await startDemo()
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start demo')
      return false
    } finally {
      setBusy(false)
    }
  }
  const reset = async (): Promise<boolean> => {
    setBusy(true)
    setError(null)
    try {
      await resetDemo()
      await refresh()
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not reset demo')
      return false
    } finally {
      setBusy(false)
    }
  }

  return { live, timeline, connection, busy, error, runDemo, reset }
}
