import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import { OptionsContext } from '../../api/optionsContext'
import type { BaseStage, OptionsSummary } from '../../api/types'
import { BaseStageNewPage } from './BaseStageNewPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  listStyles: vi.fn(),
  getBaseStage: vi.fn(),
  createGeneratedBaseStage: vi.fn(),
  updateBaseStage: vi.fn(),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})
vi.mock('../../hooks/useUnsavedChanges', () => ({
  useUnsavedChanges: () => ({ allowNavigation: vi.fn(), confirmationProps: { open: false } }),
}))

const CREATED: BaseStage = {
  id: 9,
  archived_at: null,
  aspect_ratio: '16:9',
  beat_text: 'They strain against the rope.',
  camera: 'twenty metres away',
  content_url: null,
  created_at: '',
  description: 'Four figures haul a machine up a ravine.',
  dimensions: null,
  framing: 'wide environmental shot',
  generation_count: 0,
  image_size: '1K',
  is_editable: true,
  model: 'gemini-3.1-flash-image',
  mood: 'strenuous',
  origin: 'generated',
  revision: 1,
  selected_candidate_id: null,
  state: 'draft',
  style_id: 1,
  targets: [{ id: 91, position: 0, description: 'figure above the slope' }],
  usage_count: 0,
}

const OPTIONS: OptionsSummary = {
  models: [
    'gemini-3.1-flash-image',
    'gemini-3-pro-image',
    'gpt-image-1',
    'gpt-image-1.5',
    'gpt-image-2',
  ],
  image_sizes: ['1K', '2K', '4K'],
  aspect_ratios: ['3:2', '16:9', '4:3', '1:1', '3:4', '9:16'],
  ref_image_roles: [],
  default_model: 'gemini-3.1-flash-image',
  default_image_size: '1K',
  daily_spend_cap_cents: 300,
  spent_today_cents: 0,
  remaining_today_cents: 300,
  ref_image_weight_explanation: '',
  ref_set_immutability_explanation: '',
  scene_immutability_explanation: '',
}

function renderPage(path = '/base-stages/new') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <OptionsContext.Provider value={OPTIONS}>
        <Routes>
          <Route path="/base-stages/new" element={<BaseStageNewPage />} />
          <Route path="/base-stages/:id/edit" element={<BaseStageNewPage />} />
        </Routes>
      </OptionsContext.Provider>
    </MemoryRouter>,
  )
}

