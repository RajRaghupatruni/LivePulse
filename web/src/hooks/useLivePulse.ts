import { useCallback, useEffect, useRef, useState } from 'react'
import { getLiveState, getTimeline } from '../lib/api'
import { connectRealtime } from '../lib/platform'
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

function compareTimelineItems(a: TimelineItem, b: TimelineItem): number {
  const timeOrder = Date.parse(b.timestamp) - Date.parse(a.timestamp)
  return Number.isNaN(timeOrder) || timeOrder === 0 ? b.cursor - a.cursor : timeOrder
}

function upsertTimeline(items: TimelineItem[], item: TimelineItem): TimelineItem[] {
  if (items.some((entry) => entry.event_id === item.event_id)) return items
  return [item, ...items].sort(compareTimelineItems).slice(0, 100)
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
    dominant_focus: null,
    updated_at: null,
  })
  const [timeline, setTimeline] = useState<TimelineItem[]>([])
  const [hasOlder, setHasOlder] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [connection, setConnection] = useState<ConnectionState>('CONNECTING')
  const [eventArrival, setEventArrival] = useState<Pick<TimelineItem, 'event_id' | 'event_type' | 'subject_id' | 'timestamp' | 'payload'> | null>(null)
  const cursor = useRef(0)
  const eventArrivalTimer = useRef(0)
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
    setTimeline([...history.items].sort(compareTimelineItems))
    setHasOlder(history.items.length >= 40)
    cursor.current = Math.max(cursor.current, history.latest_cursor)
  }, [commitLive])

  const loadOlder = useCallback(async () => {
    if (loadingOlder || !hasOlder || timeline.length === 0) return
    setLoadingOlder(true)
    try {
      const before = Math.min(...timeline.map((item) => item.cursor))
      const history = await getTimeline(40, before)
      setTimeline((current) => {
        const seen = new Set(current.map((item) => item.event_id))
        return [...current, ...history.items.filter((item) => !seen.has(item.event_id))].sort(compareTimelineItems)
      })
      setHasOlder(history.items.length >= 40)
    } finally {
      setLoadingOlder(false)
    }
  }, [hasOlder, loadingOlder, timeline])

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
    const attention = live.dominant_focus
    if (!attention?.transient || !attention.expires_at) return
    const delay = Math.max(0, Date.parse(attention.expires_at) - Date.now() + 75)
    const timer = window.setTimeout(() => {
      void refreshState().catch(() => setConnection('DEGRADED'))
    }, delay)
    return () => window.clearTimeout(timer)
  }, [live.dominant_focus, refreshState])

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
      let nextSocket: WebSocket
      try {
        nextSocket = connectRealtime(`/ws?last_cursor=${cursor.current}`)
      } catch {
        if (!disposed) {
          setConnection('RECONNECTING')
          const delay = Math.min(1000 * 2 ** attempt, 12000)
          attempt += 1
          reconnectTimer = window.setTimeout(() => void connect(), delay)
        }
        return
      }
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
          subject_id: message.state?.match_id ?? message.subject_id ?? message.focus?.subject_id ?? '',
          timestamp: message.timestamp ?? new Date().toISOString(),
          observed_at: message.observed_at,
          payload: message.payload ?? {},
        }
        setEventArrival({ event_id: item.event_id, event_type: item.event_type, subject_id: item.subject_id, timestamp: item.timestamp, payload: item.payload })
        window.clearTimeout(eventArrivalTimer.current)
        eventArrivalTimer.current = window.setTimeout(() => setEventArrival(null), 2800)
        setTimeline((current) => upsertTimeline(current, item))
        if (message.state) {
          const previous = liveRef.current
          if (previous.match?.match_id !== message.state.match_id) {
            // A different match can be an inactive projection. Only REST knows
            // which match is currently active, so use the event as a resync cue.
            void refreshState().catch(() => setConnection('DEGRADED'))
          } else {
            commitLive(mergeRealtimeState(previous, message.state, message.focus, message.attention))
            void refreshState().catch(() => setConnection('DEGRADED'))
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
      window.clearTimeout(eventArrivalTimer.current)
      socket?.close()
    }
  }, [commitLive, refresh, refreshState])

  return { live, timeline, connection, eventArrival, loadOlder, hasOlder, loadingOlder, refresh, refreshState }
}
