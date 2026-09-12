import { describe, expect, it } from 'vitest'
import { mergeLiveState } from './useLivePulse'
import type { LiveState } from '../types/livepulse'

const state = (version: number, matchId = 'demo-1'): LiveState => ({
  attention: 70,
  updated_at: `2026-09-12T20:00:${String(version).padStart(2, '0')}Z`,
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
    updated_at: `2026-09-12T20:00:${String(version).padStart(2, '0')}Z`,
  },
})

describe('authoritative live-state merge', () => {
  it('does not let an older snapshot overwrite a newer projection for the same match', () => {
    const current = state(4)
    expect(mergeLiveState(current, state(3))).toBe(current)
  })

  it('accepts a new active match even when its per-match version restarts', () => {
    expect(mergeLiveState(state(4), state(1, 'demo-2')).match?.match_id).toBe('demo-2')
  })
})
