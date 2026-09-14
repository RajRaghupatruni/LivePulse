import { useCallback, useEffect, useRef, useState } from 'react'
import type { ProviderConnection } from '../lib/api'
import { beginAuthorization, isDesktopShell } from '../lib/platform'

export type AuthorizationPhase = 'idle' | 'waiting' | 'connected' | 'error' | 'timeout'

const POLL_INTERVAL_MS = 3_000
const AUTHORIZATION_TIMEOUT_MS = 3 * 60_000
const CONNECTION_REQUEST_TIMEOUT_MS = 5_000

export function useProviderAuthorization() {
  const [phase, setPhase] = useState<AuthorizationPhase>('idle')
  const generation = useRef(0)
  const timer = useRef<number | undefined>(undefined)
  const requestTimeout = useRef<number | undefined>(undefined)
  const requestController = useRef<AbortController | undefined>(undefined)
  const active = useRef(false)

  const stop = useCallback(() => {
    active.current = false
    if (timer.current !== undefined) window.clearTimeout(timer.current)
    if (requestTimeout.current !== undefined) window.clearTimeout(requestTimeout.current)
    requestController.current?.abort()
    requestController.current = undefined
    requestTimeout.current = undefined
    timer.current = undefined
  }, [])

  const start = useCallback(async (
    path: string,
    getConnection: (signal?: AbortSignal) => Promise<ProviderConnection>,
    onConnected: () => void | Promise<void>,
  ) => {
    if (!isDesktopShell()) {
      await beginAuthorization(path)
      return
    }
    if (active.current) return
    stop()
    const currentGeneration = ++generation.current
    const stillCurrent = () => currentGeneration === generation.current && active.current
    const loadConnection = async () => {
      const controller = new AbortController()
      requestController.current = controller
      requestTimeout.current = window.setTimeout(
        () => controller.abort(),
        CONNECTION_REQUEST_TIMEOUT_MS,
      )
      try {
        return await getConnection(controller.signal)
      } finally {
        if (requestController.current === controller) requestController.current = undefined
        if (requestTimeout.current !== undefined) window.clearTimeout(requestTimeout.current)
        requestTimeout.current = undefined
      }
    }
    const connected = async () => {
      if (!stillCurrent()) return
      stop()
      setPhase('connected')
      window.dispatchEvent(new CustomEvent('livepulse:refresh-provider-health'))
      try { await onConnected() } catch { /* Connection succeeded; a view refresh can retry. */ }
    }

    active.current = true
    setPhase('waiting')
    // Avoid opening a second authorization window if the visible health snapshot was stale.
    try {
      const current = await loadConnection()
      if (!stillCurrent()) return
      if (current.connected) {
        await connected()
        return
      }
    } catch {
      if (!stillCurrent()) return
      // Continue to the system browser; the bounded waiter reports transient failures.
    }
    if (!stillCurrent()) return

    try {
      await beginAuthorization(path)
    } catch {
      if (stillCurrent()) {
        stop()
        setPhase('error')
      }
      return
    }
    if (!stillCurrent()) return

    const deadline = Date.now() + AUTHORIZATION_TIMEOUT_MS
    const poll = async () => {
      if (!stillCurrent()) return
      if (Date.now() >= deadline) {
        stop()
        setPhase('timeout')
        return
      }
      try {
        if ((await loadConnection()).connected) {
          await connected()
          return
        }
      } catch { /* A transient backend failure is retried until the deadline. */ }
      if (stillCurrent()) timer.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS)
    }
    await poll()
  }, [stop])

  useEffect(() => () => {
    generation.current += 1
    stop()
  }, [stop])

  const message = phase === 'waiting'
    ? 'Connecting… Complete authorization in your browser.'
    : phase === 'connected'
      ? 'Connected'
      : phase === 'timeout'
        ? 'Authorization timed out. Retry the connection.'
        : phase === 'error'
          ? 'Could not open the system browser. Retry the connection.'
          : ''

  return { phase, message, start }
}
