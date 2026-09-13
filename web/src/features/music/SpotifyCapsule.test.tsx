import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { SpotifyCapsule } from './SpotifyCapsule'

describe('SpotifyCapsule', () => {
  afterEach(() => window.history.replaceState({}, '', '/'))

  it('does not present a successful empty endpoint as configured playback', () => {
    render(<SpotifyCapsule
      snapshot={{ value: { provider: 'spotify', playback: null, observed_at: null, freshness_seconds: null }, loading: false, available: true }}
      provider={{ provider: 'spotify', status: 'disconnected', configured: false, checked_at: null, last_success_at: null, last_failure_at: null, last_observation_at: null, consecutive_failures: 0, rate_limited_until: null, detail_code: 'configuration_missing' }}
    />)

    expect(screen.getByText('NOT CONFIGURED')).toBeInTheDocument()
    expect(screen.getByText('Spotify is not configured')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start playback' })).toBeDisabled()
  })

  it('shows a bounded Spotify authorization error from the callback URL', () => {
    window.history.replaceState({}, '', '/?spotify=error&reason=authorization_denied')
    render(<SpotifyCapsule
      snapshot={{ value: { provider: 'spotify', playback: null, observed_at: null, freshness_seconds: null }, loading: false, available: true }}
      provider={{ provider: 'spotify', status: 'disconnected', configured: true, checked_at: null, last_success_at: null, last_failure_at: null, last_observation_at: null, consecutive_failures: 0, rate_limited_until: null, detail_code: 'not_connected' }}
    />)

    expect(screen.getByRole('status')).toHaveTextContent('Spotify authorization was denied')
    expect(window.location.search).toBe('')
  })
})
