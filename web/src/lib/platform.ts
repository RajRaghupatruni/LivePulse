/**
 * Browser/native boundary for LivePulse. The UI depends on this interface,
 * while a future shell may provide `window.livePulsePlatform` at startup.
 * No native-shell package is imported by the React application.
 */

export type ExternalTarget = 'chatgpt' | 'github' | 'vscode' | 'portfolio' | 'strata' | 'gmail'
export type BackendLifecycle = 'starting' | 'ready' | 'unavailable'

type PlatformAdapterCapabilities = {
  apiBaseUrl?: string
  websocketBaseUrl?: string
  launchTargets?: Partial<Record<ExternalTarget, string>>
  openExternal?: (url: string) => void | Promise<void>
  requestFullscreen?: () => void | Promise<void>
  toggleMaximize?: () => void | Promise<void>
  getBackendLifecycle?: () => BackendLifecycle
  subscribeBackendLifecycle?: (listener: (state: BackendLifecycle) => void) => () => void
  getPreference?: (key: string) => string | null
  setPreference?: (key: string, value: string) => boolean | void
  removePreference?: (key: string) => boolean | void
  navigateWithinApp?: (path: string) => void | Promise<void>
  beginAuthorization?: (path: string) => void | Promise<void>
  consumeWakeSequence?: () => boolean
}

export type LivePulsePlatformAdapter = PlatformAdapterCapabilities & (
  | { kind: 'browser' }
  | { kind: 'desktop'; apiBaseUrl: string; websocketBaseUrl: string }
)

declare global {
  interface Window {
    livePulsePlatform?: LivePulsePlatformAdapter
  }
}

const defaults: Partial<Record<ExternalTarget, string>> = {
  chatgpt: 'https://chatgpt.com/',
  github: 'https://github.com/',
  vscode: 'https://vscode.dev/',
  gmail: 'https://mail.google.com/',
}
let wakeSequenceDecision: boolean | undefined

function adapter(): LivePulsePlatformAdapter | undefined {
  return typeof window === 'undefined' ? undefined : window.livePulsePlatform
}

export function isDesktopShell(): boolean {
  return adapter()?.kind === 'desktop'
}

/** Synchronous lifecycle snapshot; a desktop host should hydrate it before mounting React. */
export function getBackendLifecycle(): BackendLifecycle | undefined {
  try { return adapter()?.getBackendLifecycle?.() } catch { return undefined }
}

/** Observe shell-owned sidecar lifecycle without coupling the UI to native events. */
export function subscribeBackendLifecycle(listener: (state: BackendLifecycle) => void): () => void {
  try { return adapter()?.subscribeBackendLifecycle?.(listener) ?? (() => undefined) } catch { return () => undefined }
}

/** Synchronous preference access lets a future host hydrate its store before React mounts. */
export function getPreference(key: string): string | null {
  try {
    const hostValue = adapter()?.getPreference?.(key)
    if (hostValue !== undefined) return hostValue
    return typeof window === 'undefined' ? null : window.localStorage.getItem(key)
  } catch { return null }
}

export function setPreference(key: string, value: string): boolean {
  try {
    const host = adapter()
    if (host?.setPreference) return host.setPreference(key, value) !== false
    if (typeof window === 'undefined') return false
    window.localStorage.setItem(key, value)
    return true
  } catch { return false }
}

export function removePreference(key: string): boolean {
  try {
    const host = adapter()
    if (host?.removePreference) return host.removePreference(key) !== false
    if (typeof window === 'undefined') return false
    window.localStorage.removeItem(key)
    return true
  } catch { return false }
}

/** Run the wake once per browser tab/desktop session; shell may supply its own restore policy. */
export function consumeWakeSequence(): boolean {
  // Keep the startup decision stable under React StrictMode's development-only
  // double invocation of lazy state initializers.
  if (wakeSequenceDecision !== undefined) return wakeSequenceDecision
  const host = adapter()
  if (host?.consumeWakeSequence) {
    try { wakeSequenceDecision = host.consumeWakeSequence() } catch { wakeSequenceDecision = false }
    return wakeSequenceDecision
  }
  if (typeof window === 'undefined') return wakeSequenceDecision = false
  try {
    if (window.sessionStorage.getItem('livepulse.wake-seen.v1')) return wakeSequenceDecision = false
    window.sessionStorage.setItem('livepulse.wake-seen.v1', '1')
  } catch {
    // If storage is unavailable, keep the app usable and allow a short establish sequence.
  }
  return wakeSequenceDecision = true
}

