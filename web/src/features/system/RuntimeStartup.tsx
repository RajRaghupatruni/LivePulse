import { CircleAlert, RotateCw, Waves } from 'lucide-react'
import type { HealthRequestState } from '../../hooks/useSystemHealth'

export function RuntimeStartup({ state, onRetry }: { state: HealthRequestState; onRetry: () => void }) {
  const unavailable = state === 'unavailable'

  return <main className="runtime-startup" aria-live="polite" data-state={state}>
    <section className="runtime-startup-panel" aria-labelledby="runtime-startup-title">
      <div className="runtime-startup-brand"><Waves size={21} aria-hidden="true" /><span>LIVEPULSE</span><i>PERSONAL COMMAND CENTER</i></div>
      <div className={`runtime-startup-mark${unavailable ? ' is-unavailable' : ''}`} aria-hidden="true">
        {unavailable ? <CircleAlert size={21} /> : <span />}
      </div>
      <p className="surface-overline">LOCAL RUNTIME · {unavailable ? 'CONNECTION REQUIRED' : 'INITIALIZING'}</p>
      <h1 id="runtime-startup-title">{unavailable ? 'Backend unavailable' : 'Starting LivePulse services'}</h1>
      <p className="runtime-startup-copy">{unavailable
        ? 'The local backend is not responding. Start the LivePulse service stack, then retry. Your providers and dashboard will load when it is ready.'
        : 'Waiting for the local backend and its required services. This window will continue automatically when they are ready.'}</p>
      <div className="runtime-startup-status"><i />{unavailable ? 'WAITING FOR RETRY' : 'CHECKING BACKEND READINESS'}</div>
      {unavailable && <button className="runtime-startup-retry" type="button" onClick={onRetry}><RotateCw size={15} aria-hidden="true" />Retry connection</button>}
    </section>
    <footer className="runtime-startup-footer"><span>LIVEPULSE <i /> PERSONAL LOCAL</span><span>LOCAL SERVICE · PRIVATE BY DESIGN</span></footer>
  </main>
}
