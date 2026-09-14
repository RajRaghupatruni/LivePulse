import type { LivePulsePlatformAdapter } from './platform'

// Packaged desktop mode is intentionally pinned to the PERSONAL_LOCAL loopback
// service; browser builds may still override endpoints through Vite settings.
const apiBaseUrl = 'http://127.0.0.1:8000'
const websocketBaseUrl = 'ws://127.0.0.1:8000'

/** Install native capabilities only inside Tauri; browsers keep the existing web adapter. */
export async function initializeTauriPlatform(): Promise<boolean> {
  const { isTauri } = await import('@tauri-apps/api/core')
  if (!isTauri()) return false

  const { getCurrentWindow } = await import('@tauri-apps/api/window')
  const appWindow = getCurrentWindow()
  const openExternal = async (url: string) => {
    const parsed = new URL(url)
    if (!['https:', 'http:'].includes(parsed.protocol)) throw new Error('Only web URLs can be opened externally')
    const { openUrl } = await import('@tauri-apps/plugin-opener')
    await openUrl(parsed)
  }
  const adapter: LivePulsePlatformAdapter = {
    kind: 'desktop',
    apiBaseUrl,
    websocketBaseUrl,
    openExternal,
    requestFullscreen: async () => {
      await appWindow.setFullscreen(!(await appWindow.isFullscreen()))
    },
    toggleMaximize: async () => {
      if (await appWindow.isMaximized()) await appWindow.unmaximize()
      else await appWindow.maximize()
    },
    beginAuthorization: async (path) => {
      // The system browser handles the provider redirect; completion mode is a fixed enum,
      // while OAuth state remains the authority for the callback experience.
      const url = new URL(path, `${apiBaseUrl}/`)
      url.searchParams.set('completion', 'desktop')
      await openExternal(url.href)
    },
  }
  window.livePulsePlatform = adapter
  return true
}
