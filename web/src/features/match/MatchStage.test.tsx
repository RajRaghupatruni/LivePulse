import { fireEvent, render, screen, within } from '@testing-library/react'
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

  it('does not present provider failures or rate limits as an empty schedule', () => {
    const { rerender } = render(<MatchStage live={liveState} fixtures={emptyFixtures('provider_failure')} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('Football provider unavailable')).toBeInTheDocument()
    expect(screen.queryByText('No match in the current window')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View provider status' })).toBeInTheDocument()

    rerender(<MatchStage live={liveState} fixtures={emptyFixtures('rate_limited')} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('Football data temporarily paused')).toBeInTheDocument()
    expect(screen.queryByText('No match in the current window')).not.toBeInTheDocument()
  })

  it('treats a failed fixture request as unavailable even when it has an older healthy snapshot', () => {
    render(<MatchStage live={liveState} fixtures={emptyFixtures('healthy')} fixtureLoading={false} fixtureAvailable={false} />)
    expect(screen.getByText('Football provider unavailable')).toBeInTheDocument()
    expect(screen.queryByText('No match in the current window')).not.toBeInTheDocument()
  })

  it('keeps the last known match visible while showing provider failure status', () => {
    const fixtures: FootballFixtures = {
      provider_status: 'provider_failure', observed_at: '2026-09-13T01:00:00Z', today: [], live: [],
      upcoming: [{ fixture_id: 1, subject_id: 'match-1', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2030-09-13T20:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: null, away_score: null }],
    }
    render(<MatchStage live={liveState} fixtures={fixtures} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByRole('status')).toHaveTextContent('SOURCE UNAVAILABLE')
    expect(screen.getByText('Northstar FC')).toBeInTheDocument()
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
      upcoming: [{ fixture_id: 1, subject_id: 'match-1', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2030-09-13T20:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: null, away_score: null }],
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
        { fixture_id: 1, subject_id: 'match-1', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2030-09-13T20:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: null, away_score: null },
        { fixture_id: 2, subject_id: 'match-2', competition: 'Premier League', home_team: 'Lakeside AFC', away_team: 'Portside City', kickoff_at: '2030-09-13T21:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: null, away_score: null },
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
      today: [{ fixture_id: 3, subject_id: 'match-3', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2026-09-13T20:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: null, away_score: null }],
      upcoming: [],
      live: [{ fixture_id: 3, subject_id: 'match-3', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2026-09-13T20:00:00Z', status: 'Second Half', state: 'live', phase: 'second_half', minute: 67, home_score: 2, away_score: 1 }],
    }
    render(<MatchStage live={liveState} fixtures={fixtures} fixtureLoading={false} fixtureAvailable />)

    expect(screen.getByRole('region', { name: /LIVE · 67′ · SECOND HALF: Northstar FC versus Harbor United/ })).toBeInTheDocument()
    expect(screen.getByLabelText('2 to 1')).toBeInTheDocument()
  })

  it('uses provider match state through kickoff, halftime, and fulltime without a reload', () => {
    window.localStorage.setItem('livepulse.selected-match.v1', 'fixture-1490480')
    const kickoffDue: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-14T01:40:00Z', today: [], live: [],
      upcoming: [{ fixture_id: 1490480, subject_id: 'fixture-1490480', competition: 'MLS', home_team: 'San Diego', away_team: 'Philadelphia Union', kickoff_at: new Date(Date.now() - 20_000).toISOString(), status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: 0, away_score: 0 }],
    }
    const { rerender } = render(<MatchStage live={liveState} fixtures={kickoffDue} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByRole('region', { name: /UPCOMING: San Diego versus Philadelphia Union/ })).toBeInTheDocument()
    expect(screen.getByText('KICKOFF DUE · AWAITING PROVIDER')).toBeInTheDocument()

    const liveFixture: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-14T01:42:00Z', today: [], upcoming: [],
      live: [{ fixture_id: 1490480, subject_id: 'fixture-1490480', competition: 'MLS', home_team: 'San Diego', away_team: 'Philadelphia Union', kickoff_at: '2026-09-14T01:00:00Z', status: 'First Half', state: 'live', phase: 'first_half', minute: 42, home_score: 0, away_score: 0 }],
    }
    rerender(<MatchStage live={liveState} fixtures={liveFixture} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByRole('region', { name: /LIVE · 42′ · FIRST HALF: San Diego versus Philadelphia Union/ })).toBeInTheDocument()
    expect(screen.getByText('LIVE', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.getByLabelText('0 to 0')).toBeInTheDocument()
    expect(screen.queryByText('UNTIL KICKOFF')).not.toBeInTheDocument()
    expect(screen.queryByText(/AWAITING PROVIDER/)).not.toBeInTheDocument()

    const halftime: FootballFixtures = { ...liveFixture, live: [{ ...liveFixture.live[0], status: 'Halftime', state: 'halftime', phase: 'halftime', minute: 45 }] }
    rerender(<MatchStage live={liveState} fixtures={halftime} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('HT', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.getByText('HALF TIME')).toBeInTheDocument()

    const fulltime: FootballFixtures = { ...liveFixture, live: [], today: [{ ...liveFixture.live[0], status: 'Match Finished', state: 'fulltime', phase: 'fulltime', minute: 90, home_score: 2, away_score: 1 }] }
    rerender(<MatchStage live={liveState} fixtures={fulltime} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('FINAL', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.getByLabelText('2 to 1')).toBeInTheDocument()
    expect(screen.queryByText('UNTIL KICKOFF')).not.toBeInTheDocument()
  })

  it('does not let a stale pre-match snapshot overwrite a newer live projection', () => {
    window.localStorage.setItem('livepulse.selected-match.v1', 'fixture-1490480')
    const staleSnapshot: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-14T01:45:00Z', today: [], live: [],
      upcoming: [{ fixture_id: 1490480, subject_id: 'fixture-1490480', competition: 'MLS', home_team: 'San Diego', away_team: 'Philadelphia Union', kickoff_at: '2026-09-14T01:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: 0, away_score: 0 }],
    }
    const projectedLive: LiveState = {
      ...liveState,
      match: { ...liveState.match!, match_id: 'fixture-1490480', home_team: 'San Diego', away_team: 'Philadelphia Union', competition: 'MLS', status: 'live', minute: 42, phase: 'first_half', version: 3, updated_at: '2026-09-14T01:42:01Z' },
    }
    render(<MatchStage live={projectedLive} fixtures={staleSnapshot} fixtureLoading={false} fixtureAvailable />)

    expect(screen.getByText('LIVE', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.getByText('LIVE · 42′ · FIRST HALF')).toBeInTheDocument()
    expect(screen.queryByText('KICKOFF DUE · AWAITING PROVIDER')).not.toBeInTheDocument()
  })

  it('shows delayed, postponed, and cancelled provider states without clock-inferred kickoff', () => {
    const makeFixtures = (status: string, state: 'delayed' | 'postponed' | 'cancelled', phase: 'delayed' | 'postponed' | 'cancelled'): FootballFixtures => ({
      provider_status: 'healthy', observed_at: '2026-09-14T01:45:00Z', upcoming: [], live: [],
      today: [{ fixture_id: 44, subject_id: 'match-44', competition: 'MLS', home_team: 'San Diego', away_team: 'Philadelphia Union', kickoff_at: new Date(Date.now() - 20_000).toISOString(), status, state, phase, minute: 0, home_score: null, away_score: null }],
    })
    const { rerender } = render(<MatchStage live={liveState} fixtures={makeFixtures('Time To Be Defined', 'delayed', 'delayed')} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('TIME TBD', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.queryByText('UNTIL KICKOFF')).not.toBeInTheDocument()

    rerender(<MatchStage live={liveState} fixtures={makeFixtures('Postponed', 'postponed', 'postponed')} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('POSTPONED', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.queryByText('UNTIL KICKOFF')).not.toBeInTheDocument()

    rerender(<MatchStage live={liveState} fixtures={makeFixtures('Cancelled', 'cancelled', 'cancelled')} fixtureLoading={false} fixtureAvailable />)
    expect(screen.getByText('CANCELLED', { selector: '.match-phase-label' })).toBeInTheDocument()
    expect(screen.queryByText('UNTIL KICKOFF')).not.toBeInTheDocument()
  })

  it('keeps match awareness, observation metadata, and View Match in the hero footer', () => {
    const fixture: FootballFixtures = {
      provider_status: 'healthy', observed_at: '2026-09-13T01:00:00Z', today: [], live: [],
      upcoming: [{ fixture_id: 1, subject_id: 'match-1', competition: 'Premier League', home_team: 'Northstar FC', away_team: 'Harbor United', kickoff_at: '2030-09-13T20:00:00Z', status: 'Not Started', state: 'scheduled', phase: 'pre_match', minute: 0, home_score: null, away_score: null }],
    }
    render(<MatchStage live={liveState} fixtures={fixture} fixtureLoading={false} fixtureAvailable />)

    const hero = screen.getByRole('region', { name: /Northstar FC versus Harbor United/ })
    expect(within(hero).getByText('MATCH AWARENESS')).toBeVisible()
    expect(within(hero).getByText(/^Observed /)).toBeVisible()
    expect(within(hero).getByRole('button', { name: 'View match details' })).toBeVisible()
  })
})
