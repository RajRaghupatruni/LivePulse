import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, AlertTriangle, CircleDot, Flag, Goal, ShieldAlert, Square } from 'lucide-react'
import type { TimelineItem } from '../../types/livepulse'

type EventPresentation = { title: string; category: string; Icon: typeof Goal }

const eventDisplay: Record<string, EventPresentation> = {
  'football.match.scheduled': { title: 'Match scheduled', category: 'fixture', Icon: Flag },
  'football.match.kickoff': { title: 'Kick-off', category: 'live', Icon: CircleDot },
  'football.match.goal': { title: 'Goal', category: 'goal', Icon: Goal },
  'football.match.yellow_card': { title: 'Yellow card', category: 'card', Icon: Square },
  'football.match.red_card': { title: 'Red card', category: 'critical', Icon: ShieldAlert },
  'football.match.halftime': { title: 'Half-time', category: 'pause', Icon: Flag },
  'football.match.second_half': { title: 'Second half', category: 'live', Icon: CircleDot },
  'football.match.fulltime': { title: 'Full-time', category: 'complete', Icon: Flag },
}

function eventDescription(item: TimelineItem) {
  const side = item.payload.side === 'home' ? item.payload.home_team : item.payload.side === 'away' ? item.payload.away_team : null
  if (item.event_type.endsWith('.goal')) return `${String(item.payload.player ?? 'Unknown')} · ${String(side ?? '')}`
  if (item.event_type.includes('card')) return `${String(item.payload.player ?? 'Player')} · ${String(side ?? '')}`
  if (item.payload.competition) return String(item.payload.competition)
  if (item.payload.summary) return String(item.payload.summary)
  return item.subject_id || sourceLabel(item.source)
}

function sourceLabel(source: string) {
  return source.split(/[-_.]/).filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
}

function eventTitle(item: TimelineItem) {
  const known = eventDisplay[item.event_type]
  if (known) return known
  const lastPart = item.event_type.split('.').at(-1)?.replaceAll('_', ' ')
  return {
    title: lastPart ? lastPart.charAt(0).toUpperCase() + lastPart.slice(1) : 'Activity',
    category: item.event_type.startsWith('system.') ? 'system' : 'activity',
    Icon: item.event_type.startsWith('system.') ? AlertTriangle : Activity,
  }
}

export function PulseTimeline({ items }: { items: TimelineItem[] }) {
  const reduceMotion = useReducedMotion()
  return (
    <section className="timeline-panel" aria-label="Universal Pulse Timeline">
      <div className="panel-heading"><div><span className="eyebrow">DURABLE EVENT HISTORY <i /></span><h2>Pulse Timeline</h2></div><span className="timeline-count">{String(items.length).padStart(2, '0')} <small>EVENTS</small></span></div>
      {items.length === 0 ? (
        <div className="timeline-empty"><div className="timeline-guide" /><span className="empty-pulse"><CircleDot size={17} /></span><p>Your signal, in sequence.</p><span>Live events surface here as they happen.</span></div>
      ) : (
        <div className="timeline-list" role="list">
          <div className="timeline-guide" />
          <AnimatePresence initial={false}>
            {items.map((item, index) => {
              const display = eventTitle(item)
              const Icon = display.Icon
              const minute = item.payload.minute
              return (
                <motion.article
                  key={item.event_id}
                  className={`timeline-item category-${display.category}`}
                  role="listitem"
                  layout={!reduceMotion}
                  initial={reduceMotion ? false : { opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduceMotion ? undefined : { opacity: 0, y: 6 }}
                  transition={{ duration: reduceMotion ? 0 : 0.22, delay: index === 0 ? 0.035 : 0 }}
                >
                  <span className="event-icon"><Icon size={15} strokeWidth={1.8} /></span>
                  <div className="event-copy"><div><h3>{display.title}</h3><time dateTime={item.timestamp} title={new Date(item.timestamp).toLocaleString()}>{new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p>{eventDescription(item)}</p><span className="event-source">{sourceLabel(item.source)}</span></div>
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
