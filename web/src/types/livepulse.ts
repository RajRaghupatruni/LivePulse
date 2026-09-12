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

export type LiveState = { match: Match | null; attention: number; updated_at: string | null }

export type TimelineItem = {
  cursor: number
  event_id: string
  event_type: string
  subject_id: string
  timestamp: string
  payload: Record<string, unknown>
}

export type TimelineResponse = { items: TimelineItem[]; latest_cursor: number }

export type RealtimeMessage = {
  type: string
  cursor?: number
  event_id?: string
  event_type?: string
  timestamp?: string
  payload?: Record<string, unknown>
  state?: Match
  latest_cursor?: number
  reason?: string
  attention?: number
}
