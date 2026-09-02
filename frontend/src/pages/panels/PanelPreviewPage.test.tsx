import { act, render, screen, waitFor } from '@testing-library/react'
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
    vi.mocked(client.generatePanel).mockReset()
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

  it('shows preserved failed generation attempts with a details link', async () => {
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
    expect(await screen.findByRole('heading', { name: 'Exact prompt sent to Gemini' })).toBeInTheDocument()
  })

  it('shows panel and preview when the initial history request fails with a section retry', async () => {
    vi.mocked(client.previewPanel).mockResolvedValue(READY_PREVIEW)
    vi.mocked(client.listPanelGenerations).mockRejectedValue(new Error('history offline'))
    renderPreview()

    expect(await screen.findByText('Mara backs toward the door.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Exact prompt sent to Gemini' })).toBeInTheDocument()
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
