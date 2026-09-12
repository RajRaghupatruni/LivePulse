import { useEffect, useState } from 'react'
import { Activity, ArrowDownRight, Layers3, Plus, RotateCcw } from 'lucide-react'
import { useReducedMotion } from 'framer-motion'
import { CommandBar } from '../components/CommandBar'
import { ConnectionBadge } from '../components/ConnectionBadge'
import { SystemHealthPanel } from '../components/SystemHealthPanel'
import { MatchSurface } from '../features/match/MatchSurface'
import { PulseTimeline } from '../features/timeline/PulseTimeline'
import { useLivePulse } from '../hooks/useLivePulse'
import { useSystemHealth } from '../hooks/useSystemHealth'
import type { HealthStatus } from '../types/livepulse'

function useLocalClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

const railItems = [
  ['postgres', 'STORE'],
  ['redpanda', 'EVENT STREAM'],
  ['outbox_publisher', 'OUTBOX'],
  ['projector', 'PROJECTOR'],
] as const

function SystemRail({ health }: { health: ReturnType<typeof useSystemHealth>['health'] }) {
  return (
    <section className="system-rail" aria-label="Observed system components">
      <div className="rail-heading"><Activity size={14} /><span>PERIPHERAL STATUS</span></div>
      {railItems.map(([key, label]) => {
        const component = health?.components[key]
        const status: HealthStatus = component?.status ?? 'unknown'
        return (
          <div className={`rail-item status-${status}`} key={key} aria-label={`${label}: ${status}`}>
            <span className="rail-state-mark" aria-hidden="true" />
            <span>{label}</span>
            <strong>{status === 'healthy' ? 'READY' : status.toUpperCase()}</strong>
          </div>
        )
      })}
      <span className="rail-note"><Layers3 size={12} /> LOCAL DEMO STACK</span>
    </section>
  )
}

export default function App() {
  const { live, timeline, connection, busy, error, runDemo, reset } = useLivePulse()
  const { health, requestState } = useSystemHealth()
  const [healthOpen, setHealthOpen] = useState(false)
  const now = useLocalClock()
  const reduceMotion = useReducedMotion()
  const matchMode = live.focus.match_mode.replaceAll('_', ' ').toUpperCase()

  const showMatch = () => {
    document.getElementById('focus-surface')?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' })
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="LivePulse home">
          <span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span>
          <span>LIVE<span className="brand-light">PULSE</span></span>
        </a>
        <div className="topbar-center"><span className="system-mark"><Layers3 size={14} /> PERSONAL COMMAND CENTER</span><span className="topbar-line" /></div>
        <div className="topbar-right">
          <div className="local-clock" aria-label={`Local time ${now.toLocaleString()}`}>
            <span>{now.toLocaleDateString([], { weekday: 'short', month: 'short', day: '2-digit', year: 'numeric' }).toUpperCase()}</span>
            <strong>{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</strong>
          </div>
          <SystemHealthPanel
            health={health}
            requestState={requestState}
            open={healthOpen}
            onToggle={() => setHealthOpen((value) => !value)}
          />
          <ConnectionBadge state={connection} />
        </div>
      </header>

      <div className="workspace" id="top">
        <section className="workspace-heading">
          <div>
            <span className="eyebrow"><span className="eyebrow-index">LIVEPULSE / 02</span> PERSONAL REALTIME SYSTEM</span>
            <h1>Today, <em>in focus.</em></h1>
            <p>A clear view of what is happening now, with the history to catch up.</p>
          </div>
          <div className="workspace-heading-meta">
            <span className="eyebrow">MATCH MODE</span>
            <strong className={`mode-chip mode-${live.focus.match_mode}`}>{matchMode}</strong>
            <small>{live.focus.reason.replaceAll('_', ' ')}</small>
          </div>
        </section>

        <div className="signal-row"><span className="section-label"><Activity size={13} /> CURRENT SIGNAL</span><span className="signal-rule" /><span className="signal-end">FOCUS {String(live.focus.score).padStart(2, '0')} / 100</span></div>

        <div className="content-grid">
          <div className="primary-column">
            <section id="focus-surface" className="focus-section" aria-label="Current focus">
              <div className="surface-heading"><div><span className="eyebrow">01 / FOCUS SURFACE</span><h2>{live.match ? 'The match, as it is now.' : 'A clear field of view.'}</h2></div><span className="focus-source">{live.focus.source.toUpperCase()} · {live.focus.transient ? 'TRANSIENT ATTENTION' : 'DETERMINISTIC FOCUS'}</span></div>
              <MatchSurface match={live.match} focus={live.focus} />
              <div className="demo-controls">
                <div className="demo-caption"><span className="demo-mark" /><span>LOCAL DETERMINISTIC SOURCE</span></div>
                <div className="demo-actions">
                  <button className="button-secondary" type="button" onClick={() => void reset()} disabled={busy}><RotateCcw size={14} /> Reset</button>
                  <button className="button-primary" type="button" onClick={() => void runDemo()} disabled={busy}><Plus size={15} /> {busy ? 'Working…' : 'Run Demo Match'} <ArrowDownRight size={14} /></button>
                </div>
              </div>
              {error && <div className="error-banner" role="alert">{error}</div>}
            </section>
            <SystemRail health={health} />
          </div>
          <PulseTimeline items={timeline} />
        </div>

        <footer className="footer-row">
          <CommandBar
            onRunDemo={runDemo}
            onReset={reset}
            onShowHealth={() => setHealthOpen(true)}
            onShowMatch={showMatch}
          />
          <div className="footer-meta"><span><i aria-hidden="true" /> M2 · STATE-DRIVEN</span><span>LOCAL SYSTEM TIME</span></div>
        </footer>
      </div>
    </main>
  )
}
