import { motion, useReducedMotion } from 'framer-motion'
import { Radio } from 'lucide-react'
import type { ConnectionState } from '../hooks/useLivePulse'

const labels: Record<ConnectionState, string> = {
  CONNECTING: 'CONNECTING',
  LIVE: 'LIVE',
  RECONNECTING: 'RECONNECTING…',
  RESYNCING: 'RESYNCING…',
  DEGRADED: 'DEGRADED',
}

export function ConnectionBadge({ state }: { state: ConnectionState }) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.div className={`connection-badge ${state.toLowerCase()}`} layout={!reduceMotion} transition={{ duration: reduceMotion ? 0 : 0.25 }} role="status" aria-live="polite">
      <Radio size={14} strokeWidth={1.8} />
      <span className="status-dot" aria-hidden="true" />
      {labels[state]}
    </motion.div>
  )
}
