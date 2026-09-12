import type { LiveState, TimelineResponse } from '../types/livepulse'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
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
export const getTimeline = () => request<TimelineResponse>('/api/v1/timeline?limit=80')
export const startDemo = () => request<{ status: string; match_id: string }>('/api/v1/demo/scenarios/comeback/start', { method: 'POST' })
export const resetDemo = () => request<{ status: string }>('/api/v1/demo/reset', { method: 'POST' })
