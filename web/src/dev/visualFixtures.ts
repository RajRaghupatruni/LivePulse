import type { ConnectionState } from '../hooks/useLivePulse'
import type { SurfaceSnapshot } from '../hooks/useProviderSurfaces'
import type { FocusTimerSnapshot } from '../features/focus/focusTimerStore'
import type { FootballFixtures, LiveState, ProviderHealth, SpotifyPlaybackView, SystemHealth, TimelineItem, WeatherSnapshot } from '../types/livepulse'
import type { GmailInbox } from '../lib/api'

export type VisualFixtureName = 'idle' | 'spotify-playing' | 'upcoming' | 'live' | 'goal' | 'degraded' | 'focus'
export type VisualFixture = {
  live: LiveState
  timeline: TimelineItem[]
  connection: ConnectionState
  eventArrival: Pick<TimelineItem, 'event_id' | 'event_type' | 'subject_id' | 'timestamp' | 'payload'> | null
  health: SystemHealth
  football: SurfaceSnapshot<FootballFixtures>
  spotify: SurfaceSnapshot<SpotifyPlaybackView>
  weather: SurfaceSnapshot<WeatherSnapshot>
  gmail: SurfaceSnapshot<GmailInbox>
  focusTimer?: FocusTimerSnapshot
}

const now = () => new Date().toISOString()
const provider = (key: string, status: ProviderHealth['status'] = 'healthy', configured = true): ProviderHealth => ({
  provider: key, status, configured, checked_at: now(), last_success_at: now(), last_failure_at: null,
  last_observation_at: now(), consecutive_failures: status === 'healthy' ? 0 : 1, rate_limited_until: null,
  detail_code: status === 'healthy' ? 'observation_received' : 'provider_stale', connected: configured,
})
const health = (degraded = false): SystemHealth => ({
  status: degraded ? 'degraded' : 'healthy', checked_at: now(), runtime_mode: 'PERSONAL_LOCAL', components: {},
  providers: {
    football: provider('football'), spotify: provider('spotify'), github: provider('github'),
    gmail: provider('gmail', degraded ? 'stale' : 'healthy'), weather: provider('weather'),
  },
})
const emptyLive: LiveState = {
  match: null, attention: 12,
  focus: { score: 12, severity: 'low', reason: 'no_active_match', transient: false, expires_at: null, source: 'system', subject_id: null, match_mode: 'idle' },
  dominant_focus: null, updated_at: now(),
}
const baseFixture = {
  fixture_id: 1001, subject_id: 'fixture-1001', competition: 'Premier League', home_team: 'Manchester City', away_team: 'Arsenal',
  kickoff_at: new Date(Date.now() + 42 * 60_000).toISOString(), status: 'Not Started', state: 'scheduled' as const, phase: 'pre_match' as const, minute: 0, home_score: null, away_score: null,
}
const liveMatch: LiveState['match'] = {
  match_id: 'fixture-1001', home_team: 'Manchester City', away_team: 'Arsenal', competition: 'Premier League', home_score: 2, away_score: 1,
  status: 'live', minute: 67, phase: 'second_half', version: 6, last_event_id: 'fixture-goal-2', last_event_type: 'football.match.goal', updated_at: now(),
}
const liveState: LiveState = {
  ...emptyLive, match: liveMatch, attention: 70,
  focus: { score: 70, severity: 'high', reason: 'live_match', transient: false, expires_at: null, source: 'football', subject_id: 'fixture-1001', match_mode: 'live' },
}
const football = (status: 'healthy' | 'degraded', kind: 'empty' | 'upcoming' | 'live' = 'empty'): FootballFixtures => ({
  provider_status: status, observed_at: now(),
  today: kind === 'live' ? [baseFixture] : [], upcoming: kind === 'upcoming' ? [baseFixture] : [],
  live: kind === 'live' ? [{ ...baseFixture, status: 'Second Half', state: 'live', phase: 'second_half', minute: 67, home_score: 2, away_score: 1 }] : [],
})
const spotifyIdle: SpotifyPlaybackView = { provider: 'spotify', playback: null, observed_at: now(), freshness_seconds: 3 }
const spotifyPlaying: SpotifyPlaybackView = {
  provider: 'spotify', observed_at: now(), freshness_seconds: 3,
  playback: {
    is_playing: true, item_type: 'track', item_id: 'track-ambient-01', item_uri: null, item_name: 'No Ordinary Love',
    artists: ['Sade'], album_name: 'Love Deluxe', show_name: null, artwork_url: null, progress_ms: 93_000, duration_ms: 420_000,
    device_id: 'studio', device_name: 'Studio speakers', device_type: 'Speaker', volume_percent: 30, shuffle: false, repeat: 'off', context_uri: null, context_type: null, timestamp_ms: Date.now(),
  },
}
const timelineItem = (eventId: string, type: string, source: string, title: string, summary: string, payload: Record<string, unknown> = {}): TimelineItem => ({
  cursor: 1, event_id: eventId, event_type: type, source, subject_id: 'fixture-1001', timestamp: now(), observed_at: now(), payload: { title, summary, ...payload },
})
const mail: GmailInbox = { status: 'ready', configured: true, messages: [
  { message_id: 'mail-1', thread_id: 'thread-1', sender: 'Alex Morgan', subject: 'Matchday access confirmed', received_at: now(), snippet: 'Your access details are ready. The final pass will be sent before kickoff.', is_unread: true, is_important: true },
  { message_id: 'mail-2', thread_id: 'thread-2', sender: 'GitHub', subject: 'LivePulse build is green', received_at: now(), snippet: 'All checks passed for the latest workflow run.', is_unread: true, is_important: false },
  { message_id: 'mail-3', thread_id: 'thread-3', sender: 'Jordan Lee', subject: 'Re: Operations review', received_at: now(), snippet: 'I have added the updated runbook and the notes from this morning.', is_unread: false, is_important: false },
  { message_id: 'mail-4', thread_id: 'thread-4', sender: 'GitHub', subject: 'Weekly security digest', received_at: now(), snippet: 'Your repositories have no new security advisories.', is_unread: false, is_important: false },
] }

