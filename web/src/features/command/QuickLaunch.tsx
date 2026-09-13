import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowUpRight, Clock3, Command, ExternalLink, Github, Home, Mail, MessageCircle, Search, Settings2, Timer, X } from 'lucide-react'
import { focusTimerStore } from '../focus/focusTimerStore'
import { externalTargetUrl, launchExternal, type ExternalTarget } from '../../lib/platform'

export type AppView = 'home' | 'timeline' | 'focus' | 'settings'
type Action = { id: string; title: string; detail: string; group: 'Launch' | 'LivePulse'; icon: ReactNode; target?: ExternalTarget; run?: () => void }

function launch(action: Action) {
  if (action.target) void launchExternal(action.target)
  action.run?.()
}

const launchItems: Array<{ id: ExternalTarget; title: string; icon: ReactNode }> = [
  { id: 'chatgpt', title: 'ChatGPT', icon: <MessageCircle size={17} /> },
  { id: 'github', title: 'GitHub', icon: <Github size={17} /> },
  { id: 'vscode', title: 'VS Code', icon: <ArrowUpRight size={17} /> },
  { id: 'portfolio', title: 'Portfolio', icon: <ExternalLink size={17} /> },
  { id: 'strata', title: 'Strata', icon: <ArrowUpRight size={17} /> },
]

export function QuickLaunch({ onOpen, onGoHome, onConfigure }: { onOpen: () => void; onGoHome: () => void; onConfigure: () => void }) {
  return <div className="quick-launch">
    <div className="quick-launch-reveal" aria-label="Quick destinations">
      <button className="launch-chip" type="button" title="Return to LivePulse Home" aria-label="Return to LivePulse Home" onClick={onGoHome}><Home size={17} /><span>LivePulse</span></button>
      {launchItems.map((item) => {
        const configured = Boolean(externalTargetUrl(item.id))
        return <button className={`launch-chip${configured ? '' : ' launch-chip-unconfigured'}`} type="button" key={item.id} title={configured ? `Open ${item.title}` : `Configure ${item.title} in Settings`} aria-label={configured ? `Open ${item.title}` : `Configure ${item.title} in Settings`} onClick={() => configured ? void launchExternal(item.id) : onConfigure()}>
        {item.icon}<span>{item.title}</span>
      </button>
      })}
      <button className="quick-launch-trigger" type="button" onClick={onOpen} aria-label="Open LivePulse command palette" aria-keyshortcuts="Control+K Meta+K"><Command size={17} aria-hidden="true" /><kbd>⌘ K</kbd></button>
    </div>
  </div>
}

export function CommandPalette({ onClose, onNavigate, onOpenGmail, onShowMatch, onShowHealth, onNextMatch, onPreviousMatch }: {
  onClose: () => void
  onNavigate: (view: AppView) => void
  onOpenGmail: () => void
  onShowMatch: () => void
  onShowHealth: () => void
  onNextMatch: () => void
  onPreviousMatch: () => void
}) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const actions = useMemo<Action[]>(() => [
    ...launchItems.map((item) => {
      const targetUrl = externalTargetUrl(item.id)
      return {
        id: item.id,
        title: targetUrl ? `Open ${item.title}` : `Configure ${item.title}`,
        detail: targetUrl ?? 'Set this destination in local Settings',
        group: 'Launch' as const,
        icon: item.icon,
        ...(targetUrl ? { target: item.id } : { run: () => onNavigate('settings') }),
      }
    }),
    { id: 'home', title: 'Go Home', detail: 'Return to the LivePulse overview', group: 'LivePulse', icon: <Home size={17} />, run: () => onNavigate('home') },
    { id: 'timeline', title: 'Open Timeline', detail: 'Review all recent signals', group: 'LivePulse', icon: <Clock3 size={17} />, run: () => onNavigate('timeline') },
    { id: 'focus', title: 'Open Focus', detail: 'Set a calm focus window', group: 'LivePulse', icon: <Timer size={17} />, run: () => onNavigate('focus') },
    { id: 'settings', title: 'Open Settings', detail: 'Inspect providers and runtime health', group: 'LivePulse', icon: <Settings2 size={17} />, run: () => { onNavigate('settings'); onShowHealth() } },
    { id: 'gmail', title: 'Open Gmail', detail: 'Review read-only message metadata', group: 'LivePulse', icon: <Mail size={17} />, run: onOpenGmail },
    { id: 'match', title: 'Open Current Match', detail: 'Bring the football instrument into view', group: 'LivePulse', icon: <ArrowUpRight size={17} />, run: onShowMatch },
    { id: 'match-next', title: 'Next match', detail: 'Select the next provider-reported fixture', group: 'LivePulse', icon: <ArrowUpRight size={17} />, run: onNextMatch },
    { id: 'match-previous', title: 'Previous match', detail: 'Select the previous provider-reported fixture', group: 'LivePulse', icon: <ArrowUpRight size={17} />, run: onPreviousMatch },
    ...([25, 50, 90] as const).map((minutes) => ({ id: `focus-${minutes}`, title: `Start focus · ${minutes} minutes`, detail: 'Quiet peripheral detail while preserving critical alerts', group: 'LivePulse' as const, icon: <Timer size={17} />, run: () => focusTimerStore.start(minutes) })),
  ], [onNavigate, onOpenGmail, onShowMatch, onShowHealth, onNextMatch, onPreviousMatch])
  const results = actions.filter((action) => `${action.title} ${action.detail}`.toLowerCase().includes(query.trim().toLowerCase()))

  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => { setActive(0) }, [query])
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((current) => Math.min(results.length - 1, current + 1)) }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive((current) => Math.max(0, current - 1)) }
    if (event.key === 'Enter' && results[active]) { event.preventDefault(); launch(results[active]); onClose() }
    if (event.key === 'Escape') { event.preventDefault(); onClose() }
  }
  const groups = ['Launch', 'LivePulse'] as const
  return <div className="command-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="command-palette" role="dialog" aria-modal="true" aria-label="Command LivePulse" onKeyDown={(event) => {
      if (event.key !== 'Tab') return
      const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)'))
      if (!focusable.length) return
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus() }
      else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus() }
    }}>
      <div className="palette-search"><Search size={19} aria-hidden="true" /><input ref={input} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={onKeyDown} placeholder="Search or launch" aria-label="Search commands and destinations" /><kbd>ESC</kbd><button className="palette-close" type="button" onClick={onClose} aria-label="Close command palette"><X size={17} /></button></div>
      <div className="palette-results" role="listbox" aria-label="Available commands">
        {groups.map((group) => {
          const groupResults = results.filter((action) => action.group === group)
          if (!groupResults.length) return null
          return <div className="palette-group" key={group}><h2>{group}</h2>{groupResults.map((action) => {
            const index = results.indexOf(action)
            return <button className={`command-result${index === active ? ' is-active' : ''}`} type="button" key={action.id} role="option" aria-selected={index === active} onMouseEnter={() => setActive(index)} onClick={() => { launch(action); onClose() }}><span className="command-result-icon">{action.icon}</span><span className="command-result-copy"><strong>{action.title}</strong><small>{action.detail}</small></span>{action.target ? <ExternalLink className="command-result-external" size={14} aria-hidden="true" /> : <span className="command-return">↵</span>}</button>
          })}</div>
        })}
        {results.length === 0 && <p className="palette-empty">No matching destination or command.</p>}
      </div>
      <footer className="palette-footer"><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>↵</kbd> Run command</span><span><kbd>ESC</kbd> Close</span></footer>
    </section>
  </div>
}
