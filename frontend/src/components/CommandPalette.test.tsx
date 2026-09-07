import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { BaseStage, Character, Scene, Style } from '../api/types'
import * as client from '../api/client'
import { CommandPalette } from './CommandPalette'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    listCharacters: vi.fn(),
    listStyles: vi.fn(),
    listScenes: vi.fn(),
    listBaseStages: vi.fn(),
  }
})

const CHARACTER: Character = {
  id: 7,
  name: 'Eugen Lariviere',
  slug: 'eugen-lariviere',
  avatar_url: null,
  avatar_initials: 'EL',
  default_style_id: null,
  has_canonical_ref_set: true,
  lore_md: '',
  negative_traits: '',
  visual_contract: '',
  created_at: '2026-01-01T00:00:00Z',
}

const STYLE: Style = {
  id: 4,
  name: 'Ink noir',
  style_contract: 'Heavy blacks and dry brush lines.',
  created_at: '2026-01-01T00:00:00Z',
}

const STAGE: BaseStage = {
  id: 9,
  description: 'Empty rain-slicked platform at night.',
  state: 'draft',
  content_url: null,
  is_editable: true,
  generation_count: 0,
  usage_count: 0,
  archived_at: null,
  targets: [],
  created_at: '2026-01-01T00:00:00Z',
  aspect_ratio: '16:9',
  beat_text: null,
  camera: null,
  dimensions: null,
  framing: null,
  image_size: null,
  model: null,
  mood: null,
  origin: 'uploaded',
  revision: 1,
  selected_candidate_id: null,
  style_id: null,
}

const PANEL: Scene = {
  base_stage_id: null,
  base_stage: null,
  id: 12,
  beat_text: 'Rain cuts across a deserted platform.',
  camera: 'low angle',
  cast: [],
  framing: 'wide',
  image_size: '1K',
  aspect_ratio: '3:2',
  model: 'test-model',
  mood: 'tense',
  style_id: 4,
  generation_count: 1,
  latest_attempt_preview_url: null,
  is_editable: false,
  created_at: '2026-01-01T00:00:00Z',
}

function Harness() {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const location = useLocation()

  return (
    <>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>
        Commands
      </button>
      <span data-testid="path">{location.pathname}</span>
      <CommandPalette
        open={open}
        onRequestOpen={() => setOpen(true)}
        onRequestClose={() => setOpen(false)}
        returnFocusRef={triggerRef}
      />
    </>
  )
}

function renderPalette() {
  return render(
    <MemoryRouter>
      <Harness />
    </MemoryRouter>,
  )
}

describe('CommandPalette', () => {
  beforeEach(() => {
    vi.mocked(client.listCharacters).mockReset().mockResolvedValue([CHARACTER])
    vi.mocked(client.listStyles).mockReset().mockResolvedValue([STYLE])
    vi.mocked(client.listScenes).mockReset().mockResolvedValue([PANEL])
    vi.mocked(client.listBaseStages).mockReset().mockResolvedValue([STAGE])
  })

  it('opens globally on Cmd/Ctrl+K with the search field focused', async () => {
    const user = userEvent.setup()
    renderPalette()

    await user.keyboard('{Control>}k{/Control}')

    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Search commands' })).toHaveFocus()
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-controls', 'command-palette-results')
    expect(screen.getByRole('option', { name: /Stage new scene/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('filters loaded library records and navigates with Enter', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByRole('button', { name: 'Commands' }))

    const search = screen.getByRole('combobox', { name: 'Search commands' })
    await user.type(search, 'eugen')
    const result = await screen.findByRole('option', { name: /Eugen Lariviere/ })
    expect(search).toHaveAttribute('aria-activedescendant', result.id)

    await user.keyboard('{Enter}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByTestId('path')).toHaveTextContent('/characters/7')
    expect(screen.getByRole('button', { name: 'Commands' })).toHaveFocus()
  })

  it('supports arrow-key selection and closes on Escape', async () => {
    const user = userEvent.setup()
    renderPalette()
    const trigger = screen.getByRole('button', { name: 'Commands' })
    await user.click(trigger)

    const search = screen.getByRole('combobox')
    await user.keyboard('{ArrowDown}')
    expect(search.getAttribute('aria-activedescendant')).toBe('command-new-character')

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('fetches library records only on the first open', async () => {
    const user = userEvent.setup()
    renderPalette()
    const trigger = screen.getByRole('button', { name: 'Commands' })

    await user.click(trigger)
    await user.type(screen.getByRole('combobox'), 'eugen')
    await screen.findByRole('option', { name: /Eugen Lariviere/ })
    await user.keyboard('{Escape}')
    await user.click(trigger)
    await user.type(screen.getByRole('combobox'), 'eugen')
    await screen.findByRole('option', { name: /Eugen Lariviere/ })

    expect(client.listCharacters).toHaveBeenCalledOnce()
    expect(client.listStyles).toHaveBeenCalledOnce()
    expect(client.listScenes).toHaveBeenCalledOnce()
    expect(client.listBaseStages).toHaveBeenCalledOnce()
  })

  it('finds base stages and navigates to the stage preview', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByRole('button', { name: 'Commands' }))

    const search = screen.getByRole('combobox', { name: 'Search commands' })
    await user.type(search, 'rain-slicked')
    const result = await screen.findByRole('option', { name: /Base Stage #9/ })
    expect(result).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{Enter}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByTestId('path')).toHaveTextContent('/base-stages/9/preview')
  })

  it('offers a standalone command to create a new base stage', async () => {
    const user = userEvent.setup()
    renderPalette()

    await user.click(screen.getByRole('button', { name: 'Commands' }))
    const search = screen.getByRole('combobox', { name: 'Search commands' })
    await user.type(search, 'base stage')
    await screen.findByRole('option', { name: /New base stage/ })

    await user.keyboard('{Enter}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByTestId('path')).toHaveTextContent('/base-stages/new')
  })

  it('keeps successful collections searchable when one endpoint fails', async () => {
    vi.mocked(client.listCharacters).mockRejectedValue(new Error('offline'))
    const user = userEvent.setup()
    renderPalette()

    await user.click(screen.getByRole('button', { name: 'Commands' }))
    await user.type(screen.getByRole('combobox'), 'ink noir')

    expect(await screen.findByRole('option', { name: /Ink noir/ })).toBeInTheDocument()
    expect(screen.getByText('Some library results are temporarily unavailable.')).toBeInTheDocument()
  })
})
