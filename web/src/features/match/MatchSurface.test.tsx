import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MatchSurface } from './MatchSurface'

const match = {
  match_id: 'demo-1', home_team: 'Northstar FC', away_team: 'Harbor United', competition: 'Premier League',
  home_score: 2, away_score: 1, status: 'fulltime', minute: 90, phase: 'fulltime', version: 10,
  last_event_id: 'event-10', last_event_type: 'football.match.fulltime', updated_at: '2026-09-12T20:00:00Z',
}

describe('MatchSurface', () => {
  it('renders authoritative score and match state', () => {
    render(<MatchSurface match={match} attention={20} />)
    expect(screen.getByText('Northstar FC')).toBeInTheDocument()
    expect(screen.getByText('Harbor United')).toBeInTheDocument()
    expect(screen.getByLabelText('2')).toBeInTheDocument()
    expect(screen.getByLabelText('1')).toBeInTheDocument()
    expect(screen.getAllByText('FULL TIME').length).toBeGreaterThan(0)
  })

  it('shows the empty match shell before the first projection', () => {
    render(<MatchSurface match={null} attention={20} />)
    expect(screen.getByText('Match telemetry will appear here')).toBeInTheDocument()
  })
})
