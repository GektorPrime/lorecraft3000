import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { ComicPage, GalleryItem, PageRender } from '../../api/types'
import { ComicPageEditorPage } from './ComicPageEditorPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  createComicPage: vi.fn(), getComicPage: vi.fn(), getGallery: vi.fn(), updateComicPage: vi.fn(), renderComicPage: vi.fn(),
}))
vi.mock('../../hooks/useUnsavedChanges', () => ({ useUnsavedChanges: () => ({ allowNavigation: vi.fn(), confirmationProps: { open: false } }) }))

const ITEMS: GalleryItem[] = [
  { candidate_id: 11, content_url: '/11.png', scene_id: 1, beat_text: 'One', aspect_ratio: '3:2', created_at: '2026-09-01T00:00:00Z' },
  { candidate_id: 12, content_url: '/12.png', scene_id: 2, beat_text: 'Two', aspect_ratio: '3:2', created_at: '2026-09-01T00:00:00Z' },
]
const PAGE: ComicPage = {
  id: 5, title: 'Page five', format: 'portrait', width_px: 1200, height_px: 1800,
  background_color: '#FFFFFF', gutter_px: 20, template_key: 'two_rows', template_version: 1,
  divider_values: [0.5], revision: 3, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', panels: [], latest_render: null,
}
const RENDER: PageRender = { id: 9, page_id: 5, page_revision: 4, width: 1200, height: 1800, content_url: '/render.png', download_url: '/render-download.png', layout: {}, created_at: '2026-09-01T00:00:00Z' }

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/panels/new" element={<ComicPageEditorPage />} /><Route path="/panels/:id/edit" element={<ComicPageEditorPage />} /></Routes></MemoryRouter>)
}

describe('ComicPageEditorPage', () => {
  beforeEach(() => {
    vi.mocked(client.createComicPage).mockReset()
    vi.mocked(client.getComicPage).mockReset()
    vi.mocked(client.getGallery).mockReset()
    vi.mocked(client.updateComicPage).mockReset()
    vi.mocked(client.renderComicPage).mockReset()
  })

  it('creates with any template and atomically assigns a Gallery candidate', async () => {
    vi.mocked(client.createComicPage).mockResolvedValue(PAGE)
    renderAt('/panels/new?candidate=11')
    await userEvent.clear(screen.getByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'Opening page')
    await userEvent.selectOptions(screen.getByLabelText('Template'), 'six_grid')
    await userEvent.click(screen.getByRole('button', { name: 'Create and compose' }))
    await waitFor(() => expect(client.createComicPage).toHaveBeenCalledWith({
      title: 'Opening page', format: 'portrait', template_key: 'six_grid', candidate_id: 11,
    }))
    expect(client.updateComicPage).not.toHaveBeenCalled()
  })

  it('hydrates, assigns/removes, edits geometry, saves a revision payload, then renders', async () => {
    vi.mocked(client.getComicPage).mockResolvedValue(PAGE)
    vi.mocked(client.getGallery).mockResolvedValue(ITEMS)
    vi.mocked(client.updateComicPage).mockImplementation(async (_id, payload) => ({
      ...PAGE, revision: 4, title: payload.title, gutter_px: payload.gutter_px, divider_values: payload.divider_values,
      panels: payload.panels.map((panel, index) => ({ ...panel, id: index + 1, content_url: `/${panel.candidate_id}.png` })),
    }))
    vi.mocked(client.renderComicPage).mockResolvedValue(RENDER)
    renderAt('/panels/5/edit')
    expect(await screen.findByLabelText('Two rows page canvas')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Render / export' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Add image 11 to panel' }))
    await userEvent.click(screen.getByRole('button', { name: 'Panel 2, empty' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add image 12 to panel' }))
    expect(screen.getByRole('button', { name: 'Already used image 11 to panel' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Horizontal focal point/), { target: { value: '0.7' } })
    fireEvent.change(screen.getByLabelText(/Zoom:/), { target: { value: '1.5' } })
    fireEvent.change(screen.getByLabelText(/Row split:/), { target: { value: '0.6' } })
    fireEvent.change(screen.getByLabelText(/Gutter:/), { target: { value: '30' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save page' }))

    await waitFor(() => expect(client.updateComicPage).toHaveBeenCalledWith(5, expect.objectContaining({
      expected_revision: 3, gutter_px: 30, divider_values: [0.6], panels: [
        { candidate_id: 11, slot_index: 0, focal_x: 0.5, focal_y: 0.5, zoom: 1 },
        { candidate_id: 12, slot_index: 1, focal_x: 0.7, focal_y: 0.5, zoom: 1.5 },
      ],
    })))
    await userEvent.click(screen.getByRole('button', { name: 'Render / export' }))
    await waitFor(() => expect(client.renderComicPage).toHaveBeenCalledWith(5, { expected_revision: 4 }))
    expect(screen.getByRole('link', { name: 'Preview' })).toHaveAttribute('href', '/render.png')
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('href', '/render-download.png')

    await userEvent.click(screen.getByRole('button', { name: 'Remove from panel' }))
    expect(screen.getByRole('button', { name: 'Panel 2, empty' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Render / export' })).toBeDisabled()
  })

  it('offers an actionable reload for revision conflicts', async () => {
    vi.mocked(client.getComicPage).mockResolvedValue(PAGE)
    vi.mocked(client.getGallery).mockResolvedValue(ITEMS)
    vi.mocked(client.updateComicPage).mockRejectedValue(new client.ApiError('stale', 'PageRevisionConflictError', 409))
    renderAt('/panels/5/edit')
    await userEvent.clear(await screen.findByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'Changed')
    await userEvent.click(screen.getByRole('button', { name: 'Save page' }))
    expect(await screen.findByText(/changed elsewhere/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload page' })).toBeInTheDocument()
  })
})
