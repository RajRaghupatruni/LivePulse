import { useEffect, useRef } from 'react'
import { Check, ChevronDown, CircleAlert, CircleHelp, Server, X } from 'lucide-react'
import type { HealthRequestState } from '../hooks/useSystemHealth'
import type { HealthComponent, HealthStatus, SystemHealth } from '../types/livepulse'

const order = ['postgres', 'redpanda', 'outbox_publisher', 'projector', 'realtime', 'demo_source']
const labels: Record<string, string> = {
  postgres: 'PostgreSQL',
  redpanda: 'Redpanda',
  outbox_publisher: 'Outbox publisher',
  projector: 'Event projector',
  realtime: 'Realtime fan-out',
  demo_source: 'Demo source',
}
const statusLabel: Record<HealthStatus, string> = {
  healthy: 'HEALTHY',
  degraded: 'DEGRADED',
  unavailable: 'UNAVAILABLE',
  disconnected: 'DISCONNECTED',
  unknown: 'UNKNOWN',
}

function StatusIcon({ status }: { status: HealthStatus }) {
  if (status === 'healthy') return <Check size={13} aria-hidden="true" />
  if (status === 'unknown') return <CircleHelp size={13} aria-hidden="true" />
  return <CircleAlert size={13} aria-hidden="true" />
}

function metricSummary(component: HealthComponent): string | null {
  const metrics = component.metrics
  if (!metrics) return null
  const parts: string[] = []
  if (typeof metrics.connected_clients === 'number') parts.push(`${metrics.connected_clients} connected`)
  if (typeof metrics.queue_overflows === 'number' && metrics.queue_overflows > 0) {
    parts.push(`${metrics.queue_overflows} resyncs`)
  }
  if (typeof metrics.published === 'number') parts.push(`${metrics.published} published last poll`)
  if (typeof metrics.failed === 'number' && metrics.failed > 0) parts.push(`${metrics.failed} failed`)
  return parts.length > 0 ? parts.join(' · ') : null
}

export function SystemHealthPanel({
  health,
  requestState,
  open,
  onToggle,
}: {
  health: SystemHealth | null
  requestState: HealthRequestState
  open: boolean
  onToggle: () => void
}) {
  const toggleRef = useRef<HTMLButtonElement>(null)
  const status = requestState === 'unavailable' ? 'unavailable' : health?.status ?? 'unknown'
  const summary = requestState === 'unavailable'
    ? 'HEALTH CHECK UNAVAILABLE'
    : status === 'healthy'
      ? 'ALL SYSTEMS NOMINAL'
      : status === 'unknown'
        ? 'CHECKING SYSTEMS'
        : 'SYSTEM DEGRADED'
  const components = order.flatMap((name) => health?.components[name] ? [health.components[name]] : [])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onToggle()
        toggleRef.current?.focus()
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onToggle, open])

  return (
    <div className="health-control">
      <button
        className={`health-summary status-${status}`}
        type="button"
        ref={toggleRef}
        aria-expanded={open}
        aria-controls="system-health-panel"
        onClick={onToggle}
      >
        <StatusIcon status={status} />
        <span>{summary}</span>
        <ChevronDown size={13} className={open ? 'health-chevron is-open' : 'health-chevron'} />
      </button>
      {open && (
        <aside className="health-panel" id="system-health-panel" aria-label="Detailed system health">
          <div className="health-panel-heading">
            <div><span className="eyebrow">LIVE DIAGNOSTICS</span><h2>System health</h2></div>
            <button className="icon-button" type="button" onClick={onToggle} aria-label="Close system health">
              <X size={15} />
            </button>
          </div>
          {requestState === 'checking' && !health ? (
            <p className="health-empty"><Server size={15} /> Checking observed dependencies…</p>
          ) : requestState === 'unavailable' && !health ? (
            <p className="health-empty"><CircleAlert size={15} /> The health endpoint could not be reached.</p>
          ) : (
            <ul className="health-list">
              {components.map((component) => (
                <li className={`health-row status-${component.status}`} key={component.name}>
                  <span className="health-row-icon"><StatusIcon status={component.status} /></span>
                  <span className="health-row-copy">
                    <strong>{labels[component.name] ?? component.name}</strong>
                    <small>{component.detail.replaceAll('_', ' ')}</small>
                    {metricSummary(component) && <small className="health-metrics">{metricSummary(component)}</small>}
                  </span>
                  <span className="health-row-state">{statusLabel[component.status]}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="health-panel-footnote">
            {health?.checked_at ? `Checked ${new Date(health.checked_at).toLocaleTimeString()}` : 'No successful health snapshot yet'}
          </p>
        </aside>
      )}
    </div>
  )
}
