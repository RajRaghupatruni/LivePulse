import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ConnectionBadge } from './ConnectionBadge'

describe('ConnectionBadge', () => {
  it.each([
    ['LIVE', 'LIVE'],
    ['RECONNECTING', 'RECONNECTING…'],
    ['RESYNCING', 'RESYNCING…'],
    ['DEGRADED', 'DEGRADED'],
  ] as const)('communicates %s in text as well as color', (state, label) => {
    const { rerender } = render(<ConnectionBadge state={state} />)
    expect(screen.getByRole('status')).toHaveTextContent(label)
    rerender(<ConnectionBadge state={state} />)
  })
})
