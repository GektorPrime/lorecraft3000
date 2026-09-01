import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OptionsSummary } from './api/types'

const originalFetch = globalThis.fetch
const OPTIONS: OptionsSummary = {
  models: ['test-model'],
  image_sizes: ['1K'],
  aspect_ratios: ['3:2'],
  ref_image_roles: ['face_front'],
  default_model: 'test-model',
  default_image_size: '1K',
  daily_spend_cap_cents: 300,
  spent_today_cents: 0,
  remaining_today_cents: 300,
  ref_image_weight_explanation: 'Reference weight',
  ref_set_immutability_explanation: 'Reference sets are immutable',
  panel_immutability_explanation: 'Panels are immutable',
}

const jsonResponse = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

function resolvedAppFetch() {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/options/summary')) return Promise.resolve(jsonResponse(OPTIONS))
    if (url.endsWith('/styles')) return Promise.resolve(jsonResponse([]))
    throw new Error(`Unexpected request: ${url}`)
  })
}

describe('App routing', () => {
  beforeEach(() => {
    globalThis.fetch = resolvedAppFetch()
    vi.resetModules()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  async function renderApp(hash: string) {
    window.location.hash = hash
    const { default: App } = await import('./App')
    render(<App />)
  }

  it('keeps valid routes under the configured shared layout', async () => {
    await renderApp('#/styles')

    await waitFor(() => expect(document.title).toBe('Styles | LoreCraft3000'))
    expect(window.location.hash).toBe('#/styles')
    expect(await screen.findByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Styles' })).toBeInTheDocument()
  })

  it('renders wildcard routes without entering the configured layout', async () => {
    await renderApp('#/missing/path')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/missing/path')
    expect(globalThis.fetch).not.toHaveBeenCalled()
    expect(screen.queryByRole('navigation', { name: 'Primary' })).not.toBeInTheDocument()
  })

  it.each([
    '#/characters/nope',
    '#/characters/0/edit',
    '#/styles/01/edit',
    '#/panels/-1/edit',
    '#/panels/1.5/preview',
    '#/generations/9007199254740992',
  ])('redirects malformed dynamic IDs to hash not-found without loading config: %s', async (hash) => {
    globalThis.fetch = vi.fn().mockImplementation(() => new Promise(() => {}))
    await renderApp(hash)

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#/not-found'))
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
