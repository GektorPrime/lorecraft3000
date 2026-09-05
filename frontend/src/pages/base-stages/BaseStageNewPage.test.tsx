import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { BaseStage } from '../../api/types'
import { BaseStageNewPage } from './BaseStageNewPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  listStyles: vi.fn(),
  createGeneratedBaseStage: vi.fn(),
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

function renderPage() {
  render(<MemoryRouter><BaseStageNewPage /></MemoryRouter>)
}

describe('BaseStageNewPage', () => {
  beforeEach(() => {
    vi.mocked(client.listStyles).mockReset().mockResolvedValue([
      { id: 1, name: 'Victorian Oil Painting', style_contract: 'Paint.', created_at: '' },
    ])
    vi.mocked(client.createGeneratedBaseStage).mockReset().mockResolvedValue(CREATED)
    mockNavigate.mockClear()
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