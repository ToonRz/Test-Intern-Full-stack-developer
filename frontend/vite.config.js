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
      // F-C1: key must match the axios baseURL (`/api/v1`). The previous
      // `/api` key proxied only `/api/...` but axios sent `/api/v1/...`,
      // so every dev request 404'd unless VITE_API_URL was set explicitly.
      '/api/v1': {
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
