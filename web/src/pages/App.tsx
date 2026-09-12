import { useEffect, useState } from 'react'
import { Activity, ArrowDownRight, Command, Layers3, Plus, RotateCcw, Zap } from 'lucide-react'
import { CommandBar } from '../components/CommandBar'
import { ConnectionBadge } from '../components/ConnectionBadge'
import { MatchSurface } from '../features/match/MatchSurface'
import { PulseTimeline } from '../features/timeline/PulseTimeline'
import { useLivePulse } from '../hooks/useLivePulse'

function useLocalClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

export default function App() {
  const { live, timeline, connection, busy, error, runDemo, reset } = useLivePulse()
  const now = useLocalClock()
  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="LivePulse home"><span className="brand-symbol"><i /><i /><i /></span><span>LIVE<span className="brand-light">PULSE</span></span></a>
        <div className="topbar-center"><span className="system-mark"><Layers3 size={14} /> PERSONAL COMMAND CENTER</span><span className="topbar-line" /></div>
        <div className="topbar-right"><div className="local-clock"><span>{now.toLocaleDateString([], { weekday: 'short', month: 'short', day: '2-digit' }).toUpperCase()}</span><strong>{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</strong></div><ConnectionBadge state={connection} /></div>
      </header>

      <div className="workspace" id="top">
        <section className="welcome-row"><div><span className="eyebrow"><span className="eyebrow-index">01</span> LIVE ENVIRONMENT <i /></span><h1>Stay in the <em>moment.</em></h1><p>Your world, moving in real time.</p></div><div className="welcome-side"><span><span className="pulse-orb" /> LOCAL DEMO ENVIRONMENT</span><small>SIMULATED FOOTBALL · DURABLE EVENT PATH</small></div></section>
        <section className="signal-row"><span className="section-label"><Zap size={13} /> LIVE SIGNAL</span><span className="signal-rule" /><span className="signal-end">01 / 01</span></section>
        <div className="content-grid">
          <div className="primary-column">
            <MatchSurface match={live.match} attention={live.attention} />
            <div className="subsystem-row"><div className="subsystem-title"><span className="eyebrow"><span className="eyebrow-index">02</span> ACTIVE CONTROL</span><h2>Demo environment</h2></div><div className="demo-controls"><button className="button-secondary" onClick={() => void reset()} disabled={busy}><RotateCcw size={14} /> Reset</button><button className="button-primary" onClick={() => void runDemo()} disabled={busy}><Plus size={15} /> {busy ? 'Working...' : 'Run Demo Match'} <ArrowDownRight size={14} /></button></div></div>
            {error && <div className="error-banner" role="alert">{error}</div>}
            <div className="system-strip"><div><Activity size={14} /><span>INGESTION</span><strong>SIMULATED PROVIDER</strong></div><div><span className="strip-separator" /><Command size={14} /><span>DELIVERY</span><strong>AT-LEAST-ONCE</strong></div><div><span className="strip-separator" /><Layers3 size={14} /><span>PROJECTION</span><strong>IDEMPOTENT</strong></div><div className="strip-health"><span>DEMO MODE</span></div></div>
          </div>
          <PulseTimeline items={timeline} />
        </div>
        <footer className="footer-row"><CommandBar /><div className="footer-meta"><span><i /> M1 · DEMO MODE</span><span>LOCAL SYSTEM TIME</span></div></footer>
      </div>
    </main>
  )
}
