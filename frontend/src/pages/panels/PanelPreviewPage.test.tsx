import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Generation, GenerationSummary, Panel, PanelPreview } from '../../api/types'
import { PanelPreviewPage } from './PanelPreviewPage'

const { refreshBudget } = vi.hoisted(() => ({ refreshBudget: vi.fn() }))

vi.mock('../../api/useBudget', () => ({
  useBudget: () => ({ refreshBudget, budget: {}, refreshError: null }),
}))

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getPanel: vi.fn(),
    previewPanel: vi.fn(),
    listPanelGenerations: vi.fn(),
    duplicatePanel: vi.fn(),
    generatePanel: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const LOCKED_PANEL: Panel = {
  id: 3,
  beat_text: 'Mara backs toward the door.',
  camera: 'eye level',
  framing: 'medium shot',
  mood: '',
  aspect_ratio: '3:2',
  cast: [],
  style_id: 1,
  model: 'gemini-3.1-flash-image',
  image_size: '1K',
  created_at: '',
  is_editable: false,
  generation_count: 1,
}

const BLOCKED_PREVIEW: PanelPreview = {
  scene_id: 3,
  model: 'gemini-3.1-flash-image',
  image_size: '1K',
  prompt: '',
  prompt_hash: '',
  attachments: [],
  warnings: [],
  estimated_cost_cents: 0,
  spent_today_cents: 0,
  remaining_after_cents: 0,
  can_generate: false,
  blocked_reason: 'no canonical reference set',
}

const READY_PREVIEW: PanelPreview = {
  ...BLOCKED_PREVIEW,
  prompt: 'REFERENCE IMAGE DECLARATIONS\nImage 1 is Elias.\n\nSCENE\nElias opens the door.',
  prompt_hash: 'reviewed-prompt-hash',
  estimated_cost_cents: 7,
  remaining_after_cents: 293,
  can_generate: true,
  blocked_reason: null,
}

const FAILED_ATTEMPT: GenerationSummary = {
  id: 5,
  scene_id: 3,
  model: 'gemini-3-pro-image',
  cost_usd_cents: 0,
  reserved_cost_usd_cents: 0,
  actual_cost_usd_cents: 0,
  state: 'failed',
  error_text: 'Media resolution is not supported',
  completed_at: '2026-08-31 15:00:01',
  created_at: '2026-08-31 15:00:00',
}

const HIGH_DEMAND_ATTEMPT: GenerationSummary = {
  ...FAILED_ATTEMPT,
  id: 6,
  cost_usd_cents: 20,
  error_text:
    "Gemini generation failed: Error code: 500 - gemini-3-pro-image is currently experiencing high demand. Please try again later.",
}

const PENDING_ATTEMPT: GenerationSummary = {
  ...FAILED_ATTEMPT,
  id: 7,
  state: 'pending',
  error_text: null,
  completed_at: null,
}

const GENERATED: Generation = {
  id: 8,
  scene_id: 3,
  model: 'gemini-3-pro-image',
  image_size: '2K',
  aspect_ratio: '3:4',
  prompt: '',
  prompt_hash: '',
  attachments: [],
  warnings: [],
  cost_usd_cents: 20,
  reserved_cost_usd_cents: 20,
  actual_cost_usd_cents: null,
  state: 'succeeded',
  interaction_id: null,
  error_text: null,
  completed_at: '',
  created_at: '',
  candidates: [],
}

