import { useEffect, useState } from 'react'
import { Cloud, CloudFog, CloudLightning, CloudRain, CloudSnow, Sun, Moon, Wind, Expand } from 'lucide-react'
import type { SystemHealth } from '../../types/livepulse'
import type { SurfaceSnapshot } from '../../hooks/useProviderSurfaces'
import type { WeatherSnapshot } from '../../types/livepulse'
import { SystemPulse } from '../system/SystemPulse'
import type { ConnectionState } from '../../hooks/useLivePulse'
import type { HealthRequestState } from '../../hooks/useSystemHealth'

function useLocalClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const update = () => setNow(new Date())
    const timer = window.setInterval(update, 1000)
    document.addEventListener('visibilitychange', update)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', update)
    }
  }, [])
  return now
}

function WeatherGlyph({ category }: { category: string }) {
  const props = { size: 31, strokeWidth: 1.55, 'aria-hidden': true as const }
  if (category === 'rain' || category === 'drizzle') return <CloudRain {...props} />
  if (category === 'snow') return <CloudSnow {...props} />
  if (category === 'fog') return <CloudFog {...props} />
  if (category === 'thunderstorm') return <CloudLightning {...props} />
  if (category === 'clear') return <Sun {...props} />
  if (category === 'night') return <Moon {...props} />
  if (category === 'wind') return <Wind {...props} />
  return <Cloud {...props} />
}

function weatherRegion(timezone: string) {
  const region = timezone.split('/').at(-1)?.replaceAll('_', ' ')
  return region || timezone
}

export function AmbientHeader({ health, requestState, connection, weather, onToggleFullscreen }: {
  health: SystemHealth | null
  requestState: HealthRequestState
  connection: ConnectionState
  weather: SurfaceSnapshot<WeatherSnapshot>
  onToggleFullscreen: () => void
}) {
  const now = useLocalClock()
  const conditions = weather.value?.current
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const weatherZoneDiffers = Boolean(conditions?.timezone && conditions.timezone !== localTimezone)
  const weatherText = weather.loading ? 'Weather · checking'
      : !weather.available && !weather.value ? 'Weather unavailable'
        : !conditions ? 'Weather not configured'
          : conditions.description

  return <header className="command-header">
    <a className="livepulse-brand" href="#workspace" aria-label="LivePulse home">
      <span className="brand-glyph" aria-hidden="true"><i /><i /><i /><b /></span>
      <span className="brand-lockup"><span className="brand-word">Live<span>Pulse</span></span><span className="brand-tagline">Your world, in signal.</span></span>
    </a>
    <span className="header-separator" aria-hidden="true" />
    <div className="ambient-clock" aria-label={`Local time ${now.toLocaleString()}`}>
      <strong>{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}</strong>
      <span>{now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}</span>
    </div>
    <div className={`weather-context${weatherZoneDiffers ? ' weather-zone-differs' : ''}`} aria-label={conditions ? `${weatherText}, ${Math.round(conditions.temperature_f)} degrees Fahrenheit, ${weatherRegion(conditions.timezone)}${weatherZoneDiffers ? ` weather timezone ${conditions.timezone}` : ''}` : weatherText}>
      {conditions ? <WeatherGlyph category={conditions.category} /> : <span className="weather-placeholder" aria-hidden="true" />}
      <span className="weather-copy"><strong className={conditions ? 'weather-reading' : undefined}>{conditions ? `${Math.round(conditions.temperature_f)}°` : weatherText}</strong><small>{conditions ? weatherText : 'Current conditions'}</small>{conditions && <small className="weather-range">H: {Math.round(conditions.high_f)}° · L: {Math.round(conditions.low_f)}°</small>}</span>
      {conditions && <span className="weather-zone-label">{weatherRegion(conditions.timezone)}</span>}
    </div>
    <div className="header-spacer" />
    <SystemPulse health={health} requestState={requestState} connection={connection} />
    <button className="fullscreen-toggle" type="button" onClick={onToggleFullscreen} aria-label="Toggle fullscreen" title="Toggle fullscreen"><Expand size={17} aria-hidden="true" /></button>
  </header>
}
