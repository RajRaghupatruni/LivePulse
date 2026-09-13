import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getLiveState, getTimeline } from '../lib/api'
import { mergeLiveState, mergeRealtimeState, useLivePulse } from './useLivePulse'
import type { LiveState } from '../types/livepulse'

vi.mock('../lib/api', () => ({
  getLiveState: vi.fn(),
  getTimeline: vi.fn(),
  resetDemo: vi.fn(),
  startDemo: vi.fn(),
}))

class FakeWebSocket {
  static OPEN = 1
  static instance: FakeWebSocket
  readonly url: string
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instance = this
  }

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.(new Event('open'))
  }

  send(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent)
  }

  close() {
    this.readyState = 3
  }
}

const state = (version: number, matchId = 'demo-1', updatedAt = `2026-09-12T20:00:${String(version).padStart(2, '0')}Z`): LiveState => ({
  attention: 70,
  focus: {
    score: 70,
    severity: 'high',
    reason: 'live_match',
    transient: false,
    expires_at: null,
    source: 'football',
    subject_id: matchId,
    match_mode: 'live',
  },
  updated_at: updatedAt,
  match: {
    match_id: matchId,
    home_team: 'Northstar FC',
    away_team: 'Harbor United',
    competition: 'Premier League',
    home_score: version,
    away_score: 0,
    status: 'live',
    minute: version,
    phase: 'first_half',
    version,
    last_event_id: `event-${version}`,
    last_event_type: 'football.match.goal',
    updated_at: updatedAt,
  },
})

describe('authoritative live-state merge', () => {
  it('does not let an older snapshot overwrite a newer projection for the same match', () => {
    const current = state(4)
    expect(mergeLiveState(current, state(3))).toBe(current)
  })

  it('accepts a new active match even when its per-match version restarts', () => {
    expect(mergeLiveState(state(4), state(1, 'demo-2', '2026-09-12T20:00:05Z')).match?.match_id).toBe('demo-2')
  })

  it('does not let a WebSocket projection for another match replace active state', () => {
    const current = state(1, 'active-match', '2026-09-12T20:00:05Z')
    const inactiveProjection = state(9, 'inactive-match', '2026-09-12T20:00:10Z')
    expect(mergeRealtimeState(current, inactiveProjection.match!)).toBe(current)
  })

  it('rejects a stale WebSocket state event for the same match', () => {
    const current = state(4)
    expect(mergeRealtimeState(current, state(3).match!, undefined, 100)).toBe(current)
  })
})

describe('inactive-match realtime notifications', () => {
  const originalWebSocket = globalThis.WebSocket

  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket
    vi.mocked(getLiveState).mockResolvedValue(state(1, 'active-match'))
    vi.mocked(getTimeline).mockResolvedValue({ items: [], latest_cursor: 0 })
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
  })

  it('keeps inactive state in history and refreshes the authoritative active match', async () => {
    const { result, unmount } = renderHook(() => useLivePulse())
    await waitFor(() => expect(FakeWebSocket.instance).toBeDefined())
    act(() => FakeWebSocket.instance.open())
    await waitFor(() => expect(getLiveState).toHaveBeenCalledTimes(2))

    const inactive = state(9, 'inactive-match', '2026-09-12T20:00:10Z')
    const notification = {
      type: 'timeline.item',
      cursor: 1,
      event_id: 'inactive-event',
      event_type: 'football.match.goal',
      source: 'demo-football',
      timestamp: inactive.updated_at,
      state: inactive.match,
      focus: inactive.focus,
      payload: {},
    }
    act(() => FakeWebSocket.instance.send(notification))
    await waitFor(() => expect(getLiveState).toHaveBeenCalledTimes(3))

    expect(result.current.live.match?.match_id).toBe('active-match')
    expect(result.current.timeline.map((item) => item.event_id)).toEqual(['inactive-event'])
    act(() => FakeWebSocket.instance.send(notification))
    expect(result.current.timeline).toHaveLength(1)
    unmount()
  })

  it('orders mixed-domain timeline events by occurrence time and cursor', async () => {
    vi.mocked(getTimeline).mockResolvedValue({
      items: [
        {
          cursor: 2,
          event_id: 'newer-weather',
          event_type: 'weather.conditions.updated',
          source: 'weather',
          subject_id: 'configured-location',
          timestamp: '2026-09-12T20:00:02Z',
          payload: {},
        },
        {
          cursor: 1,
          event_id: 'older-football',
          event_type: 'football.match.kickoff',
          source: 'api-football',
          subject_id: 'active-match',
          timestamp: '2026-09-12T20:00:01Z',
          payload: {},
        },
      ],
      latest_cursor: 2,
    })
    const { result, unmount } = renderHook(() => useLivePulse())
    await waitFor(() => expect(result.current.timeline).toHaveLength(2))
    expect(result.current.timeline.map((item) => item.event_id)).toEqual([
      'newer-weather',
      'older-football',
    ])

    act(() =>
      FakeWebSocket.instance.send({
        type: 'timeline.item',
        cursor: 3,
        event_id: 'late-github',
        event_type: 'developer.workflow.failed',
        source: 'github',
        timestamp: '2026-09-12T19:59:59Z',
        payload: {},
      }),
    )
    await waitFor(() => expect(result.current.timeline).toHaveLength(3))
    expect(result.current.timeline.map((item) => item.event_id)).toEqual([
      'newer-weather',
      'older-football',
      'late-github',
    ])
    unmount()
  })
})
