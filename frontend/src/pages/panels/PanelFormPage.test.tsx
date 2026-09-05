import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { BaseStage, Character, OptionsSummary, Panel, Style } from '../../api/types'
import { PanelFormPage } from './PanelFormPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    createPanel: vi.fn(),
    duplicatePanel: vi.fn(),
    getPanel: vi.fn(),
    listBaseStages: vi.fn(),
    listCharacters: vi.fn(),
    listStyles: vi.fn(),
    updatePanel: vi.fn(),
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

const READY_MARA: Character = {
  ...UNREADY_CHARACTER,
  has_canonical_ref_set: true,
}

const STYLES: Style[] = [
  { id: 7, name: 'Ink', style_contract: '', created_at: '' },
  { id: 9, name: 'Oil', style_contract: '', created_at: '' },
]

const BASE_STAGE: BaseStage = {
  id: 4,
  description: 'Moonlit station platform',
  content_url: '/api/v1/base-stages/4/content',
  dimensions: { width: 1536, height: 1024 },
  aspect_ratio: '3:2',
  targets: [
    { id: 41, position: 1, description: 'traveler beside the train' },
    { id: 42, position: 2, description: 'guard near the arch' },
  ],
  state: 'ready',
  origin: 'upload',
  revision: 1,
  beat_text: null,
  camera: null,
  framing: null,
  generation_count: 0,
  is_editable: false,
  mood: null,
  style_id: null,
  model: null,
  image_size: null,
  selected_candidate_id: null,
  usage_count: 0,
  archived_at: null,
  created_at: '',
}

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
  latest_attempt_preview_url: null,
  base_stage_id: null,
  base_stage: null,
}

vi.mock('../../api/useOptions', () => ({
  useOptions: () => OPTIONS,
}))

