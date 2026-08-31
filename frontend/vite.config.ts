import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-only: proxy API calls to the FastAPI backend (`uv run uvicorn
    // app.main:app --reload`, default port 8000) so the frontend can always
    // call same-origin relative URLs like `/api/v1/characters`. In
    // production, FastAPI serves this app's build directly (see
    // app/main.py), so no proxy is needed there.
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
