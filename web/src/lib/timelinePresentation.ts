import type { TimelineItem } from '../types/livepulse'

export type TimelinePresentation = {
  domain: 'football' | 'spotify' | 'github' | 'gmail' | 'weather' | 'system' | 'other'
  title: string
  summary: string
  detail: string | null
  severity: 'normal' | 'warning' | 'critical'
  eventTime: string | null
  safeHref: string | null
}

const text = (value: unknown, fallback = ''): string => typeof value === 'string' ? value.trim() : fallback
const number = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null
const safeLink = (value: unknown, host: string) => {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === host ? url.href : null
  } catch {
    return null
  }
}

function teamForSide(item: TimelineItem) {
  const side = item.payload.side
  return side === 'home' ? text(item.payload.home_team) : side === 'away' ? text(item.payload.away_team) : ''
}

export function presentTimelineItem(item: TimelineItem): TimelinePresentation {
  const payload = item.payload
  const minute = number(payload.minute)
  const eventTime = minute !== null && minute > 0 ? `${minute}′` : null
  const type = item.event_type

  if (type.startsWith('football.match.')) {
    const team = teamForSide(item)
    const player = text(payload.player)
    const labels: Record<string, [string, string, TimelinePresentation['severity']]> = {
      'football.match.scheduled': ['Fixture scheduled', text(payload.competition, 'Football') , 'normal'],
      'football.match.kickoff': ['Kick-off', text(payload.competition, 'Match started'), 'normal'],
      'football.match.goal': ['Goal', [player, team].filter(Boolean).join(' · ') || 'Score updated', 'critical'],
      'football.match.score_corrected': ['Score corrected', text(payload.competition, 'Authoritative score updated'), 'warning'],
      'football.match.yellow_card': ['Yellow card', [player, team].filter(Boolean).join(' · ') || 'Disciplinary event', 'warning'],
      'football.match.red_card': ['Red card', [player, team].filter(Boolean).join(' · ') || 'Disciplinary event', 'critical'],
      'football.match.substitution': ['Substitution', [player, text(payload.substitute), team].filter(Boolean).join(' · ') || 'Squad change', 'normal'],
      'football.match.halftime': ['Half-time', text(payload.competition, 'The first half has ended'), 'normal'],
      'football.match.second_half': ['Second half', text(payload.competition, 'Play has resumed'), 'normal'],
      'football.match.extra_time': ['Extra time', text(payload.competition, 'Extra time has started'), 'normal'],
      'football.match.penalties': ['Penalty shoot-out', text(payload.competition, 'Penalties are underway'), 'normal'],
      'football.match.fulltime': ['Full-time', text(payload.competition, 'Final result confirmed'), 'normal'],
    }
    const [title, summary, severity] = labels[type] ?? ['Football update', text(payload.competition, 'Match activity'), 'normal']
    return { domain: 'football', title, summary, detail: eventTime, severity, eventTime, safeHref: null }
  }

  if (type === 'spotify.track.changed' || type === 'spotify.playback.started' || type === 'spotify.playback.resumed' || type === 'spotify.playback.paused' || type === 'spotify.device.changed') {
    const track = text(payload.item_name)
    const artistList = Array.isArray(payload.artists) ? payload.artists.filter((artist): artist is string => typeof artist === 'string') : []
    const device = text(payload.device_name)
    const action = type === 'spotify.playback.paused' ? 'Playback paused' : type === 'spotify.device.changed' ? 'Playback moved' : 'Now playing'
    return {
      domain: 'spotify',
      title: track || action,
      summary: [artistList.join(', '), text(payload.album_name), device].filter(Boolean).join(' · ') || action,
      detail: action,
      severity: 'normal',
      eventTime: null,
      safeHref: null,
    }
  }

  if (type.startsWith('developer.')) {
    const repository = text(payload.repository, 'Monitored repository')
    const workflow = text(payload.workflow)
    const branch = text(payload.branch)
    const title = type === 'developer.workflow.failed' ? `${workflow || 'Workflow'} failed`
      : type === 'developer.workflow.completed' ? `${workflow || 'Workflow'} completed`
        : type === 'developer.deployment.failed' ? 'Deployment failed'
          : type === 'developer.deployment.completed' ? 'Deployment completed'
            : type === 'developer.pull_request.merged' ? 'Pull request merged'
              : type === 'developer.pull_request.opened' ? 'Pull request opened'
                : type === 'developer.push.received' ? 'Push received' : 'Repository activity'
    const summary = [repository, branch ? `branch ${branch}` : '', text(payload.conclusion || payload.state)].filter(Boolean).join(' · ')
    return {
      domain: 'github', title, summary: summary || repository,
      detail: number(payload.number) ? `PR #${number(payload.number)}` : null,
      severity: type.endsWith('.failed') ? 'warning' : 'normal', eventTime: null,
      safeHref: safeLink(payload.url, 'github.com'),
    }
  }

  if (type === 'mail.message.received' || type === 'mail.thread.updated') {
    const important = payload.important === true
    const removed = payload.message_removed === true
    return {
      domain: 'gmail',
      title: removed ? 'Thread updated' : text(payload.subject, type === 'mail.message.received' ? 'New message' : 'Message updated'),
      summary: [text(payload.sender, 'Sender unavailable'), payload.unread === true ? 'Unread' : '', important ? 'Important' : ''].filter(Boolean).join(' · '),
      detail: text(payload.snippet).slice(0, 240) || null,
      severity: important ? 'warning' : 'normal', eventTime: null, safeHref: null,
    }
  }

  if (type === 'weather.conditions.updated') {
    const category = text(payload.category, 'Conditions')
    const temp = number(payload.temperature_f)
    const description = text(payload.description, category)
    return {
      domain: 'weather', title: 'Weather changed',
      summary: temp === null ? description : `${description} · ${Math.round(temp)}°F`,
      detail: text(payload.timezone) || null, severity: 'normal', eventTime: null, safeHref: null,
    }
  }

  if (type.startsWith('system.')) {
    return { domain: 'system', title: 'System recovery', summary: 'Realtime state was reconciled', detail: null, severity: 'normal', eventTime: null, safeHref: null }
  }
  return { domain: 'other', title: 'LivePulse activity', summary: 'A new event entered the timeline', detail: null, severity: 'normal', eventTime: null, safeHref: null }
}

export function timeAgo(value: string | null | undefined, now = Date.now()): string | null {
  if (!value) return null
  const at = Date.parse(value)
  if (!Number.isFinite(at)) return null
  const seconds = Math.max(0, Math.floor((now - at) / 1000))
  if (seconds < 60) return 'Just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}

export function providerStatusLabel(status: string, configured?: boolean): string {
  if (!configured && status === 'disconnected') return 'Not configured'
  const labels: Record<string, string> = {
    healthy: 'Fresh', degraded: 'Degraded', unavailable: 'Unavailable', unknown: 'Checking',
    disconnected: 'Disconnected', connecting: 'Connecting', stale: 'Stale', resyncing: 'Resyncing',
    rate_limited: 'Rate limited', auth_failure: 'Reconnect required', provider_failure: 'Provider error',
  }
  return labels[status] ?? 'Status unknown'
}
