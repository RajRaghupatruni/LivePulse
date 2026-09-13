import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, ChevronLeft, ChevronRight, Clock3, MoveUpRight, Pin, Radio, ShieldAlert } from 'lucide-react'
import type { FootballFixture, FootballFixtures, LiveState, Match, TimelineItem } from '../../types/livepulse'
import { getPreference, removePreference, setPreference } from '../../lib/platform'
import { presentTimelineItem } from '../../lib/timelinePresentation'

type MatchKind = 'live' | 'upcoming' | 'halftime' | 'fulltime' | 'idle'
type MatchPick = { match: Match | null; kind: MatchKind; kickoff?: string; observed?: string | null }
type DetailTab = 'updates' | 'schedule' | 'lineups' | 'stats'
const SELECTED_MATCH_KEY = 'livepulse.selected-match.v1'

function allFixtures(fixtures: FootballFixtures | null) {
  const unique = new Map<number, FootballFixture>()
  // Provider snapshots can include the same fixture in multiple windows; the
  // live projection is the freshest and must win over scheduled copies.
  for (const fixture of [...(fixtures?.upcoming ?? []), ...(fixtures?.today ?? []), ...(fixtures?.live ?? [])]) unique.set(fixture.fixture_id, fixture)
  return [...unique.values()].sort((a, b) => Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at) || a.fixture_id - b.fixture_id)
}

function asMatch(fixture: FootballFixture): Match {
  const raw = fixture.status.toLowerCase()
  const status = ['1h', '2h', 'et', 'p', 'live', 'in_play', 'first_half', 'second_half'].includes(raw) ? 'live'
    : ['ht', 'halftime'].includes(raw) ? 'halftime'
      : ['ft', 'aet', 'pen', 'fulltime'].includes(raw) ? 'fulltime' : 'scheduled'
  return {
    match_id: fixture.subject_id,
    home_team: fixture.home_team,
    away_team: fixture.away_team,
    competition: fixture.competition,
    home_score: fixture.home_score ?? 0,
    away_score: fixture.away_score ?? 0,
    status,
    minute: fixture.minute,
    phase: status === 'halftime' ? 'halftime' : status === 'live' ? 'second_half' : status,
    version: 0,
    last_event_id: null,
    last_event_type: null,
    updated_at: fixture.kickoff_at,
  }
}

function chooseMatch(live: LiveState, fixtures: FootballFixtures | null, selectedId: string | null): MatchPick {
  const discovered = allFixtures(fixtures)
  if (selectedId) {
    const selected = discovered.find((fixture) => fixture.subject_id === selectedId)
    if (selected) {
      const match = asMatch(selected)
      const kind: MatchKind = match.status === 'live' ? 'live' : match.status === 'halftime' ? 'halftime' : match.status === 'fulltime' ? 'fulltime' : 'upcoming'
      return { match, kind, kickoff: kind === 'upcoming' ? selected.kickoff_at : undefined, observed: fixtures?.observed_at }
    }
  }
  if (live.match && ['live', 'halftime'].includes(live.match.status)) return { match: live.match, kind: live.match.status === 'halftime' ? 'halftime' : 'live' }
  const liveFixture = discovered.find((fixture) => ['1h', '2h', 'et', 'p', 'live', 'in_play', 'first_half', 'second_half', 'ht', 'halftime'].includes(fixture.status.toLowerCase()))
  if (liveFixture) {
    const match = asMatch(liveFixture)
    return { match, kind: match.status === 'halftime' ? 'halftime' : 'live', observed: fixtures?.observed_at }
  }
  const currentTime = Date.now()
  const upcoming = discovered.find((fixture) => Date.parse(fixture.kickoff_at) > currentTime && !['ft', 'aet', 'pen', 'fulltime'].includes(fixture.status.toLowerCase()))
  if (upcoming) return { match: asMatch(upcoming), kind: 'upcoming', kickoff: upcoming.kickoff_at, observed: fixtures?.observed_at }
  const kickoffDue = [...discovered].reverse().find((fixture) => Date.parse(fixture.kickoff_at) >= currentTime - 4 * 60 * 60_000 && ['ns', 'tbd', 'pst', 'scheduled'].includes(fixture.status.toLowerCase()))
  if (kickoffDue) return { match: asMatch(kickoffDue), kind: 'upcoming', kickoff: kickoffDue.kickoff_at, observed: fixtures?.observed_at }
  if (live.match?.status === 'fulltime') return { match: live.match, kind: 'fulltime' }
  const completed = [...discovered].reverse().find((fixture) => ['ft', 'aet', 'pen', 'fulltime'].includes(fixture.status.toLowerCase()))
  if (completed) return { match: asMatch(completed), kind: 'fulltime', observed: fixtures?.observed_at }
  return { match: null, kind: 'idle' }
}

