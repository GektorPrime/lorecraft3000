import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const originalFetch = globalThis.fetch

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

const OPTIONS_SUMMARY = {
  models: ['gemini-3.1-flash-image'],
  image_sizes: ['1K'],
  aspect_ratios: ['3:2'],
  ref_image_roles: ['face_front'],
  default_model: 'gemini-3.1-flash-image',
  default_image_size: '1K',
  daily_spend_cap_cents: 300,
  spent_today_cents: 0,
  remaining_today_cents: 300,
  ref_image_weight_explanation: 'x',
  ref_set_immutability_explanation: 'y',
  panel_immutability_explanation: 'z',
}

describe('Home page', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse(OPTIONS_SUMMARY))
  })
  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('renders exactly one header and does not duplicate the app brand text', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument())

    // Issue #15 (and its follow-up fix): the homepage must have exactly one
    // <header>, AND the brand text it carries ("LoreCraft3000") must not be
    // repeated anywhere else on the page — one <header> alone doesn't rule
    // out a page-level heading duplicating the same brand text, which is
    // exactly the bug this test guards against.
    expect(document.querySelectorAll('header')).toHaveLength(1)
    expect(screen.getAllByText('LoreCraft3000')).toHaveLength(1)

    // The one occurrence of the brand lives in the header, not the page body.
    const header = document.querySelector('header')
    expect(header).not.toBeNull()
    expect(within(header as HTMLElement).getByText('LoreCraft3000')).toBeInTheDocument()

    // The page's own <h1> is page-specific wording, not a brand repeat.
    expect(screen.getByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
  })

  it('renders four square navigation tiles with no raw ID entry and no emoji icons', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument())

    const nav = screen.getByRole('navigation', { name: 'Main sections' })
    const tiles = within(nav)
    expect(tiles.getByRole('link', { name: /Characters/ })).toBeInTheDocument()
    expect(tiles.getByRole('link', { name: /Styles/ })).toBeInTheDocument()
    expect(tiles.getByRole('link', { name: /^Panels$/ })).toBeInTheDocument()
    expect(tiles.getByRole('link', { name: /Stage New Panel/ })).toBeInTheDocument()
    expect(tiles.getAllByRole('link')).toHaveLength(4)

    // Tile icons are plain text/CSS badges, not emoji.
    const EMOJI_PATTERN = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u
    expect(EMOJI_PATTERN.test(nav.textContent ?? '')).toBe(false)
  })
})
