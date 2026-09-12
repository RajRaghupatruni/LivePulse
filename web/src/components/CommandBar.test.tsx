import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CommandBar } from './CommandBar'

describe('CommandBar', () => {
  const actions = () => ({
    onRunDemo: vi.fn(async () => true),
    onReset: vi.fn(async () => true),
    onShowHealth: vi.fn(),
    onShowMatch: vi.fn(),
  })

  it('opens and focuses from the Ctrl+K shortcut', () => {
    render(<CommandBar {...actions()} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    expect(screen.getByLabelText('LivePulse command conversation')).toBeInTheDocument()
    expect(screen.getByLabelText('Ask anything or control LivePulse')).toHaveFocus()
  })

  it('opens and focuses from the Cmd+K shortcut', () => {
    render(<CommandBar {...actions()} />)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(screen.getByLabelText('LivePulse command conversation')).toBeInTheDocument()
    expect(screen.getByLabelText('Ask anything or control LivePulse')).toHaveFocus()
  })

  it('routes a deterministic command and clearly declines unknown AI input', async () => {
    const user = userEvent.setup()
    const handlers = actions()
    render(<CommandBar {...handlers} />)
    const input = screen.getByLabelText('Ask anything or control LivePulse')
    await user.type(input, 'show system health{Enter}')
    expect(handlers.onShowHealth).toHaveBeenCalledOnce()
    expect(screen.getByText('System health details are open.')).toBeInTheDocument()

    await user.type(input, 'tell me a story{Enter}')
    expect(screen.getByText('AI chat connects in the intelligence milestone.')).toBeInTheDocument()
  })

  it('runs the demo through its normal application action', async () => {
    const user = userEvent.setup()
    const handlers = actions()
    render(<CommandBar {...handlers} />)
    await user.type(screen.getByLabelText('Ask anything or control LivePulse'), 'run demo{Enter}')
    expect(handlers.onRunDemo).toHaveBeenCalledOnce()
    expect(screen.getByText('Demo match started.')).toBeInTheDocument()
  })
})
