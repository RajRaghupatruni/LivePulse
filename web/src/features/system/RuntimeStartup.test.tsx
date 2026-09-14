import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RuntimeStartup } from './RuntimeStartup'

describe('desktop startup surface', () => {
  it('communicates waiting for readiness without exposing a technical error', () => {
    render(<RuntimeStartup state="starting" onRetry={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Starting LivePulse services' })).toBeInTheDocument()
    expect(screen.getByText('CHECKING BACKEND READINESS')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })

  it('offers retry when the backend is unavailable', () => {
    const retry = vi.fn()
    render(<RuntimeStartup state="unavailable" onRetry={retry} />)

    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }))
    expect(retry).toHaveBeenCalledOnce()
    expect(screen.getByText(/Start the LivePulse service stack/)).toBeInTheDocument()
  })
})
