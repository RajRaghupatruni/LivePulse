import { useEffect, useState } from 'react'
import { Check, CirclePause, CirclePlay, RotateCcw } from 'lucide-react'
import { focusTimerStore, useFocusTimerSnapshot, type FocusTimerSnapshot } from './focusTimerStore'

function clock(ms: number) {
  const seconds = Math.ceil(Math.max(0, ms) / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

export function FocusTimer({ snapshotOverride }: { snapshotOverride?: FocusTimerSnapshot }) {
  const storedSnapshot = useFocusTimerSnapshot()
  const snapshot = snapshotOverride ?? storedSnapshot
  const readOnlyFixture = snapshotOverride !== undefined
  const [now, setNow] = useState(Date.now())
  const active = snapshot.status === 'running' || snapshot.status === 'paused'
  useEffect(() => {
    if (!active) return
    const tick = () => {
      setNow(Date.now())
      if (!readOnlyFixture && snapshot.status === 'running' && snapshot.deadline !== null && snapshot.deadline <= Date.now()) focusTimerStore.complete()
    }
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [active, readOnlyFixture, snapshot.status, snapshot.deadline])
  const remaining = snapshot.status === 'running' && snapshot.deadline !== null
    ? Math.max(0, snapshot.deadline - now)
    : snapshot.remainingMs ?? 0
  const total = (snapshot.durationMinutes ?? 0) * 60_000
  const progress = snapshot.status === 'complete' ? 100 : total > 0 ? Math.max(0, Math.min(100, (total - remaining) / total * 100)) : 0

  return <section className={`focus-timer${active ? ' focus-timer-active' : ''}${snapshot.status === 'paused' ? ' focus-timer-paused' : ''}`} aria-label="Focus timer">
    <span className="focus-timer-orbit" aria-hidden="true" style={{ background: `conic-gradient(currentColor ${progress}%, rgb(175 187 207 / 12%) 0)` }}><i /></span>
    <div className="focus-timer-main">
      <span className="focus-timer-label">{snapshot.status === 'complete' ? 'SESSION COMPLETE' : active ? 'FOCUS SESSION' : 'FOCUS TIMER'}</span>
      <strong>{active ? clock(remaining) : snapshot.status === 'complete' ? 'Done' : 'Set a quiet window'}</strong>
      <span className="focus-timer-caption">{active ? `${snapshot.durationMinutes} minute session · ${snapshot.status}` : snapshot.status === 'complete' ? 'Your session is complete.' : 'Peripheral motion and detail recede.'}</span>
    </div>
    {active ? <div className="focus-active-controls">
      <button type="button" disabled={readOnlyFixture} onClick={() => snapshot.status === 'running' ? focusTimerStore.pause() : focusTimerStore.resume()} aria-label={snapshot.status === 'running' ? 'Pause focus timer' : 'Resume focus timer'}>{snapshot.status === 'running' ? <CirclePause size={17} /> : <CirclePlay size={17} />}</button>
      <button type="button" disabled={readOnlyFixture} onClick={() => focusTimerStore.cancel()} aria-label="End focus session"><RotateCcw size={15} /></button>
    </div> : snapshot.status === 'complete' ? <button className="focus-complete-button" type="button" disabled={readOnlyFixture} onClick={() => focusTimerStore.cancel()} aria-label="Dismiss completed focus timer"><Check size={17} /></button> : <div className="focus-presets" aria-label="Start focus session">
      {[25, 50, 90].map((minutes) => <button type="button" key={minutes} disabled={readOnlyFixture} onClick={() => focusTimerStore.start(minutes as 25 | 50 | 90)}>{minutes}<small>MIN</small></button>)}
    </div>}
  </section>
}
