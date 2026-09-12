import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PulseTimeline } from './PulseTimeline'

describe('PulseTimeline', () => {
  it('renders event history and empty state', () => {
    const item = {
      cursor: 1, event_id: 'evt-1', event_type: 'football.match.goal', subject_id: 'demo-1',
      timestamp: '2026-09-12T20:00:00Z', payload: { side: 'home', home_team: 'Northstar FC', player: 'M. Vale', minute: 28 },
    }
    const { rerender } = render(<PulseTimeline items={[]} />)
    expect(screen.getByText('Your signal, in sequence.')).toBeInTheDocument()
    rerender(<PulseTimeline items={[item]} />)
    expect(screen.getByText('Goal')).toBeInTheDocument()
    expect(screen.getByText('M. Vale · Northstar FC')).toBeInTheDocument()
    expect(screen.getByText('28′')).toBeInTheDocument()
  })
})