describe('BaseStageNewPage', () => {
  beforeEach(() => {
    vi.mocked(client.listStyles).mockReset().mockResolvedValue([
      { id: 1, name: 'Victorian Oil Painting', style_contract: 'Paint.', created_at: '' },
    ])
    vi.mocked(client.getBaseStage).mockReset().mockResolvedValue(CREATED)
    vi.mocked(client.createGeneratedBaseStage).mockReset().mockResolvedValue(CREATED)
    vi.mocked(client.updateBaseStage).mockReset().mockResolvedValue(CREATED)
    mockNavigate.mockClear()
  })

  it('uses the centrally configured models, image sizes, ratios, and defaults', () => {
    renderPage()

    const model = screen.getByLabelText('Model')
    expect(within(model).getAllByRole('option').map((option) => option.textContent)).toEqual(OPTIONS.models)
    expect(model).toHaveValue(OPTIONS.default_model)

    const imageSize = screen.getByLabelText('Image size')
    expect(within(imageSize).getAllByRole('option').map((option) => option.textContent)).toEqual(OPTIONS.image_sizes)
    expect(imageSize).toHaveValue(OPTIONS.default_image_size)

    const aspectRatio = screen.getByLabelText('Aspect ratio')
    expect(within(aspectRatio).getAllByRole('option').map((option) => option.textContent)).toEqual(OPTIONS.aspect_ratios)
    expect(aspectRatio).toHaveValue('16:9')
  })

  it('requires description, beat text, and at least one identity target', async () => {
    const user = userEvent.setup()
    renderPage()

    const submit = await screen.findByRole('button', { name: 'Create base stage' })
    await user.click(submit)
    expect(await screen.findByText('Enter a description for this base stage.')).toBeInTheDocument()
    expect(client.createGeneratedBaseStage).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('Description'), 'A ravine scene.')
    await user.type(screen.getByLabelText('Beat text'), 'They strain.')
    await screen.findByRole('option', { name: 'Victorian Oil Painting' })
    await user.selectOptions(screen.getByLabelText('Model'), 'gemini-3.1-flash-image')
    await user.click(submit)
    expect(await screen.findByText('Add at least one identity target.')).toBeInTheDocument()
    expect(client.createGeneratedBaseStage).not.toHaveBeenCalled()
  })

  it('creates a generated base stage and navigates to its preview', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText('Description'), 'Four figures haul a machine up a ravine.')
    await user.type(screen.getByLabelText('Beat text'), 'They strain against the rope.')
    await user.type(screen.getByLabelText('Camera position'), 'twenty metres away')
    await user.type(screen.getByLabelText('Framing'), 'wide environmental shot')
    await user.type(screen.getByLabelText('Mood'), 'strenuous')
    // List styles resolves asynchronously.
    await screen.findByRole('option', { name: 'Victorian Oil Painting' })
    await user.selectOptions(screen.getByLabelText('Style'), '1')
    await user.selectOptions(screen.getByLabelText('Model'), 'gemini-3.1-flash-image')
    await user.click(screen.getByRole('button', { name: 'Add target' }))
    await user.type(screen.getByLabelText('Target 1'), 'figure above the slope')
    await user.click(screen.getByRole('button', { name: 'Create base stage' }))

    await waitFor(() => expect(client.createGeneratedBaseStage).toHaveBeenCalled())
    const payload = vi.mocked(client.createGeneratedBaseStage).mock.calls[0]![0]
    expect(payload.description).toBe('Four figures haul a machine up a ravine.')
    expect(payload.beat_text).toBe('They strain against the rope.')
    expect(payload.camera).toBe('twenty metres away')
    expect(payload.framing).toBe('wide environmental shot')
    expect(payload.mood).toBe('strenuous')
    expect(payload.aspect_ratio).toBe('16:9')
    expect(payload.style_id).toBe(1)
    expect(payload.model).toBe('gemini-3.1-flash-image')
    expect(payload.image_size).toBe('1K')
    expect(payload.targets).toEqual(['figure above the slope'])
    expect(mockNavigate).toHaveBeenCalledWith('/base-stages/9/preview')
  })

  it('loads and updates an editable generated draft', async () => {
    const user = userEvent.setup()
    renderPage('/base-stages/9/edit')

    expect(await screen.findByRole('heading', { name: 'Edit base stage #9' })).toBeInTheDocument()
    const description = screen.getByLabelText('Description')
    expect(description).toHaveValue('Four figures haul a machine up a ravine.')
    expect(screen.getByLabelText('Target 1')).toHaveValue('figure above the slope')

    await user.clear(description)
    await user.type(description, 'Three figures move the machine through a flooded ravine.')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(client.updateBaseStage).toHaveBeenCalledWith(
      9,
      expect.objectContaining({
        description: 'Three figures move the machine through a flooded ravine.',
        model: OPTIONS.default_model,
        targets: ['figure above the slope'],
      }),
    ))
    expect(client.createGeneratedBaseStage).not.toHaveBeenCalled()
    expect(mockNavigate).toHaveBeenCalledWith('/base-stages/9/preview')
  })

  it('does not render the form for a locked draft', async () => {
    vi.mocked(client.getBaseStage).mockResolvedValue({ ...CREATED, is_editable: false })
    renderPage('/base-stages/9/edit')

    expect(await screen.findByRole('heading', { name: 'Base stage locked' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
  })

  it('surfaces API failures instead of navigating', async () => {
    vi.mocked(client.createGeneratedBaseStage).mockRejectedValue(new Error('provider missing'))
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText('Description'), 'A ravine scene.')
    await user.type(screen.getByLabelText('Beat text'), 'They strain.')
    await screen.findByRole('option', { name: 'Victorian Oil Painting' })
    await user.selectOptions(screen.getByLabelText('Model'), 'gemini-3.1-flash-image')
    await user.click(screen.getByRole('button', { name: 'Add target' }))
    await user.type(screen.getByLabelText('Target 1'), 'figure above the slope')
    await user.click(screen.getByRole('button', { name: 'Create base stage' }))

    expect(await screen.findByText(/Could not create base stage: provider missing/)).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
