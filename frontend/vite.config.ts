import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const tunnelHostSuffixes = ['.devtunnels.ms', '.app.github.dev']

function isTunnelOrigin(value: string): boolean {
  try {
    const hostname = new URL(value).hostname
    return tunnelHostSuffixes.some((suffix) => hostname.endsWith(suffix))
  } catch {
    return false
  }
}

export function isTrustedProxyOrigin(origin: string, requestHost: string | undefined): boolean {
  if (isTunnelOrigin(origin)) return true
  try {
    return requestHost !== undefined && new URL(origin).host === requestHost
  } catch {
    return false
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Permit VS Code port-forwarding and Codespaces URLs without disabling
    // Vite's DNS-rebinding protection for arbitrary hosts. Keep tunnels private.
    allowedHosts: tunnelHostSuffixes,
    // Dev-only: proxy API calls to the FastAPI backend (`uv run uvicorn
    // app.main:app --reload`, default port 8000) so the frontend can always
    // call same-origin relative URLs like `/api/v1/characters`. In
    // production, FastAPI serves this app's build directly (see
    // app/main.py), so no proxy is needed there.
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest, request) => {
            // Dev Tunnels supplies the public browser IP. Do not forward it to
            // Uvicorn, which would otherwise replace Vite's loopback peer and
            // trigger the backend's local-request guard.
            proxyRequest.removeHeader('forwarded')
            proxyRequest.removeHeader('x-forwarded-for')
            proxyRequest.removeHeader('x-forwarded-host')
            proxyRequest.removeHeader('x-forwarded-port')
            proxyRequest.removeHeader('x-forwarded-proto')

            const origin = request.headers.origin
            if (origin && isTrustedProxyOrigin(origin, request.headers.host)) {
              proxyRequest.setHeader('origin', 'http://127.0.0.1:8000')
            }
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
