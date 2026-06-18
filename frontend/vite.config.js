import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Default proxy target is `backend:8000` for Docker; `npm run dev` on the
// host (without Docker) falls back to localhost:8000.
const devProxyTarget = process.env.VITE_DEV_PROXY || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: devProxyTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.js'],
    css: true,
  },
})
