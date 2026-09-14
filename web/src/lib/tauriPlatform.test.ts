import { afterEach, describe, expect, it, vi } from 'vitest'

const { openUrl } = vi.hoisted(() => ({ openUrl: vi.fn().mockResolvedValue(undefined) }))

vi.mock('@tauri-apps/api/core', () => ({ isTauri: () => true }))
vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({ setFullscreen: vi.fn(), isFullscreen: vi.fn(), isMaximized: vi.fn() }),
}))
vi.mock('@tauri-apps/plugin-opener', () => ({ openUrl }))

import { initializeTauriPlatform } from './tauriPlatform'

describe('Tauri OAuth launch', () => {
  afterEach(() => {
    delete window.livePulsePlatform
    openUrl.mockClear()
  })

  it('opens the fixed local OAuth start URL in the system browser with desktop completion mode', async () => {
    expect(await initializeTauriPlatform()).toBe(true)
    await window.livePulsePlatform?.beginAuthorization?.('/api/v1/providers/spotify/oauth/start')

    expect(openUrl).toHaveBeenCalledOnce()
    const opened = openUrl.mock.calls[0][0] as URL
    expect(opened.origin).toBe('http://127.0.0.1:8000')
    expect(opened.pathname).toBe('/api/v1/providers/spotify/oauth/start')
    expect(opened.searchParams.get('completion')).toBe('desktop')
  })
})