describe('PanelFormPage — field descriptions', () => {
  beforeEach(() => {
    vi.mocked(client.getPanel).mockReset().mockResolvedValue(EDITABLE_PANEL)
    vi.mocked(client.listCharacters).mockReset().mockResolvedValue([READY_CHARACTER])
    vi.mocked(client.listStyles).mockReset().mockResolvedValue(STYLES)
    vi.mocked(client.listBaseStages).mockReset().mockResolvedValue([])
    vi.mocked(client.createPanel).mockReset().mockResolvedValue({ ...EDITABLE_PANEL, id: 20 })
    vi.mocked(client.duplicatePanel).mockReset().mockResolvedValue({ ...EDITABLE_PANEL, id: 20 })
    vi.mocked(client.updatePanel).mockReset().mockResolvedValue(EDITABLE_PANEL)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function renderForm(path = '/panels/new') {
    const router = createMemoryRouter(
      [
        { path: '/panels/new', element: <PanelFormPage /> },
        { path: '/panels/:id/edit', element: <PanelFormPage /> },
        { path: '/panels/:id/preview', element: <h1>Panel preview</h1> },
        { path: '/panels', element: <h1>Panels</h1> },
        { path: '/styles/new', element: <h1>New style</h1> },
        { path: '/characters/new', element: <h1>New character</h1> },
        { path: '/characters', element: <h1>Characters</h1> },
        { path: '/base-stages/upload', element: <h1>Upload base stage</h1> },
      ],
      { initialEntries: [path] },
    )
    render(<RouterProvider router={router} />)
    return router
  }

  it('describes camera as viewer position/angle, distinct from framing as crop', async () => {
    renderForm()
    await screen.findByLabelText('Action')

    const form = document.querySelector('form')
    expect(form).toHaveClass('form-card')
    expect(form?.closest('section')).toHaveClass('form-page', 'form-page--wide')

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

  it('rejects a malformed edit ID without loading panel resources', async () => {
    renderForm('/panels/bad/edit')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(client.getPanel).not.toHaveBeenCalled()
    expect(client.listCharacters).not.toHaveBeenCalled()
    expect(client.listStyles).not.toHaveBeenCalled()
  })

  it('renders not found when an edit panel is missing', async () => {
    vi.mocked(client.getPanel).mockRejectedValue(
      new client.ApiError('missing', 'NotFoundError', 404),
    )
    renderForm('/panels/12/edit')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('uses a static edit title while loading', async () => {
    vi.mocked(client.getPanel).mockReturnValue(new Promise(() => {}))
    renderForm('/panels/12/edit')

    await waitFor(() => expect(document.title).toBe('Edit Panel | LoreCraft3000'))
  })

  it('updates the edit title after the panel loads', async () => {
    renderForm('/panels/12/edit')

    await screen.findByDisplayValue('Mara opens the door')
    await waitFor(() => expect(document.title).toBe('Edit Panel #12 | LoreCraft3000'))
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

  it('captures prerequisite defaults as a clean create baseline and Cancels to panels', async () => {
    const user = userEvent.setup()
    const router = renderForm()

    expect(await screen.findByLabelText('Style')).toHaveValue('7')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(router.state.location.pathname).toBe('/panels')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('captures edit hydration as clean and Cancels to preview', async () => {
    const user = userEvent.setup()
    const router = renderForm('/panels/12/edit')

    await screen.findByDisplayValue('Mara opens the door')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(router.state.location.pathname).toBe('/panels/12/preview')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('protects material panel edits when Cancel is declined', async () => {
    const user = userEvent.setup()
    const router = renderForm()
    const action = await screen.findByLabelText('Action')

    await user.type(action, 'Elias enters')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(await screen.findByRole('button', { name: 'Keep editing' }))

    expect(router.state.location.pathname).toBe('/panels/new')
    expect(action).toHaveValue('Elias enters')
  })

  it('keeps a failed save dirty and bypasses protection after a successful save', async () => {
    const user = userEvent.setup()
    vi.mocked(client.createPanel)
      .mockRejectedValueOnce(new Error('save failed'))
      .mockResolvedValueOnce({ ...EDITABLE_PANEL, id: 20 })
    const router = renderForm()

    await user.type(await screen.findByLabelText('Action'), 'Elias enters')
    await user.type(screen.getByLabelText('Camera'), 'eye level')
    await user.type(screen.getByLabelText('Shot framing'), 'wide shot')
    await user.click(screen.getByRole('button', { name: /Elias/ }))
    const beforeUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Save and preview' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('save failed')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(await screen.findByRole('button', { name: 'Keep editing' }))
    expect(router.state.location.pathname).toBe('/panels/new')

    await user.click(screen.getByRole('button', { name: 'Save and preview' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/panels/20/preview'))
    expect(client.createPanel).toHaveBeenLastCalledWith(
      expect.objectContaining({ cast: [{ character_id: 1, role: '', prominence: 1 }] }),
    )
  })

  it('supports the no-style Base Stage path with visual selection and a complete ordered payload', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listStyles).mockResolvedValue([])
    vi.mocked(client.listCharacters).mockResolvedValue([READY_CHARACTER, READY_MARA])
    vi.mocked(client.listBaseStages).mockResolvedValue([BASE_STAGE])
    renderForm()

    const mode = await screen.findByRole('checkbox', { name: 'Use a base stage' })
    expect(screen.getByText('A style is required')).toBeInTheDocument()
    await user.click(mode)

    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Style')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Model')).toBeInTheDocument()
    expect(screen.getByLabelText('Image size')).toBeInTheDocument()
    const stageChoice = screen.getByRole('radio', { name: /Moonlit station platform/ })
    await user.click(stageChoice)
    expect(screen.getByAltText('Selected base stage: Moonlit station platform')).toHaveAttribute(
      'src',
      BASE_STAGE.content_url,
    )
    expect(screen.getByLabelText('Inherited aspect ratio')).toHaveValue('3:2')

    const characterSelectors = screen.getAllByLabelText('Character')
    expect(characterSelectors).toHaveLength(2)
    expect(characterSelectors[0]).toBeInvalid()
    await user.selectOptions(characterSelectors[0]!, '1')
    expect(within(characterSelectors[1]!).getByRole('option', { name: 'Elias' })).toBeDisabled()
    await user.selectOptions(characterSelectors[1]!, '2')
    // The control mirrors CastSelector: an empty value falls back to 1, so the
    // value is set directly rather than cleared and retyped (which would append).
    fireEvent.change(
      screen.getByLabelText('Prominence', { selector: '#base-stage-prominence-41' }),
      { target: { value: '3' } },
    )
    await user.click(screen.getByRole('button', { name: 'Save and preview' }))

    await waitFor(() => expect(client.createPanel).toHaveBeenCalledWith({
      base_stage_id: 4,
      beat_text: null,
      camera: null,
      framing: null,
      mood: null,
      aspect_ratio: '3:2',
      cast: [
        { character_id: 1, base_stage_target_id: 41, role: '', prominence: 3 },
        { character_id: 2, base_stage_target_id: 42, role: '', prominence: 1 },
      ],
      style_id: null,
      model: OPTIONS.default_model,
      image_size: OPTIONS.default_image_size,
    }))
  })

  it('preserves both drafts across mode switches and resets mappings when the stage changes', async () => {
    const user = userEvent.setup()
    const secondStage: BaseStage = {
      ...BASE_STAGE,
      id: 5,
      description: 'Castle courtyard',
      content_url: '/api/v1/base-stages/5/content',
      targets: [{ id: 51, position: 1, description: 'figure at the gate' }],
    }
    vi.mocked(client.listCharacters).mockResolvedValue([READY_CHARACTER, READY_MARA])
    vi.mocked(client.listBaseStages).mockResolvedValue([BASE_STAGE, secondStage])
    renderForm()

    const action = await screen.findByLabelText('Action')
    await user.type(action, 'Elias boards the train')
    const mode = screen.getByRole('checkbox', { name: 'Use a base stage' })
    await user.click(mode)
    await user.click(screen.getByRole('radio', { name: /Moonlit station platform/ }))
    await user.selectOptions(screen.getAllByLabelText('Character')[0]!, '1')

    await user.click(mode)
    expect(screen.getByLabelText('Action')).toHaveValue('Elias boards the train')
    await user.click(mode)
    expect(screen.getByRole('radio', { name: /Moonlit station platform/ })).toBeChecked()
    expect(screen.getAllByLabelText('Character')[0]).toHaveValue('1')

    await user.click(screen.getByRole('radio', { name: /Castle courtyard/ }))
    expect(screen.getAllByLabelText('Character')[0]).toHaveValue('')
    const beforeUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)
  })

  it('hydrates an archived linked Base Stage and its target mappings on edit', async () => {
    vi.mocked(client.listCharacters).mockResolvedValue([READY_CHARACTER, READY_MARA])
    vi.mocked(client.listBaseStages).mockResolvedValue([])
    vi.mocked(client.getPanel).mockResolvedValue({
      ...EDITABLE_PANEL,
      base_stage_id: 4,
      style_id: null,
      cast: [
        { ...EDITABLE_PANEL.cast[0]!, character_id: 1, name: 'Elias', base_stage_target_id: 41 },
        { ...EDITABLE_PANEL.cast[0]!, character_id: 2, name: 'Mara', base_stage_target_id: 42 },
      ],
      base_stage: {
        id: 4,
        description: BASE_STAGE.description,
        content_url: BASE_STAGE.content_url!,
        aspect_ratio: BASE_STAGE.aspect_ratio,
        state: 'ready',
        style_id: null,
        archived_at: '2026-09-01T00:00:00Z',
        targets: BASE_STAGE.targets,
      },
    })
    renderForm('/panels/12/edit')

    expect(await screen.findByRole('checkbox', { name: 'Use a base stage' })).toBeChecked()
    expect(screen.getByRole('radio', { name: /Moonlit station platform/ })).toBeChecked()
    expect(screen.getAllByLabelText('Character').map((select) => (select as HTMLSelectElement).value))
      .toEqual(['1', '2'])
    expect(screen.queryByLabelText('Action')).not.toBeInTheDocument()
  })

  it('lets duplication finish without navigating after the locked page is left', async () => {
    let resolveDuplicate!: (panel: Panel) => void
    vi.mocked(client.getPanel).mockResolvedValue({ ...EDITABLE_PANEL, is_editable: false })
    vi.mocked(client.duplicatePanel).mockReturnValue(
      new Promise((resolve) => {
        resolveDuplicate = resolve
      }),
    )
    const user = userEvent.setup()
    const router = renderForm('/panels/12/edit')

    await user.click(await screen.findByRole('button', { name: 'Duplicate & edit' }))
    expect(screen.getByRole('button', { name: 'Duplicate & edit' })).toHaveAttribute(
      'aria-busy',
      'true',
    )
    await router.navigate('/panels')
    expect(await screen.findByRole('heading', { name: 'Panels' })).toBeInTheDocument()

    await act(async () => resolveDuplicate({ ...EDITABLE_PANEL, id: 20 }))
    expect(router.state.location.pathname).toBe('/panels')
  })
})
