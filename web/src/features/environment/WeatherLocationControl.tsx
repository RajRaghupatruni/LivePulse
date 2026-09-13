import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Cloud, CloudFog, CloudLightning, CloudRain, CloudSnow, MapPin, Search, Sun, X } from 'lucide-react'
import type { SurfaceSnapshot } from '../../hooks/useProviderSurfaces'
import type { WeatherLocation, WeatherSnapshot } from '../../types/livepulse'

function WeatherGlyph({ category }: { category: string }) {
  const props = { size: 27, strokeWidth: 1.55, 'aria-hidden': true as const }
  if (category === 'rain' || category === 'drizzle') return <CloudRain {...props} />
  if (category === 'snow') return <CloudSnow {...props} />
  if (category === 'fog') return <CloudFog {...props} />
  if (category === 'thunderstorm') return <CloudLightning {...props} />
  if (category === 'clear') return <Sun {...props} />
  return <Cloud {...props} />
}

function localTime(timezone: string) {
  try {
    return new Intl.DateTimeFormat([], {
      timeZone: timezone,
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    }).format(new Date())
  } catch {
    return null
  }
}

function locationLine(location: WeatherLocation) {
  return [location.city, location.region].filter(Boolean).join(', ')
}

export function WeatherLocationControl({
  weather,
  selected,
  recent,
  loading,
  searchResults,
  searching,
  selecting,
  error,
  onSearch,
  onSelect,
}: {
  weather: SurfaceSnapshot<WeatherSnapshot>
  selected: WeatherLocation | null
  recent: WeatherLocation[]
  loading: boolean
  searchResults: WeatherLocation[]
  searching: boolean
  selecting: boolean
  error: string | null
  onSearch: (query: string) => void
  onSelect: (location: WeatherLocation) => Promise<boolean>
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const conditionsMatch = !selected || weather.value?.location?.id === selected.id
  const conditions = conditionsMatch ? weather.value?.current : null
  const active = selected ?? weather.value?.location ?? null

  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [open])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])

  const choose = async (location: WeatherLocation) => {
    const saved = await onSelect(location)
    if (saved) {
      setQuery('')
      onSearch('')
      setOpen(false)
      triggerRef.current?.focus()
    }
  }

  return <div className="weather-location-control">
    <button
      ref={triggerRef}
      type="button"
      className="weather-context"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={active
        ? `Weather in ${active.display_name}${conditions ? `, ${Math.round(conditions.temperature_f)} degrees, ${conditions.description}` : ''}. Change location.`
        : 'Choose weather location'}
      onClick={() => setOpen((value) => !value)}
    >
      {conditions ? <WeatherGlyph category={conditions.category} /> : <span className="weather-placeholder" aria-hidden="true" />}
      <span className="weather-copy">
        <strong className={conditions ? 'weather-reading' : undefined}>
          {conditions ? `${Math.round(conditions.temperature_f)}°` : loading ? 'Weather · checking' : 'Choose location'}
        </strong>
        <small>{conditions?.description ?? (weather.available ? 'Current conditions' : 'Select a place')}</small>
        {conditions && <small className="weather-range">H: {Math.round(conditions.high_f)}° · L: {Math.round(conditions.low_f)}°</small>}
      </span>
      <span className="weather-place-label">{active ? locationLine(active) : 'Set weather location'}</span>
      <ChevronDown className="weather-chevron" size={13} aria-hidden="true" />
    </button>

    {open && <div className="weather-location-popover" role="dialog" aria-label="Choose weather location">
      <div className="weather-popover-heading">
        <span><MapPin size={14} aria-hidden="true" /> WEATHER LOCATION</span>
        <button type="button" className="weather-popover-close" onClick={() => { setOpen(false); triggerRef.current?.focus() }} aria-label="Close location selector"><X size={15} aria-hidden="true" /></button>
      </div>
      {active && <div className="weather-selected-place">
        <div><strong>{active.display_name}</strong><small>{active.country} · {active.timezone}</small></div>
        <span>{localTime(active.timezone) ?? 'Local time unavailable'}</span>
      </div>}
      <label className="weather-search">
        <Search size={15} aria-hidden="true" />
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => { setQuery(event.target.value); onSearch(event.target.value) }}
          placeholder="Search city, state, or country"
          aria-label="Search weather locations"
          autoComplete="off"
        />
        {query && <button type="button" aria-label="Clear location search" onClick={() => { setQuery(''); onSearch(''); inputRef.current?.focus() }}><X size={13} aria-hidden="true" /></button>}
      </label>
      {error && <p className="weather-search-error" role="status">{error}</p>}
      {query.trim().length >= 2 ? <div className="weather-location-list" aria-label="Search results">
        {searching && <p className="weather-location-message">Searching places…</p>}
        {!searching && searchResults.length === 0 && !error && <p className="weather-location-message">No matching places found.</p>}
        {searchResults.map((location) => <LocationOption key={location.id} location={location} selected={location.id === active?.id} disabled={selecting} onChoose={choose} />)}
      </div> : <>
        <div className="weather-list-title">RECENT PLACES</div>
        {recent.length ? <div className="weather-location-list" aria-label="Recent weather locations">
          {recent.map((location) => <LocationOption key={location.id} location={location} selected={location.id === active?.id} disabled={selecting} onChoose={choose} />)}
        </div> : <p className="weather-location-message">Search for a city to set your local weather.</p>}
      </>}
      {selecting && <p className="weather-location-message" role="status">Updating conditions for {active?.city ?? 'selected location'}…</p>}
      <div className="weather-attribution">Place names by Open-Meteo · OpenStreetMap contributors</div>
    </div>}
  </div>
}

function LocationOption({ location, selected, disabled, onChoose }: {
  location: WeatherLocation
  selected: boolean
  disabled: boolean
  onChoose: (location: WeatherLocation) => void | Promise<unknown>
}) {
  return <button
    className="weather-location-option"
    type="button"
    disabled={disabled}
    aria-current={selected ? 'true' : undefined}
    onClick={() => onChoose(location)}
  >
    <span className="weather-location-pin"><MapPin size={14} aria-hidden="true" /></span>
    <span><strong>{locationLine(location)}</strong><small>{location.country} · {location.timezone}</small></span>
    {selected && <Check size={15} aria-label="Selected" />}
  </button>
}
