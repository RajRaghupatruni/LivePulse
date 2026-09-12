import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUpRight, Command, X } from 'lucide-react'
import { resolveCommand } from '../lib/commands'

export type ConversationMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  delivery: 'complete' | 'streaming'
  citations?: Array<{ label: string; href: string }>
  codeBlocks?: Array<{ language: string; code: string }>
}

type CommandBarProps = {
  onRunDemo: () => Promise<boolean>
  onReset: () => Promise<boolean>
  onShowHealth: () => void
  onShowMatch: () => void
}

export function CommandBar({ onRunDemo, onReset, onShowHealth, onShowMatch }: CommandBarProps) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const nextId = useRef(0)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen(true)
      } else if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const addMessage = (role: ConversationMessage['role'], content: string) => {
    nextId.current += 1
    setMessages((current) => [...current, { id: nextId.current, role, content, delivery: 'complete' }])
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const input = value.trim()
    if (!input || busy) return
    setValue('')
    setOpen(true)
    addMessage('user', input)
    const command = resolveCommand(input)
    if (!command) {
      addMessage('assistant', 'AI chat connects in the intelligence milestone.')
      return
    }
    if (command === 'close') {
      setOpen(false)
      return
    }

    setBusy(true)
    try {
      if (command === 'run_demo') {
        addMessage('assistant', await onRunDemo() ? 'Demo match started.' : 'Could not start the demo. Review the status message on the focus surface.')
      } else if (command === 'reset_demo') {
        addMessage('assistant', await onReset() ? 'Demo state reset.' : 'Could not reset the demo. Review the status message on the focus surface.')
      } else if (command === 'show_system_health') {
        onShowHealth()
        addMessage('assistant', 'System health details are open.')
      } else if (command === 'show_match') {
        onShowMatch()
        addMessage('assistant', 'Showing the current match focus.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="command-surface">
      {open && (
        <section className="command-panel" aria-label="LivePulse command conversation">
          <div className="command-panel-heading">
            <div><span className="eyebrow">LOCAL COMMAND ROUTER · AI NOT CONNECTED</span><h2>What do you need?</h2></div>
            <button className="icon-button" type="button" aria-label="Close command panel" onClick={() => setOpen(false)}><X size={15} /></button>
          </div>
          {messages.length === 0 ? (
            <p className="command-empty">Run demo · Reset demo · Show system health · Show match</p>
          ) : (
            <div className="command-messages" role="log" aria-live="polite" aria-relevant="additions">
              {messages.map((message) => (
                <article className={`command-message role-${message.role}`} key={message.id}>
                  <span>{message.role === 'user' ? 'YOU' : 'LIVEPULSE'}</span>
                  <p>{message.content}</p>
                  {message.delivery === 'streaming' && <span className="streaming-status">RESPONSE IN PROGRESS</span>}
                  {message.codeBlocks?.map((block, index) => (
                    <pre className="command-code" key={`${message.id}-code-${index}`}><code data-language={block.language}>{block.code}</code></pre>
                  ))}
                  {message.citations && message.citations.length > 0 && (
                    <ul className="command-citations">
                      {message.citations.map((citation) => <li key={citation.href}><a href={citation.href} target="_blank" rel="noreferrer">{citation.label}</a></li>)}
                    </ul>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      )}
      <form className="command-dock" onSubmit={(event) => void submit(event)}>
        <div className="command-mark"><Command size={16} /></div>
        <input
          ref={inputRef}
          aria-label="Ask anything or control LivePulse"
          aria-keyshortcuts="Control+K Meta+K"
          placeholder="Ask anything or control LivePulse..."
          value={value}
          disabled={busy}
          onFocus={() => setOpen(true)}
          onChange={(event) => setValue(event.target.value)}
        />
        <kbd aria-hidden="true">⌘ K</kbd>
        <button type="submit" aria-label="Send command" disabled={busy || value.trim().length === 0}>
          <ArrowUpRight size={16} />
        </button>
      </form>
    </div>
  )
}
