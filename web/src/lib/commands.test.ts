import { describe, expect, it } from 'vitest'
import { resolveCommand } from './commands'

describe('local command registry', () => {
  it('resolves safe command phrases after whitespace normalization', () => {
    expect(resolveCommand('  RUN   DEMO match ')).toBe('run_demo')
    expect(resolveCommand('show system health')).toBe('show_system_health')
    expect(resolveCommand('show match')).toBe('show_match')
    expect(resolveCommand('reset demo')).toBe('reset_demo')
    expect(resolveCommand('close')).toBe('close')
  })

  it('does not route unknown natural language as an application command', () => {
    expect(resolveCommand('what is happening today?')).toBeNull()
  })
})
