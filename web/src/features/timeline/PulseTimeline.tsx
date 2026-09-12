import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CircleDot, Flag, Goal, ShieldAlert, Square } from 'lucide-react'
import type { TimelineItem } from '../../types/livepulse'

const eventDisplay: Record<string, { title: string; kind: string; Icon: typeof Goal }> = {
  'football.match.scheduled': { title: 'Match scheduled', kind: 'neutral', Icon: Flag },
  'football.match.kickoff': { title: 'Kick-off', kind: 'live', Icon: CircleDot },
  'football.match.goal': { title: 'Goal', kind: 'goal', Icon: Goal },
  'football.match.yellow_card': { title: 'Yellow card', kind: 'card', Icon: Square },
  'football.match.red_card': { title: 'Red card', kind: 'alert', Icon: ShieldAlert },
  'football.match.halftime': { title: 'Half-time', kind: 'neutral', Icon: Flag },
  'football.match.second_half': { title: 'Second half', kind: 'live', Icon: CircleDot },
  'football.match.fulltime': { title: 'Full-time', kind: 'neutral', Icon: Flag },
}

function eventDescription(item: TimelineItem) {
  const side = item.payload.side === 'home' ? item.payload.home_team : item.payload.side === 'away' ? item.payload.away_team : null
  if (item.event_type.endsWith('.goal')) return `${String(item.payload.player ?? 'Unknown')} · ${String(side ?? '')}`
  if (item.event_type.includes('card')) return `${String(item.payload.player ?? 'Player')} · ${String(side ?? '')}`
  return String(item.payload.competition ?? 'Premier League')
}

export function PulseTimeline({ items }: { items: TimelineItem[] }) {
  return (
    <section className="timeline-panel" aria-label="Universal Pulse Timeline">
      <div className="panel-heading"><div><span className="eyebrow">EVENT STREAM <i /></span><h2>Pulse Timeline</h2></div><span className="timeline-count">{String(items.length).padStart(2, '0')} <small>EVENTS</small></span></div>
      {items.length === 0 ? (
        <div className="timeline-empty"><div className="timeline-guide" /><span className="empty-pulse"><CircleDot size={17} /></span><p>Your signal, in sequence.</p><span>Live events surface here as they happen.</span></div>
      ) : (
        <div className="timeline-list" role="list">
          <div className="timeline-guide" />
          <AnimatePresence initial={false}>
            {items.map((item, index) => {
              const display = eventDisplay[item.event_type] ?? { title: item.event_type, kind: 'neutral', Icon: AlertTriangle }
              const Icon = display.Icon
              const minute = item.payload.minute
              return (
                <motion.article key={item.event_id} className={`timeline-item ${display.kind}`} role="listitem" layout initial={{ opacity: 0, y: -12, scale: 0.985 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }} transition={{ duration: 0.24, delay: index === 0 ? 0.04 : 0 }}>
                  <span className="event-icon"><Icon size={15} strokeWidth={1.8} /></span>
                  <div className="event-copy"><div><h3>{display.title}</h3><time>{new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p>{eventDescription(item)}</p></div>
                  <span className="event-minute">{typeof minute === 'number' && minute > 0 ? `${minute}′` : <span>—</span>}</span>
                </motion.article>
              )
            })}
          </AnimatePresence>
        </div>
      )}
    </section>
  )
}
