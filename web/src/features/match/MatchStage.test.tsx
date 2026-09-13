import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { MatchStage } from './MatchStage'
import type { FootballFixtures, LiveState } from '../../types/livepulse'

const liveState: LiveState = {
  match: null,
  attention: 10,
  focus: { score: 10, severity: 'low', reason: 'no_active_match', transient: false, expires_at: null, source: 'football', subject_id: null, match_mode: 'idle' },
  updated_at: null,
}

const emptyFixtures = (status: string): FootballFixtures => ({
  provider_status: status,
  observed_at: null,
  today: [],
  upcoming: [],
  live: [],
})

describe('MatchStage', () => {
  beforeEach(() => window.localStorage.clear())

  it('distinguishes an unconfigured football provider from an observed empty schedule', () => {
    const { rerender } = render(<MatchStage live={liveState} fixtures={emptyFixtures('disconnected')} fixtureLoading={false} fixtureAvailable={false} />)
    expect(screen.getByText('Connect a football source')).toBeInTheDocument()
    rerender(<MatchStage live={liveState} fixtures={emptyFixtures('healthy')} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('No match in the current window')).toBeInTheDocument()
  })

  it('shows a schedule-specific empty state when the provider reports no fixtures', () => {
    render(<MatchStage live={liveState} fixtures={emptyFixtures('healthy')} fixtureLoading={false} fixtureAvailable />)
    fireEvent.click(screen.getByRole('button', { name: 'Open match center' }))
    fireEvent.click(screen.getByRole('button', { name: 'Schedule' }))

    expect(screen.getByText('No fixtures reported')).toBeInTheDocument()
    expect(screen.queryByText(/Match statistics are not available/)).not.toBeInTheDocument()
  })

  it('expands the selected match and closes it with Escape', () => {
    const fixture: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-13T01:00:00Z', today: [], live: [],
      upcoming: [{ fixture_id: 1, subject_id: 'match-1', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2030-09-13T20:00:00Z', status: 'scheduled', minute: 0, home_score: null, away_score: null }],
    }
    render(<MatchStage live={liveState} fixtures={fixture} fixtureLoading={false} fixtureAvailable />)
    fireEvent.click(screen.getByRole('button', { name: 'View match details' }))
    const dialog = screen.getByRole('dialog', { name: /Northstar FC/ })
    expect(dialog).toBeInTheDocument()
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('switches fixtures, pins the manual selection, and returns to automatic selection', () => {
    const fixtures: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-13T01:00:00Z', today: [], live: [],
      upcoming: [
        { fixture_id: 1, subject_id: 'match-1', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2030-09-13T20:00:00Z', status: 'scheduled', minute: 0, home_score: null, away_score: null },
        { fixture_id: 2, subject_id: 'match-2', competition: 'Premier League', home_team: 'Lakeside AFC', away_team: 'Portside City', kickoff_at: '2030-09-13T21:00:00Z', status: 'scheduled', minute: 0, home_score: null, away_score: null },
      ],
    }
    render(<MatchStage live={liveState} fixtures={fixtures} fixtureLoading={false} fixtureAvailable />)

    expect(screen.getByText('Northstar FC')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next match' }))
    expect(screen.getByText('Lakeside AFC')).toBeInTheDocument()
    expect(window.localStorage.getItem('livepulse.selected-match.v1')).toBe('match-2')

    fireEvent.click(screen.getByRole('button', { name: 'Pin this match' }))
    expect(screen.getByRole('button', { name: 'Unpin this match' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'AUTO' }))
    expect(screen.getByText('Northstar FC')).toBeInTheDocument()
    expect(window.localStorage.getItem('livepulse.selected-match.v1')).toBeNull()
  })

  it('prefers a live provider observation when the same fixture also appears as scheduled', () => {
    const fixtures: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-13T01:00:00Z',
      today: [{ fixture_id: 3, subject_id: 'match-3', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2026-09-13T20:00:00Z', status: 'NS', minute: 0, home_score: null, away_score: null }],
      upcoming: [],
      live: [{ fixture_id: 3, subject_id: 'match-3', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2026-09-13T20:00:00Z', status: '2H', minute: 67, home_score: 2, away_score: 1 }],
    }
    render(<MatchStage live={liveState} fixtures={fixtures} fixtureLoading={false} fixtureAvailable />)

    expect(screen.getByRole('region', { name: /67′ · SECOND HALF: Northstar FC versus Harbor United/ })).toBeInTheDocument()
    expect(screen.getByLabelText('2 to 1')).toBeInTheDocument()
  })
})
