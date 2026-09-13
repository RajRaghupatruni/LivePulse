import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiUrl, beginAuthorization, consumeWakeSequence, externalTargetUrl, getBackendLifecycle, getPreference, isDesktopShell, openExternal, removePreference, requestFullscreen, setPreference, subscribeBackendLifecycle, websocketUrl } from './platform'

describe('platform boundary', () => {
  afterEach(() => { delete window.livePulsePlatform; vi.restoreAllMocks() })

  it('uses same-origin browser routes until a shell supplies a local API endpoint', () => {
    expect(isDesktopShell()).toBe(false)
    expect(apiUrl('/api/v1/live-state')).toBe('/api/v1/live-state')
    window.livePulsePlatform = { kind: 'desktop', apiBaseUrl: 'http://127.0.0.1:8111', websocketBaseUrl: 'ws://127.0.0.1:8111' }
    expect(isDesktopShell()).toBe(true)
    expect(apiUrl('/api/v1/live-state')).toBe('http://127.0.0.1:8111/api/v1/live-state')
  })

  it('centralizes WebSocket address selection for browser and desktop runtime config', () => {
    expect(websocketUrl('/ws?last_cursor=4')).toContain('/ws?last_cursor=4')
    window.livePulsePlatform = { kind: 'desktop', apiBaseUrl: 'http://127.0.0.1:8111', websocketBaseUrl: 'ws://127.0.0.1:8111' }
    expect(websocketUrl('/ws?last_cursor=4')).toBe('ws://127.0.0.1:8111/ws?last_cursor=4')
  })

  it('fails closed when a desktop host omits its local backend endpoints', () => {
    window.livePulsePlatform = { kind: 'desktop', apiBaseUrl: '', websocketBaseUrl: '' }
    expect(() => apiUrl('/api/v1/live-state')).toThrow('configure apiBaseUrl')
    expect(() => websocketUrl('/ws')).toThrow('configure websocketBaseUrl')
  })

  it('validates external targets and delegates opening to the active shell', async () => {
    const openExternalFromShell = vi.fn()
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8111',
      websocketBaseUrl: 'ws://127.0.0.1:8111',
      launchTargets: { portfolio: 'https://portfolio.example.test/' },
      openExternal: openExternalFromShell,
    }
    expect(externalTargetUrl('portfolio')).toBe('https://portfolio.example.test/')
    await expect(openExternal('javascript:alert(1)')).resolves.toBe(false)
    await expect(openExternal('https://chatgpt.com/')).resolves.toBe(true)
    expect(openExternalFromShell).toHaveBeenCalledWith('https://chatgpt.com/')
  })

  it('delegates authorization and fullscreen behavior to the shell adapter', async () => {
    const authorize = vi.fn()
    const fullscreen = vi.fn()
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8111',
      websocketBaseUrl: 'ws://127.0.0.1:8111',
      beginAuthorization: authorize,
      requestFullscreen: fullscreen,
    }

    await beginAuthorization('/api/v1/providers/gmail/oauth/start')
    await expect(requestFullscreen()).resolves.toBe(true)
    expect(authorize).toHaveBeenCalledWith('/api/v1/providers/gmail/oauth/start')
    expect(fullscreen).toHaveBeenCalledOnce()
  })

  it('routes preference persistence and backend lifecycle through the injected shell adapter', () => {
    const preferences = new Map<string, string>()
    let listener: ((state: 'starting' | 'ready' | 'unavailable') => void) | undefined
    window.livePulsePlatform = {
      kind: 'desktop',
      apiBaseUrl: 'http://127.0.0.1:8111',
      websocketBaseUrl: 'ws://127.0.0.1:8111',
      getPreference: (key) => preferences.get(key) ?? null,
      setPreference: (key, value) => { preferences.set(key, value) },
      removePreference: (key) => { preferences.delete(key) },
      getBackendLifecycle: () => 'starting',
      subscribeBackendLifecycle: (next) => { listener = next; return () => { listener = undefined } },
    }
    expect(getPreference('launch.github')).toBeNull()
    expect(setPreference('launch.github', 'https://github.com/')).toBe(true)
    expect(getPreference('launch.github')).toBe('https://github.com/')
    expect(getBackendLifecycle()).toBe('starting')
    const changed = vi.fn()
    const unsubscribe = subscribeBackendLifecycle(changed)
    listener?.('ready')
    expect(changed).toHaveBeenCalledWith('ready')
    unsubscribe()
    expect(removePreference('launch.github')).toBe(true)
    expect(getPreference('launch.github')).toBeNull()
  })

  it('retains browser localStorage as the preference fallback', () => {
    setPreference('livepulse.test.v1', 'browser')
    expect(getPreference('livepulse.test.v1')).toBe('browser')
    removePreference('livepulse.test.v1')
    expect(getPreference('livepulse.test.v1')).toBeNull()
  })

  it('keeps wake startup idempotent when React evaluates the initializer twice', () => {
    window.sessionStorage.clear()
    expect(consumeWakeSequence()).toBe(true)
    expect(consumeWakeSequence()).toBe(true)
    expect(window.sessionStorage.getItem('livepulse.wake-seen.v1')).toBe('1')
  })
})
