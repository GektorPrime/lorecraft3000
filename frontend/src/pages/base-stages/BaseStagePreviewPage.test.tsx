import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { BaseStage, BaseStagePreview, GenerationSummary } from '../../api/types'
import { BaseStagePreviewPage } from './BaseStagePreviewPage'

const { refreshBudget } = vi.hoisted(() => ({ refreshBudget: vi.fn() }))

vi.mock('../../api/useBudget', () => ({
  useBudget: () => ({ refreshBudget, budget: {}, refreshError: null }),
}))

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getBaseStage: vi.fn(),
    previewBaseStage: vi.fn(),
    listBaseStageGenerations: vi.fn(),
    generateBaseStage: vi.fn(),
    publishBaseStage: vi.fn(),
    duplicateBaseStage: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const DRAFT: BaseStage = {
  id: 5,
  archived_at: null,
  aspect_ratio: '16:9',
  beat_text: 'They strain against the rope.',
  camera: 'twenty metres away',
  content_url: null,
  created_at: '',
  description: 'Four figures haul a machine up a muddy ravine.',
  dimensions: null,
  framing: 'wide environmental shot',
  generation_count: 1,
  image_size: '1K',
  is_editable: true,
  model: 'gemini-3.1-flash-image',
  mood: 'strenuous',
  origin: 'generated',
  revision: 1,
  selected_candidate_id: null,
  state: 'draft',
  style_id: 1,
  targets: [
    { id: 51, position: 0, description: 'figure above the slope' },
    { id: 52, position: 1, description: 'figure beside the oak' },
  ],
  usage_count: 0,
}

const PREVIEW: BaseStagePreview = {
  base_stage_id: 5,
  model: 'gemini-3.1-flash-image',
  image_size: '1K',
  aspect_ratio: '16:9',
  prompt: 'BASE STAGE\nFour figures haul a machine up a muddy ravine.\n\nIDENTITY TARGETS\nFigure 1: figure above the slope',
  prompt_hash: 'stage-hash',
  warnings: [],
  estimated_cost_cents: 2500,
  spent_today_cents: 0,
  remaining_after_cents: 0,
  can_generate: true,
  blocked_reason: null,
}

const READY_STAGE: BaseStage = {
  ...DRAFT,
  state: 'ready',
  is_editable: false,
  content_url: '/api/v1/base-stages/5/content',
  selected_candidate_id: 900,
  dimensions: { width: 1536, height: 1024 },
}

const SUCCEEDED_ATTEMPT: GenerationSummary = {
  id: 100,
  scene_id: null,
  base_stage_id: 5,
  state: 'succeeded',
  model: 'gemini-3.1-flash-image',
  cost_usd_cents: 2500,
  reserved_cost_usd_cents: 2500,
  actual_cost_usd_cents: 2500,
  completed_at: '2026-01-01T00:00:01Z',
  created_at: '2026-01-01T00:00:00Z',
  error_text: null,
  candidates: [
    {
      id: 900,
      generation_id: 100,
      idx: 0,
      content_url: '/api/v1/candidates/900/content',
      review_status: 'pending',
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/base-stages/5/preview']}>
      <Routes>
        <Route path="/base-stages/:id/preview" element={<BaseStagePreviewPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('BaseStagePreviewPage', () => {
  beforeEach(() => {
    vi.mocked(client.getBaseStage).mockReset().mockResolvedValue(DRAFT)
    vi.mocked(client.previewBaseStage).mockReset().mockResolvedValue(PREVIEW)
    vi.mocked(client.listBaseStageGenerations).mockReset().mockResolvedValue([SUCCEEDED_ATTEMPT])
    vi.mocked(client.generateBaseStage).mockReset().mockResolvedValue({} as never)
    vi.mocked(client.publishBaseStage).mockReset().mockResolvedValue(READY_STAGE)
    vi.mocked(client.duplicateBaseStage).mockReset().mockResolvedValue({ ...DRAFT, id: 6 })
    refreshBudget.mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    mockNavigate.mockClear()
  })

  it('shows the identity-neutral prompt, targets, and publish action for a generated candidate', async () => {
    vi.mocked(client.getBaseStage).mockResolvedValueOnce(DRAFT).mockResolvedValueOnce(READY_STAGE)
    renderPage()

    expect(await screen.findByText(/Four figures haul a machine up a muddy ravine/)).toBeInTheDocument()
    // Targets come from the stage, not the prompt.
    expect(await screen.findByText('figure above the slope')).toBeInTheDocument()
    expect(screen.getByText('figure beside the oak')).toBeInTheDocument()
    // Identity-neutral: no character references are loaded into the prompt.
    expect(screen.getByText(/no character identities are included at this stage/i)).toBeInTheDocument()

    const publish = await screen.findByRole('button', { name: 'Publish as base stage image' })
    await userEvent.setup().click(publish)
    await waitFor(() => expect(client.publishBaseStage).toHaveBeenCalledWith(5, 900))
    expect(await screen.findByText(/Base stage #5 — Ready/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Publish as base stage image/ })).not.toBeInTheDocument()
  })

  it('generates a candidate with the assembled prompt hash', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Generate candidate · \$25\.00/ }))
    await waitFor(() => expect(client.generateBaseStage).toHaveBeenCalledWith(5, 'stage-hash'))
    expect(refreshBudget).toHaveBeenCalled()
  })

  it('duplicates an editable draft into a fresh draft at a new preview page', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Duplicate' }))
    await waitFor(() => expect(client.duplicateBaseStage).toHaveBeenCalledWith(5))
    expect(mockNavigate).toHaveBeenCalledWith('/base-stages/6/preview')
  })

  it('reports a stale prompt hash from the backend as a changed-input notice', async () => {
    vi.mocked(client.generateBaseStage).mockRejectedValue(new client.ApiError("assembled prompt changed after preview", "GenerationChangedError", 409))
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Generate candidate/ }))
    expect(await screen.findByText(/The generation inputs changed/)).toBeInTheDocument()
  })

  it('shows publish unavailable for a locked stage and offers no generate button', async () => {
    vi.mocked(client.getBaseStage).mockResolvedValue(READY_STAGE)
    vi.mocked(client.previewBaseStage).mockResolvedValue({ ...PREVIEW, can_generate: false, blocked_reason: 'stage is published' })
    renderPage()

    expect(await screen.findByText('Base stage #5 — Ready')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Publish as base stage image/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Generate candidate/ })).not.toBeInTheDocument()
  })

  it('returns 404 to the NotFound page for a missing base stage', async () => {
    vi.mocked(client.getBaseStage).mockRejectedValue(new client.ApiError("not found", "NotFound", 404))
    renderPage()

    expect(await screen.findByRole('heading', { name: /Not found/i })).toBeInTheDocument()
  })
})