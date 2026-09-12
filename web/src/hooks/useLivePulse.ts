import { useCallback, useEffect, useRef, useState } from 'react'
import { getLiveState, getTimeline, resetDemo, startDemo } from '../lib/api'
import type { LiveState, RealtimeMessage, TimelineItem } from '../types/livepulse'

export type ConnectionState = 'CONNECTING' | 'LIVE' | 'RECONNECTING' | 'RESYNCING' | 'DEGRADED'

const EVENT_ATTENTION_TTL_MS = 12_000

export function mergeLiveState(current: LiveState, next: LiveState): LiveState {
  const sameMatch = current.match?.match_id === next.match?.match_id
  if (sameMatch && current.match && next.match && next.match.version < current.match.version) {
    return current
  }
  return next
}

function upsertTimeline(items: TimelineItem[], item: TimelineItem): TimelineItem[] {
  if (items.some((entry) => entry.event_id === item.event_id)) return items
  return [item, ...items].sort((a, b) => b.cursor - a.cursor).slice(0, 100)
}

export function useLivePulse() {
  const [live, setLive] = useState<LiveState>({ match: null, attention: 20, updated_at: null })
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [connection, setConnection] = useState<ConnectionState>('CONNECTING')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cursor = useRef(0)
  const snapshotGeneration = useRef(0)
  const focusTimer = useRef<number | null>(null)
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
    let disposed = false
    let socket: WebSocket | null = null
    let reconnectTimer = 0
    let attempt = 0

    const clearFocusTimer = () => {
      if (focusTimer.current !== null) window.clearTimeout(focusTimer.current)
      focusTimer.current = null
    }

    const scheduleFocusDecay = (updatedAt: string) => {
      clearFocusTimer()
      const expiresAt = Date.parse(updatedAt) + EVENT_ATTENTION_TTL_MS + 100
      focusTimer.current = window.setTimeout(() => {
        void refreshState().catch(() => setConnection('DEGRADED'))
      }, Math.max(0, expiresAt - Date.now()))
    }

    const connect = async () => {
      try {
        await refresh()
      } catch {
        if (!disposed) setConnection('DEGRADED')
      }
      if (disposed) return
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${protocol}//${window.location.host}/ws?last_cursor=${cursor.current}`)
      socket.onopen = () => {
        attempt = 0
        setConnection('LIVE')
        void refresh().catch(() => setConnection('DEGRADED'))
      }
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as RealtimeMessage
        if (message.type === 'heartbeat') return
        if (message.type === 'resync_required') {
          setConnection('RESYNCING')
          void refresh().then(() => setConnection('LIVE')).catch(() => setConnection('DEGRADED'))
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
          subject_id: message.state?.match_id ?? '',
          timestamp: message.timestamp ?? new Date().toISOString(),
          payload: message.payload ?? {},
        }
        setTimeline((current) => upsertTimeline(current, item))
        if (message.state) {
          const previous = liveRef.current
          const staleState = previous.match?.match_id === message.state.match_id
            && message.state.version < previous.match.version
          if (!staleState) {
            commitLive({
              ...previous,
            match: message.state!,
            attention: message.attention ?? previous.attention,
            updated_at: message.state!.updated_at,
            })
            if (message.attention === 95) scheduleFocusDecay(message.state.updated_at)
            else clearFocusTimer()
          }
        } else {
          void refreshState().catch(() => setConnection('DEGRADED'))
        }
      }
      socket.onclose = () => {
        if (disposed) return
        setConnection('RECONNECTING')
        const delay = Math.min(1000 * 2 ** attempt, 12000)
        attempt += 1
        reconnectTimer = window.setTimeout(() => void connect(), delay)
      }
      socket.onerror = () => socket?.close()
    }

    void connect()
    return () => {
      disposed = true
      window.clearTimeout(reconnectTimer)
      clearFocusTimer()
      socket?.close()
    }
  }, [commitLive, refresh, refreshState])

  const runDemo = async () => {
    setBusy(true)
    setError(null)
    try {
      await startDemo()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start demo')
    } finally {
      setBusy(false)
    }
  }
  const reset = async () => {
    setBusy(true)
    setError(null)
    try {
      await resetDemo()
      if (focusTimer.current !== null) window.clearTimeout(focusTimer.current)
      focusTimer.current = null
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not reset demo')
    } finally {
      setBusy(false)
    }
  }

  return { live, timeline, connection, busy, error, runDemo, reset }
}
