import { useCallback, useEffect, useState } from 'react'
import { getSystemHealth } from '../lib/api'
import type { SystemHealth } from '../types/livepulse'

export type HealthRequestState = 'checking' | 'available' | 'unavailable'

export function useSystemHealth() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [requestState, setRequestState] = useState<HealthRequestState>('checking')

  const refresh = useCallback(async () => {
    try {
      setHealth(await getSystemHealth())
      setRequestState('available')
    } catch {
      setRequestState('unavailable')
    }
  }, [])

  useEffect(() => {
    let disposed = false
    let timer = 0
    let nextDelay = 15_000
    const poll = async () => {
      try {
        const next = await getSystemHealth()
        if (!disposed) {
          setHealth(next)
          setRequestState('available')
          nextDelay = next.status === 'unknown' ? 2_500 : 15_000
        }
      } catch {
        if (!disposed) {
          setRequestState('unavailable')
          nextDelay = 5_000
        }
      } finally {
        if (!disposed) timer = window.setTimeout(() => void poll(), nextDelay)
      }
    }
    void poll()
    return () => {
      disposed = true
      window.clearTimeout(timer)
    }
  }, [])

  return { health, requestState, refresh }
}
