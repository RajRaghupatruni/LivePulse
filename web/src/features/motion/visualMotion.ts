import type { TimelineItem } from '../../types/livepulse'

export type VisualEventName =
  | 'FOOTBALL_KICKOFF'
  | 'FOOTBALL_GOAL'
  | 'FOOTBALL_CARD'
  | 'FOOTBALL_HALFTIME'
  | 'FOOTBALL_FULLTIME'
  | 'GMAIL_MESSAGE_RECEIVED'
  | 'GITHUB_ACTIVITY'
  | 'GITHUB_WORKFLOW_STARTED'
  | 'GITHUB_WORKFLOW_COMPLETED'
  | 'GITHUB_WORKFLOW_FAILED'
  | 'GITHUB_DEPLOYMENT_FAILED'
  | 'SPOTIFY_TRACK_CHANGED'
  | 'SPOTIFY_PLAYBACK_STARTED'
  | 'SPOTIFY_PLAYBACK_PAUSED'
  | 'WEATHER_CHANGED'
  | 'FOCUS_CHANGED'
  | 'MATCH_MODE_ENTER'
  | 'MATCH_MODE_EXIT'
  | 'SYSTEM_RECONNECTING'
  | 'SYSTEM_RESYNCING'
  | 'SYSTEM_DEGRADED'
  | 'SYSTEM_RECOVERED'

export type VisualEvent = {
  id: string
  name: VisualEventName
  source: string
  subjectId: string | null
  occurredAt: string
  intensity: 'subtle' | 'moderate' | 'strong'
}

const timelineEvents: Record<string, Pick<VisualEvent, 'name' | 'intensity'>> = {
  'football.match.kickoff': { name: 'FOOTBALL_KICKOFF', intensity: 'moderate' },
  'football.match.goal': { name: 'FOOTBALL_GOAL', intensity: 'strong' },
  'football.match.yellow_card': { name: 'FOOTBALL_CARD', intensity: 'moderate' },
  'football.match.red_card': { name: 'FOOTBALL_CARD', intensity: 'strong' },
  'football.match.halftime': { name: 'FOOTBALL_HALFTIME', intensity: 'subtle' },
  'football.match.fulltime': { name: 'FOOTBALL_FULLTIME', intensity: 'moderate' },
  'mail.message.received': { name: 'GMAIL_MESSAGE_RECEIVED', intensity: 'subtle' },
  'mail.thread.updated': { name: 'GMAIL_MESSAGE_RECEIVED', intensity: 'subtle' },
  'developer.workflow.started': { name: 'GITHUB_WORKFLOW_STARTED', intensity: 'subtle' },
  'developer.workflow.completed': { name: 'GITHUB_WORKFLOW_COMPLETED', intensity: 'subtle' },
  'developer.workflow.failed': { name: 'GITHUB_WORKFLOW_FAILED', intensity: 'moderate' },
  'developer.pull_request.opened': { name: 'GITHUB_ACTIVITY', intensity: 'subtle' },
  'developer.pull_request.merged': { name: 'GITHUB_ACTIVITY', intensity: 'subtle' },
  'developer.push.received': { name: 'GITHUB_ACTIVITY', intensity: 'subtle' },
  'developer.deployment.completed': { name: 'GITHUB_ACTIVITY', intensity: 'subtle' },
  'developer.deployment.failed': { name: 'GITHUB_DEPLOYMENT_FAILED', intensity: 'moderate' },
  'spotify.track.changed': { name: 'SPOTIFY_TRACK_CHANGED', intensity: 'subtle' },
  'spotify.playback.started': { name: 'SPOTIFY_PLAYBACK_STARTED', intensity: 'subtle' },
  'spotify.playback.paused': { name: 'SPOTIFY_PLAYBACK_PAUSED', intensity: 'subtle' },
  'spotify.playback.resumed': { name: 'SPOTIFY_PLAYBACK_STARTED', intensity: 'subtle' },
  'weather.conditions.updated': { name: 'WEATHER_CHANGED', intensity: 'subtle' },
}

export function visualEventFromTimeline(item: Pick<TimelineItem, 'event_id' | 'event_type' | 'source' | 'subject_id' | 'timestamp'>): VisualEvent | null {
  const mapping = timelineEvents[item.event_type]
  if (!mapping) return null
  return {
    id: item.event_id,
    ...mapping,
    source: item.source,
    subjectId: item.subject_id || null,
    occurredAt: item.timestamp,
  }
}

export function visualEventFromTransition(
  name: VisualEventName,
  id: string,
  source: string,
  subjectId: string | null = null,
  intensity: VisualEvent['intensity'] = 'subtle',
  occurredAt = new Date().toISOString(),
): VisualEvent {
  return { id, name, source, subjectId, intensity, occurredAt }
}

export function eventLifetimeMs(event: VisualEvent): number {
  if (event.name === 'FOOTBALL_GOAL') return 1450
  if (event.name === 'FOOTBALL_CARD' || event.name === 'SYSTEM_DEGRADED' || event.name === 'GITHUB_WORKFLOW_FAILED' || event.name === 'GITHUB_DEPLOYMENT_FAILED') return 1050
  if (event.name === 'SYSTEM_RECOVERED' || event.name === 'FOOTBALL_FULLTIME') return 900
  return 700
}
