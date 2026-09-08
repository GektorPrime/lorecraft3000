import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { ComicPage } from '../../api/types'
import { ComicPageListPage } from './ComicPageListPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  listComicPages: vi.fn(),
  deleteComicPage: vi.fn(),
}))

const PAGE: ComicPage = {
  id: 7, title: 'The arrival', format: 'portrait', width_px: 1200, height_px: 1800,
  background_color: '#FFFFFF', gutter_px: 20, template_key: 'two_rows', template_version: 1,
  divider_values: [0.5], revision: 2, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-02T00:00:00Z',
  panels: [{ id: 1, candidate_id: 11, slot_index: 0, focal_x: 0.5, focal_y: 0.5, zoom: 1, content_url: '/candidate.png' }],
  latest_render: { id: 8, page_id: 7, page_revision: 2, width: 1200, height: 1800, content_url: '/preview.png', download_url: '/download.png', layout: {}, created_at: '2026-09-02T00:00:00Z' },
}

const renderPage = () => render(<MemoryRouter><ComicPageListPage /></MemoryRouter>)

describe('ComicPageListPage', () => {
  beforeEach(() => { vi.mocked(client.listComicPages).mockReset(); vi.mocked(client.deleteComicPage).mockReset() })

  it('shows loading, empty actions, and retries errors', async () => {
    vi.mocked(client.listComicPages).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([])
    renderPage()
    expect(screen.getByText('Loading comic pages…')).toBeInTheDocument()
    expect(await screen.findByText(/offline/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('No comic pages yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Gallery' })).toBeInTheDocument()
  })

  it('shows rendered cards, direct download, and confirms deletion', async () => {
    vi.mocked(client.listComicPages).mockResolvedValue([PAGE])
    vi.mocked(client.deleteComicPage).mockResolvedValue()
    renderPage()
    expect(await screen.findByRole('heading', { name: 'The arrival' })).toBeInTheDocument()
    expect(screen.getByText('1/2 panels')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('href', '/download.png')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete comic page' }))
    await waitFor(() => expect(client.deleteComicPage).toHaveBeenCalledWith(7))
    expect(screen.queryByRole('heading', { name: 'The arrival' })).not.toBeInTheDocument()
  })
})
