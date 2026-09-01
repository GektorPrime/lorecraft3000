import { fireEvent, render, screen } from '@testing-library/react'
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/generations/8']}>
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
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(trigger)
    await user.click(screen.getByRole('dialog'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('closes when Escape is pressed', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Preview candidate 0' }))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
