import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { atmosphereBudget, environmentFrameLoop, initialPerformanceProfile, nextPerformanceProfile, type PerformanceProfile } from './performanceProfile'

const WorldCanvas = lazy(() => import('./WorldCanvas').then((module) => ({ default: module.WorldCanvas })))

type Props = {
  mode: string
  degraded: boolean
  focused: boolean
  reducedMotion: boolean
  weather?: string
  connection?: string
  attention?: number
  spotifyPlaying?: boolean
  eventType?: string | null
  eventName?: string | null
  eventIntensity?: 'subtle' | 'moderate' | 'strong' | null
  timeOfDay?: 'dawn' | 'day' | 'dusk' | 'night' | string
}

function isPortrait() {
  return window.matchMedia?.('(orientation: portrait)').matches ?? window.innerHeight > window.innerWidth
}

/** Existing bundled NYC image remains the primary world; one lazily loaded WebGL layer adds restrained depth. */
export function SpatialEnvironment({ mode, degraded, focused, reducedMotion, weather = '', connection = 'CONNECTING', attention = 0, spotifyPlaying = false, eventType = null, eventName = null, eventIntensity = null, timeOfDay = 'night' }: Props) {
  const posture = degraded ? 'degraded' : mode === 'live' || mode === 'halftime' || mode === 'highlight' ? 'match' : mode === 'scheduled' ? 'approach' : 'idle'
  const weatherTone = ['rain', 'drizzle', 'cloudy', 'overcast', 'clear', 'night', 'snow', 'fog', 'thunderstorm'].includes(weather.toLowerCase()) ? weather.toLowerCase() : ''
  const attentionBand = attention >= 95 ? 'critical' : attention >= 70 ? 'elevated' : attention >= 40 ? 'steady' : 'quiet'
  const eventTone = eventType === 'football.match.goal' || eventName === 'FOOTBALL_GOAL' ? 'goal' : eventType === 'football.match.red_card' ? 'red-card' : eventName === 'FOOTBALL_CARD' ? 'card' : ''
  const [portrait, setPortrait] = useState(isPortrait)
  const [profile, setProfile] = useState<PerformanceProfile>(() => initialPerformanceProfile(window.devicePixelRatio || 1, window.innerWidth, window.innerHeight))
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden')
  const updateProfile = useCallback((fps: number) => setProfile((current) => nextPerformanceProfile(current, fps)), [])

  useEffect(() => {
    const onResize = () => setPortrait(isPortrait())
    const onVisibility = () => setVisible(document.visibilityState !== 'hidden')
    window.addEventListener('resize', onResize, { passive: true })
    document.addEventListener('visibilitychange', onVisibility)
    return () => { window.removeEventListener('resize', onResize); document.removeEventListener('visibilitychange', onVisibility) }
  }, [])

  const budget = atmosphereBudget(profile, portrait, reducedMotion)
  const classNames = `environment environment-${posture} environment-focus-${attentionBand} environment-transport-${connection.toLowerCase()} environment-time-${timeOfDay}${eventTone ? ` environment-event-${eventTone}` : ''}${spotifyPlaying ? ' environment-media-active' : ''}${focused ? ' environment-focused' : ''}${reducedMotion ? ' environment-static' : ''}${weatherTone ? ` environment-weather-${weatherTone}` : ''} environment-quality-${profile.toLowerCase()}`
  const frameLoop = environmentFrameLoop(reducedMotion, visible)

  return <div className={classNames} data-quality={profile.toLowerCase()} data-motion-event={eventName?.toLowerCase().replaceAll('_', '-') ?? undefined} aria-hidden="true">
    <div className="environment-skyline" />
    <Suspense fallback={null}>
      <WorldCanvas count={budget.particleCount} dpr={budget.dpr} frameLoop={frameLoop} reducedMotion={reducedMotion} weather={weatherTone} degraded={degraded || connection === 'DEGRADED'} eventIntensity={eventIntensity} onProfileSample={updateProfile} />
    </Suspense>
    <div className="environment-atmosphere environment-atmosphere-far" />
    <div className="environment-atmosphere environment-atmosphere-near" />
    <div className="environment-horizon" />
    <div className="environment-vignette" />
  </div>
}
