import { useEffect, useState } from 'react'
import { Expand } from 'lucide-react'
import type { SystemHealth } from '../../types/livepulse'
import type { SurfaceSnapshot } from '../../hooks/useProviderSurfaces'
import type { WeatherLocation, WeatherLocationState, WeatherSnapshot } from '../../types/livepulse'
import { SystemPulse } from '../system/SystemPulse'
import { WeatherLocationControl } from './WeatherLocationControl'
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

export function AmbientHeader({
  health,
  requestState,
  connection,
  weather,
  onToggleFullscreen,
  weatherLocation,
  weatherLocationLoading,
  weatherSearchResults,
  weatherSearching,
  weatherSelecting,
  weatherLocationError,
  onWeatherSearch,
  onWeatherSelect,
}: {
  health: SystemHealth | null
  requestState: HealthRequestState
  connection: ConnectionState
  weather: SurfaceSnapshot<WeatherSnapshot>
  onToggleFullscreen: () => void
  weatherLocation: WeatherLocationState
  weatherLocationLoading: boolean
  weatherSearchResults: WeatherLocation[]
  weatherSearching: boolean
  weatherSelecting: boolean
  weatherLocationError: string | null
  onWeatherSearch: (query: string) => void
  onWeatherSelect: (location: WeatherLocation) => Promise<boolean>
}) {
  const now = useLocalClock()
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
    <WeatherLocationControl
      weather={weather}
      selected={weatherLocation.selected}
      recent={weatherLocation.recent}
      loading={weatherLocationLoading}
      searchResults={weatherSearchResults}
      searching={weatherSearching}
      selecting={weatherSelecting}
      error={weatherLocationError}
      onSearch={onWeatherSearch}
      onSelect={onWeatherSelect}
    />
    <div className="header-spacer" />
    <SystemPulse health={health} requestState={requestState} connection={connection} />
    <button className="fullscreen-toggle" type="button" onClick={onToggleFullscreen} aria-label="Toggle fullscreen" title="Toggle fullscreen"><Expand size={17} aria-hidden="true" /></button>
  </header>
}
