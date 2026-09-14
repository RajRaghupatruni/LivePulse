import type {
  FootballFixtures,
  LiveState,
  SpotifyCommandResult,
  SpotifyDevice,
  SpotifyPlaybackView,
  SystemHealth,
  TimelineResponse,
  WeatherSnapshot,
  WeatherLocation,
  WeatherLocationState,
} from '../types/livepulse'
import { apiUrl } from './platform'

export type GmailMessage = {
  message_id: string
  thread_id: string
  sender: string
  subject: string
  received_at: string
  snippet: string
  is_unread: boolean
  is_important: boolean
}

export type GmailInbox = {
  status: 'ready' | 'not_configured' | 'disconnected' | 'unavailable'
  configured: boolean
  messages: GmailMessage[]
}

export type BackendReadiness = { status: 'ready' }
export type ProviderConnection = {
  provider: 'spotify' | 'gmail'
  connected: boolean
  status: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message ?? `LivePulse request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const getLiveState = () => request<LiveState>('/api/v1/live-state')
export const getTimeline = (limit = 40, before?: number) => {
  const query = new URLSearchParams({ limit: String(limit) })
  if (before !== undefined) query.set('before', String(before))
  return request<TimelineResponse>(`/api/v1/timeline?${query.toString()}`)
}
export const getSystemHealth = () => request<SystemHealth>('/api/v1/system/health')
export const getBackendReadiness = () => request<BackendReadiness>('/health/ready')
export const getFootballFixtures = () => request<FootballFixtures>('/api/v1/football/fixtures')
export const getSpotifyPlayback = () => request<SpotifyPlaybackView>('/api/v1/providers/spotify/playback')
export const getSpotifyConnection = (signal?: AbortSignal) => request<ProviderConnection>(
  '/api/v1/providers/spotify/connection', { signal },
)
export const getSpotifyDevices = () => request<SpotifyDevice[]>('/api/v1/providers/spotify/devices')
export const getWeatherSnapshot = () => request<WeatherSnapshot>('/api/v1/providers/weather/current')
export const getWeatherLocationState = () => request<WeatherLocationState>('/api/v1/providers/weather/location')
export const searchWeatherLocations = (query: string, signal?: AbortSignal) => {
  const params = new URLSearchParams({ q: query })
  return request<{ results: WeatherLocation[] }>(`/api/v1/providers/weather/location/search?${params}`, { signal })
}
export const selectWeatherLocation = (location: WeatherLocation) =>
  request<WeatherLocationState>('/api/v1/providers/weather/location/select', {
    method: 'POST',
    body: JSON.stringify({ ...location, selected_at: null, last_used_at: null }),
  })
export const getGmailInbox = (limit = 4) => request<GmailInbox>(`/api/v1/providers/gmail/messages?limit=${limit}`)
export const getGmailConnection = (signal?: AbortSignal) => request<ProviderConnection>(
  '/api/v1/providers/gmail/connection', { signal },
)
export const getGmailMessage = (messageId: string) => request<GmailMessage>(`/api/v1/providers/gmail/messages/${encodeURIComponent(messageId)}`)

export type SpotifyCommand = 'spotify.play' | 'spotify.pause' | 'spotify.previous' | 'spotify.next' | 'spotify.transfer_device'
export type SpotifyCommandArguments = { device_id?: string }
export const executeSpotifyCommand = (command: SpotifyCommand, argumentsValue?: SpotifyCommandArguments) =>
  request<SpotifyCommandResult>('/api/v1/providers/spotify/commands', {
    method: 'POST',
    body: JSON.stringify({ command, ...(argumentsValue ? { arguments: argumentsValue } : {}) }),
  })
