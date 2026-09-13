import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, CircleAlert, CircleHelp, X } from 'lucide-react'
import type { ConnectionState } from '../../hooks/useLivePulse'
import type { HealthComponent, HealthStatus, ProviderHealth, SystemHealth } from '../../types/livepulse'
import type { HealthRequestState } from '../../hooks/useSystemHealth'
import { providerStatusLabel, timeAgo } from '../../lib/timelinePresentation'

const components: Array<[string, string]> = [
  ['postgres', 'Data store'], ['redpanda', 'Event stream'], ['outbox_publisher', 'Outbox'],
  ['projector', 'Projection'], ['realtime', 'Realtime fan-out'],
]
const providers: Array<[string, string]> = [['football', 'Football'], ['spotify', 'Spotify'], ['github', 'GitHub'], ['gmail', 'Gmail'], ['weather', 'Weather']]
const stateNames: Record<string, string> = { healthy: 'Fresh', degraded: 'Degraded', unavailable: 'Unavailable', unknown: 'Checking', disconnected: 'Not configured', connecting: 'Connecting', stale: 'Stale', resyncing: 'Resyncing', rate_limited: 'Rate limited', auth_failure: 'Reconnect required', provider_failure: 'Provider error' }
const infraDetails: Record<string, string> = { query_ok: 'Database query responded', broker_connected: 'Broker connection responded', consumer_connected: 'Projection consumer connected', poll_complete: 'Latest projection poll completed', in_process_fanout: 'Local realtime channel is active', client_resync_required: 'A client is recovering state' }

function StatusGlyph({ status }: { status: string }) {
  if (status === 'healthy') return <Check size={14} aria-hidden="true" />
  if (status === 'unknown' || status === 'connecting') return <CircleHelp size={14} aria-hidden="true" />
  return <CircleAlert size={14} aria-hidden="true" />
}

function InfrastructureRow({ component, label }: { component: HealthComponent; label: string }) {
  return <li className={`diagnostic-row health-${component.status}`}><span><StatusGlyph status={component.status} /></span><strong>{label}</strong><small>{infraDetails[component.detail] ?? 'Latest locally observed state'}</small><em>{stateNames[component.status] ?? 'Unknown'}</em></li>
}

function ProviderRow({ provider, label }: { provider: ProviderHealth; label: string }) {
  const age = timeAgo(provider.last_success_at ?? provider.last_observation_at)
  const freshness = age ? `Last observation ${age}` : provider.configured ? 'Waiting for first observation' : 'Credentials not configured'
  return <li className={`diagnostic-row health-${provider.status}`}><span><StatusGlyph status={provider.status} /></span><strong>{label}</strong><small>{freshness}</small><em>{providerStatusLabel(provider.status, provider.configured)}</em></li>
}

export function SystemPulse({ health, requestState, connection }: { health: SystemHealth | null; requestState: HealthRequestState; connection: ConnectionState }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const requestFailed = requestState === 'unavailable'
  const status: HealthStatus = requestFailed ? 'unavailable' : health?.status ?? (requestState === 'starting' ? 'connecting' : 'unknown')
  const alertCount = Object.values(health?.providers ?? {}).filter((provider) => provider.configured && !['healthy', 'unknown', 'connecting'].includes(provider.status)).length
  const label = requestFailed ? 'Backend unavailable' : requestState === 'starting' ? 'Local backend starting' : status === 'healthy' ? alertCount ? `Local services stable · ${alertCount} provider issue${alertCount === 1 ? '' : 's'}` : 'Local services stable' : status === 'degraded' ? `${alertCount || 1} system issue${alertCount === 1 ? '' : 's'} needs attention` : status === 'unavailable' ? 'System unavailable' : 'Resolving system state'
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (open && event.key === 'Escape') { event.stopPropagation(); setOpen(false); triggerRef.current?.focus() } }
    const show = () => setOpen(true)
    window.addEventListener('keydown', close)
    window.addEventListener('livepulse:open-health', show)
    return () => { window.removeEventListener('keydown', close); window.removeEventListener('livepulse:open-health', show) }
  }, [open])
  const infra = components.flatMap(([key, label]) => health?.components[key] ? [{ component: health.components[key], label }] : [])
  const sources = providers.flatMap(([key, label]) => health?.providers?.[key] ? [{ provider: health.providers[key], label }] : [])
  const providerSummary = sources.length ? sources.map(({ provider, label }) => `${label} ${stateNames[provider.status] ?? 'Unknown'}`).join(', ') : 'Provider status is resolving'
  return <div className="system-pulse-anchor">
    <button className={`system-pulse-trigger health-${status}`} type="button" ref={triggerRef} aria-expanded={open} aria-controls="system-pulse-details" onClick={() => setOpen((value) => !value)}>
      <span className="pulse-instrument" aria-hidden="true"><i /><i /><i /><b /></span>
      <span className="pulse-trigger-copy"><span>SYSTEM PULSE</span><strong>{label}</strong></span>
      <span className="provider-mini-strip" aria-label={providerSummary}>{providers.map(([key, name]) => { const provider = health?.providers?.[key]; const tone = provider?.status ?? 'unknown'; return <i className={`provider-mini provider-${tone}`} key={key} title={`${name}: ${provider ? providerStatusLabel(provider.status, provider.configured) : 'Checking'}`} aria-hidden="true">{name.slice(0, 1)}</i> })}</span>
      <span className={`transport-word transport-${connection.toLowerCase()}`}><i />{connection === 'LIVE' ? 'LIVE' : connection}</span>
      {alertCount > 0 && <span className="pulse-alert-count">{alertCount}</span>}
      <ChevronDown className={open ? 'pulse-chevron is-open' : 'pulse-chevron'} size={16} aria-hidden="true" />
    </button>
    {open && <aside className="system-pulse-panel" id="system-pulse-details" aria-label="System diagnostics">
      <div className="system-panel-head"><div><span>LOCAL RUNTIME · OBSERVED STATE</span><h2>System Pulse</h2></div><button className="quiet-icon-button" type="button" onClick={() => { setOpen(false); triggerRef.current?.focus() }} aria-label="Close system diagnostics"><X size={17} /></button></div>
      <div className="runtime-strip"><span>{requestFailed ? 'HEALTH SNAPSHOT UNAVAILABLE' : `SYSTEM ${status.toUpperCase()}`}</span><span className={`transport-word transport-${connection.toLowerCase()}`}><i /> REALTIME {connection}</span></div>
      {requestFailed && !health ? <p className="health-empty-message">The local backend is unavailable. LivePulse will keep retrying and restore provider and timeline state when it responds.</p> : requestState === 'starting' && !health ? <p className="health-empty-message">The local backend is starting. The interface is ready and will connect automatically.</p> : <>
        <section className="diagnostics-section"><h3>LOCAL INFRASTRUCTURE</h3><ul>{infra.map(({ component, label }) => <InfrastructureRow key={component.name} component={component} label={label} />)}</ul></section>
        <section className="diagnostics-section"><h3>PROVIDER FRESHNESS</h3><ul>{sources.map(({ provider, label }) => <ProviderRow key={provider.provider} provider={provider} label={label} />)}</ul></section>
      </>}
      <footer className="system-panel-footer"><span>{health?.checked_at ? `Checked ${new Date(health.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Waiting for system snapshot'}</span><span>PROVIDER HEALTH IS SEPARATE FROM REALTIME</span></footer>
    </aside>}
  </div>
}
