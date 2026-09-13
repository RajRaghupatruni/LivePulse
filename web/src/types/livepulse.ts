export type Match = {
  match_id: string
  home_team: string
  away_team: string
  competition: string
  home_score: number
  away_score: number
  status: string
  minute: number
  phase: string
  version: number
  last_event_id: string | null
  last_event_type: string | null
  updated_at: string
}

export type FocusState = {
  score: number
  severity: 'low' | 'normal' | 'high' | 'critical'
  reason: string
  transient: boolean
  expires_at: string | null
  source: string
  subject_id: string | null
  match_mode: 'idle' | 'scheduled' | 'live' | 'halftime' | 'highlight' | 'fulltime'
}

export type LiveState = {
  match: Match | null
  attention: number
  focus: FocusState
  dominant_focus?: DominantFocus | null
  updated_at: string | null
}

export type DominantFocus = {
  priority: number
  domain: 'football' | 'gmail' | 'github' | 'system'
  reason: string
  subject_id: string | null
  event_id: string | null
  transient: boolean
  created_at: string
  observed_at: string
  expires_at: string | null
}

export type TimelineItem = {
  cursor: number
  event_id: string
  event_type: string
  source: string
  subject_id: string
  timestamp: string
  observed_at?: string
  payload: Record<string, unknown>
}

export type TimelineResponse = { items: TimelineItem[]; latest_cursor: number }

export type HealthStatus =
  | 'healthy'
  | 'degraded'
  | 'unavailable'
  | 'unknown'
  | 'disconnected'
  | 'connecting'
  | 'stale'
  | 'resyncing'
  | 'rate_limited'
  | 'auth_failure'
  | 'provider_failure'

export type HealthComponent = {
  name: string
  status: HealthStatus
  detail: string
  checked_at: string | null
  last_success_at: string | null
  metrics?: Record<string, number | string | null>
}

export type ProviderHealth = {
  provider: string
  status: HealthStatus
  configured: boolean
  checked_at: string | null
  last_success_at: string | null
  last_failure_at: string | null
  last_observation_at: string | null
  consecutive_failures: number
  rate_limited_until: string | null
  detail_code: string
  connected?: boolean
  freshness?: string
  cadence?: Record<string, unknown> | null
  quota?: Record<string, unknown> | null
  webhook?: Record<string, unknown>
  reconciliation?: Record<string, unknown>
}

export type SystemHealth = {
  status: HealthStatus
  checked_at: string
  runtime_mode?: 'PERSONAL_LOCAL' | 'PUBLIC_DEMO'
  components: Record<string, HealthComponent>
  providers?: Record<string, ProviderHealth>
}

export type FootballFixture = {
  fixture_id: number
  subject_id: string
  competition: string
  home_team: string
  away_team: string
  kickoff_at: string
  status: string
  minute: number
  home_score: number | null
  away_score: number | null
}

export type FootballFixtures = {
  provider_status: string
  observed_at: string | null
  today: FootballFixture[]
  upcoming: FootballFixture[]
  live: FootballFixture[]
}

export type SpotifyPlaybackSnapshot = {
  is_playing: boolean
  item_type: string | null
  item_id: string | null
  item_uri: string | null
  item_name: string | null
  artists: string[]
  album_name: string | null
  show_name: string | null
  artwork_url: string | null
  progress_ms: number | null
  duration_ms: number | null
  device_id: string | null
  device_name: string | null
  device_type: string | null
  volume_percent: number | null
  shuffle: boolean | null
  repeat: string | null
  context_uri: string | null
  context_type: string | null
  timestamp_ms: number | null
}

export type SpotifyPlaybackView = {
  provider: 'spotify'
  playback: SpotifyPlaybackSnapshot | null
  observed_at: string | null
  freshness_seconds: number | null
}

export type SpotifyDevice = {
  id: string | null
  name: string
  type: string
  is_active: boolean
  is_restricted: boolean
  volume_percent: number | null
  supports_volume: boolean
}

export type SpotifyCommandResult = {
  success: boolean
  provider: string
  error_code: string | null
  message: string
  resulting_state_hint?: { subject_id: string | null; state: string | null; observed_at: string | null } | null
}

export type WeatherSnapshot = {
  location: WeatherLocation | null
  recent_locations: WeatherLocation[]
  current: {
    observed_at: string
    local_time: string
    timezone: string
    temperature_f: number
    apparent_temperature_f: number
    weather_code: number
    category: string
    description: string
    precipitation_in: number
    wind_speed_mph: number
    high_f: number
    low_f: number
    precipitation_probability_max_pct: number | null
  } | null
  fetched_at: string | null
  health: ProviderHealth
}

export type WeatherLocation = {
  id: string
  display_name: string
  city: string
  region: string | null
  country: string
  latitude: number
  longitude: number
  timezone: string
  selected_at: string | null
  last_used_at: string | null
}

export type WeatherLocationState = {
  selected: WeatherLocation | null
  recent: WeatherLocation[]
}

export type RealtimeMessage = {
  type: string
  cursor?: number
  event_id?: string
  event_type?: string
  source?: string
  subject_id?: string
  timestamp?: string
  observed_at?: string
  payload?: Record<string, unknown>
  state?: Match
  latest_cursor?: number
  reason?: string
  attention?: number
  focus?: FocusState
}
