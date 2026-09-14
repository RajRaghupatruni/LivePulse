import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getBackendReadiness, getSystemHealth } from '../lib/api'
import type { SystemHealth } from '../types/livepulse'
import { useSystemHealth } from './useSystemHealth'

vi.mock('../lib/api', () => ({ getBackendReadiness: vi.fn(), getSystemHealth: vi.fn() }))

describe('backend readiness presentation', () => {
  afterEach(() => {
    delete window.livePulsePlatform
    vi.useRealTimers()
    vi.mocked(getBackendReadiness).mockReset()
    vi.mocked(getSystemHealth).mockReset()
  })

  it('shows startup briefly, then reports an unavailable browser backend after repeated failure', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-13T12:00:00Z'))
    vi.mocked(getBackendReadiness).mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useSystemHealth())

    await act(async () => { await Promise.resolve() })
    expect(result.current.requestState).toBe('starting')

    vi.setSystemTime(new Date('2026-09-13T12:00:16Z'))
    await act(async () => { await result.current.refresh() })
    expect(result.current.requestState).toBe('unavailable')
  })

  it('uses the shell lifecycle snapshot and follows shell readiness changes', async () => {
    vi.mocked(getBackendReadiness).mockRejectedValue(new Error('not ready'))
    let onLifecycle: ((state: 'starting' | 'ready' | 'unavailable') => void) | undefined
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8111',
      websocketBaseUrl: 'ws://127.0.0.1:8111',
      getBackendLifecycle: () => 'starting',
      subscribeBackendLifecycle: (listener) => { onLifecycle = listener; return () => { onLifecycle = undefined } },
    }
    const { result } = renderHook(() => useSystemHealth())

    await act(async () => { await Promise.resolve() })
    expect(result.current.requestState).toBe('starting')

    act(() => onLifecycle?.('unavailable'))
    expect(result.current.requestState).toBe('unavailable')
    act(() => onLifecycle?.('ready'))
    expect(result.current.requestState).toBe('available')
  })

  it('marks an observed backend ready and reports a later outage truthfully', async () => {
    vi.mocked(getBackendReadiness)
      .mockResolvedValueOnce({ status: 'ready' })
      .mockRejectedValueOnce(new Error('offline'))
    vi.mocked(getSystemHealth)
      .mockResolvedValueOnce({} as SystemHealth)
      .mockRejectedValueOnce(new Error('offline'))
    const { result } = renderHook(() => useSystemHealth())

    await act(async () => { await Promise.resolve() })
    expect(result.current.requestState).toBe('available')
    await act(async () => { await result.current.refresh() })
    expect(result.current.requestState).toBe('unavailable')
  })

  it('recovers from unavailable to ready only after a successful readiness probe', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-13T12:00:00Z'))
    vi.mocked(getBackendReadiness)
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ status: 'ready' })
    vi.mocked(getSystemHealth).mockResolvedValue({} as SystemHealth)
    const { result } = renderHook(() => useSystemHealth())

    await act(async () => { await Promise.resolve() })
    expect(result.current.requestState).toBe('starting')
    vi.setSystemTime(new Date('2026-09-13T12:00:16Z'))
    await act(async () => { await result.current.refresh() })
    expect(result.current.requestState).toBe('unavailable')
    expect(result.current.hasBeenReadyOnce).toBe(false)
    expect(getSystemHealth).not.toHaveBeenCalled()

    await act(async () => { await result.current.refresh() })
    expect(result.current.requestState).toBe('available')
    expect(result.current.hasBeenReadyOnce).toBe(true)
    expect(getSystemHealth).toHaveBeenCalledOnce()
  })

  it('does not show ready when a shell-ready backend cannot answer health requests', async () => {
    window.livePulsePlatform = { kind: 'desktop', apiBaseUrl: 'http://127.0.0.1:8111', websocketBaseUrl: 'ws://127.0.0.1:8111', getBackendLifecycle: () => 'ready' }
    vi.mocked(getBackendReadiness).mockRejectedValue(new Error('sidecar endpoint unavailable'))
    vi.mocked(getSystemHealth).mockRejectedValue(new Error('sidecar endpoint unavailable'))
    const { result } = renderHook(() => useSystemHealth())

    await act(async () => { await Promise.resolve() })
    expect(result.current.requestState).toBe('unavailable')
  })
})
