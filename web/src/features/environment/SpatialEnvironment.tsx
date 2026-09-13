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
  timeOfDay?: 'dawn' | 'day' | 'dusk' | 'night' | string
}

/** Static local skyline plane with semantic lighting; every important state stays in the DOM. */
export function SpatialEnvironment({ mode, degraded, focused, reducedMotion, weather = '', connection = 'CONNECTING', attention = 0, spotifyPlaying = false, eventType = null, timeOfDay = 'night' }: Props) {
  const posture = degraded ? 'degraded' : mode === 'live' || mode === 'halftime' || mode === 'highlight' ? 'match' : mode === 'scheduled' ? 'approach' : 'idle'
  const weatherTone = ['rain', 'drizzle', 'cloudy', 'overcast', 'clear', 'night', 'snow'].includes(weather.toLowerCase()) ? weather.toLowerCase() : ''
  const attentionBand = attention >= 95 ? 'critical' : attention >= 70 ? 'elevated' : attention >= 40 ? 'steady' : 'quiet'
  const eventTone = eventType === 'football.match.goal' ? 'goal' : eventType === 'football.match.red_card' ? 'red-card' : ''
  return <div className={`environment environment-${posture} environment-focus-${attentionBand} environment-transport-${connection.toLowerCase()} environment-time-${timeOfDay}${eventTone ? ` environment-event-${eventTone}` : ''}${spotifyPlaying ? ' environment-media-active' : ''}${focused ? ' environment-focused' : ''}${reducedMotion ? ' environment-static' : ''}${weatherTone ? ` environment-weather-${weatherTone}` : ''}`} aria-hidden="true">
    <div className="environment-skyline" />
    <div className="environment-atmosphere environment-atmosphere-far" />
    <div className="environment-atmosphere environment-atmosphere-near" />
    <div className="environment-horizon" />
    <div className="environment-vignette" />
  </div>
}
