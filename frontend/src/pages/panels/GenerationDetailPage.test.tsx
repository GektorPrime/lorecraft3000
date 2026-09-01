import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Generation } from '../../api/types'
import { GenerationDetailPage } from './GenerationDetailPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getGeneration: vi.fn(),
    reviewCandidate: vi.fn(),
  }
})

const GENERATION: Generation = {
  id: 8,
  scene_id: 3,
  model: 'gemini-3-pro-image',
  image_size: '2K',
  aspect_ratio: '3:4',
  prompt: 'A detailed comic panel',
  prompt_hash: 'prompt-hash',
  attachments: [],
  warnings: [],
  cost_usd_cents: 20,
  reserved_cost_usd_cents: 20,
  actual_cost_usd_cents: null,
  state: 'succeeded',
  interaction_id: null,
  error_text: null,
  completed_at: '2026-08-31 15:00:01',
  created_at: '2026-08-31 15:00:00',
  candidates: [
    {
      id: 12,
      generation_id: 8,
      idx: 0,
      review_status: 'pending',
      content_url: '/api/v1/candidates/12/content',
      created_at: '2026-08-31 15:00:01',
    },
  ],
}

function renderPage(path = '/generations/8') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/generations/:id" element={<GenerationDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('GenerationDetailPage candidate preview', () => {
  beforeEach(() => {
    vi.mocked(client.getGeneration).mockReset().mockResolvedValue(GENERATION)
    vi.mocked(client.reviewCandidate).mockReset()
  })

  it('opens a modal that uses the original candidate content URL', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Preview candidate 0' }))

    const dialog = screen.getByRole('dialog', { name: 'Candidate 0, larger preview' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('img', { name: 'Candidate 0, full-size preview' })).toHaveAttribute(
      'src',
      '/api/v1/candidates/12/content',
    )
  })

  it('closes from the close button and backdrop', async () => {
    const user = userEvent.setup()
    renderPage()
    const trigger = await screen.findByRole('button', { name: 'Preview candidate 0' })

    await user.click(trigger)
    await user.click(screen.getByRole('button', { name: 'Close preview' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    await user.click(trigger)
    await user.click(screen.getByRole('dialog'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('closes when Escape is pressed', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Preview candidate 0' }))
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('rejects malformed generation IDs without an API request', async () => {
    renderPage('/generations/bad')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(client.getGeneration).not.toHaveBeenCalled()
  })

  it('renders not found for a missing generation', async () => {
    vi.mocked(client.getGeneration).mockRejectedValue(
      new client.ApiError('missing', 'NotFoundError', 404),
    )
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('retries an initial failure and updates the generation title', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getGeneration)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(GENERATION)
    renderPage()

    await waitFor(() => expect(document.title).toBe('Loading Generation | LoreCraft3000'))
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { name: 'Generation #8' })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Generation #8 | LoreCraft3000'))
  })

  it('keeps generation content when review succeeds but refresh fails', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getGeneration)
      .mockResolvedValueOnce(GENERATION)
      .mockRejectedValueOnce(new Error('refresh offline'))
    vi.mocked(client.reviewCandidate).mockResolvedValue({
      ...GENERATION.candidates[0],
      review_status: 'accepted',
    })
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Accept' }))

    expect(await screen.findByText(/Candidate accepted, but generation details/)).toHaveTextContent(
      'Candidate accepted, but generation details could not be refreshed: Error: refresh offline',
    )
    expect(screen.getByText('A detailed comic panel')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview candidate 0' })).toBeInTheDocument()
  })
})
