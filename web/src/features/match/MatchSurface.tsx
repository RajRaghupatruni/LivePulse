import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, ArrowUpRight, Clock3 } from 'lucide-react'
import type { FocusState, Match } from '../../types/livepulse'

function phaseLabel(match: Match) {
  if (match.status === 'fulltime') return 'FULL TIME'
  if (match.status === 'halftime') return 'HALF TIME'
  if (match.status === 'live') return `${match.minute}′ · ${match.phase.replace('_', ' ')}`
  return match.status.replace('_', ' ').toUpperCase()
}

function ScoreDigit({ value, side }: { value: number; side: 'home' | 'away' }) {
  const reduceMotion = useReducedMotion()
  return (
    <div className="score-digit" aria-label={`${value}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={`${side}-${value}`}
          initial={reduceMotion ? false : { y: 18, opacity: 0, filter: 'blur(4px)' }}
          animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
          exit={reduceMotion ? undefined : { y: -18, opacity: 0, filter: 'blur(4px)' }}
          transition={{ duration: reduceMotion ? 0 : 0.28, ease: 'easeOut' }}
        >{value}</motion.span>
      </AnimatePresence>
    </div>
  )
}

const modeLabels: Record<FocusState['match_mode'], string> = {
  idle: 'AWAITING MATCH',
  scheduled: 'SCHEDULED',
  live: 'MATCH MODE',
  halftime: 'HALF-TIME',
  highlight: 'MOMENT IN FOCUS',
  fulltime: 'FINAL STATE',
}

export function MatchSurface({ match, focus }: { match: Match | null; focus: FocusState }) {
  const reduceMotion = useReducedMotion()
  if (!match) {
    return (
      <section className="match-surface match-empty" data-match-mode="idle" aria-label="Focus surface, no active match">
        <div className="surface-meta"><span><Activity size={14} /> FOCUS SURFACE <i className="meta-divider" /> NO ACTIVE MATCH</span><span>LOCAL DEMO ONLY</span></div>
        <div className="empty-state"><div className="orbit-mark"><span /></div><p>A clear field of view.</p><span>Run the deterministic match to bring live telemetry into focus.</span></div>
        <div className="match-footer"><div className="focus-meter"><span className="meter-label">SYSTEM FOCUS</span><span className="meter-track"><i style={{ width: `${focus.score}%` }} /></span><strong>{focus.score}<small> / 100</small></strong></div><span className="match-version">{modeLabels[focus.match_mode]}</span></div>
      </section>
    )
  }
  const live = focus.match_mode === 'live' || focus.match_mode === 'halftime' || focus.match_mode === 'highlight'
  return (
    <motion.section
      className={`match-surface match-mode-${focus.match_mode} focus-${focus.severity}`}
      data-match-mode={focus.match_mode}
      aria-label="Primary match focus surface"
      layout
      transition={{ duration: reduceMotion ? 0 : 0.32, ease: 'easeOut' }}
    >
      <div className="surface-meta">
        <span><Activity size={14} /> FOCUS SURFACE <i className="meta-divider" /> {match.competition.toUpperCase()}</span>
        <span className={live ? 'match-live-label' : ''}><span className="tiny-dot" /> {phaseLabel(match)}</span>
      </div>
      <div className="match-main">
        <div className="team-block home-team"><div className="team-badge monogram home-badge">{match.home_team.charAt(0)}</div><div><span className="team-caption">HOME</span><h2>{match.home_team}</h2></div></div>
        <div className="score-board">
          <div className="score-pair" aria-label={`${match.home_team} ${match.home_score}, ${match.away_team} ${match.away_score}`}><ScoreDigit side="home" value={match.home_score} /><span className="score-colon" aria-hidden="true">:</span><ScoreDigit side="away" value={match.away_score} /></div>
          <div className="score-clock"><Clock3 size={13} /> {phaseLabel(match)}</div>
        </div>
        <div className="team-block away-team"><div className="team-badge monogram away-badge">{match.away_team.charAt(0)}</div><div><span className="team-caption">AWAY</span><h2>{match.away_team}</h2></div></div>
      </div>
      <div className="match-footer">
        <div className="focus-meter"><span className="meter-label">FOCUS ENGINE · {focus.reason.replaceAll('_', ' ').toUpperCase()}</span><span className="meter-track"><i style={{ width: `${focus.score}%` }} /></span><strong>{focus.score}<small> / 100</small></strong></div>
        <div className="match-mode-label">{modeLabels[focus.match_mode]} <i /> <span>STATE v{String(match.version).padStart(2, '0')}</span><ArrowUpRight size={12} /></div>
      </div>
    </motion.section>
  )
}
