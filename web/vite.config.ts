import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const apiTarget = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': apiTarget, '/health': apiTarget, '/ws': { target: apiTarget.replace('http:', 'ws:').replace('https:', 'wss:'), ws: true } } },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', css: true },
})
