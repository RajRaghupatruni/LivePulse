import { useEffect, useState, type KeyboardEvent } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, Cloud, ExternalLink, GitBranch, Mail, Music2, Trophy } from 'lucide-react'
import type { TimelineItem } from '../../types/livepulse'
import { presentTimelineItem, timeAgo } from '../../lib/timelinePresentation'
import { openExternal } from '../../lib/platform'

const iconFor = {
  football: Trophy, spotify: Music2, github: GitBranch, gmail: Mail, weather: Cloud, system: Activity, other: Activity,
} as const

function displayTime(item: TimelineItem) {
  const elapsed = timeAgo(item.timestamp)
  return elapsed ?? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function PulseTimeline({ items, hasOlder = false, loadingOlder = false, onLoadOlder, onRefresh, arrivalId = null }: {
  items: TimelineItem[]; hasOlder?: boolean; loadingOlder?: boolean; onLoadOlder?: () => void; onRefresh?: () => void; arrivalId?: string | null
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const reduced = useReducedMotion()
  useEffect(() => {
    if (!expanded) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      document.querySelectorAll<HTMLButtonElement>('.timeline-entry-main').forEach((button) => {
        if (button.dataset.eventId === expanded) button.focus()
      })
      setExpanded(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [expanded])
  const navigateRows = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    const current = event.target instanceof HTMLElement ? event.target.closest<HTMLButtonElement>('.timeline-entry-main') : null
    if (!current) return
    const rows = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('.timeline-entry-main'))
    const index = rows.indexOf(current)
    if (index < 0) return
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))
    event.preventDefault()
    rows[nextIndex]?.focus()
  }
  return <section className="pulse-timeline" aria-label="Pulse Timeline">
    <div className="timeline-current-marker"><span>NOW</span><i /></div>
    {items.length === 0 ? <div className="timeline-empty"><span className="timeline-empty-mark"><Activity size={18} /></span><strong>Timeline establishing</strong><p>Events appear here as providers observe change.</p>{onRefresh && <button type="button" onClick={onRefresh}>Reconcile now</button>}</div> : <div className="timeline-list" role="feed" aria-label="Recent events" onKeyDown={navigateRows}>
      <AnimatePresence initial={false} mode="popLayout">
        {items.map((item, index) => {
          const data = presentTimelineItem(item)
          const Icon = iconFor[data.domain]
          const isExpanded = expanded === item.event_id
          const observed = item.observed_at ? new Date(item.observed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : null
          const received = item.observed_at ? timeAgo(item.observed_at) : null
          return <motion.article className={`timeline-entry domain-${data.domain} severity-${data.severity}${index === 0 ? ' timeline-entry-latest' : ''}${item.event_id === arrivalId ? ' timeline-entry-arriving' : ''}`} key={item.event_id} layout initial={reduced || item.event_id !== arrivalId ? false : { opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, height: 0 }} transition={{ duration: reduced ? 0 : .28, ease: [.2, .8, .2, 1] }} aria-posinset={index + 1}>
            <button className="timeline-entry-main" type="button" data-event-id={item.event_id} aria-expanded={isExpanded} onClick={() => setExpanded(isExpanded ? null : item.event_id)}>
              <span className="timeline-domain-mark"><Icon size={16} strokeWidth={1.7} aria-hidden="true" />{data.severity === 'critical' && <i className="timeline-severity-mark" />}</span>
              <span className="timeline-event-copy"><span className="timeline-event-head"><strong>{data.title}</strong><time dateTime={item.timestamp} title={new Date(item.timestamp).toLocaleString()}>{displayTime(item)}</time></span><span className="timeline-summary">{data.summary}</span>{data.detail && (isExpanded || data.domain === 'football') && <span className="timeline-detail">{data.detail}</span>}</span>
              <span className="timeline-expand" aria-hidden="true">{isExpanded ? '−' : '+'}</span>
            </button>
            {isExpanded && <div className="timeline-entry-details"><span>Source <strong>{item.source}</strong></span><span>Observed <strong>{observed ?? 'Timestamp unavailable'}</strong></span><span>Freshness <strong>{received ?? 'Unavailable'}</strong></span>{data.safeHref && <button type="button" onClick={() => void openExternal(data.safeHref!)}>Open source <ExternalLink size={13} /></button>}</div>}
          </motion.article>
        })}
      </AnimatePresence>
    </div>}
    {hasOlder && onLoadOlder && <button className="timeline-load-older" type="button" onClick={onLoadOlder} disabled={loadingOlder}><span>{loadingOlder ? 'Loading chronology…' : 'Load earlier events'}</span><span aria-hidden="true">{loadingOlder ? '···' : '↓'}</span></button>}
    <div className="timeline-end-mark"><span /><span>CHRONOLOGY CONTINUES</span><span /></div>
  </section>
}