function renderPreview() {
  return render(
    <MemoryRouter initialEntries={['/panels/3/preview']}>
      <Routes>
        <Route path="/panels/:id/preview" element={<PanelPreviewPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PanelPreviewPage — locked panel duplicate & edit', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.getPanel).mockReset().mockResolvedValue(LOCKED_PANEL)
    vi.mocked(client.previewPanel).mockReset().mockResolvedValue(BLOCKED_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockReset().mockResolvedValue([])
    vi.mocked(client.duplicatePanel).mockReset()
    vi.mocked(client.generatePanel).mockReset()
    refreshBudget.mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('offers Duplicate & edit instead of an Edit link once a panel is locked', async () => {
    renderPreview()
    await screen.findByText(/Mara backs toward the door\./)

    expect(screen.queryByRole('link', { name: 'Edit panel' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Duplicate & edit/ })).toBeInTheDocument()
  })

  it('duplicates and navigates straight to editing the new panel', async () => {
    const user = userEvent.setup()
    vi.mocked(client.duplicatePanel).mockResolvedValue({
      ...LOCKED_PANEL,
      id: 99,
      is_editable: true,
      generation_count: 0,
    })

    renderPreview()
    const button = await screen.findByRole('button', { name: /Duplicate & edit/ })
    await user.click(button)

    await waitFor(() => expect(client.duplicatePanel).toHaveBeenCalledWith(3))
    expect(mockNavigate).toHaveBeenCalledWith('/panels/99/edit')
  })

  it('still shows Edit panel (not duplicate) for an editable panel', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({ ...LOCKED_PANEL, is_editable: true, generation_count: 0 })
    vi.mocked(client.previewPanel).mockResolvedValue({
      ...BLOCKED_PREVIEW,
      can_generate: true,
      blocked_reason: null,
    })
    renderPreview()
    await screen.findByText(/Mara backs toward the door\./)
    expect(screen.getByRole('link', { name: 'Edit panel' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Duplicate & edit/ })).not.toBeInTheDocument()
  })

  it('shows the complete exact prompt before the paid generation button', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 0,
    })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)

    renderPreview()

    await screen.findByRole('heading', { name: 'Exact prompt sent to Gemini' })
    const prompt = document.querySelector('.prompt-preview')
    const button = screen.getByRole('button', { name: /Generate one candidate/ })
    if (!(prompt instanceof HTMLElement)) throw new Error('prompt preview was not rendered')
    expect(prompt.tagName).toBe('PRE')
    expect(prompt).toHaveTextContent(READY_PREVIEW.prompt, { normalizeWhitespace: false })
    expect(
      prompt.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('shows preserved failed generation attempts with a details link', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 1,
    })
    vi.mocked(client.listPanelGenerations).mockResolvedValue([FAILED_ATTEMPT])

    renderPreview()

    expect(await screen.findByText('Attempt #5')).toBeInTheDocument()
    expect(screen.getByText('Media resolution is not supported')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View details' })).toHaveAttribute(
      'href',
      '/generations/5',
    )
    expect(screen.getByRole('link', { name: 'Edit panel' })).toBeInTheDocument()
  })

  it('summarizes high-demand errors and retries from current panel settings', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 1,
    })
    vi.mocked(client.listPanelGenerations).mockResolvedValue([HIGH_DEMAND_ATTEMPT])
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.generatePanel).mockResolvedValue(GENERATED)

    renderPreview()

    expect(
      await screen.findByText(/Gemini Pro is temporarily busy/),
    ).toBeInTheDocument()
    expect(screen.getByText('Technical details')).toBeInTheDocument()
    refreshBudget.mockClear()
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(client.generatePanel).toHaveBeenCalledWith(3, READY_PREVIEW.prompt_hash)
    expect(refreshBudget).toHaveBeenCalled()
    expect(mockNavigate).toHaveBeenCalledWith('/generations/8')
  })

  it('reloads and explains when the reviewed prompt changed', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 0,
    })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.generatePanel).mockRejectedValue(
      new client.ApiError(
        'the assembled prompt changed after preview; review the updated prompt before generating',
        'PreviewChangedError',
        409,
      ),
    )

    renderPreview()
    await user.click(await screen.findByRole('button', { name: /Generate one candidate/ }))

    expect(
      await screen.findByText(/inputs changed.*review the updated prompt/i),
    ).toBeInTheDocument()
    expect(client.previewPanel).toHaveBeenCalledTimes(2)
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('disables paid generation while an attempt is pending', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      generation_count: 1,
    })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockResolvedValue([PENDING_ATTEMPT])

    renderPreview()

    const button = await screen.findByRole('button', { name: 'Generation in progress' })
    expect(button).toBeDisabled()
    expect(screen.getByText(/refreshes automatically/)).toBeInTheDocument()
  })
})