function durationLabel(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return days > 0 ? `${days}d ${String(hours).padStart(2, '0')}h` : `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}

function phaseName(pick: MatchPick) {
  if (pick.kind === 'upcoming') return 'UPCOMING'
  if (pick.kind === 'fulltime') return 'FULL TIME'
  if (pick.kind === 'halftime') return 'HALF TIME'
  if (pick.kind === 'live') return `${Math.max(0, pick.match?.minute ?? 0)}′ · ${pick.match?.phase.replaceAll('_', ' ').toUpperCase() ?? 'LIVE'}`
  return 'FOOTBALL'
}

function crest(team: string) {
  return team.split(/\s+/).filter(Boolean).map((part) => part[0]).slice(0, 2).join('').toUpperCase() || 'FC'
}

export function MatchStage({ live, fixtures, fixtureLoading, fixtureAvailable, timeline = [], eventArrival = null }: {
  live: LiveState
  fixtures: FootballFixtures | null
  fixtureLoading: boolean
  fixtureAvailable: boolean
  timeline?: TimelineItem[]
  eventArrival?: Pick<TimelineItem, 'event_id' | 'event_type' | 'subject_id' | 'timestamp' | 'payload'> | null
}) {
  const reduceMotion = useReducedMotion()
  const [selectedId, setSelectedId] = useState<string | null>(() => getPreference(SELECTED_MATCH_KEY))
  const [pinned, setPinned] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailTab, setDetailTab] = useState<DetailTab>('updates')
  const detailReturnFocus = useRef<HTMLElement | null>(null)
  const [event, setEvent] = useState<TimelineItem | null>(null)
  const candidates = useMemo(() => allFixtures(fixtures), [fixtures])
  const picked = useMemo(() => chooseMatch(live, fixtures, selectedId), [live, fixtures, selectedId])
  const match = picked.match
  const selectedMatchId = match?.match_id
  const selectedIndex = candidates.findIndex((fixture) => fixture.subject_id === selectedMatchId)
  const moveMatch = useCallback((direction: number) => {
    if (!candidates.length) return
    const index = selectedIndex >= 0 ? selectedIndex : 0
    setSelectedId(candidates[(index + direction + candidates.length) % candidates.length].subject_id)
  }, [candidates, selectedIndex])
  const openDetails = (event: MouseEvent<HTMLElement>) => {
    detailReturnFocus.current = event.currentTarget
    setDetailOpen(true)
  }
  const closeDetails = useCallback(() => {
    setDetailOpen(false)
    requestAnimationFrame(() => detailReturnFocus.current?.focus())
  }, [])

  useEffect(() => {
    if (selectedId) setPreference(SELECTED_MATCH_KEY, selectedId)
    else removePreference(SELECTED_MATCH_KEY)
  }, [selectedId])
  useEffect(() => {
    if (picked.kind !== 'upcoming') return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [picked.kind, picked.kickoff])
  useEffect(() => {
    if (!eventArrival || !selectedMatchId || eventArrival.subject_id !== selectedMatchId || !['football.match.goal', 'football.match.red_card'].includes(eventArrival.event_type)) return
    const item = timeline.find((candidate) => candidate.event_id === eventArrival.event_id) ?? { ...eventArrival, cursor: 0, source: 'football', payload: eventArrival.payload ?? {} }
    setEvent(item as TimelineItem)
    const timeout = window.setTimeout(() => setEvent(null), 6200)
    return () => window.clearTimeout(timeout)
  }, [eventArrival, selectedMatchId, timeline])
  useEffect(() => {
    const previous = () => moveMatch(-1)
    const next = () => moveMatch(1)
    window.addEventListener('livepulse:match-previous', previous)
    window.addEventListener('livepulse:match-next', next)
    return () => { window.removeEventListener('livepulse:match-previous', previous); window.removeEventListener('livepulse:match-next', next) }
  }, [moveMatch])
  const remaining = picked.kickoff ? Date.parse(picked.kickoff) - now : 0
  const urgency = remaining <= 5 * 60_000 ? 'imminent' : remaining <= 30 * 60_000 ? 'approach' : 'soon'
  const mode = !match ? 'idle' : picked.kind === 'upcoming' ? urgency : picked.kind
  const updates = timeline.filter((item) => item.source === 'football' || item.event_type.startsWith('football.')).slice(0, 8)
  const isGoal = event?.event_type.endsWith('.goal')
  const eventPresentation = event ? presentTimelineItem(event) : null

  if (!match) return <section className="match-stage match-stage-idle" aria-label="Football match surface">
    <div className="match-art" aria-hidden="true" /><div className="match-shade" aria-hidden="true" />
    <header className="match-stage-top"><div><span className="surface-overline">FOOTBALL · MATCH CENTER</span><h2>Football</h2></div><span className="match-phase-label"><i />{fixtureLoading ? 'CHECKING SOURCE' : fixtureAvailable ? 'NO SCHEDULED MATCH' : 'SOURCE UNAVAILABLE'}</span></header>
    <div className="match-empty"><span className="match-pulse-mark"><Activity size={22} /></span><h3>{fixtureLoading ? 'Resolving the next fixture' : fixtures?.provider_status === 'disconnected' ? 'Connect a football source' : fixtureAvailable ? 'No match in the current window' : 'Football data is unavailable'}</h3><p>{fixtureAvailable ? 'When the provider reports a fixture, this surface will establish the match context.' : 'Provider configuration and freshness are available in System Pulse.'}</p><button type="button" onClick={openDetails}>Open match center <MoveUpRight size={15} /></button></div>
    <div className="match-field-signature" aria-hidden="true"><svg viewBox="0 0 440 180"><path d="M10 114 C64 42 139 38 211 75 C275 109 333 138 430 60"/><path d="M8 130 C66 61 139 56 211 91 C279 124 336 151 430 77"/><path d="M7 147 C68 80 141 73 213 107 C284 139 340 166 430 94"/><path d="M16 97 C74 27 144 22 212 57 C272 88 331 118 422 44"/></svg></div>
    {detailOpen && createPortal(<MatchDetails title="Football match center" tab={detailTab} setTab={setDetailTab} fixtures={candidates} selectedId={selectedId} selectMatch={(id) => { setSelectedId(id); closeDetails() }} updates={updates} onClose={closeDetails} />, document.body)}
  </section>

  const scoreVisible = picked.kind !== 'upcoming'
  return <motion.section className={`match-stage match-stage-${mode}${event ? ` event-${isGoal ? 'goal' : 'red-card'}` : ''}`} aria-label={`${phaseName(picked)}: ${match.home_team} versus ${match.away_team}`} layout transition={{ duration: reduceMotion ? 0 : .65, ease: [.2, .8, .2, 1] }}>
    <div className="match-art" aria-hidden="true" /><div className="match-shade" aria-hidden="true" /><div className="match-stage-grid" aria-hidden="true" />
    <header className="match-stage-top">
      <div className="match-competition"><span className={`match-state-dot${picked.kind === 'live' || picked.kind === 'halftime' ? ' is-live' : ''}`} /><div><span className="surface-overline">{match.competition || 'FOOTBALL'}</span><h2>{picked.kind === 'upcoming' ? 'Match approaching' : picked.kind === 'fulltime' ? 'Final result' : 'Match center'}</h2></div></div>
      <div className={`match-phase-label${picked.kind === 'live' ? ' phase-live' : ''}`}><i />{phaseName(picked)}</div>
      <div className="match-controls"><button type="button" aria-label="Previous match" disabled={candidates.length < 2} onClick={() => moveMatch(-1)}><ChevronLeft size={16}/></button><button type="button" aria-label="Next match" disabled={candidates.length < 2} onClick={() => moveMatch(1)}><ChevronRight size={16}/></button><button type="button" className="match-auto" onClick={() => { setSelectedId(null); setPinned(false) }}>AUTO</button><button type="button" className={pinned ? 'is-pinned' : ''} aria-pressed={pinned} aria-label={pinned ? 'Unpin this match' : 'Pin this match'} onClick={() => { setPinned((value) => !value); if (!selectedId) setSelectedId(match.match_id) }}><Pin size={14}/></button></div>
    </header>
    <div className="match-summary"><span>{picked.kind === 'upcoming' ? `KICKOFF · ${new Date(picked.kickoff!).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : picked.kind === 'live' ? 'LIVE MATCH' : picked.kind === 'halftime' ? 'INTERVAL' : 'PROVIDER OBSERVED'}</span><span>{candidates.length ? `MATCH ${selectedIndex >= 0 ? selectedIndex + 1 : 1} / ${candidates.length}` : 'SINGLE MATCH'}</span></div>
    <div className="fixture-composition">
      <div className="fixture-team fixture-home"><span className="team-monogram">{crest(match.home_team)}</span><span className="fixture-team-copy"><small>HOME</small><strong>{match.home_team}</strong></span></div>
      <div className="fixture-center">{scoreVisible ? <div className="fixture-score" aria-label={`${match.home_score} to ${match.away_score}`}><AnimatePresence mode="popLayout" initial={false}><motion.span key={`h-${match.home_score}`} initial={reduceMotion ? false : { y: 16, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={reduceMotion ? undefined : { y: -12, opacity: 0 }} transition={{ duration: reduceMotion ? 0 : .34 }}>{match.home_score}</motion.span></AnimatePresence><i>:</i><AnimatePresence mode="popLayout" initial={false}><motion.span key={`a-${match.away_score}`} initial={reduceMotion ? false : { y: 16, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={reduceMotion ? undefined : { y: -12, opacity: 0 }} transition={{ duration: reduceMotion ? 0 : .34 }}>{match.away_score}</motion.span></AnimatePresence></div> : <div className={`countdown-dial ${urgency}`}><span>{durationLabel(remaining)}</span><small>UNTIL KICKOFF</small></div>}<span className={`fixture-phase${picked.kind === 'live' ? ' is-live' : ''}`}>{picked.kind === 'upcoming' ? remaining <= 0 ? 'KICKOFF DUE · AWAITING PROVIDER' : 'KICKOFF WINDOW' : phaseName(picked)}</span></div>
      <div className="fixture-team fixture-away"><span className="team-monogram">{crest(match.away_team)}</span><span className="fixture-team-copy"><small>AWAY</small><strong>{match.away_team}</strong></span></div>
    </div>
    <svg className={`match-pulse-field${picked.kind === 'live' ? ' pulse-live' : ''}${pinned ? ' pulse-pinned' : ''}`} viewBox="0 0 540 100" aria-hidden="true"><path d="M4 56 C72 22 123 78 189 49 S300 23 365 52 462 76 536 38"/><path d="M4 66 C75 34 125 88 191 60 S300 36 365 62 462 86 536 48"/><path d="M4 46 C73 12 121 68 188 40 S300 14 364 42 463 66 536 28"/><path className="pulse-field-core" d="M6 56 C75 32 125 75 190 50 S301 26 365 53 463 73 534 38"/><circle cx="365" cy="52" r="3"/></svg>
    <div className="match-stage-foot"><span><i className="match-foot-mark" /> {picked.kind === 'upcoming' ? 'MATCH AWARENESS' : `FOCUS ENGINE · ${live.focus.reason.replaceAll('_', ' ')}`}</span><span>{picked.observed ? `Observed ${new Date(picked.observed).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : picked.kind === 'upcoming' ? 'FIXTURE CONFIRMED' : `FOCUS ${live.focus.score} / 100`}</span><button className="stage-expand-mark" type="button" onClick={openDetails} aria-label="View match details">VIEW MATCH <MoveUpRight size={14} /></button></div>
    <AnimatePresence>{event && <motion.div className={`event-arrival event-arrival-${isGoal ? 'goal' : 'red-card'}`} initial={reduceMotion ? { opacity: 1 } : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: reduceMotion ? 0 : .3 }}><span>{isGoal ? 'GOAL' : 'RED CARD'}</span><strong>{eventPresentation?.summary ?? (isGoal ? 'Score changed' : 'Dismissal recorded')}</strong><span>{match.home_score} : {match.away_score}</span></motion.div>}</AnimatePresence>
    {detailOpen && createPortal(<MatchDetails title={`${match.home_team} ${match.home_score} — ${match.away_score} ${match.away_team}`} tab={detailTab} setTab={setDetailTab} fixtures={candidates} selectedId={selectedId ?? match.match_id} selectMatch={(id) => { setSelectedId(id); setDetailTab('updates') }} updates={updates} onClose={closeDetails} />, document.body)}
  </motion.section>
}

function MatchDetails({ title, tab, setTab, fixtures, selectedId, selectMatch, updates, onClose }: {
  title: string
  tab: DetailTab
  setTab: (tab: DetailTab) => void
  fixtures: FootballFixture[]
  selectedId: string | null
  selectMatch: (id: string) => void
  updates: TimelineItem[]
  onClose: () => void
}) {
  const tabs: Array<[DetailTab, string]> = [['updates', 'Updates'], ['schedule', 'Schedule'], ['lineups', 'Lineups'], ['stats', 'Stats']]
  const closeButton = useRef<HTMLButtonElement | null>(null)
  const dialog = useRef<HTMLElement | null>(null)
  useEffect(() => { closeButton.current?.focus() }, [])
  const onDialogKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); return }
    if (event.key !== 'Tab') return
    const focusable = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled)') ?? [])
    if (!focusable.length) return
    if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus() }
    else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus() }
  }
  return <div className="match-detail-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section ref={dialog} className="match-details" role="dialog" aria-modal="true" aria-labelledby="match-details-title" onKeyDown={onDialogKeyDown}>
    <header><div><span className="surface-overline">FOOTBALL · PROVIDER DATA</span><h2 id="match-details-title">{title}</h2></div><button ref={closeButton} type="button" aria-label="Close match details" onClick={onClose}>×</button></header>
    <nav className="match-detail-tabs" aria-label="Match details">{tabs.map(([key, label]) => <button key={key} type="button" className={tab === key ? 'is-active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>{label}</button>)}</nav>
    <div className="match-detail-content">
      {tab === 'schedule'
        ? fixtures.length > 0
          ? <div className="schedule-list">{fixtures.map((fixture) => <button type="button" className={fixture.subject_id === selectedId ? 'is-selected' : ''} key={fixture.fixture_id} onClick={() => selectMatch(fixture.subject_id)}><span>{new Date(fixture.kickoff_at).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span><strong>{fixture.home_team} <i>{fixture.home_score ?? '·'} : {fixture.away_score ?? '·'}</i> {fixture.away_team}</strong><small>{fixture.competition} · {fixture.status}</small></button>)}</div>
          : <div className="match-detail-empty"><Clock3 size={19}/><strong>No fixtures reported</strong><p>The football source has not reported upcoming or recent matches.</p></div>
        : tab === 'updates'
          ? updates.length ? <div className="match-update-list">{updates.map((item) => { const event = presentTimelineItem(item); return <article key={item.event_id}><span><Radio size={14}/>{new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><strong>{event.title}</strong><p>{event.summary}</p></article> })}</div> : <div className="match-detail-empty"><Activity size={19}/><strong>No provider updates yet</strong><p>Match events will appear here as they are observed.</p></div>
          : <div className="match-detail-empty"><ShieldAlert size={20}/><strong>{tab === 'lineups' ? 'Lineups are not available from this provider contract' : 'Match statistics are not available from this provider contract'}</strong><p>LivePulse only presents fields supplied by the connected football source.</p></div>}
    </div>
    <footer><Clock3 size={14}/><span>Provider data is authoritative · no inferred match statistics</span></footer>
  </section></div>
}
