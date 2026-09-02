import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Character, Panel, Style } from '../api/types'
import * as client from '../api/client'
import { CommandPalette } from './CommandPalette'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    listCharacters: vi.fn(),
    listStyles: vi.fn(),
    listPanels: vi.fn(),
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

const PANEL: Panel = {
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
    vi.mocked(client.listPanels).mockReset().mockResolvedValue([PANEL])
  })

  it('opens globally on Cmd/Ctrl+K with the search field focused', async () => {
    const user = userEvent.setup()
    renderPalette()

    await user.keyboard('{Control>}k{/Control}')

    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Search commands' })).toHaveFocus()
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-controls', 'command-palette-results')
    expect(screen.getByRole('option', { name: /Stage new panel/ })).toHaveAttribute(
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
    expect(client.listPanels).toHaveBeenCalledOnce()
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
