import { useCallback, useEffect, useRef, useState } from 'react'
import { getLiveState, getTimeline, resetDemo, startDemo } from '../lib/api'
import type { LiveState, RealtimeMessage, TimelineItem } from '../types/livepulse'

export type ConnectionState = 'CONNECTING' | 'LIVE' | 'RECONNECTING' | 'RESYNCING' | 'DEGRADED'

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
  const refresh = useCallback(async () => {
    const [state, history] = await Promise.all([getLiveState(), getTimeline()])
    setLive(state)
    setTimeline(history.items)
    cursor.current = Math.max(cursor.current, history.latest_cursor)
  }, [])

  useEffect(() => {
    let disposed = false
    let socket: WebSocket | null = null
    let reconnectTimer = 0
    let attempt = 0

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
          setLive((current) => ({
            ...current,
            match: message.state!,
            attention: message.attention ?? current.attention,
            updated_at: message.state!.updated_at,
          }))
        } else {
          void getLiveState().then(setLive).catch(() => setConnection('DEGRADED'))
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
      socket?.close()
    }
  }, [refresh])

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
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not reset demo')
    } finally {
      setBusy(false)
    }
  }

  return { live, timeline, connection, busy, error, runDemo, reset }
}
