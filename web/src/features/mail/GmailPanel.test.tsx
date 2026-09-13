import { fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
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
