import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import * as client from '../../api/client'
import type { GalleryItem } from '../../api/types'
import { GalleryPage } from './GalleryPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return { ...actual, getGallery: vi.fn() }
})

const ACCEPTED: GalleryItem = {
  candidate_id: 900,
  content_url: '/api/v1/candidates/900/content',
  panel_id: 3,
  beat_text: 'Mara backs toward the door.',
  aspect_ratio: '3:2',
  created_at: '2026-09-02T00:00:00Z',
}

const SECOND_ACCEPTED: GalleryItem = {
  ...ACCEPTED,
  candidate_id: 901,
  content_url: '/api/v1/candidates/901/content',
  panel_id: 4,
  beat_text: 'Elias reaches for the lantern.',
}

describe('GalleryPage', () => {
  beforeEach(() => {
    vi.mocked(client.getGallery).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function renderGallery() {
    return render(
      <MemoryRouter>
        <GalleryPage />
      </MemoryRouter>,
    )
  }

  it('shows a loading state then the grid of accepted images', async () => {
    vi.mocked(client.getGallery).mockResolvedValue([ACCEPTED])
    renderGallery()

    expect(screen.getByText('Loading gallery…')).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('Mara backs toward the door.')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Gallery' })).toBeInTheDocument()
    expect(
      screen.getByLabelText('Preview accepted image from panel 3'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open panel' })).toHaveAttribute(
      'href',
      '/panels/3/preview',
    )
  })

  it('shows the empty state when no images are accepted', async () => {
    vi.mocked(client.getGallery).mockResolvedValue([])
    renderGallery()

    expect(await screen.findByText('No accepted images yet.')).toBeInTheDocument()
  })

  it('cycles through full-size images with arrow keys while the dialog stays open', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getGallery).mockResolvedValue([ACCEPTED, SECOND_ACCEPTED])
    renderGallery()

    await user.click(
      await screen.findByRole('button', { name: 'Preview accepted image from panel 3' }),
    )
    let dialog = screen.getByRole('dialog')
    expect(screen.getByRole('img', { name: /panel 3, full-size preview/ })).toHaveAttribute(
      'src',
      ACCEPTED.content_url,
    )

    fireEvent.keyDown(dialog, { key: 'ArrowRight' })
    dialog = screen.getByRole('dialog')
    expect(screen.getByRole('img', { name: /panel 4, full-size preview/ })).toHaveAttribute(
      'src',
      SECOND_ACCEPTED.content_url,
    )

    fireEvent.keyDown(dialog, { key: 'ArrowLeft' })
    expect(screen.getByRole('img', { name: /panel 3, full-size preview/ })).toHaveAttribute(
      'src',
      ACCEPTED.content_url,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('surfaces a load error', async () => {
    vi.mocked(client.getGallery).mockRejectedValue(new Error('gallery offline'))
    renderGallery()

    expect(await screen.findByText(/gallery offline/)).toBeInTheDocument()
  })
})
