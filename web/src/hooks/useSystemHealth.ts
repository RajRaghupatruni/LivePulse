import { useCallback, useEffect, useRef, useState } from 'react'
import { getBackendLifecycle, subscribeBackendLifecycle } from '../lib/platform'
import { getSystemHealth } from '../lib/api'
import type { SystemHealth } from '../types/livepulse'

export type HealthRequestState = 'checking' | 'starting' | 'available' | 'unavailable'

const STARTUP_GRACE_MS = 15_000
const READY_REFRESH_MS = 30_000
const UNREADY_RETRY_MS = 8_000

function requestStateForLifecycle(lifecycle: ReturnType<typeof getBackendLifecycle>): HealthRequestState | undefined {
  if (lifecycle === 'ready') return 'available'
  if (lifecycle === 'starting') return 'starting'
  if (lifecycle === 'unavailable') return 'unavailable'
  return undefined
}

export function useSystemHealth() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [requestState, setRequestState] = useState<HealthRequestState>(() => requestStateForLifecycle(getBackendLifecycle()) ?? 'checking')
  const startedAt = useRef(Date.now())
  const hasBeenReady = useRef(requestState === 'available')

  const refresh = useCallback(async () => {
    try {
      setHealth(await getSystemHealth())
      hasBeenReady.current = true
      setRequestState('available')
      return true
    } catch {
      const lifecycle = getBackendLifecycle()
      if (lifecycle === 'starting') setRequestState('starting')
      else if (lifecycle === 'ready' || lifecycle === 'unavailable') {
        // A shell lifecycle snapshot can establish that startup completed, but a
        // failed health request still means this UI cannot reach the backend.
        setRequestState('unavailable')
      } else {
        setRequestState((current) => hasBeenReady.current || current === 'available'
          ? 'unavailable'
          : Date.now() - startedAt.current < STARTUP_GRACE_MS ? 'starting' : 'unavailable')
      }
      return false
    }
  }, [])

  useEffect(() => {
    let disposed = false
    let timer = 0
    const poll = async () => {
      if (document.visibilityState === 'hidden') {
        timer = window.setTimeout(() => void poll(), READY_REFRESH_MS)
        return
      }
      const ready = await refresh()
      if (!disposed) timer = window.setTimeout(() => void poll(), ready ? READY_REFRESH_MS : UNREADY_RETRY_MS)
    }
    const scheduleNow = () => {
      window.clearTimeout(timer)
      void poll()
    }
    const unsubscribe = subscribeBackendLifecycle((lifecycle) => {
      const mapped = requestStateForLifecycle(lifecycle)
      if (!mapped) return
      if (mapped === 'available') hasBeenReady.current = true
      setRequestState(mapped)
      scheduleNow()
    })
    void poll()
    const onVisibility = () => {
      window.clearTimeout(timer)
      if (document.visibilityState === 'visible') void poll()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      disposed = true
      unsubscribe()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [refresh])

  return { health, requestState, refresh }
}
