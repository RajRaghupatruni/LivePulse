import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProviderConnection } from '../lib/api'
import { useProviderAuthorization } from './useProviderAuthorization'

const disconnected: ProviderConnection = { provider: 'spotify', connected: false, status: 'disconnected' }
const connected: ProviderConnection = { provider: 'spotify', connected: true, status: 'connected' }

describe('desktop provider authorization', () => {
  afterEach(() => {
    vi.useRealTimers()
    delete window.livePulsePlatform
  })

  it('waits for connection, refreshes provider views, and stops after success', async () => {
    const openSystemBrowser = vi.fn().mockResolvedValue(undefined)
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8000',
      websocketBaseUrl: 'ws://127.0.0.1:8000',
      beginAuthorization: openSystemBrowser,
    }
    const getConnection = vi.fn()
      .mockResolvedValueOnce(disconnected)
      .mockResolvedValueOnce(connected)
    const onConnected = vi.fn()
    const healthRefresh = vi.fn()
    window.addEventListener('livepulse:refresh-provider-health', healthRefresh)
    const { result } = renderHook(() => useProviderAuthorization())

    await act(async () => {
      await result.current.start('/api/v1/providers/spotify/oauth/start', getConnection, onConnected)
    })

    expect(openSystemBrowser).toHaveBeenCalledWith('/api/v1/providers/spotify/oauth/start')
    expect(result.current.phase).toBe('connected')
    expect(result.current.message).toBe('Connected')
    expect(getConnection).toHaveBeenCalledTimes(2)
    expect(onConnected).toHaveBeenCalledOnce()
    expect(healthRefresh).toHaveBeenCalledOnce()
    window.removeEventListener('livepulse:refresh-provider-health', healthRefresh)
  })

  it('does not open a second authorization window when the provider is already connected', async () => {
    const openSystemBrowser = vi.fn()
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8000',
      websocketBaseUrl: 'ws://127.0.0.1:8000',
      beginAuthorization: openSystemBrowser,
    }
    const getConnection = vi.fn().mockResolvedValue(connected)
    const onConnected = vi.fn()
    const { result } = renderHook(() => useProviderAuthorization())

    await act(async () => {
      await result.current.start('/api/v1/providers/gmail/oauth/start', getConnection, onConnected)
    })

    expect(openSystemBrowser).not.toHaveBeenCalled()
    expect(getConnection).toHaveBeenCalledOnce()
    expect(onConnected).toHaveBeenCalledOnce()
    expect(result.current.phase).toBe('connected')
  })

  it('times out with a retry state and cleans its timer on unmount', async () => {
    vi.useFakeTimers()
    const openSystemBrowser = vi.fn().mockResolvedValue(undefined)
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8000',
      websocketBaseUrl: 'ws://127.0.0.1:8000',
      beginAuthorization: openSystemBrowser,
    }
    const getConnection = vi.fn().mockResolvedValue(disconnected)
    const { result, unmount } = renderHook(() => useProviderAuthorization())

    await act(async () => {
      await result.current.start('/api/v1/providers/gmail/oauth/start', getConnection, vi.fn())
    })
    await act(async () => {
      await result.current.start('/api/v1/providers/gmail/oauth/start', getConnection, vi.fn())
    })
    expect(result.current.phase).toBe('waiting')
    expect(result.current.message).toContain('Complete authorization in your browser')
    expect(openSystemBrowser).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(180_000) })
    expect(result.current.phase).toBe('timeout')
    expect(result.current.message).toContain('Retry the connection')
    expect(vi.getTimerCount()).toBe(0)

    await act(async () => {
      await result.current.start('/api/v1/providers/gmail/oauth/start', getConnection, vi.fn())
    })
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps browser-development authorization as a normal frontend redirect', async () => {
    const navigateToAuthorization = vi.fn().mockResolvedValue(undefined)
    window.livePulsePlatform = { kind: 'browser', beginAuthorization: navigateToAuthorization }
    const getConnection = vi.fn()
    const onConnected = vi.fn()
    const { result } = renderHook(() => useProviderAuthorization())

    await act(async () => {
      await result.current.start('/api/v1/providers/gmail/oauth/start', getConnection, onConnected)
    })

    expect(navigateToAuthorization).toHaveBeenCalledWith('/api/v1/providers/gmail/oauth/start')
    expect(getConnection).not.toHaveBeenCalled()
    expect(onConnected).not.toHaveBeenCalled()
    expect(result.current.phase).toBe('idle')
  })
})
