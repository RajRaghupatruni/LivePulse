import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SystemHealthPanel } from './SystemHealthPanel'
import type { SystemHealth } from '../types/livepulse'

const health: SystemHealth = {
  status: 'degraded',
  checked_at: '2026-09-12T20:00:00Z',
  components: {
    postgres: { name: 'postgres', status: 'healthy', detail: 'query_ok', checked_at: null, last_success_at: null },
    projector: { name: 'projector', status: 'degraded', detail: 'heartbeat_stale', checked_at: null, last_success_at: null },
  },
}

describe('SystemHealthPanel', () => {
  it('shows observed degradation details on expansion', () => {
    const onToggle = vi.fn()
    const view = render(<SystemHealthPanel health={health} requestState="available" open={false} onToggle={onToggle} />)
    expect(screen.getByText('SYSTEM DEGRADED')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /system degraded/i }))
    expect(onToggle).toHaveBeenCalledOnce()
    view.rerender(<SystemHealthPanel health={health} requestState="available" open onToggle={onToggle} />)
    expect(screen.getByText('PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('Event projector')).toBeInTheDocument()
    expect(screen.getByText('heartbeat stale')).toBeInTheDocument()
  })
})
