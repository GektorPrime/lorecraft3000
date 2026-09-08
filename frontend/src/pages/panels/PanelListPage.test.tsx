import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Panel } from '../../api/types'
import { createGrid } from '../../panels/layout'
import { PanelListPage } from './PanelListPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  listPanels: vi.fn(),
  deletePanel: vi.fn(),
}))

const PANEL: Panel = {
  id: 7, title: 'The arrival', format: 'portrait', width_px: 1200, height_px: 1800,
  background_color: '#FFFFFF', gutter_px: 20, frame_px: 12,
  revision: 2, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-02T00:00:00Z',
  slots: createGrid(1, 2).map((slot, index) => ({
    ...slot,
    id: index + 1,
    ...(index === 0 ? { candidate_id: 11, content_url: '/candidate.png' } : {}),
  })),
  latest_render: { id: 8, panel_id: 7, panel_revision: 2, width: 1200, height: 1800, content_url: '/preview.png', download_url: '/download.png', layout: {}, created_at: '2026-09-02T00:00:00Z' },
}

const renderPage = () => render(<MemoryRouter><PanelListPage /></MemoryRouter>)

describe('PanelListPage', () => {
  beforeEach(() => { vi.mocked(client.listPanels).mockReset(); vi.mocked(client.deletePanel).mockReset() })

  it('shows loading, empty actions, and retries errors', async () => {
    vi.mocked(client.listPanels).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([])
    renderPage()
    expect(screen.getByText('Loading panels…')).toBeInTheDocument()
    expect(await screen.findByText(/offline/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('No panels yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Gallery' })).toBeInTheDocument()
  })

  it('shows rendered cards, direct download, and confirms deletion', async () => {
    vi.mocked(client.listPanels).mockResolvedValue([PANEL])
    vi.mocked(client.deletePanel).mockResolvedValue()
    renderPage()
    expect(await screen.findByRole('heading', { name: 'The arrival' })).toBeInTheDocument()
    expect(screen.getByText('1/2 slots')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('href', '/download.png')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete panel' }))
    await waitFor(() => expect(client.deletePanel).toHaveBeenCalledWith(7))
    expect(screen.queryByRole('heading', { name: 'The arrival' })).not.toBeInTheDocument()
  })
})
