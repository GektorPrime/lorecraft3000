import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  scene_immutability_explanation: 'Scenes are immutable',
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
    if (url.endsWith('/characters')) return Promise.resolve(jsonResponse([]))
    if (url.endsWith('/styles')) return Promise.resolve(jsonResponse([]))
    if (url.endsWith('/base-stages/archived')) return Promise.resolve(jsonResponse([]))
    if (url.endsWith('/base-stages')) return Promise.resolve(jsonResponse([]))
    if (url.endsWith('/scenes')) return Promise.resolve(jsonResponse([]))
    if (url.endsWith('/panels')) return Promise.resolve(jsonResponse([]))
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

    // The sidebar groups links by workflow rather than preserving the old
    // topbar's arbitrary flat order.
    const library = screen.getByRole('list', { name: 'Library' })
    expect(within(library).getByRole('link', { name: 'Characters' })).toBeInTheDocument()
    expect(within(library).getByRole('link', { name: 'Styles' })).toBeInTheDocument()
    expect(within(library).getByRole('link', { name: 'Base Stages' })).toBeInTheDocument()

    const work = screen.getByRole('list', { name: 'Work' })
    expect(within(work).getByRole('link', { name: 'Scenes' })).toBeInTheDocument()
    expect(within(work).getByRole('link', { name: 'Panels' })).toBeInTheDocument()
    expect(within(work).getByRole('link', { name: 'Gallery' })).toBeInTheDocument()
  })

  it('renders the base stage library route without a generated-stage action', async () => {
    await renderApp('#/base-stages')

    expect(await screen.findByRole('heading', { name: 'Base Stages' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Upload base stage' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /Generate/ })).not.toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Base Stages | LoreCraft3000'))
  })

  it('renders the panel list in place of the Panels placeholder', async () => {
    await renderApp('#/panels')

    expect(await screen.findByRole('heading', { name: 'Panels' })).toBeInTheDocument()
    expect(within(screen.getByRole('main')).getAllByRole('link', { name: 'New panel' }).length).toBeGreaterThan(0)
    await waitFor(() => expect(document.title).toBe('Panels | LoreCraft3000'))
  })

  it('does not mark Scenes active when on /scenes/new', async () => {
    await renderApp('#/scenes/new')

    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    const scenes = Array.from(nav.querySelectorAll('a')).find((a) => a.textContent === 'Scenes')
    expect(scenes).toBeDefined()
    await waitFor(() => expect(scenes?.classList.contains('active')).toBe(false))
  })

  it('marks Dashboard active on the home route', async () => {
    await renderApp('#/')

    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    const dashboard = Array.from(nav.querySelectorAll('a')).find((a) => a.textContent === 'Dashboard')
    expect(dashboard).toBeDefined()
    await waitFor(() => expect(dashboard?.classList.contains('active')).toBe(true))
  })

  it('opens the mobile navigation as a focus-managed drawer', async () => {
    const user = userEvent.setup()
    await renderApp('#/')

    const menu = await screen.findByRole('button', { name: 'Open navigation' })
    await user.click(menu)

    expect(menu).toHaveAttribute('aria-expanded', 'true')
    expect(document.activeElement).toBe(screen.getAllByRole('button', { name: 'Close navigation' })[0])

    await user.keyboard('{Escape}')

    expect(menu).toHaveAttribute('aria-expanded', 'false')
    expect(menu).toHaveFocus()
  })

  it('opens the command palette from shell chrome and restores trigger focus', async () => {
    const user = userEvent.setup()
    await renderApp('#/')

    const trigger = await screen.findByRole('button', { name: 'Open command palette' })
    await user.click(trigger)

    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Search commands' })).toHaveFocus()

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
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
    '#/scenes/-1/edit',
    '#/scenes/1.5/preview',
  ])('redirects malformed dynamic IDs to hash not-found without loading config: %s', async (hash) => {
    globalThis.fetch = vi.fn().mockImplementation(() => new Promise(() => {}))
    await renderApp(hash)

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#/not-found'))
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
