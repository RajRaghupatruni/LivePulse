import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SystemPulse } from './SystemPulse'

describe('System Pulse diagnostics', () => {
  it('opens from the global health command while collapsed and closes with Escape', () => {
    render(<SystemPulse health={null} requestState="checking" connection="CONNECTING" />)

    expect(screen.queryByRole('complementary', { name: 'System diagnostics' })).not.toBeInTheDocument()
    fireEvent(window, new Event('livepulse:open-health'))
    expect(screen.getByRole('complementary', { name: 'System diagnostics' })).toBeInTheDocument()
    expect(screen.getByText('Resolving system state')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('complementary', { name: 'System diagnostics' })).not.toBeInTheDocument()
  })
})
