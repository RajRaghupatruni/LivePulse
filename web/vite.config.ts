import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const apiTarget = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    watch: { ignored: ['../src-tauri/**'] },
    proxy: {
      // Preserve the loopback browser Host and Origin. The API intentionally
      // trusts exact local origins and must never see the internal Docker name.
      '/api': { target: apiTarget, changeOrigin: false },
      '/health': { target: apiTarget, changeOrigin: false },
      '/ws': {
        target: apiTarget.replace('http:', 'ws:').replace('https:', 'wss:'),
        ws: true,
        changeOrigin: false,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replaceAll('\\', '/')
          if (normalized.includes('/node_modules/three/')) return 'three'
          if (normalized.includes('/node_modules/@react-three/fiber/')) return 'react-three'
        },
      },
    },
  },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', css: true },
})
