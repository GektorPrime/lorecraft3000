import { describe, expect, it } from 'vitest'
import { isTrustedProxyOrigin } from './vite.config'

describe('isTrustedProxyOrigin', () => {
  it('accepts the same LAN origin that served the frontend', () => {
    expect(isTrustedProxyOrigin('http://192.168.1.20:5173', '192.168.1.20:5173')).toBe(true)
  })

  it('rejects origins from a different host or port', () => {
    expect(isTrustedProxyOrigin('https://example.com', '192.168.1.20:5173')).toBe(false)
    expect(isTrustedProxyOrigin('http://192.168.1.20:4173', '192.168.1.20:5173')).toBe(false)
  })

  it('keeps private development tunnel origins trusted', () => {
    expect(isTrustedProxyOrigin('https://private.devtunnels.ms', 'localhost:5173')).toBe(true)
    expect(isTrustedProxyOrigin('https://workspace.app.github.dev', 'localhost:5173')).toBe(true)
  })

  it('rejects malformed origins and missing request hosts', () => {
    expect(isTrustedProxyOrigin('not a URL', '192.168.1.20:5173')).toBe(false)
    expect(isTrustedProxyOrigin('http://192.168.1.20:5173', undefined)).toBe(false)
  })
})
