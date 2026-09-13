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
  updated_at: string | null
}

export type TimelineItem = {
  cursor: number
  event_id: string
  event_type: string
  source: string
  subject_id: string
  timestamp: string
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
}

export type SystemHealth = {
  status: HealthStatus
  checked_at: string
  components: Record<string, HealthComponent>
  providers?: Record<string, ProviderHealth>
}

export type RealtimeMessage = {
  type: string
  cursor?: number
  event_id?: string
  event_type?: string
  source?: string
  timestamp?: string
  payload?: Record<string, unknown>
  state?: Match
  latest_cursor?: number
  reason?: string
  attention?: number
  focus?: FocusState
}
