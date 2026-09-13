import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { SurfaceSnapshot } from '../../hooks/useProviderSurfaces'
import type { WeatherLocation, WeatherSnapshot } from '../../types/livepulse'
import { WeatherLocationControl } from './WeatherLocationControl'

const celina: WeatherLocation = {
  id: 'celina-id',
  display_name: 'Celina, Texas, United States',
  city: 'Celina',
  region: 'Texas',
  country: 'United States',
  latitude: 33.3246,
  longitude: -96.7844,
  timezone: 'America/Chicago',
  selected_at: null,
  last_used_at: null,
}

const weather: SurfaceSnapshot<WeatherSnapshot> = {
  value: null,
  loading: false,
  available: true,
}

function renderControl(overrides: Partial<React.ComponentProps<typeof WeatherLocationControl>> = {}) {
  const onSelect = vi.fn(async () => true)
  const onSearch = vi.fn()
  const props: React.ComponentProps<typeof WeatherLocationControl> = {
    weather,
    selected: celina,
    recent: [celina],
    loading: false,
    searchResults: [],
    searching: false,
    selecting: false,
    error: null,
    onSearch,
    onSelect,
    ...overrides,
  }
  return { ...render(<WeatherLocationControl {...props} />), onSelect, onSearch }
}

describe('weather location control', () => {
  it('shows the selected physical place and never substitutes its timezone as the city', () => {
    renderControl()
    const trigger = screen.getByRole('button', { name: /weather in celina, texas, united states/i })
    expect(trigger).toHaveTextContent('Celina, Texas')
    expect(trigger).not.toHaveAccessibleName(/America\/Chicago|Chicago/)
  })

  it('selects a normalized search result and exposes useful local place metadata', async () => {
    const user = userEvent.setup()
    const view = renderControl()
    await user.click(screen.getByRole('button', { name: /weather in celina/i }))
    const input = screen.getByRole('textbox', { name: 'Search weather locations' })
    fireEvent.change(input, { target: { value: 'New York' } })
    expect(view.onSearch).toHaveBeenLastCalledWith('New York')
    view.rerender(<WeatherLocationControl
      weather={weather}
      selected={celina}
      recent={[celina]}
      loading={false}
      searchResults={[{ ...celina, id: 'new-york', city: 'New York', region: 'New York', display_name: 'New York, New York, United States', timezone: 'America/New_York' }]}
      searching={false}
      selecting={false}
      error={null}
      onSearch={view.onSearch}
      onSelect={view.onSelect}
    />)
    expect(screen.getByText('United States · America/New_York')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /New York, New York/i }))
    await waitFor(() => expect(view.onSelect).toHaveBeenCalledWith(expect.objectContaining({ city: 'New York' })))
    expect(screen.queryByRole('dialog', { name: 'Choose weather location' })).not.toBeInTheDocument()
  })

  it('keeps the current conditions visible when a search fails', async () => {
    const snapshot: WeatherSnapshot = {
      location: celina,
      recent_locations: [celina],
      current: {
        observed_at: '2026-09-13T12:00:00Z',
        local_time: '2026-09-13T07:00:00-05:00',
        timezone: celina.timezone,
        temperature_f: 71,
        apparent_temperature_f: 70,
        weather_code: 0,
        category: 'clear',
        description: 'Clear',
        precipitation_in: 0,
        wind_speed_mph: 3,
        high_f: 76,
        low_f: 59,
        precipitation_probability_max_pct: 0,
      },
      fetched_at: '2026-09-13T12:00:00Z',
      health: {} as WeatherSnapshot['health'],
    }
    const user = userEvent.setup()
    renderControl({ weather: { value: snapshot, loading: false, available: true }, error: 'Location search is temporarily unavailable.' })
    expect(screen.getByText('71°')).toBeInTheDocument()
    expect(screen.getByText('Clear')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /weather in celina/i }))
    expect(screen.getByText('Location search is temporarily unavailable.')).toBeInTheDocument()
  })
})
