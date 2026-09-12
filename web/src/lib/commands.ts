export type LocalCommand = 'run_demo' | 'reset_demo' | 'show_system_health' | 'show_match' | 'close'

const commandRegistry: ReadonlyArray<{ command: LocalCommand; phrases: readonly string[] }> = [
  { command: 'run_demo', phrases: ['run demo', 'run demo match'] },
  { command: 'reset_demo', phrases: ['reset demo', 'reset demo match'] },
  { command: 'show_system_health', phrases: ['show system health', 'system health'] },
  { command: 'show_match', phrases: ['show match', 'focus match'] },
  { command: 'close', phrases: ['close'] },
]

export function resolveCommand(input: string): LocalCommand | null {
  const normalized = input.trim().toLowerCase().split(/\s+/).join(' ')
  return commandRegistry.find(({ phrases }) => phrases.includes(normalized))?.command ?? null
}
