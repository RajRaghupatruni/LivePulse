import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUpRight, Inbox, Mail, RefreshCw, Star } from 'lucide-react'
import { getGmailInbox, getGmailMessage, type GmailInbox as InboxSnapshot, type GmailMessage } from '../../lib/api'
import { beginAuthorization, launchExternal } from '../../lib/platform'
import type { ProviderHealth } from '../../types/livepulse'

function shortTime(value: string) {
  const date = new Date(value)
  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay ? date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function GmailPanel({ provider, expanded = false, showAll = false, onViewAll, onCloseAll, snapshotOverride }: { provider?: ProviderHealth; expanded?: boolean; showAll?: boolean; onViewAll?: () => void; onCloseAll?: () => void; snapshotOverride?: { value: InboxSnapshot | null; loading: boolean; available: boolean } }) {
  const [loadedInbox, setLoadedInbox] = useState<InboxSnapshot | null>(null)
  const [loadingFromProvider, setLoadingFromProvider] = useState(true)
  const inbox = snapshotOverride?.value ?? loadedInbox
  const loading = snapshotOverride?.loading ?? loadingFromProvider
  const [selected, setSelected] = useState<GmailMessage | null>(null)
  const [detail, setDetail] = useState<GmailMessage | null>(null)
  const [callbackMessage, setCallbackMessage] = useState('')
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const viewAllTriggerRef = useRef<HTMLButtonElement | null>(null)
  const expandedCloseRef = useRef<HTMLButtonElement | null>(null)
  const expandedDialogRef = useRef<HTMLElement | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const dialogRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const url = new URL(window.location.href)
    const result = url.searchParams.get('gmail')
    if (result === 'connected') {
      setCallbackMessage('Gmail connected. Read-only sync is starting.')
    } else if (result === 'error') {
      const reason = url.searchParams.get('reason')
      setCallbackMessage(reason === 'authorization_denied'
        ? 'Gmail authorization was denied. You can try connecting again.'
        : reason === 'state_invalid'
          ? 'Gmail authorization could not be verified. Please start again.'
          : reason === 'authorization_incomplete' || reason === 'callback_invalid'
            ? 'Gmail authorization was incomplete. Please try again.'
            : reason === 'setup_required'
              ? 'Gmail OAuth setup is unavailable. Check the local provider configuration.'
              : 'Gmail connection could not be completed. Please try again.')
    } else {
      return
    }
    url.searchParams.delete('gmail')
    url.searchParams.delete('reason')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])

  const refresh = useCallback(async () => {
    if (provider?.configured === false) {
      setLoadedInbox({ status: 'not_configured', configured: false, messages: [] })
      setLoadingFromProvider(false)
      return
    }
    try {
      const result = await getGmailInbox(expanded ? 20 : 4)
      setLoadedInbox(result)
    } catch {
      setLoadedInbox((current) => current ?? { status: 'unavailable', configured: Boolean(provider?.configured), messages: [] })
    } finally {
      setLoadingFromProvider(false)
    }
  }, [expanded, provider?.configured])

  useEffect(() => {
    if (snapshotOverride) return
    let disposed = false
    const run = async () => {
      await refresh()
      if (!disposed) timer = window.setTimeout(() => void run(), 60_000)
    }
    let timer = 0
    void run()
    return () => { disposed = true; window.clearTimeout(timer) }
  }, [refresh, snapshotOverride])

  const openMessage = async (message: GmailMessage) => {
    setSelected(message)
    try { setDetail(await getGmailMessage(message.message_id)) } catch { setDetail(message) }
  }
  const closeMessage = useCallback(() => {
    setSelected(null)
    setDetail(null)
    requestAnimationFrame(() => triggerRef.current?.focus())
  }, [])
  const closeAll = useCallback(() => {
    onCloseAll?.()
    requestAnimationFrame(() => viewAllTriggerRef.current?.focus())
  }, [onCloseAll])
  useEffect(() => {
    if (!showAll) return
    expandedCloseRef.current?.focus()
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        closeAll()
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [closeAll, showAll])
  useEffect(() => {
    if (!selected) return
    closeButtonRef.current?.focus()
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        closeMessage()
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [closeMessage, selected])
  const trapFocus = (event: KeyboardEvent<HTMLElement>, dialog: HTMLElement | null) => {
    if (event.key !== 'Tab') return
    const focusable = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled)') ?? [])
    if (!focusable.length) return
    if (event.shiftKey && document.activeElement === focusable[0]) {
      event.preventDefault()
      focusable.at(-1)?.focus()
    } else if (!event.shiftKey && document.activeElement === focusable.at(-1)) {
      event.preventDefault()
      focusable[0].focus()
    }
  }
  const trapTab = (event: KeyboardEvent<HTMLElement>) => trapFocus(event, dialogRef.current)
  const trapExpandedTab = (event: KeyboardEvent<HTMLElement>) => trapFocus(event, expandedDialogRef.current)
  const configured = inbox?.configured ?? provider?.configured
  const status = inbox?.status
  const renderMessages = (extraClass = '') => <div className={`gmail-list${extraClass ? ` ${extraClass}` : ''}`} role="list" aria-label="Recent messages">
    {(inbox?.messages ?? []).map((message) => <div className="gmail-message-item" role="listitem" key={message.message_id}>
      <button className={`gmail-message${message.is_unread ? ' is-unread' : ''}${selected?.message_id === message.message_id ? ' is-selected' : ''}`} type="button" aria-label={`${message.sender}: ${message.subject}`} onClick={(event) => { triggerRef.current = event.currentTarget; void openMessage(message) }}>
        <span className="gmail-message-avatar" aria-hidden="true">{message.sender.trim().charAt(0).toUpperCase() || '•'}</span>
        <span className="gmail-message-copy"><span className="gmail-message-line"><strong>{message.sender || 'Unknown sender'}</strong><time dateTime={message.received_at}>{shortTime(message.received_at)}</time></span><span className="gmail-message-subject">{message.is_important && <Star size={11} fill="currentColor" aria-label="Important" />}{message.subject}</span><span className="gmail-message-snippet">{message.snippet}</span></span>
        {message.is_unread && <i className="gmail-unread-mark" aria-label="Unread" />}
      </button>
    </div>)}
  </div>

  return <section className={`gmail-panel${expanded ? ' gmail-panel-expanded' : ''}`} id="gmail" aria-label="Gmail">
    <header className="surface-heading">
      <span className="surface-icon gmail-icon"><Mail size={16} aria-hidden="true" /></span>
      <div><span className="surface-overline">PERSONAL INBOX</span><h2>Gmail</h2></div>
      <span className={`surface-live-mark${provider?.status === 'healthy' ? ' is-ready' : ''}`} title={provider?.status ?? 'Awaiting provider'} />
      <button className="surface-refresh" type="button" aria-label="Refresh Gmail" onClick={() => { setLoadingFromProvider(true); void refresh() }}><RefreshCw size={14} /></button>
    </header>
    {callbackMessage && <p className="gmail-oauth-feedback" role="status">{callbackMessage}</p>}
    {loading && !inbox ? <div className="gmail-state"><span className="quiet-spinner" /><strong>Resolving inbox</strong><small>Read-only metadata from your connected account</small></div>
      : configured === false || status === 'not_configured' || status === 'disconnected' ? <div className="gmail-state gmail-state-setup"><Inbox size={19} /><strong>{configured === false ? 'Gmail setup required' : 'Reconnect Gmail'}</strong><small>{configured === false ? 'Add Google OAuth credentials and local encryption configuration to the backend.' : 'Read-only access. Message bodies are not retained.'}</small>{configured !== false && <button type="button" className="text-action" onClick={() => void beginAuthorization('/api/v1/providers/gmail/oauth/start')}>Connect account <ArrowUpRight size={13} /></button>}</div>
        : status === 'unavailable' || !inbox ? <div className="gmail-state"><span className="state-mark state-mark-warning" /><strong>Inbox unavailable</strong><small>System Pulse has the provider freshness details.</small></div>
          : inbox.messages.length === 0 ? <div className="gmail-state"><Inbox size={18} /><strong>Inbox is clear</strong><small>No recent message metadata was returned.</small></div>
            : renderMessages()}
    <footer className="gmail-footer"><span>{provider?.status === 'healthy' ? 'SYNCED' : provider?.status?.toUpperCase() ?? 'LOCAL READ-ONLY'}</span><button ref={viewAllTriggerRef} type="button" onClick={onViewAll} aria-label={showAll ? 'Close expanded Gmail inbox' : 'View all Gmail messages'}>{showAll ? 'Close' : 'View all'} <ArrowUpRight size={13} /></button><button className="gmail-external" type="button" onClick={() => void launchExternal('gmail')} aria-label="Open Gmail externally"><ArrowUpRight size={13} /></button></footer>
    {showAll && createPortal(<div className="gmail-expanded-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeAll() }}>
      <section ref={expandedDialogRef} className="gmail-expanded-dialog" role="dialog" aria-modal="true" aria-labelledby="gmail-expanded-title" onKeyDown={trapExpandedTab}>
        <header><div><span>PERSONAL INBOX · READ ONLY</span><h2 id="gmail-expanded-title">Recent messages</h2><p>Bounded message metadata from the connected account.</p></div><button ref={expandedCloseRef} type="button" onClick={closeAll} aria-label="Close expanded Gmail inbox">×</button></header>
        {loading && !inbox ? <div className="gmail-state"><span className="quiet-spinner" /><strong>Resolving inbox</strong><small>Read-only metadata from your connected account</small></div>
          : configured === false || status === 'not_configured' || status === 'disconnected' ? <div className="gmail-state gmail-state-setup"><Inbox size={19} /><strong>{configured === false ? 'Gmail setup required' : 'Reconnect Gmail'}</strong><small>{configured === false ? 'Add Google OAuth credentials and local encryption configuration to the backend.' : 'Read-only access. Message bodies are not retained.'}</small>{configured !== false && <button type="button" className="text-action" onClick={() => void beginAuthorization('/api/v1/providers/gmail/oauth/start')}>Connect account <ArrowUpRight size={13} /></button>}</div>
            : status === 'unavailable' || !inbox ? <div className="gmail-state"><span className="state-mark state-mark-warning" /><strong>Inbox unavailable</strong><small>System Pulse has the provider freshness details.</small></div>
              : inbox.messages.length === 0 ? <div className="gmail-state"><Inbox size={18} /><strong>Inbox is clear</strong><small>No recent message metadata was returned.</small></div>
                : renderMessages('gmail-expanded-list')}
        <footer><span>MESSAGE BODIES ARE NOT STORED</span><button type="button" onClick={() => void launchExternal('gmail')}>Open Gmail <ArrowUpRight size={14} /></button></footer>
      </section>
    </div>, document.body)}
    {selected && createPortal(<div className="gmail-detail-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeMessage() }}>
      <section ref={dialogRef} className="gmail-detail" role="dialog" aria-modal="true" aria-labelledby="gmail-detail-title" onKeyDown={trapTab}>
        <header><span>MESSAGE METADATA · READ ONLY</span><button ref={closeButtonRef} type="button" onClick={closeMessage} aria-label="Close message">×</button></header>
        <h3 id="gmail-detail-title">{detail?.subject ?? selected.subject}</h3><p>{detail?.sender ?? selected.sender}</p><time dateTime={detail?.received_at ?? selected.received_at}>{new Date(detail?.received_at ?? selected.received_at).toLocaleString()}</time><div className="gmail-detail-snippet">{detail?.snippet ?? selected.snippet}</div>
        <footer><span>BODY NOT STORED</span><button type="button" onClick={() => void launchExternal('gmail')}>Open in Gmail <ArrowUpRight size={14} /></button></footer>
      </section>
    </div>, document.body)}
  </section>
}
