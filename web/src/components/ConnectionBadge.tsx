import { motion } from 'framer-motion'
import { Radio } from 'lucide-react'
import type { ConnectionState } from '../hooks/useLivePulse'

const labels: Record<ConnectionState, string> = {
  CONNECTING: 'CONNECTING',
  LIVE: 'SYSTEM LIVE',
  RECONNECTING: 'RECONNECTING',
  RESYNCING: 'RESYNCING',
  DEGRADED: 'DEGRADED',
}

export function ConnectionBadge({ state }: { state: ConnectionState }) {
  return (
    <motion.div className={`connection-badge ${state.toLowerCase()}`} layout transition={{ duration: 0.25 }} aria-live="polite">
      <Radio size={14} strokeWidth={1.8} />
      <span className="status-dot" />
      {labels[state]}
    </motion.div>
  )
}
