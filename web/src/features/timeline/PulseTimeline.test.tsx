import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PulseTimeline } from './PulseTimeline'

describe('PulseTimeline', () => {
  it('distinguishes a material event and reveals safe chronology metadata on demand', () => {
    const item = {
      cursor: 1, event_id: 'evt-1', event_type: 'football.match.goal', source: 'football', subject_id: 'match-1',
      timestamp: '2026-09-12T20:00:00Z', observed_at: '2026-09-12T20:00:01Z',
      payload: { side: 'home', home_team: 'Northstar FC', player: 'M. Vale', minute: 28 },
    }
    render(<PulseTimeline items={[item]} />)
    expect(screen.getByText('Goal')).toBeInTheDocument()
    expect(screen.getByText('M. Vale · Northstar FC')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Goal/ }))
    expect(screen.getByText('football')).toBeInTheDocument()
    expect(screen.getByText('Observed')).toBeInTheDocument()
  })

  it('keeps an explicit empty state and offers cursor history when available', () => {
    const onLoadOlder = vi.fn()
    render(<PulseTimeline items={[]} hasOlder onLoadOlder={onLoadOlder} />)
    expect(screen.getByText('Timeline establishing')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Load earlier events/ }))
    expect(onLoadOlder).toHaveBeenCalledOnce()
  })

  it('moves among timeline rows with the arrow and boundary keys', () => {
    const items = ['one', 'two', 'three'].map((id, cursor) => ({
      cursor: cursor + 1,
      event_id: id,
      event_type: 'developer.workflow.completed',
      source: 'github',
      subject_id: id,
      timestamp: `2026-09-12T20:00:0${cursor}Z`,
      payload: { repository: `repo-${id}` },
    }))
    render(<PulseTimeline items={items} />)
    const rows = screen.getAllByRole('button', { name: /workflow completed/i })
    rows[0].focus()
    fireEvent.keyDown(rows[0], { key: 'ArrowDown' })
    expect(rows[1]).toHaveFocus()
    fireEvent.keyDown(rows[1], { key: 'End' })
    expect(rows[2]).toHaveFocus()
    fireEvent.keyDown(rows[2], { key: 'Home' })
    expect(rows[0]).toHaveFocus()
  })

  it('does not treat history as an arrival and marks only the newly delivered event', () => {
    const items = ['old', 'new'].map((id, cursor) => ({
      cursor: cursor + 1, event_id: id, event_type: 'mail.message.received', source: 'gmail', subject_id: id,
      timestamp: `2026-09-12T20:00:0${cursor}Z`, payload: {},
    }))
    const view = render(<PulseTimeline items={items} />)
    expect(document.querySelectorAll('.timeline-entry-arriving')).toHaveLength(0)
    expect(document.querySelector('.timeline-entry')?.getAttribute('style') ?? '').not.toContain('opacity: 0')
    view.rerender(<PulseTimeline items={items} arrivalId="new" />)
    expect(document.querySelectorAll('.timeline-entry-arriving')).toHaveLength(1)
    expect(document.querySelector('.timeline-entry-arriving .timeline-entry-main')).toHaveAttribute('data-event-id', 'new')
  })
})
