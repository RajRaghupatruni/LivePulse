import { useCallback, useEffect, useMemo, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { Activity, Focus, Home, Radio, Settings2, Waves } from 'lucide-react'
import { AmbientHeader } from '../features/environment/AmbientHeader'
import { SpatialEnvironment } from '../features/environment/SpatialEnvironment'
import { weatherAtmosphere, weatherTimeOfDay } from '../features/environment/weatherAtmosphere'
import { FocusTimer } from '../features/focus/FocusTimer'
import { useFocusTimerSnapshot } from '../features/focus/focusTimerStore'
import { MatchStage } from '../features/match/MatchStage'
import { SpotifyCapsule } from '../features/music/SpotifyCapsule'
import { PulseTimeline } from '../features/timeline/PulseTimeline'
import { CommandPalette, QuickLaunch, type AppView } from '../features/command/QuickLaunch'
import { GmailPanel } from '../features/mail/GmailPanel'
import { LaunchDestinationSettings } from '../features/command/LaunchDestinationSettings'
import { RuntimeStartup } from '../features/system/RuntimeStartup'
import { useLivePulse } from '../hooks/useLivePulse'
import { useProviderSurfaces } from '../hooks/useProviderSurfaces'
import { useSystemHealth } from '../hooks/useSystemHealth'
import { useWeatherLocation } from '../hooks/useWeatherLocation'
import { consumeWakeSequence, requestFullscreen } from '../lib/platform'
import type { VisualFixture, VisualFixtureName } from '../dev/visualFixtures'
import { useVisualMotion } from '../features/motion/useVisualMotion'
import { usePhysicalSurfaces } from '../features/motion/usePhysicalSurfaces'

const navigation: Array<{ id: AppView; label: string; icon: typeof Home }> = [
  { id: 'home', label: 'Home', icon: Home },
  { id: 'timeline', label: 'Timeline', icon: Activity },
  { id: 'focus', label: 'Focus', icon: Focus },
  { id: 'settings', label: 'Settings', icon: Settings2 },
]

export default function App() {
  const { live, timeline, connection, eventArrival, loadOlder, hasOlder, loadingOlder, refresh } = useLivePulse()
  const { health, requestState, hasBeenReadyOnce, refresh: refreshHealth } = useSystemHealth()
  const surfaces = useProviderSurfaces(health?.runtime_mode === 'PERSONAL_LOCAL')
  const weatherLocation = useWeatherLocation(health?.runtime_mode === 'PERSONAL_LOCAL')
  const timer = useFocusTimerSnapshot()
  const reducedMotion = useReducedMotion()
  usePhysicalSurfaces(Boolean(reducedMotion))
  const [view, setView] = useState<AppView>('home')
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [timelineHistory, setTimelineHistory] = useState(false)
  const [gmailExpanded, setGmailExpanded] = useState(false)
  const [wake, setWake] = useState(consumeWakeSequence)
  const [dayPhase, setDayPhase] = useState(() => weatherTimeOfDay(null))
  const [visualName, setVisualName] = useState<'real' | VisualFixtureName>('real')
  const [visualFixture, setVisualFixture] = useState<VisualFixture | null>(null)

  const applyVisualFixture = useCallback(async (name: 'real' | VisualFixtureName) => {
    setVisualName(name)
    if (!import.meta.env.DEV || name === 'real') { setVisualFixture(null); return }
    const { createVisualFixture } = await import('../dev/visualFixtures')
    setVisualFixture(createVisualFixture(name))
  }, [])

  useEffect(() => {
    if (!wake) return
    const timeout = window.setTimeout(() => setWake(false), 1950)
    return () => window.clearTimeout(timeout)
  }, [wake])
  useEffect(() => {
    if (!import.meta.env.DEV) return
    const requested = new URLSearchParams(window.location.search).get('visual') as VisualFixtureName | null
    if (requested && ['idle', 'spotify-playing', 'upcoming', 'live', 'goal', 'degraded', 'focus'].includes(requested)) void applyVisualFixture(requested)
  }, [applyVisualFixture])
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((value) => !value)
      }
      if (event.key === 'Escape') {
        setTimelineHistory(false)
        setGmailExpanded(false)
        setPaletteOpen(false)
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  const shownLive = visualFixture?.live ?? live
  const shownTimeline = visualFixture?.timeline ?? timeline
  const shownConnection = visualFixture?.connection ?? connection
  const shownEventArrival = visualFixture?.eventArrival ?? eventArrival
  const shownHealth = visualFixture?.health ?? health
  const shownSurfaces = {
    football: visualFixture?.football ?? surfaces.football,
    spotify: visualFixture?.spotify ?? surfaces.spotify,
    weather: visualFixture?.weather ?? surfaces.weather,
    gmail: visualFixture?.gmail,
  }
  const snapshotLocation = shownSurfaces.weather.value?.location ?? null
  const selectedWeatherLocation = weatherLocation.state.selected ?? snapshotLocation
  const weatherSnapshotMatchesSelection = !weatherLocation.state.selected
    || snapshotLocation?.id === weatherLocation.state.selected.id
  const weather = weatherSnapshotMatchesSelection
    ? shownSurfaces.weather.value?.current
    : null
  const weatherTimezone = selectedWeatherLocation?.timezone ?? null
  useEffect(() => {
    const updatePeriod = () => setDayPhase(weatherTimeOfDay(weatherTimezone))
    updatePeriod()
    const timer = window.setInterval(updatePeriod, 60_000)
    return () => window.clearInterval(timer)
  }, [weatherTimezone])
  const visibleTimer = visualFixture?.focusTimer ?? timer
  const focused = visibleTimer.status === 'running' || visibleTimer.status === 'paused'
  const focusLabel = focused ? `FOCUS SESSION · ${visibleTimer.durationMinutes} MIN · ${visibleTimer.status.toUpperCase()}` : null
  const fixtureSet = shownSurfaces.football.value
  const hasUpcoming = [...(fixtureSet?.today ?? []), ...(fixtureSet?.upcoming ?? [])].some((fixture) => Date.parse(fixture.kickoff_at) > Date.now())
  const matchMode = shownLive.match && ['live', 'halftime'].includes(shownLive.match.status) ? shownLive.focus.match_mode
    : fixtureSet?.live.length ? 'live' : hasUpcoming ? 'scheduled' : shownLive.match?.status === 'fulltime' ? 'fulltime' : shownLive.focus.match_mode
  const degraded = shownHealth?.status === 'degraded' || shownConnection === 'DEGRADED'
  const dominantPriority = shownLive.dominant_focus?.priority ?? shownLive.focus.score
  const spotifyPlayback = shownSurfaces.spotify.value?.playback
  const visualMotion = useVisualMotion({
    eventArrival: shownEventArrival,
    matchMode,
    focusKey: [shownLive.focus.reason, shownLive.focus.source, shownLive.focus.subject_id, shownLive.focus.score].join('|'),
    connection: shownConnection,
    healthStatus: shownHealth?.status ?? null,
    weatherKey: selectedWeatherLocation ? [selectedWeatherLocation.id, weather?.category ?? '', dayPhase].join('|') : '',
    spotifyTrackId: spotifyPlayback?.item_id ?? null,
    spotifyPlaying: spotifyPlayback?.is_playing ?? null,
  })
  const currentVisualEvent = visualMotion.current
  const timelineItems = timelineHistory || view === 'timeline' ? shownTimeline : shownTimeline.slice(0, 6)
  const environmentalState = useMemo(() => ({
    mode: matchMode,
    degraded,
    focused,
    attention: dominantPriority,
    connection: shownConnection,
    eventType: shownEventArrival && shownEventArrival.event_id === currentVisualEvent?.id ? shownEventArrival.event_type : null,
    weather: weatherAtmosphere(weather?.category),
    spotifyPlaying: shownSurfaces.spotify.value?.playback?.is_playing ?? false,
  }), [matchMode, degraded, focused, dominantPriority, shownConnection, shownEventArrival, currentVisualEvent?.id, weather?.category, shownSurfaces.spotify.value?.playback?.is_playing])

  if (!hasBeenReadyOnce && requestState !== 'available') {
    return <RuntimeStartup state={requestState} onRetry={() => { void refreshHealth() }} />
  }

  const navigate = (next: AppView) => {
    setGmailExpanded(false)
    setView(next)
    if (next === 'settings') window.dispatchEvent(new Event('livepulse:open-health'))
  }
  const showMatch = () => { navigate('home'); requestAnimationFrame(() => document.querySelector('.match-stage')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' })) }
  const showGmail = () => { navigate('home'); setGmailExpanded(true); requestAnimationFrame(() => document.querySelector('#gmail')?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' })) }
  const showHealth = () => { navigate('settings'); window.dispatchEvent(new Event('livepulse:open-health')) }
  const moveMatch = (direction: 'next' | 'previous') => {
    if (view !== 'home') navigate('home')
    window.setTimeout(() => window.dispatchEvent(new Event(`livepulse:match-${direction}`)), 0)
  }

  return <main className={`livepulse-app${wake ? ' is-waking' : ''}${focused ? ' is-focused' : ''}`} data-match-mode={matchMode} data-focus-domain={shownLive.dominant_focus?.domain ?? shownLive.focus.source} data-motion-event={currentVisualEvent?.name.toLowerCase().replaceAll('_', '-') ?? undefined} data-motion-intensity={currentVisualEvent?.intensity ?? undefined} data-view={view} data-time-of-day={dayPhase} data-backend-state={requestState}>
    <SpatialEnvironment {...environmentalState} reducedMotion={Boolean(reducedMotion)} timeOfDay={dayPhase} eventName={currentVisualEvent?.name ?? null} eventIntensity={currentVisualEvent?.intensity ?? null} />
    <div className="app-shell">
      <nav className="navigation-rail" aria-label="Main navigation">
        <button className="nav-brand-mark" type="button" aria-label="LivePulse home" onClick={() => navigate('home')}><Waves size={22} aria-hidden="true" /></button>
        <div className="nav-items">{navigation.map(({ id, label, icon: Icon }) => <button className={`nav-item${view === id ? ' is-active' : ''}`} type="button" key={id} aria-label={label} aria-current={view === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={19} strokeWidth={1.7} aria-hidden="true" /><span>{label}</span></button>)}</div>
        <span className="nav-rail-bottom" aria-hidden="true"><i /></span>
      </nav>
      <div className="app-content" id="workspace">
        <AmbientHeader
          health={shownHealth}
          requestState={requestState}
          connection={shownConnection}
          weather={shownSurfaces.weather}
          onToggleFullscreen={() => void requestFullscreen()}
          weatherLocation={weatherLocation.state}
          weatherLocationLoading={weatherLocation.loading}
          weatherSearchResults={weatherLocation.searchResults}
          weatherSearching={weatherLocation.searching}
          weatherSelecting={weatherLocation.selecting}
          weatherLocationError={weatherLocation.error}
          onWeatherSearch={weatherLocation.search}
          onWeatherSelect={weatherLocation.select}
        />
        <section className="workspace-intro" aria-label="LivePulse status">
          <div className="intro-copy"><span className="intro-eyebrow"><span className="intro-pulse" />{focusLabel ?? (shownLive.dominant_focus ? `CURRENT SIGNAL · ${shownLive.dominant_focus.domain.toUpperCase()}` : 'PERSONAL OPERATIONS')}</span></div>
          <div className="intro-right"><strong><Radio size={15} aria-hidden="true" />{shownConnection === 'LIVE' ? 'Realtime connected' : shownConnection === 'RESYNCING' ? 'Reconciling recent state' : shownConnection === 'RECONNECTING' ? 'Realtime reconnecting' : shownConnection === 'DEGRADED' ? 'Realtime unavailable' : 'Establishing realtime'}</strong></div>
        </section>

        {view === 'home' && <section className="dashboard-composition" aria-label="LivePulse overview">
          <div className="dashboard-main-row">
            <MatchStage live={shownLive} fixtures={fixtureSet} fixtureLoading={shownSurfaces.football.loading} fixtureAvailable={shownSurfaces.football.available} timeline={shownTimeline} eventArrival={shownEventArrival} />
            <div className="inbox-focus-rail">
              <GmailPanel provider={shownHealth?.providers?.gmail} expanded={gmailExpanded} showAll={gmailExpanded} onViewAll={() => setGmailExpanded((value) => !value)} onCloseAll={() => setGmailExpanded(false)} snapshotOverride={shownSurfaces.gmail} />
              <FocusTimer snapshotOverride={visualFixture?.focusTimer} />
            </div>
            <aside className="timeline-environment" aria-label="Recent signals">
              <div className="surface-heading timeline-heading"><span className="surface-icon timeline-icon"><Activity size={16} aria-hidden="true" /></span><div><span className="surface-overline">EVENT CHRONOLOGY</span><h2>Recent signals</h2></div><span className={`timeline-live timeline-${shownConnection.toLowerCase()}`}><i />{shownConnection === 'LIVE' ? 'LIVE' : shownConnection}</span></div>
              <PulseTimeline items={timelineItems} arrivalId={shownEventArrival?.event_id ?? null} hasOlder={hasOlder} loadingOlder={loadingOlder} onLoadOlder={() => { setTimelineHistory(true); void loadOlder() }} onRefresh={() => { void refresh() }} />
              <button className="panel-view-all" type="button" onClick={() => { setTimelineHistory(true); navigate('timeline') }}>View all signals <span>→</span></button>
            </aside>
          </div>
          <div className="dashboard-lower-row">
            <SpotifyCapsule snapshot={shownSurfaces.spotify} provider={shownHealth?.providers?.spotify} />
            <QuickLaunch onOpen={() => setPaletteOpen(true)} onGoHome={() => navigate('home')} onConfigure={() => navigate('settings')} />
          </div>
        </section>}

        {view === 'timeline' && <section className="page-surface timeline-page"><header className="page-title"><span className="surface-overline">UNIVERSAL EVENT HISTORY</span><h2>Pulse Timeline</h2><p>Provider events arranged by observed time, with source and freshness preserved.</p></header><PulseTimeline items={shownTimeline} arrivalId={shownEventArrival?.event_id ?? null} hasOlder={hasOlder} loadingOlder={loadingOlder} onLoadOlder={() => void loadOlder()} onRefresh={() => { void refresh() }} /></section>}

        {view === 'focus' && <section className="page-surface focus-page"><header className="page-title"><span className="surface-overline">ATTENTION POSTURE</span><h2>Focus</h2><p>A deterministic quiet window. Critical match events and system alerts continue to surface.</p></header><FocusTimer snapshotOverride={visualFixture?.focusTimer} /><div className="focus-principles"><span><i /> Peripheral surfaces recede</span><span><i /> Critical events remain visible</span><span><i /> Spotify controls stay available</span></div><button className="text-action" type="button" onClick={() => navigate('home')}>Return to Home →</button></section>}

        {view === 'settings' && <section className="page-surface settings-page"><header className="page-title"><span className="surface-overline">LOCAL RUNTIME</span><h2>System & providers</h2><p>LivePulse runs against the local backend. Provider freshness is reported from observed state.</p></header><div className="settings-toolbar"><span className={`backend-indicator backend-${requestState}`}><i />{requestState === 'available' ? 'Backend ready' : requestState === 'checking' || requestState === 'starting' ? 'Backend starting' : 'Backend unavailable'}</span><button className="text-action" type="button" onClick={() => void refreshHealth()}>Check again <span>↻</span></button><button className="text-action" type="button" onClick={() => void requestFullscreen()}>Toggle fullscreen <span>⛶</span></button></div><div className="settings-grid"><GmailPanel provider={shownHealth?.providers?.gmail} expanded showAll={gmailExpanded} snapshotOverride={shownSurfaces.gmail} onViewAll={() => setGmailExpanded((value) => !value)} onCloseAll={() => setGmailExpanded(false)} /><LaunchDestinationSettings /></div><p className="settings-note">OAuth credentials remain in the local backend. Gmail dashboard reads return bounded metadata only; message bodies are not stored.</p></section>}

        <footer className="environment-footer"><span className="footer-signature"><i /> LIVEPULSE <span>PERSONAL LOCAL</span></span><span className="footer-hint">LOCAL BACKEND · REALTIME {shownConnection}</span>{import.meta.env.DEV && <label className="visual-fixture-select">VISUAL CALIBRATION<select value={visualName} onChange={(event) => void applyVisualFixture(event.target.value as 'real' | VisualFixtureName)} aria-label="Select development visual state"><option value="real">Real provider state</option><option value="idle">Normal / idle</option><option value="spotify-playing">Spotify playing</option><option value="upcoming">Upcoming match</option><option value="live">Live match</option><option value="goal">Goal event</option><option value="degraded">Provider degraded</option><option value="focus">Focus timer active</option></select></label>}<button className="footer-health" type="button" onClick={showHealth}><span className={`footer-health-mark health-${shownHealth?.status ?? requestState}`} />System Pulse</button></footer>
      </div>
    </div>
    {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} onNavigate={navigate} onOpenGmail={showGmail} onShowMatch={showMatch} onShowHealth={showHealth} onNextMatch={() => moveMatch('next')} onPreviousMatch={() => moveMatch('previous')} />}
  </main>
}
