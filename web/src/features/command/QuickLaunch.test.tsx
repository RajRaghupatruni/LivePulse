import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QuickLaunch } from './QuickLaunch'

describe('QuickLaunch', () => {
  it('keeps the reference destinations visible and routes unset targets to Settings', async () => {
    const user = userEvent.setup()
    const onConfigure = vi.fn()

    render(<QuickLaunch onOpen={vi.fn()} onGoHome={vi.fn()} onConfigure={onConfigure} />)

    expect(screen.getByRole('button', { name: 'Open ChatGPT' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Open GitHub' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Open VS Code' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Configure Portfolio in Settings' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Configure Strata in Settings' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Configure Portfolio in Settings' }))
    expect(onConfigure).toHaveBeenCalledOnce()
  })

  it('returns Home and opens the local command palette from the dock', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const onGoHome = vi.fn()

    render(<QuickLaunch onOpen={onOpen} onGoHome={onGoHome} onConfigure={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Return to LivePulse Home' }))
    await user.click(screen.getByRole('button', { name: 'Open LivePulse command palette' }))

    expect(onGoHome).toHaveBeenCalledOnce()
    expect(onOpen).toHaveBeenCalledOnce()
  })
})
