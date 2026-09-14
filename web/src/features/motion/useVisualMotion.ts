import { useCallback, useEffect, useRef, useState } from 'react'
import type { ConnectionState } from '../../hooks/useLivePulse'
import type { TimelineItem } from '../../types/livepulse'
import { eventLifetimeMs, visualEventFromTimeline, visualEventFromTransition, type VisualEvent } from './visualMotion'

type EventArrival = Pick<TimelineItem, 'event_id' | 'event_type' | 'subject_id' | 'timestamp'> & Partial<Pick<TimelineItem, 'source'>>

type VisualMotionInput = {
  eventArrival: EventArrival | null
  matchMode: string
  focusKey: string
  connection: ConnectionState
  healthStatus: string | null
  weatherKey: string
  spotifyTrackId: string | null
  spotifyPlaying: boolean | null
}

type PreviousState = Omit<VisualMotionInput, 'eventArrival'>

function matchIsActive(mode: string) {
  return ['live', 'halftime', 'highlight'].includes(mode)
}

/**
 * The app-level visual event bus. Inputs are authoritative state transitions and
 * newly delivered canonical timeline items; routine snapshots never enter it.
 */
export function useVisualMotion(input: VisualMotionInput) {
  const [events, setEvents] = useState<VisualEvent[]>([])
  const [currentEventId, setCurrentEventId] = useState<string | null>(null)
  const previous = useRef<PreviousState | null>(null)
  const recentIds = useRef<string[]>([])
  const sequence = useRef(0)
  const timers = useRef(new Map<string, number>())
  const arrivalId = input.eventArrival?.event_id
  const arrivalType = input.eventArrival?.event_type
  const arrivalSource = input.eventArrival?.source
  const arrivalSubject = input.eventArrival?.subject_id
  const arrivalTime = input.eventArrival?.timestamp

  const emit = useCallback((event: VisualEvent) => {
    if (recentIds.current.includes(event.id)) return
    recentIds.current.push(event.id)
    if (recentIds.current.length > 500) recentIds.current.splice(0, recentIds.current.length - 500)
    setCurrentEventId(event.id)
    setEvents((current) => [...current, event].slice(-8))
    const timeout = window.setTimeout(() => {
      timers.current.delete(event.id)
      setCurrentEventId((current) => current === event.id ? null : current)
      setEvents((current) => current.filter((candidate) => candidate.id !== event.id))
    }, eventLifetimeMs(event))
    timers.current.set(event.id, timeout)
  }, [])

  useEffect(() => {
    const state: PreviousState = {
      matchMode: input.matchMode,
      focusKey: input.focusKey,
      connection: input.connection,
      healthStatus: input.healthStatus,
      weatherKey: input.weatherKey,
      spotifyTrackId: input.spotifyTrackId,
      spotifyPlaying: input.spotifyPlaying,
    }
    const old = previous.current
    if (old) {
      let systemTransition: 'SYSTEM_DEGRADED' | 'SYSTEM_RECOVERED' | null = null
      const makeTransition = (name: Parameters<typeof visualEventFromTransition>[0], source: string, subject: string | null, intensity: VisualEvent['intensity'] = 'subtle') => {
        sequence.current += 1
        return visualEventFromTransition(name, `state:${name}:${sequence.current}`, source, subject, intensity)
      }

      if (old.matchMode !== state.matchMode) {
        if (!matchIsActive(old.matchMode) && matchIsActive(state.matchMode)) emit(makeTransition('MATCH_MODE_ENTER', 'football', null, 'moderate'))
        if (matchIsActive(old.matchMode) && !matchIsActive(state.matchMode)) emit(makeTransition('MATCH_MODE_EXIT', 'football', null))
      }
      if (old.focusKey && state.focusKey && old.focusKey !== state.focusKey) emit(makeTransition('FOCUS_CHANGED', 'focus', null, 'moderate'))

      if (old.connection !== state.connection) {
        if (state.connection === 'RECONNECTING') emit(makeTransition('SYSTEM_RECONNECTING', 'realtime', null, 'moderate'))
        else if (state.connection === 'RESYNCING') emit(makeTransition('SYSTEM_RESYNCING', 'realtime', null, 'moderate'))
        else if (state.connection === 'DEGRADED') { emit(makeTransition('SYSTEM_DEGRADED', 'realtime', null, 'strong')); systemTransition = 'SYSTEM_DEGRADED' }
        else if (state.connection === 'LIVE' && ['RECONNECTING', 'RESYNCING', 'DEGRADED'].includes(old.connection)) { emit(makeTransition('SYSTEM_RECOVERED', 'realtime', null, 'moderate')); systemTransition = 'SYSTEM_RECOVERED' }
      }
      if (old.healthStatus !== state.healthStatus) {
        if (['degraded', 'unavailable'].includes(state.healthStatus ?? '') && systemTransition !== 'SYSTEM_DEGRADED') emit(makeTransition('SYSTEM_DEGRADED', 'system', null, 'strong'))
        else if (state.healthStatus === 'healthy' && ['degraded', 'unavailable'].includes(old.healthStatus ?? '') && systemTransition !== 'SYSTEM_RECOVERED') emit(makeTransition('SYSTEM_RECOVERED', 'system', null, 'moderate'))
      }
      if (old.weatherKey && state.weatherKey && old.weatherKey !== state.weatherKey) emit(makeTransition('WEATHER_CHANGED', 'weather', null))
      if (old.spotifyTrackId && state.spotifyTrackId && old.spotifyTrackId !== state.spotifyTrackId) emit(makeTransition('SPOTIFY_TRACK_CHANGED', 'spotify', state.spotifyTrackId))
      if (old.spotifyPlaying !== null && state.spotifyPlaying !== null && old.spotifyPlaying !== state.spotifyPlaying) {
        emit(makeTransition(state.spotifyPlaying ? 'SPOTIFY_PLAYBACK_STARTED' : 'SPOTIFY_PLAYBACK_PAUSED', 'spotify', state.spotifyTrackId))
      }
    }
    previous.current = state

    if (arrivalId && arrivalType && arrivalTime) {
      const event = visualEventFromTimeline({
        event_id: arrivalId,
        event_type: arrivalType,
        source: arrivalSource ?? arrivalType.split('.')[0],
        subject_id: arrivalSubject ?? '',
        timestamp: arrivalTime,
      })
      if (event) emit(event)
    }
  }, [
    arrivalId, arrivalType, arrivalSource, arrivalSubject, arrivalTime,
    input.matchMode, input.focusKey, input.connection, input.healthStatus,
    input.weatherKey, input.spotifyTrackId, input.spotifyPlaying, emit,
  ])

  useEffect(() => () => {
    for (const timeout of timers.current.values()) window.clearTimeout(timeout)
    timers.current.clear()
  }, [])

  return { events, current: events.find((event) => event.id === currentEventId) ?? null }
}
