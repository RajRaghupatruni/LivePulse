import { ArrowUpRight, Command } from 'lucide-react'

export function CommandBar() {
  return (
    <div className="command-dock" aria-label="Command bar placeholder">
      <div className="command-mark"><Command size={16} /></div>
      <input aria-label="Ask anything or control LivePulse" placeholder="Ask anything or control LivePulse..." disabled />
      <kbd>⌘ K</kbd>
      <button aria-label="Command bar unavailable in M1" disabled><ArrowUpRight size={16} /></button>
    </div>
  )
}
