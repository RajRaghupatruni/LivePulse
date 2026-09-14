import { describe, expect, it } from 'vitest'
import { eventLifetimeMs, visualEventFromTimeline } from './visualMotion'

const item = (event_type: string) => ({ event_id: `event:${event_type}`, event_type, source: event_type.split('.')[0], subject_id: 'subject-1', timestamp: '2026-09-14T12:00:00Z' })

describe('semantic visual events', () => {
  it('maps meaningful domain events without inventing events from unknown data', () => {
    expect(visualEventFromTimeline(item('football.match.goal'))).toMatchObject({ name: 'FOOTBALL_GOAL', intensity: 'strong' })
    expect(visualEventFromTimeline(item('mail.message.received'))).toMatchObject({ name: 'GMAIL_MESSAGE_RECEIVED' })
    expect(visualEventFromTimeline(item('developer.workflow.failed'))).toMatchObject({ name: 'GITHUB_WORKFLOW_FAILED' })
    expect(visualEventFromTimeline(item('spotify.track.changed'))).toMatchObject({ name: 'SPOTIFY_TRACK_CHANGED' })
    expect(visualEventFromTimeline(item('unmapped.provider.noise'))).toBeNull()
  })

  it('gives important match events bounded, severity-aware lifetimes', () => {
    const goal = visualEventFromTimeline(item('football.match.goal'))!
    const card = visualEventFromTimeline(item('football.match.red_card'))!
    const kickoff = visualEventFromTimeline(item('football.match.kickoff'))!
    expect(eventLifetimeMs(goal)).toBeGreaterThan(eventLifetimeMs(card))
    expect(eventLifetimeMs(goal)).toBeLessThanOrEqual(1500)
    expect(eventLifetimeMs(kickoff)).toBeLessThan(eventLifetimeMs(goal))
  })
})
