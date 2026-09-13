import { useEffect, useState } from 'react'
import { getFootballFixtures, getSpotifyPlayback, getWeatherSnapshot } from '../lib/api'
import type { FootballFixtures, SpotifyPlaybackView, WeatherSnapshot } from '../types/livepulse'

export type SurfaceSnapshot<T> = { value: T | null; loading: boolean; available: boolean }

function useVisibleSnapshot<T>(enabled: boolean, provider: string, load: () => Promise<T>, intervalMs: number): SurfaceSnapshot<T> {
  const [state, setState] = useState<SurfaceSnapshot<T>>({ value: null, loading: enabled, available: false })

  useEffect(() => {
    if (!enabled) {
      let disposed = false
      Promise.resolve().then(() => { if (!disposed) setState({ value: null, loading: false, available: false }) })
      return () => { disposed = true }
    }
    let disposed = false
    let timer = 0
    let request: Promise<void> | null = null
    const poll = async () => {
      if (document.visibilityState === 'hidden') {
        timer = window.setTimeout(() => void poll(), intervalMs)
        return
      }
      if (!request) {
        request = load().then((value) => {
          if (!disposed) setState({ value, loading: false, available: true })
        }).catch(() => {
          if (!disposed) setState((current) => ({ ...current, loading: false, available: false }))
        }).finally(() => { request = null })
      }
      await request
      if (!disposed) timer = window.setTimeout(() => void poll(), intervalMs)
    }
    const onVisibility = () => {
      window.clearTimeout(timer)
      if (document.visibilityState === 'visible') void poll()
    }
    const onRefresh = (event: Event) => {
      const target = (event as CustomEvent<string | undefined>).detail
      if (target && target !== provider) return
      window.clearTimeout(timer)
      void poll()
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('livepulse:refresh-provider-surfaces', onRefresh)
    void poll()
    return () => {
      disposed = true
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('livepulse:refresh-provider-surfaces', onRefresh)
    }
  }, [enabled, provider, intervalMs, load])

  return state
}

const loadFixtures = () => getFootballFixtures()
const loadPlayback = () => getSpotifyPlayback()
const loadWeather = () => getWeatherSnapshot()

export function useProviderSurfaces(enabled: boolean) {
  const football = useVisibleSnapshot<FootballFixtures>(enabled, 'football', loadFixtures, 120_000)
  const spotify = useVisibleSnapshot<SpotifyPlaybackView>(enabled, 'spotify', loadPlayback, 15_000)
  const weather = useVisibleSnapshot<WeatherSnapshot>(enabled, 'weather', loadWeather, 20 * 60_000)
  return { football, spotify, weather }
}