const fixtureWeatherLocation = {
  id: 'visual-new-york',
  display_name: 'New York, New York, United States',
  city: 'New York',
  region: 'New York',
  country: 'United States',
  latitude: 40.7128,
  longitude: -74.006,
  timezone: 'America/New_York',
  selected_at: null,
  last_used_at: null,
}

export function createVisualFixture(name: VisualFixtureName): VisualFixture {
  const base: VisualFixture = {
    live: emptyLive, timeline: [], connection: 'LIVE', eventArrival: null, health: health(),
    football: { value: football('healthy'), loading: false, available: true },
    spotify: { value: spotifyIdle, loading: false, available: true },
    weather: { value: { location: fixtureWeatherLocation, recent_locations: [fixtureWeatherLocation], current: { observed_at: now(), local_time: now(), timezone: 'America/New_York', temperature_f: 64, apparent_temperature_f: 64, weather_code: 2, category: 'clear', description: 'Partly cloudy', precipitation_in: 0, wind_speed_mph: 5, high_f: 69, low_f: 54, precipitation_probability_max_pct: 8 }, fetched_at: now(), health: provider('weather') }, loading: false, available: true },
    gmail: { value: mail, loading: false, available: true },
  }
  if (name === 'spotify-playing') base.spotify = { value: spotifyPlaying, loading: false, available: true }
  if (name === 'upcoming') base.football = { value: football('healthy', 'upcoming'), loading: false, available: true }
  if (name === 'live' || name === 'goal' || name === 'focus') {
    base.live = liveState
    base.football = { value: football('healthy', 'live'), loading: false, available: true }
    base.timeline = [timelineItem('fixture-kickoff', 'football.match.kickoff', 'football', 'Kick-off', 'Match has started'), timelineItem('fixture-build', 'football.match.possession', 'football', 'Pressure building', 'Manchester City are holding the attacking phase')]
  }
  if (name === 'goal') {
    const arrival = timelineItem('fixture-goal-arrival', 'football.match.goal', 'football', 'Goal', 'Erling Haaland · Manchester City', { player: 'Erling Haaland', side: 'home' })
    base.timeline = [arrival, ...base.timeline]
    base.eventArrival = { event_id: arrival.event_id, event_type: arrival.event_type, subject_id: arrival.subject_id, timestamp: arrival.timestamp, payload: arrival.payload }
    base.live = { ...liveState, match: liveMatch ? { ...liveMatch, home_score: 3, minute: 68, updated_at: now(), last_event_id: arrival.event_id } : null }
    base.football = { value: { ...football('healthy', 'live'), live: [{ ...baseFixture, status: '2H', minute: 68, home_score: 3, away_score: 1 }] }, loading: false, available: true }
  }
  if (name === 'degraded') {
    base.connection = 'DEGRADED'
    base.health = health(true)
    base.football = { value: football('degraded'), loading: false, available: true }
  }
  if (name === 'focus') base.focusTimer = { status: 'running', durationMinutes: 25, deadline: Date.now() + 22 * 60_000, remainingMs: null }
  return base
}
