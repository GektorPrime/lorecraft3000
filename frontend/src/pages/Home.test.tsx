import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Character, GalleryItem, Panel, Style } from '../api/types'
import App from '../App'

const originalFetch = globalThis.fetch

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
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
  spent_today_cents: 75,
  remaining_today_cents: 225,
  ref_image_weight_explanation: 'x',
  ref_set_immutability_explanation: 'y',
  panel_immutability_explanation: 'z',
}

function panel(id: number, editable = false): Panel {
  return {
    id,
    beat_text: `Beat for panel ${id}`,
    camera: 'eye level',
    cast: [],
    framing: 'medium',
    image_size: '1K',
    aspect_ratio: '3:2',
    model: 'test-model',
    mood: 'quiet',
    style_id: 1,
    generation_count: id,
    latest_attempt_preview_url: null,
    is_editable: editable,
    created_at: `2026-01-${String(id).padStart(2, '0')}T00:00:00Z`,
  }
}

function galleryItem(id: number): GalleryItem {
  return {
    candidate_id: id,
    panel_id: id,
    beat_text: `Accepted beat ${id}`,
    aspect_ratio: '3:2',
    content_url: `/api/v1/content/${id}`,
    created_at: `2026-01-${String(id).padStart(2, '0')}T00:00:00Z`,
  }
}

const CHARACTERS: Character[] = [
  {
    id: 1,
    name: 'Eugen',
    slug: 'eugen',
    avatar_url: null,
    avatar_initials: 'E',
    default_style_id: null,
    has_canonical_ref_set: true,
    lore_md: '',
    negative_traits: '',
    visual_contract: '',
    created_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 2,
    name: 'Mara',
    slug: 'mara',
    avatar_url: null,
    avatar_initials: 'M',
    default_style_id: null,
    has_canonical_ref_set: false,
    lore_md: '',
    negative_traits: '',
    visual_contract: '',
    created_at: '2026-01-02T00:00:00Z',
  },
]

const STYLES: Style[] = [
  {
    id: 1,
    name: 'Ink noir',
    style_contract: 'Heavy blacks.',
    created_at: '2026-01-01T00:00:00Z',
  },
]

describe('Dashboard', () => {
  let panels: Panel[]
  let gallery: GalleryItem[]
  let characters: Character[]
  let styles: Style[]
  let galleryFails: boolean

  beforeEach(() => {
    window.location.hash = '#/'
    panels = [panel(3, true), panel(2), panel(1)]
    gallery = [galleryItem(3), galleryItem(2), galleryItem(1)]
    characters = CHARACTERS
    styles = STYLES
    galleryFails = false

    globalThis.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/options/summary')) return Promise.resolve(jsonResponse(OPTIONS_SUMMARY))
      if (url.endsWith('/panels')) return Promise.resolve(jsonResponse(panels))
      if (url.endsWith('/gallery')) {
        return Promise.resolve(
          galleryFails
            ? jsonResponse({ detail: { message: 'gallery offline', type: 'Offline' } }, 503)
            : jsonResponse(gallery),
        )
      }
      if (url.endsWith('/characters')) return Promise.resolve(jsonResponse(characters))
      if (url.endsWith('/styles')) return Promise.resolve(jsonResponse(styles))
      throw new Error(`Unexpected request: ${url}`)
    })
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  it('keeps one banner and one brand occurrence with a page-specific heading', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()

    expect(document.querySelectorAll('header')).toHaveLength(1)
    expect(screen.getAllByText('LoreCraft3000')).toHaveLength(1)
    const header = document.querySelector('header')
    expect(header).not.toBeNull()
    expect(within(header as HTMLElement).getByText('LoreCraft3000')).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Dashboard | LoreCraft3000'))

    const dashboard = screen.getByRole('region', { name: 'Dashboard' })
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u
    expect(emoji.test(dashboard.textContent ?? '')).toBe(false)
  })

  it('shows budget, library counts, recent panels and recent accepted output', async () => {
    render(<App />)

    expect(await screen.findByText('$2.25')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Dashboard daily spend' })).toHaveAttribute(
      'aria-valuenow',
      '75',
    )

    const library = screen.getByRole('region', { name: 'Library' })
    expect(await within(library).findByRole('link', { name: '2 Characters' })).toBeInTheDocument()
    expect(within(library).getByRole('link', { name: '1 Styles' })).toBeInTheDocument()

    const work = screen.getByRole('region', { name: 'Continue working' })
    expect(await within(work).findByText('Beat for panel 3')).toBeInTheDocument()
    expect(within(work).getByRole('link', { name: /Continue editing/ })).toHaveAttribute(
      'href',
      '#/panels/3/edit',
    )
    expect(within(work).getAllByText(/Beat for panel/)).toHaveLength(3)

    const output = screen.getByRole('region', { name: 'Recent output' })
    expect(await within(output).findByRole('img', { name: 'Accepted image from panel 3' })).toBeInTheDocument()
    expect(within(output).getAllByRole('img')).toHaveLength(3)
  })

  it('limits the dashboard to three panels and six output images', async () => {
    panels = [panel(9), panel(8), panel(7), panel(6)]
    gallery = Array.from({ length: 7 }, (_, index) => galleryItem(20 - index))
    render(<App />)

    await screen.findByRole('heading', { level: 1, name: 'Dashboard' })
    const work = screen.getByRole('region', { name: 'Continue working' })
    expect(await within(work).findByText('Beat for panel 9')).toBeInTheDocument()
    expect(within(work).queryByText('Beat for panel 6')).not.toBeInTheDocument()

    const output = screen.getByRole('region', { name: 'Recent output' })
    await within(output).findByRole('img', { name: 'Accepted image from panel 20' })
    expect(within(output).getAllByRole('img')).toHaveLength(6)
    expect(within(output).queryByRole('img', { name: 'Accepted image from panel 14' })).not.toBeInTheDocument()
  })

  it('renders useful empty states with next actions', async () => {
    panels = []
    gallery = []
    characters = []
    styles = []
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'No panels staged yet' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Stage first panel' })).toHaveAttribute(
      'href',
      '#/panels/new',
    )
    expect(screen.getByRole('heading', { name: 'No accepted images yet' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Review panels' })).toBeInTheDocument()
  })

  it('keeps healthy sections visible when one dashboard request fails', async () => {
    galleryFails = true
    render(<App />)

    expect(await screen.findByText('Could not load gallery: gallery offline')).toBeInTheDocument()
    expect(screen.getByText('Beat for panel 3')).toBeInTheDocument()
    const library = screen.getByRole('region', { name: 'Library' })
    expect(await within(library).findByRole('link', { name: '2 Characters' })).toBeInTheDocument()
    expect(within(library).getByRole('link', { name: '1 Styles' })).toBeInTheDocument()
  })
})
