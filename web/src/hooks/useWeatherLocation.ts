import { useCallback, useEffect, useRef, useState } from 'react'
import { getWeatherLocationState, searchWeatherLocations, selectWeatherLocation } from '../lib/api'
import type { WeatherLocation, WeatherLocationState } from '../types/livepulse'

const EMPTY_STATE: WeatherLocationState = { selected: null, recent: [] }

export function useWeatherLocation(enabled: boolean) {
  const [state, setState] = useState<WeatherLocationState>(EMPTY_STATE)
  const [loading, setLoading] = useState(enabled)
  const [searchResults, setSearchResults] = useState<WeatherLocation[]>([])
  const [searching, setSearching] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const controller = useRef<AbortController | null>(null)

  const reload = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    try {
      setState(await getWeatherLocationState())
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Weather location is unavailable.')
    } finally {
      setLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) {
      setState(EMPTY_STATE)
      setLoading(false)
      return
    }
    void reload()
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
      controller.current?.abort()
    }
  }, [enabled, reload])

  const search = useCallback((rawQuery: string) => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    controller.current?.abort()
    const query = rawQuery.trim()
    setError(null)
    if (query.length < 2) {
      setSearchResults([])
      setSearching(false)
      return
    }
    setSearchResults([])
    setSearching(true)
    timer.current = window.setTimeout(() => {
      const nextController = new AbortController()
      controller.current = nextController
      void searchWeatherLocations(query, nextController.signal).then(({ results }) => {
        if (!nextController.signal.aborted) setSearchResults(results)
      }).catch((cause: unknown) => {
        if (!nextController.signal.aborted) {
          setSearchResults([])
          setError(cause instanceof Error ? cause.message : 'Location search is unavailable.')
        }
      }).finally(() => {
        if (!nextController.signal.aborted) setSearching(false)
      })
    }, 350)
  }, [])

  const select = useCallback(async (location: WeatherLocation) => {
    const previous = state
    setSelecting(true)
    setError(null)
    setState({
      selected: location,
      recent: [location, ...previous.recent.filter((item) => item.id !== location.id)].slice(0, 5),
    })
    try {
      setState(await selectWeatherLocation(location))
      window.dispatchEvent(new CustomEvent('livepulse:refresh-provider-surfaces', { detail: 'weather' }))
      return true
    } catch (cause) {
      setState(previous)
      setError(cause instanceof Error ? cause.message : 'Could not save this location.')
      return false
    } finally {
      setSelecting(false)
    }
  }, [state])

  return { state, loading, searchResults, searching, selecting, error, search, select, reload }
}
