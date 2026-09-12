import { AnimatePresence, motion } from 'framer-motion'
import { Activity, ArrowUpRight, Clock3 } from 'lucide-react'
import type { Match } from '../../types/livepulse'

function phaseLabel(match: Match) {
  if (match.status === 'fulltime') return 'FULL TIME'
  if (match.status === 'halftime') return 'HALF TIME'
  if (match.status === 'live') return `${match.minute}′ · ${match.phase.replace('_', ' ')}`
  return match.status.replace('_', ' ').toUpperCase()
}

function ScoreDigit({ value }: { value: number }) {
  return (
    <div className="score-digit" aria-label={`${value}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span key={value} initial={{ y: 18, opacity: 0, filter: 'blur(4px)' }} animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }} exit={{ y: -18, opacity: 0, filter: 'blur(4px)' }} transition={{ duration: 0.28, ease: 'easeOut' }}>{value}</motion.span>
      </AnimatePresence>
    </div>
  )
}

export function MatchSurface({ match, attention }: { match: Match | null; attention: number }) {
  if (!match) {
    return (
      <section className="match-surface match-empty">
        <div className="surface-meta"><span><Activity size={14} /> MATCH INTELLIGENCE</span><span>AWAITING SIGNAL</span></div>
        <div className="empty-state"><div className="orbit-mark"><span /></div><p>Match telemetry will appear here</p><span>Start the deterministic demo to bring the surface online.</span></div>
      </section>
    )
  }
  const live = match.status === 'live' || match.status === 'halftime'
  return (
    <section className="match-surface" aria-label="Primary match">
      <div className="surface-meta">
        <span><Activity size={14} /> MATCH INTELLIGENCE <i className="meta-divider" /> {match.competition.toUpperCase()}</span>
        <span className={live ? 'match-live-label' : ''}><span className="tiny-dot" /> {phaseLabel(match)}</span>
      </div>
      <div className="match-main">
        <div className="team-block home-team"><div className="team-badge monogram home-badge">N</div><div><span className="team-caption">HOME</span><h2>{match.home_team}</h2></div></div>
        <div className="score-board">
          <div className="score-pair"><ScoreDigit value={match.home_score} /><span className="score-colon">:</span><ScoreDigit value={match.away_score} /></div>
          <div className="score-clock"><Clock3 size={13} /> {phaseLabel(match)}</div>
        </div>
        <div className="team-block away-team"><div className="team-badge monogram away-badge">H</div><div><span className="team-caption">AWAY</span><h2>{match.away_team}</h2></div></div>
      </div>
      <div className="match-footer">
        <div className="focus-meter"><span className="meter-label">FOCUS ENGINE</span><span className="meter-track"><i style={{ width: `${attention}%` }} /></span><strong>{attention}<small> / 100</small></strong></div>
        <div className="match-version">STATE v{String(match.version).padStart(2, '0')} <ArrowUpRight size={12} /></div>
      </div>
    </section>
  )
}
