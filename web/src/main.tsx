import React from 'react'
import ReactDOM from 'react-dom/client'
import { MotionConfig } from 'framer-motion'
import App from './pages/App'
import { initializeTauriPlatform } from './lib/tauriPlatform'
import './styles.css'

async function mountLivePulse() {
  try {
    await initializeTauriPlatform()
  } catch {
    // Keep browser fallback usable if native capability detection is unavailable.
  }
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <MotionConfig reducedMotion="user">
        <App />
      </MotionConfig>
    </React.StrictMode>,
  )
}

void mountLivePulse()
