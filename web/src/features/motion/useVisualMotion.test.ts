import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useVisualMotion } from './useVisualMotion'

const base: Parameters<typeof useVisualMotion>[0] = {
  eventArrival: null,
  matchMode: 'idle',
  focusKey: 'idle',
  connection: 'LIVE' as const,
  healthStatus: 'healthy',
  weatherKey: 'nyc|clear|night',
  spotifyTrackId: null,
  spotifyPlaying: null,
}

describe('useVisualMotion', () => {
  it('emits a goal once even when an identical WebSocket snapshot repeats', () => {
    const { result, rerender } = renderHook(({ input }) => useVisualMotion(input), { initialProps: { input: base } })
    const goal = { event_id: 'goal-1', event_type: 'football.match.goal', subject_id: 'match-1', timestamp: '2026-09-14T12:00:00Z' }
    rerender({ input: { ...base, eventArrival: goal, matchMode: 'live' } })
    expect(result.current.events.map((event) => event.name)).toContain('FOOTBALL_GOAL')
    rerender({ input: { ...base, eventArrival: { ...goal }, matchMode: 'live' } })
    expect(result.current.events.filter((event) => event.id === 'goal-1')).toHaveLength(1)
  })

  it('emits new mail and GitHub failure signatures from newly delivered canonical events', () => {
    const { result, rerender } = renderHook(({ input }) => useVisualMotion(input), { initialProps: { input: base } })
    const mail = { event_id: 'mail-1', event_type: 'mail.message.received', subject_id: 'thread-1', timestamp: '2026-09-14T12:00:00Z' }
    act(() => rerender({ input: { ...base, eventArrival: mail } }))
    expect(result.current.current?.name).toBe('GMAIL_MESSAGE_RECEIVED')
    act(() => rerender({ input: { ...base, eventArrival: { ...mail } } }))
    expect(result.current.events.filter((event) => event.id === 'mail-1')).toHaveLength(1)
    act(() => rerender({ input: { ...base, eventArrival: { event_id: 'workflow-1', event_type: 'developer.workflow.failed', subject_id: 'repo-1', timestamp: '2026-09-14T12:00:01Z' } } }))
    expect(result.current.current?.name).toBe('GITHUB_WORKFLOW_FAILED')
  })

  it('reacts once to match-mode and system recovery transitions', () => {
    const { result, rerender } = renderHook(({ input }) => useVisualMotion(input), { initialProps: { input: base } })
    rerender({ input: { ...base, matchMode: 'live', connection: 'RECONNECTING' } })
    expect(result.current.events.map((event) => event.name)).toEqual(expect.arrayContaining(['MATCH_MODE_ENTER', 'SYSTEM_RECONNECTING']))
    rerender({ input: { ...base, matchMode: 'live', connection: 'RESYNCING' } })
    expect(result.current.events.filter((event) => event.name === 'SYSTEM_RESYNCING')).toHaveLength(1)
    rerender({ input: { ...base, matchMode: 'live', connection: 'LIVE' } })
    expect(result.current.current?.name).toBe('SYSTEM_RECOVERED')
    rerender({ input: { ...base, matchMode: 'live', connection: 'LIVE' } })
    expect(result.current.events.filter((event) => event.name === 'SYSTEM_RECOVERED')).toHaveLength(1)
  })

  it('ignores the initial snapshot and emits only when observed state changes', () => {
    const { result, rerender } = renderHook(({ input }) => useVisualMotion(input), { initialProps: { input: { ...base, matchMode: 'live', healthStatus: 'degraded' } } })
    expect(result.current.events).toEqual([])
    rerender({ input: { ...base, matchMode: 'live', healthStatus: 'healthy' } })
    expect(result.current.current?.name).toBe('SYSTEM_RECOVERED')
  })

  it('coalesces one recovery reported by both the realtime link and system health', () => {
    const initial: Parameters<typeof useVisualMotion>[0] = { ...base, connection: 'DEGRADED', healthStatus: 'degraded' }
    const { result, rerender } = renderHook(({ input }) => useVisualMotion(input), { initialProps: { input: initial } })
    rerender({ input: { ...base, connection: 'LIVE', healthStatus: 'healthy' } })
    expect(result.current.events.filter((event) => event.name === 'SYSTEM_RECOVERED')).toHaveLength(1)
  })

  it('does not revive an older cinematic event after a newer event expires', () => {
    vi.useFakeTimers()
    const { result, rerender, unmount } = renderHook(({ input }) => useVisualMotion(input), { initialProps: { input: base } })
    const goal = { event_id: 'goal-long', event_type: 'football.match.goal', subject_id: 'match-1', timestamp: '2026-09-14T12:00:00Z' }
    const card = { event_id: 'card-short', event_type: 'football.match.yellow_card', subject_id: 'match-1', timestamp: '2026-09-14T12:00:01Z' }
    act(() => rerender({ input: { ...base, eventArrival: goal } }))
    act(() => vi.advanceTimersByTime(100))
    act(() => rerender({ input: { ...base, eventArrival: card } }))
    expect(result.current.current?.id).toBe('card-short')
    act(() => vi.advanceTimersByTime(1050))
    expect(result.current.events.map((event) => event.id)).toContain('goal-long')
    expect(result.current.current).toBeNull()
    unmount()
    vi.useRealTimers()
  })
})
