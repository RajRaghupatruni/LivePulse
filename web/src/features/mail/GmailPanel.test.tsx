import { fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import type { GmailInbox, GmailMessage } from '../../lib/api'
import { GmailPanel } from './GmailPanel'

const message: GmailMessage = {
  message_id: 'message-1',
  thread_id: 'thread-1',
  sender: 'Alex Chen',
  subject: 'Re: Vacation plans',
  received_at: '2026-09-13T18:00:00Z',
  snippet: 'The updated itinerary is ready.',
  is_unread: true,
  is_important: true,
}
const inbox: GmailInbox = { status: 'ready', configured: true, messages: [message] }
const snapshotOverride = { value: inbox, loading: false, available: true }

function GmailHarness() {
  const [showAll, setShowAll] = useState(false)
  return <GmailPanel
    expanded={showAll}
    showAll={showAll}
    onViewAll={() => setShowAll((current) => !current)}
    onCloseAll={() => setShowAll(false)}
    snapshotOverride={snapshotOverride}
  />
}

describe('read-only Gmail expansion', () => {
  afterEach(() => window.history.replaceState({}, '', '/'))

  it('shows a bounded Gmail callback result and removes it from the address bar', () => {
    window.history.replaceState({}, '', '/?gmail=error&reason=authorization_denied')
    render(<GmailPanel provider={{ provider: 'gmail', status: 'disconnected', configured: true, checked_at: null, last_success_at: null, last_failure_at: null, last_observation_at: null, consecutive_failures: 0, rate_limited_until: null, detail_code: 'not_connected' }} snapshotOverride={{ value: { status: 'disconnected', configured: true, messages: [] }, loading: false, available: true }} />)

    expect(screen.getByRole('status')).toHaveTextContent('Gmail authorization was denied')
    expect(window.location.search).toBe('')
  })

  it('shows successful connection feedback and removes its callback query', () => {
    window.history.replaceState({}, '', '/?gmail=connected')
    render(<GmailPanel snapshotOverride={{ value: inbox, loading: false, available: true }} />)

    expect(screen.getByRole('status')).toHaveTextContent('Gmail connected. Read-only sync is starting.')
    expect(window.location.search).toBe('')
  })

  it('opens the full inbox overlay, opens message metadata, and closes with Escape', async () => {
    render(<GmailHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'View all Gmail messages' }))

    const expandedInbox = screen.getByRole('dialog', { name: 'Recent messages' })
    expect(expandedInbox).toBeInTheDocument()
    fireEvent.click(within(expandedInbox).getByRole('button', { name: 'Alex Chen: Re: Vacation plans' }))
    expect(await screen.findByText('MESSAGE METADATA · READ ONLY')).toBeInTheDocument()
    expect(screen.getByText('BODY NOT STORED')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close message' }))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Recent messages' })).not.toBeInTheDocument()
  })
})
