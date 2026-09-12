import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MatchSurface } from './MatchSurface'

const match = {
  match_id: 'demo-1', home_team: 'Northstar FC', away_team: 'Harbor United', competition: 'Premier League',
  home_score: 2, away_score: 1, status: 'fulltime', minute: 90, phase: 'fulltime', version: 10,
  last_event_id: 'event-10', last_event_type: 'football.match.fulltime', updated_at: '2026-09-12T20:00:00Z',
}
const focus = {
  score: 30, severity: 'low' as const, reason: 'fulltime', transient: false, expires_at: null,
  source: 'football', subject_id: 'demo-1', match_mode: 'fulltime' as const,
}

describe('MatchSurface', () => {
  it('renders authoritative score and match state', () => {
    render(<MatchSurface match={match} focus={focus} />)
    expect(screen.getByText('Northstar FC')).toBeInTheDocument()
    expect(screen.getByText('Harbor United')).toBeInTheDocument()
    expect(screen.getByLabelText('2')).toBeInTheDocument()
    expect(screen.getByLabelText('1')).toBeInTheDocument()
    expect(screen.getAllByText('FULL TIME').length).toBeGreaterThan(0)
  })

  it('shows the empty match shell before the first projection', () => {
    render(<MatchSurface match={null} focus={{ ...focus, match_mode: 'idle' }} />)
    expect(screen.getByText('A clear field of view.')).toBeInTheDocument()
  })

  it('reflects normalized Match Mode during a transient highlight', () => {
    render(<MatchSurface match={{ ...match, status: 'live' }} focus={{ ...focus, score: 100, severity: 'critical', reason: 'goal', transient: true, match_mode: 'highlight' }} />)
    expect(screen.getByText('MOMENT IN FOCUS')).toBeInTheDocument()
    expect(screen.getByText('FOCUS ENGINE · GOAL')).toBeInTheDocument()
  })
})