function localTargetUrl(target: ExternalTarget): string | undefined {
  return getPreference(`livepulse.launch.${target}.v1`) ?? undefined
}

export function externalTargetUrl(target: ExternalTarget): string | null {
  const configured = adapter()?.launchTargets?.[target] ?? localTargetUrl(target)
  const envConfigured: Partial<Record<ExternalTarget, string | undefined>> = {
    chatgpt: import.meta.env.VITE_CHATGPT_URL,
    github: import.meta.env.VITE_GITHUB_URL,
    vscode: import.meta.env.VITE_VSCODE_URL,
    portfolio: import.meta.env.VITE_PORTFOLIO_URL,
    strata: import.meta.env.VITE_STRATA_URL,
    gmail: import.meta.env.VITE_GMAIL_URL,
  }
  const candidate = configured ?? envConfigured[target] ?? defaults[target]
  return candidate ? safeExternalUrl(candidate) : null
}

export function saveExternalTargetUrl(target: ExternalTarget, value: string): boolean {
  const normalized = value.trim()
  if (normalized && !safeExternalUrl(normalized)) return false
  return normalized
    ? setPreference(`livepulse.launch.${target}.v1`, normalized)
    : removePreference(`livepulse.launch.${target}.v1`)
}

function safeExternalUrl(value: string | undefined): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:' || parsed.protocol === 'vscode:') return parsed.href
  } catch {
    return null
  }
  return null
}

/** Open a known/configured destination through the active shell boundary. */
export async function openExternal(value: string): Promise<boolean> {
  const url = safeExternalUrl(value)
  if (!url) return false
  const host = adapter()
  if (host?.openExternal) {
    try {
      await host.openExternal(url)
      return true
    } catch { return false }
  }
  if (typeof window !== 'undefined') {
    try {
      const opened = window.open(url, '_blank', 'noopener,noreferrer')
      if (opened) opened.opener = null
      return Boolean(opened)
    } catch { return false }
  }
  return false
}

export async function launchExternal(target: ExternalTarget): Promise<boolean> {
  const url = externalTargetUrl(target)
  return url ? openExternal(url) : false
}

export async function requestFullscreen(): Promise<boolean> {
  const host = adapter()
  if (host?.requestFullscreen) {
    try {
      await host.requestFullscreen()
      return true
    } catch { return false }
  }
  if (typeof document === 'undefined') return false
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
      return false
    }
    await document.documentElement.requestFullscreen?.()
    return Boolean(document.fullscreenElement)
  } catch { return false }
}

export async function toggleWindowMaximize(): Promise<boolean> {
  const host = adapter()
  if (!host?.toggleMaximize) return false
  try {
    await host.toggleMaximize()
    return true
  } catch { return false }
}

export async function navigateWithinApp(path: string): Promise<void> {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Only local LivePulse routes are supported')
  const host = adapter()
  if (host?.navigateWithinApp) {
    await host.navigateWithinApp(path)
    return
  }
  if (typeof window !== 'undefined') window.location.assign(apiUrl(path))
}

export async function beginAuthorization(path: string): Promise<void> {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Only local LivePulse authorization routes are supported')
  const host = adapter()
  if (host?.beginAuthorization) {
    await host.beginAuthorization(path)
    return
  }
  if (typeof window !== 'undefined') window.location.assign(path)
}

export function apiUrl(path: string): string {
  const host = adapter()
  const base = host?.apiBaseUrl ?? import.meta.env.VITE_API_BASE_URL ?? ''
  if (host?.kind === 'desktop' && !base) throw new Error('Desktop shell must configure apiBaseUrl for its local backend')
  return base ? new URL(path, base.endsWith('/') ? base : `${base}/`).href : path
}

export function websocketUrl(path: string): string {
  const host = adapter()
  const base = host?.websocketBaseUrl ?? import.meta.env.VITE_WEBSOCKET_BASE_URL
  if (base) return new URL(path, base.endsWith('/') ? base : `${base}/`).href
  if (host?.kind === 'desktop') throw new Error('Desktop shell must configure websocketBaseUrl for its local backend')
  if (typeof window === 'undefined') throw new Error('Realtime transport requires a configured shell endpoint outside a browser window')
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

export function connectRealtime(path: string): WebSocket {
  return new WebSocket(websocketUrl(path))
}
