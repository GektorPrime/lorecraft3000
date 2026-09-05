import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

vi.mock('../../api/useOptions', () => ({
  useOptions: () => ({
    models: ['gemini-3.1-flash-image', 'gemini-3-pro-image'],
  }),
}))

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getPanel: vi.fn(),
    previewPanel: vi.fn(),
    listPanelGenerations: vi.fn(),
    duplicatePanel: vi.fn(),
    deletePanel: vi.fn(),
    generatePanel: vi.fn(),
    reviewCandidate: vi.fn(),
    editCandidate: vi.fn(),
    updatePanelModel: vi.fn(),
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
  latest_attempt_preview_url: '/api/v1/candidates/900/content',
  base_stage_id: null,
  base_stage: null,
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

const CANDIDATE = {
  id: 900,
  generation_id: 5,
  idx: 1,
  review_status: 'pending',
  content_url: '/api/v1/candidates/900/content',
  created_at: '2026-08-31 15:00:02',
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
  candidates: [],
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

const SUCCEEDED_ATTEMPT: GenerationSummary = {
  ...PENDING_ATTEMPT,
  state: 'succeeded',
  completed_at: '2026-08-31 15:00:03',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
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

function renderPreview(path = '/panels/3/preview') {
  return render(
    <MemoryRouter initialEntries={[path]}>
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
    vi.mocked(client.deletePanel).mockReset().mockResolvedValue(undefined)
    vi.mocked(client.generatePanel).mockReset()
    vi.mocked(client.reviewCandidate).mockReset()
    vi.mocked(client.editCandidate).mockReset()
    vi.mocked(client.updatePanelModel).mockReset()
    refreshBudget.mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('offers Duplicate & edit instead of an Edit link once a panel is locked', async () => {
    renderPreview()
    await screen.findByText(/Mara backs toward the door\./)

    expect(screen.queryByRole('link', { name: 'Edit panel' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Duplicate & edit/ })).toBeInTheDocument()
  })

  it('shows each candidate review status on its generation attempt', async () => {
    vi.mocked(client.listPanelGenerations).mockResolvedValue([
      { ...SUCCEEDED_ATTEMPT, candidates: [CANDIDATE] },
      {
        ...SUCCEEDED_ATTEMPT,
        id: 8,
        candidates: [{ ...CANDIDATE, id: 901, generation_id: 8, review_status: 'accepted' }],
      },
      {
        ...SUCCEEDED_ATTEMPT,
        id: 9,
        candidates: [{ ...CANDIDATE, id: 902, generation_id: 9, review_status: 'rejected' }],
      },
    ])
    renderPreview()

    await screen.findAllByText('Attempt #7')
    const attemptList = document.querySelector('.attempt-list')
    expect(attemptList).not.toBeNull()
    expect(within(attemptList as HTMLElement).getAllByText('Succeeded')).toHaveLength(3)
    expect(within(attemptList as HTMLElement).getAllByText('Waiting')).toHaveLength(1)
    expect(within(attemptList as HTMLElement).getAllByText('Accepted')).toHaveLength(1)
    expect(within(attemptList as HTMLElement).getAllByText('Rejected')).toHaveLength(1)
    const summary = within(attemptList as HTMLElement).getAllByText('Attempt #7')[0]
      .closest('.attempt-row__summary')
    expect(summary?.lastElementChild).toHaveClass('attempt-row__badges')
  })

  it('edits a successful candidate with an instruction and refreshes history', async () => {
    const user = userEvent.setup()
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations)
      .mockResolvedValueOnce([{ ...SUCCEEDED_ATTEMPT, candidates: [CANDIDATE] }])
      .mockResolvedValue([
        { ...SUCCEEDED_ATTEMPT, candidates: [CANDIDATE] },
        {
          ...SUCCEEDED_ATTEMPT,
          id: 8,
          candidates: [{ ...CANDIDATE, id: 901, generation_id: 8 }],
        },
      ])
    vi.mocked(client.editCandidate).mockResolvedValue(GENERATED)
    renderPreview()

    await screen.findAllByText('Attempt #7')
    await user.click(screen.getByRole('button', { name: 'Edit this image' }))

    const box = screen.getByLabelText(/Describe the change to make to this image/)
    await user.type(box, 'make it night time with neon')
    refreshBudget.mockClear()
    await user.click(screen.getByRole('button', { name: 'Submit edit' }))

    await waitFor(() =>
      expect(client.editCandidate).toHaveBeenCalledWith(
        CANDIDATE.id,
        'make it night time with neon',
      ),
    )
    expect(await screen.findByText('Attempt #8')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Describe the change to make to this image/)).not.toBeInTheDocument()
    expect(refreshBudget).toHaveBeenCalledTimes(2)
  })

  it('disables submit until an edit instruction is entered', async () => {
    const user = userEvent.setup()
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockResolvedValue([
      { ...SUCCEEDED_ATTEMPT, candidates: [CANDIDATE] },
    ])
    renderPreview()

    await screen.findAllByText('Attempt #7')
    await user.click(screen.getByRole('button', { name: 'Edit this image' }))
    expect(screen.getByRole('button', { name: 'Submit edit' })).toBeDisabled()

    await user.type(
      screen.getByLabelText(/Describe the change to make to this image/),
      'brighten it',
    )
    expect(screen.getByRole('button', { name: 'Submit edit' })).toBeEnabled()
  })

  it('puts the purple Back to panels button in the page header', async () => {
    renderPreview()
    await screen.findByText(/Mara backs toward the door\./)

    const back = screen.getByRole('link', { name: 'Back to panels' })
    expect(back).toHaveClass('btn--primary')
    expect(back.closest('.page-header__actions')).not.toBeNull()
  })

  it('deletes the panel from the action block after confirmation', async () => {
    const user = userEvent.setup()
    renderPreview()

    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    await user.click(screen.getByRole('button', { name: 'Delete panel' }))

    await waitFor(() => expect(client.deletePanel).toHaveBeenCalledWith(3))
    expect(mockNavigate).toHaveBeenCalledWith('/panels')
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

  it('keeps the panel preview and history visible when duplication fails', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listPanelGenerations).mockResolvedValue([FAILED_ATTEMPT])
    vi.mocked(client.duplicatePanel).mockRejectedValue(new Error('offline'))
    renderPreview()

    await user.click(await screen.findByRole('button', { name: /Duplicate & edit/ }))

    expect(await screen.findByText('Could not duplicate panel: Error: offline')).toHaveAttribute('role', 'alert')
    expect(screen.getByText('Mara backs toward the door.')).toBeInTheDocument()
    expect(screen.getByText('Attempt #5')).toBeInTheDocument()
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

  it('changes the model for the whole editable panel and refreshes its preview', async () => {
    const user = userEvent.setup()
    const editablePanel = { ...LOCKED_PANEL, is_editable: true, generation_count: 0 }
    const updatedPanel = { ...editablePanel, model: 'gemini-3-pro-image' }
    vi.mocked(client.getPanel)
      .mockResolvedValueOnce(editablePanel)
      .mockResolvedValueOnce(updatedPanel)
    vi.mocked(client.previewPanel)
      .mockResolvedValueOnce(READY_PREVIEW)
      .mockResolvedValueOnce({ ...READY_PREVIEW, model: 'gemini-3-pro-image' })
    vi.mocked(client.updatePanelModel).mockResolvedValue(updatedPanel)

    renderPreview()
    const model = await screen.findByRole('combobox', { name: 'Generation model' })
    await user.selectOptions(model, 'gemini-3-pro-image')

    await waitFor(() => expect(client.updatePanelModel).toHaveBeenCalledWith(
      3,
      'gemini-3-pro-image',
    ))
    await waitFor(() => expect(client.previewPanel).toHaveBeenCalledTimes(2))
    expect(model).toHaveValue('gemini-3-pro-image')
  })

  it('allows the model to change after a successful generation', async () => {
    renderPreview()

    const model = await screen.findByRole('combobox', { name: 'Generation model' })
    expect(model).toBeEnabled()
    expect(model).toHaveValue('gemini-3.1-flash-image')
    expect(screen.getByText(/Applies to future generations/)).toBeInTheDocument()
  })

  it('shows the complete exact prompt before the paid generation button', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 0,
    })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)

    renderPreview()

    await screen.findByRole('heading', { name: 'Exact generation prompt' })
    const prompt = document.querySelector('.prompt-preview')
    const button = screen.getByRole('button', { name: /Generate one candidate/ })
    if (!(prompt instanceof HTMLElement)) throw new Error('prompt preview was not rendered')
    expect(prompt.tagName).toBe('PRE')
    expect(prompt).toHaveTextContent(READY_PREVIEW.prompt, { normalizeWhitespace: false })
    expect(prompt.closest('.panel-preview__content')).not.toBeNull()
    expect(button.closest('.panel-preview__sidebar')).not.toBeNull()
    expect(
      prompt.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('copies the exact prompt to the clipboard', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.spyOn(navigator, 'clipboard', 'get').mockReturnValue({ writeText } as unknown as Clipboard)
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 0,
    })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)

    renderPreview()

    const copy = await screen.findByRole('button', { name: 'Copy prompt' })
    await user.click(copy)

    expect(writeText).toHaveBeenCalledWith(READY_PREVIEW.prompt)
    expect(await screen.findByRole('button', { name: 'Copied!' })).toBeInTheDocument()
  })

  it('states that reference images are uploaded to Gemini before generating', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 0,
    })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)

    renderPreview()

    const note = await screen.findByText(/uploaded to Google's Gemini API/i)
    expect(note).toHaveTextContent(/leave your computer/i)
    // The disclosure appears before the paid generation button.
    const button = screen.getByRole('button', { name: /Generate one candidate/ })
    expect(
      note.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('shows the Base Stage source, ordered mapping, reference numbering, and expanded privacy disclosure', async () => {
    const stagedPanel: Panel = {
      ...LOCKED_PANEL,
      base_stage_id: 4,
      cast: [
        {
          character_id: 1,
          name: 'Elias',
          avatar_url: null,
          avatar_initials: 'EL',
          role: '',
          prominence: 2,
          base_stage_target_id: 41,
        },
      ],
      base_stage: {
        id: 4,
        description: 'Moonlit station platform',
        content_url: '/api/v1/base-stages/4/content',
        aspect_ratio: '3:2',
        state: 'ready',
        style_id: null,
        archived_at: null,
        targets: [{ id: 41, position: 1, description: 'traveler beside the train' }],
      },
    }
    vi.mocked(client.getPanel).mockResolvedValue(stagedPanel)
    vi.mocked(client.previewPanel).mockResolvedValue({
      ...READY_PREVIEW,
      base_stage_id: 4,
      source_content_url: '/api/v1/base-stages/4/content',
      attachments: [{
        character_id: 1,
        character_name: 'Elias',
        image_number: 2,
        ref_set_id: 8,
        ref_set_version: 3,
        role: 'face_front',
      }],
    })

    renderPreview()

    const sourceHeading = await screen.findByRole('heading', { name: 'Base Stage source' })
    expect(screen.getByRole('img', { name: /Base Stage source: Moonlit station platform/ })).toHaveAttribute(
      'src',
      '/api/v1/base-stages/4/content',
    )
    expect(screen.getByText('Image 1 is the source composition')).toBeInTheDocument()
    expect(screen.getByText('Character canonical references begin at Image 2.')).toBeInTheDocument()
    expect(screen.getByText('traveler beside the train').closest('li')).toHaveTextContent('Elias')
    expect(screen.getByText(/Image 2: Elias/)).toBeInTheDocument()
    const allocation = screen.getByRole('heading', { name: 'Reference-slot allocation' })
    expect(sourceHeading.compareDocumentPosition(allocation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText(/Base Stage image and character canonical references are uploaded/i))
      .toHaveTextContent(/leave your computer/i)
    expect(screen.getByRole('heading', { name: 'Exact generation prompt' })).toBeInTheDocument()
  })

  it('shows preserved failed generation attempts with error details', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 1,
    })
    vi.mocked(client.listPanelGenerations).mockResolvedValue([FAILED_ATTEMPT])

    renderPreview()

    expect(await screen.findByText('Attempt #5')).toBeInTheDocument()
    const timestamp = document.querySelector('time')
    expect(timestamp).toHaveAttribute('datetime', '2026-08-31T15:00:00.000Z')
    expect(timestamp).toHaveAttribute('title')
    expect(screen.getByText('Media resolution is not supported')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View details' })).not.toBeInTheDocument()
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
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('shows a carousel and reviews candidates from their attempt controls', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 1,
    })
    vi.mocked(client.listPanelGenerations)
      .mockResolvedValueOnce([{ ...SUCCEEDED_ATTEMPT, candidates: [CANDIDATE] }])
      .mockResolvedValue([
        {
          ...SUCCEEDED_ATTEMPT,
          candidates: [{ ...CANDIDATE, review_status: 'accepted' }],
        },
      ])
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.reviewCandidate).mockResolvedValue({
      ...CANDIDATE,
      review_status: 'accepted',
    })

    renderPreview()

    expect(await screen.findByText('1 / 1')).toBeInTheDocument()
    expect(screen.getAllByText('Waiting')).toHaveLength(2)

    // Carousel sits immediately after the page header, before the beat text
    // and prompt/preview sections.
    const heading = screen.getByRole('heading', { name: 'Preview panel' })
    const carousel = screen.getByLabelText('Generated candidate across attempts')
    const beat = screen.getByText('Mara backs toward the door.')
    const allocationHeading = screen.getByRole('heading', { name: 'Reference-slot allocation' })
    expect(
      heading.compareDocumentPosition(carousel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(
      carousel.compareDocumentPosition(beat) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(
      carousel.compareDocumentPosition(allocationHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    const attempt = document.querySelector('.attempt-row')
    expect(attempt).not.toBeNull()
    const actions = (attempt as HTMLElement).querySelector('.attempt-row__candidate-actions')
    expect(actions).not.toBeNull()
    expect(within(actions as HTMLElement).getAllByRole('button').map((button) => button.textContent?.trim()))
      .toEqual(['Accept', 'Reject', 'Edit this image'])
    await user.click(within(actions as HTMLElement).getByRole('button', { name: 'Accept' }))
    expect(client.reviewCandidate).toHaveBeenCalledWith(900, 'accepted')
    // Outcome is shown in place (badge flips), not via a top-of-page banner.
    expect(await screen.findAllByText('Accepted')).toHaveLength(2)
    expect(screen.queryByText('Waiting')).not.toBeInTheDocument()
    expect(screen.queryByText('Candidate accepted.')).not.toBeInTheDocument()
  })

  it('uses the newest attempt with an image in the carousel', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      is_editable: true,
      generation_count: 2,
    })
    vi.mocked(client.listPanelGenerations).mockResolvedValue([
      { ...SUCCEEDED_ATTEMPT, id: 10, candidates: [{ ...CANDIDATE, id: 901, generation_id: 10 }] },
      { ...FAILED_ATTEMPT, candidates: [] },
    ])

    renderPreview()

    expect(await screen.findByText('1 / 1')).toBeInTheDocument()
    const carousel = screen.getByLabelText('Generated candidate across attempts')
    expect(carousel).toHaveTextContent('Attempt #10')
    const alt = screen.getByAltText('Generated image from attempt 10')
    expect(alt).toBeInTheDocument()
  })

  it('cycles carousel images with arrow keys while the dialog stays open', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel).mockResolvedValue({
      ...LOCKED_PANEL,
      generation_count: 2,
    })
    vi.mocked(client.listPanelGenerations).mockResolvedValue([
      {
        ...SUCCEEDED_ATTEMPT,
        id: 10,
        candidates: [
          { ...CANDIDATE, id: 901, generation_id: 10, content_url: '/candidate-10.png' },
        ],
      },
      {
        ...SUCCEEDED_ATTEMPT,
        id: 9,
        candidates: [
          { ...CANDIDATE, id: 902, generation_id: 9, content_url: '/candidate-9.png' },
        ],
      },
    ])

    renderPreview()
    const carousel = await screen.findByLabelText('Generated candidate across attempts')
    await user.click(
      within(carousel).getByRole('button', { name: 'Preview image from attempt 10' }),
    )
    let dialog = screen.getByRole('dialog')
    expect(screen.getByRole('img', { name: /attempt 10, full-size preview/ })).toHaveAttribute(
      'src',
      '/candidate-10.png',
    )

    fireEvent.keyDown(dialog, { key: 'ArrowRight' })
    dialog = screen.getByRole('dialog')
    expect(screen.getByRole('img', { name: /attempt 9, full-size preview/ })).toHaveAttribute(
      'src',
      '/candidate-9.png',
    )

    fireEvent.keyDown(dialog, { key: 'ArrowLeft' })
    expect(screen.getByRole('img', { name: /attempt 10, full-size preview/ })).toHaveAttribute(
      'src',
      '/candidate-10.png',
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
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

  it('keeps panel, prompt, and history when generation and its reload fail', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel)
      .mockResolvedValueOnce(LOCKED_PANEL)
      .mockRejectedValueOnce(new Error('reload offline'))
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockResolvedValue([FAILED_ATTEMPT])
    vi.mocked(client.generatePanel).mockRejectedValue(new Error('provider offline'))
    renderPreview()

    await user.click(await screen.findByRole('button', { name: /Generate one candidate/ }))

    expect(await screen.findByText(/Could not start generation/)).toHaveAttribute('role', 'alert')
    expect(screen.getByText(/Could not refresh panel: Error: reload offline/)).toHaveAttribute(
      'role',
      'alert',
    )
    expect(screen.getByText('Mara backs toward the door.')).toBeInTheDocument()
    expect(document.querySelector('.prompt-preview')).toHaveTextContent(READY_PREVIEW.prompt, {
      normalizeWhitespace: false,
    })
    expect(screen.getByText('Attempt #5')).toBeInTheDocument()
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
    expect(screen.getByRole('combobox', { name: 'Generation model' })).toBeDisabled()
    expect(screen.getByText(/Locked while a generation is in progress/)).toBeInTheDocument()
    expect(screen.getByText(/refreshes automatically/)).toBeInTheDocument()
    expect(screen.getByText(/refreshes automatically/)).toHaveAttribute('role', 'status')
  })

  it('accepts a poll slower than two seconds without starting an overlapping request', async () => {
    vi.useFakeTimers()
    const slowHistory = deferred<GenerationSummary[]>()
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations)
      .mockResolvedValueOnce([PENDING_ATTEMPT])
      .mockImplementationOnce(() => slowHistory.promise)

    await act(async () => {
      renderPreview()
    })
    expect(screen.getByRole('button', { name: 'Generation in progress' })).toBeDisabled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(client.listPanelGenerations).toHaveBeenCalledTimes(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(client.listPanelGenerations).toHaveBeenCalledTimes(2)

    await act(async () => {
      slowHistory.resolve([SUCCEEDED_ATTEMPT])
      await slowHistory.promise
    })

    expect(screen.getByText('Generation attempt #7 succeeded.')).toHaveAttribute('role', 'status')
    expect(screen.getByText('Attempt #7')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(client.listPanelGenerations).toHaveBeenCalledTimes(2)
  })

  it('announces a pending-to-failed transition once and stops polling', async () => {
    vi.useFakeTimers()
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations)
      .mockResolvedValueOnce([PENDING_ATTEMPT])
      .mockResolvedValueOnce([{
        ...PENDING_ATTEMPT,
        state: 'failed',
        error_text: 'provider failed',
        completed_at: '2026-08-31 15:00:03',
      }])

    await act(async () => {
      renderPreview()
    })
    expect(screen.getByText(/refreshes automatically/)).toHaveAttribute('role', 'status')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(screen.getByText('Generation attempt #7 failed.')).toHaveAttribute('role', 'alert')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(client.listPanelGenerations).toHaveBeenCalledTimes(2)
  })

  it('does not navigate when generation completes after unmount', async () => {
    const generation = deferred<Generation>()
    const user = userEvent.setup()
    vi.mocked(client.getPanel).mockResolvedValue({ ...LOCKED_PANEL, is_editable: true })
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.generatePanel).mockImplementation(() => generation.promise)
    const page = renderPreview()

    await user.click(await screen.findByRole('button', { name: /Generate one candidate/ }))
    page.unmount()
    await act(async () => {
      generation.resolve(GENERATED)
      await generation.promise
    })

    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('does not navigate when duplication completes after unmount', async () => {
    const duplicate = deferred<Panel>()
    const user = userEvent.setup()
    vi.mocked(client.duplicatePanel).mockImplementation(() => duplicate.promise)
    const page = renderPreview()

    await user.click(await screen.findByRole('button', { name: /Duplicate & edit/ }))
    page.unmount()
    await act(async () => {
      duplicate.resolve({ ...LOCKED_PANEL, id: 99, is_editable: true })
      await duplicate.promise
    })

    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('shows panel and history when the initial preview request fails, then retries it', async () => {
    const user = userEvent.setup()
    vi.mocked(client.previewPanel)
      .mockRejectedValueOnce(new Error('preview offline'))
      .mockResolvedValueOnce(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockResolvedValue([FAILED_ATTEMPT])
    renderPreview()

    expect(await screen.findByText('Mara backs toward the door.')).toBeInTheDocument()
    expect(screen.getByText('Attempt #5')).toBeInTheDocument()
    expect(screen.getByText(/Could not load generation preview: Error: preview offline/)).toHaveAttribute(
      'role',
      'alert',
    )

    await user.click(screen.getByRole('button', { name: 'Retry preview' }))
    expect(await screen.findByRole('heading', { name: 'Exact generation prompt' })).toBeInTheDocument()
  })

  it('shows panel and preview when the initial history request fails with a section retry', async () => {
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockRejectedValue(new Error('history offline'))
    renderPreview()

    expect(await screen.findByText('Mara backs toward the door.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Exact generation prompt' })).toBeInTheDocument()
    expect(screen.getByText(/Could not load generation history: Error: history offline/)).toHaveAttribute(
      'role',
      'alert',
    )
    expect(screen.getByRole('button', { name: 'Retry generation history' })).toBeInTheDocument()
  })

  it('rejects malformed panel IDs without resource calls', async () => {
    renderPreview('/panels/bad/preview')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(client.getPanel).not.toHaveBeenCalled()
    expect(client.previewPanel).not.toHaveBeenCalled()
    expect(client.listPanelGenerations).not.toHaveBeenCalled()
  })

  it('renders not found when the initial panel request returns 404', async () => {
    vi.mocked(client.getPanel).mockRejectedValue(
      new client.ApiError('missing', 'NotFoundError', 404),
    )
    renderPreview()

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('retries an initial failure and updates the loaded title', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getPanel)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(LOCKED_PANEL)
    renderPreview()

    await waitFor(() => expect(document.title).toBe('Loading Panel Preview | LoreCraft3000'))
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/Mara backs toward the door/)).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Panel #3 Preview | LoreCraft3000'))
  })
})
