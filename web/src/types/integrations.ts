import type { TimelineItem } from './livepulse'

/** Generic timeline metadata lets source-specific items use the shared timeline layout. */
export type PulseTimelinePresentation = {
  item: TimelineItem
  category: string
  icon_key: string
  severity: 'low' | 'normal' | 'high' | 'critical'
  title: string
  subtitle?: string
  occurred_at: string
  cursor: number
}

/** Normalized server-owned attention information for future source candidates. */
export type AttentionSnapshot = {
  score: number
  severity: 'low' | 'normal' | 'high' | 'critical'
  reason: string
  transient: boolean
  expires_at: string | null
  source: string
  subject_id: string | null
}

export type FocusCandidate = {
  source: string
  subject_id: string | null
  attention: AttentionSnapshot
}
