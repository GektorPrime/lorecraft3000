import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Character, OptionsSummary, Panel, Style } from '../../api/types'
import { PanelFormPage } from './PanelFormPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getPanel: vi.fn(),
    listCharacters: vi.fn(),
    listStyles: vi.fn(),
  }
})

const OPTIONS: OptionsSummary = {
  models: ['gemini-3.1-flash-image'],
  image_sizes: ['1K', '2K'],
  aspect_ratios: ['3:2', '16:9'],
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

const READY_CHARACTER: Character = {
  id: 1,
  name: 'Elias',
  slug: 'elias',
  lore_md: '',
  visual_contract: '',
  negative_traits: '',
  default_style_id: null,
  created_at: '',
  has_canonical_ref_set: true,
  avatar_url: null,
  avatar_initials: 'EL',
}

const UNREADY_CHARACTER: Character = {
  ...READY_CHARACTER,
  id: 2,
  name: 'Mara',
  slug: 'mara',
  has_canonical_ref_set: false,
  avatar_initials: 'MA',
}

const STYLES: Style[] = [
  { id: 7, name: 'Ink', style_contract: '', created_at: '' },
  { id: 9, name: 'Oil', style_contract: '', created_at: '' },
]

const EDITABLE_PANEL: Panel = {
  id: 12,
  beat_text: 'Mara opens the door',
  camera: 'eye level',
  framing: 'medium shot',
  mood: '',
  aspect_ratio: '3:2',
  cast: [
    {
      character_id: 2,
      role: 'at the door',
      prominence: 2,
      name: 'Mara',
      avatar_url: null,
      avatar_initials: 'MA',
    },
  ],
  style_id: 9,
  model: 'gemini-3.1-flash-image',
  image_size: '1K',
  created_at: '',
  is_editable: true,
  generation_count: 0,
}

vi.mock('../../api/useOptions', () => ({
  useOptions: () => OPTIONS,
}))

describe('PanelFormPage — field descriptions', () => {
  beforeEach(() => {
    vi.mocked(client.getPanel).mockReset().mockResolvedValue(EDITABLE_PANEL)
    vi.mocked(client.listCharacters).mockReset().mockResolvedValue([READY_CHARACTER])
    vi.mocked(client.listStyles).mockReset().mockResolvedValue(STYLES)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function renderForm(path = '/panels/new') {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/panels/new" element={<PanelFormPage />} />
          <Route path="/panels/:id/edit" element={<PanelFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('describes camera as viewer position/angle, distinct from framing as crop', async () => {
    renderForm()
    await screen.findByLabelText('Action')

    const cameraHint = document.getElementById('camera-hint')
    const framingHint = document.getElementById('framing-hint')
    expect(cameraHint).toHaveTextContent(/viewer's position and angle/i)
    expect(framingHint?.textContent).not.toMatch(/viewer's position/i)
    expect(framingHint).toHaveTextContent(/how tightly the shot is cropped/i)
    expect(framingHint).toHaveTextContent(/what remains visible/i)

    expect(screen.getByLabelText('Camera')).toHaveAttribute('aria-describedby', 'camera-hint')
    expect(screen.getByLabelText('Shot framing')).toHaveAttribute('aria-describedby', 'framing-hint')
  })

  it('provides a visible description with an example for aspect ratio, style, and image size', async () => {
    renderForm()
    await screen.findByLabelText('Action')

    const aspectHint = document.getElementById('aspect_ratio-hint')
    const styleHint = document.getElementById('style_id-hint')
    const sizeHint = document.getElementById('image_size-hint')

    expect(aspectHint).toHaveTextContent(/example/i)
    expect(styleHint).toHaveTextContent(/example/i)
    expect(sizeHint).toHaveTextContent(/example/i)

    expect(screen.getByLabelText('Aspect ratio')).toHaveAttribute('aria-describedby', 'aspect_ratio-hint')
    expect(screen.getByLabelText('Style')).toHaveAttribute('aria-describedby', 'style_id-hint')
    expect(screen.getByLabelText('Image size')).toHaveAttribute('aria-describedby', 'image_size-hint')
  })

  it('describes cast order and staging visibly (not only via placeholder)', async () => {
    renderForm()
    await screen.findByLabelText('Action')
    expect(screen.getByText(/Cast order:/)).toBeInTheDocument()
    expect(screen.getByText(/Staging:/)).toBeInTheDocument()
  })

  it('describes every remaining field (action, mood)', async () => {
    renderForm()
    await screen.findByLabelText('Action')
    expect(document.getElementById('beat_text-hint')).toBeTruthy()
    expect(document.getElementById('mood-hint')).toBeTruthy()
    expect(screen.getByLabelText('Action')).toHaveAttribute('aria-describedby', 'beat_text-hint')
    expect(screen.getByLabelText('Mood')).toHaveAttribute('aria-describedby', 'mood-hint')
  })

  it('waits for character/style lists to load without throwing', async () => {
    renderForm()
    await waitFor(() => expect(client.listCharacters).toHaveBeenCalled())
    await waitFor(() => expect(client.listStyles).toHaveBeenCalled())
  })

  it('shows prerequisite loading without flashing the form', async () => {
    vi.mocked(client.listCharacters).mockReturnValue(new Promise(() => {}))
    vi.mocked(client.listStyles).mockReturnValue(new Promise(() => {}))

    renderForm()

    expect(screen.getByText('Loading panel prerequisites...')).toBeInTheDocument()
    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
  })

  it('shows a prerequisite failure and retries both lists successfully', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listCharacters)
      .mockRejectedValueOnce(new Error('characters unavailable'))
      .mockResolvedValueOnce([READY_CHARACTER])

    renderForm()

    expect(await screen.findByText(/characters unavailable/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry panel prerequisites' }))

    expect(await screen.findByLabelText('Action')).toBeInTheDocument()
    expect(client.listCharacters).toHaveBeenCalledTimes(2)
    expect(client.listStyles).toHaveBeenCalledTimes(2)
  })

  it('shows the same prerequisite failure state when styles fail to load', async () => {
    vi.mocked(client.listStyles).mockRejectedValue(new Error('styles unavailable'))

    renderForm()

    expect(await screen.findByText(/styles unavailable/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry panel prerequisites' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
  })

  it('links to style creation when there are no styles', async () => {
    vi.mocked(client.listStyles).mockResolvedValue([])
    renderForm()

    expect(await screen.findByText(/A style is required/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create a style' })).toHaveAttribute('href', '/styles/new')
    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
  })

  it('links to character creation when there are no characters', async () => {
    vi.mocked(client.listCharacters).mockResolvedValue([])
    renderForm()

    expect(await screen.findByText(/A character is required/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create a character' })).toHaveAttribute(
      'href',
      '/characters/new',
    )
  })

  it('links to character management when no character has a canonical reference set', async () => {
    vi.mocked(client.listCharacters).mockResolvedValue([UNREADY_CHARACTER])
    renderForm()

    expect(await screen.findByText(/needs a canonical reference set/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Manage characters' })).toHaveAttribute(
      'href',
      '/characters',
    )
  })

  it('initializes the first style only after prerequisites load successfully', async () => {
    renderForm()

    expect(await screen.findByLabelText('Style')).toHaveValue('7')
  })

  it('keeps panel-detail loading separate from loaded prerequisites', async () => {
    vi.mocked(client.getPanel).mockReturnValue(new Promise(() => {}))
    renderForm('/panels/12/edit')

    expect(await screen.findByText('Loading panel details...')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Loading panel prerequisites...')).not.toBeInTheDocument())
    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
  })

  it('shows a panel-detail failure and retries it without reloading prerequisites', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel)
      .mockRejectedValueOnce(new Error('panel unavailable'))
      .mockResolvedValueOnce(EDITABLE_PANEL)

    renderForm('/panels/12/edit')

    expect(await screen.findByText(/panel unavailable/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry panel details' }))

    expect(await screen.findByDisplayValue('Mara opens the door')).toBeInTheDocument()
    expect(client.getPanel).toHaveBeenCalledTimes(2)
    expect(client.listCharacters).toHaveBeenCalledTimes(1)
    expect(client.listStyles).toHaveBeenCalledTimes(1)
  })

  it('preserves an existing noncanonical cast member while editing a mixed list', async () => {
    vi.mocked(client.listCharacters).mockResolvedValue([READY_CHARACTER, UNREADY_CHARACTER])
    renderForm('/panels/12/edit')

    expect(await screen.findByRole('textbox', { name: 'Staging role for Mara' })).toHaveValue(
      'at the door',
    )
    expect(screen.getByRole('spinbutton', { name: 'Prominence for Mara' })).toHaveValue(2)
  })

  it('preserves an existing cast when no listed character is generation-ready', async () => {
    vi.mocked(client.listCharacters).mockResolvedValue([UNREADY_CHARACTER])
    renderForm('/panels/12/edit')

    expect(await screen.findByRole('textbox', { name: 'Staging role for Mara' })).toHaveValue(
      'at the door',
    )
    expect(screen.queryByText(/before you can stage a panel/)).not.toBeInTheDocument()
  })
})
