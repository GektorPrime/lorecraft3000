import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { GalleryItem, Panel, PanelRender } from '../../api/types'
import { createGrid } from '../../panels/layout'
import { PanelEditorPage } from './PanelEditorPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  createPanel: vi.fn(), getPanel: vi.fn(), getGallery: vi.fn(), updatePanel: vi.fn(), renderPanel: vi.fn(),
}))
vi.mock('../../hooks/useUnsavedChanges', () => ({ useUnsavedChanges: () => ({ allowNavigation: vi.fn(), confirmationProps: { open: false } }) }))

const ITEMS: GalleryItem[] = [
  { candidate_id: 11, content_url: '/11.png', scene_id: 1, beat_text: 'One', aspect_ratio: '3:2', created_at: '2026-09-01T00:00:00Z' },
  { candidate_id: 12, content_url: '/12.png', scene_id: 2, beat_text: 'Two', aspect_ratio: '3:2', created_at: '2026-09-01T00:00:00Z' },
]
const slots = createGrid(1, 2).map((slot, index) => ({ ...slot, id: index + 1 }))
const PANEL: Panel = {
  id: 5, title: 'Panel five', format: 'portrait', width_px: 1200, height_px: 1800,
  background_color: '#FFFFFF', gutter_px: 20, frame_px: 0, revision: 3,
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', slots, latest_render: null,
}
const RENDER: PanelRender = { id: 9, panel_id: 5, panel_revision: 4, width: 1200, height: 1800, content_url: '/render.png', download_url: '/render-download.png', layout: {}, created_at: '2026-09-01T00:00:00Z' }

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/panels/new" element={<PanelEditorPage />} /><Route path="/panels/:id/edit" element={<PanelEditorPage />} /></Routes></MemoryRouter>)
}

describe('PanelEditorPage', () => {
  beforeEach(() => {
    vi.mocked(client.createPanel).mockReset()
    vi.mocked(client.getPanel).mockReset()
    vi.mocked(client.getGallery).mockReset()
    vi.mocked(client.updatePanel).mockReset()
    vi.mocked(client.renderPanel).mockReset()
  })

  it('previews and selects a grid with the mouse while preserving Gallery handoff', async () => {
    vi.mocked(client.createPanel).mockResolvedValue(PANEL)
    renderAt('/panels/new?candidate=11')
    fireEvent.mouseEnter(screen.getByRole('button', { name: '3 columns × 2 rows' }))
    expect(screen.getByText('3 columns × 2 rows')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '3 columns × 2 rows' }))
    await userEvent.clear(screen.getByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'Opening panel')
    await userEvent.click(screen.getByRole('button', { name: 'Create and compose' }))
    await waitFor(() => expect(client.createPanel).toHaveBeenCalledWith({
      title: 'Opening panel', format: 'portrait', rows: 2, columns: 3, candidate_id: 11,
    }))
  })

  it('supports arrow-key focus and keyboard grid selection', async () => {
    vi.mocked(client.createPanel).mockResolvedValue(PANEL)
    renderAt('/panels/new')
    const first = screen.getByRole('button', { name: '1 column × 1 row' })
    first.focus()
    await userEvent.keyboard('{ArrowRight}{ArrowDown}{Enter}')
    expect(screen.getByText('2 columns × 2 rows')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create and compose' }))
    await waitFor(() => expect(client.createPanel).toHaveBeenCalledWith(expect.objectContaining({ rows: 2, columns: 2 })))
  })

  it('assigns only the selected slot, allows duplicates, saves geometry and gates render', async () => {
    vi.mocked(client.getPanel).mockResolvedValue(PANEL)
    vi.mocked(client.getGallery).mockResolvedValue(ITEMS)
    vi.mocked(client.updatePanel).mockImplementation(async (_id, payload) => ({
      ...PANEL, ...payload, revision: 4,
      slots: payload.slots.map((slot, index) => ({ ...slot, id: index + 1, content_url: slot.candidate_id === null ? null : `/${slot.candidate_id}.png` })),
    }))
    vi.mocked(client.renderPanel).mockResolvedValue(RENDER)
    renderAt('/panels/5/edit')
    expect(await screen.findByLabelText('Panel canvas')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Render / export' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Assign image 11 to selected slot' }))
    await userEvent.click(screen.getByRole('button', { name: 'Assign image 12 to selected slot' }))
    expect(screen.getByRole('button', { name: 'Slot 1, image 12' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Slot 2, empty' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Slot 2, empty' }))
    await userEvent.click(screen.getByRole('button', { name: 'Assign image 12 to selected slot' }))
    expect(screen.getAllByText('Used · assign again')).toHaveLength(1)
    expect(screen.getByText(/2 of 2 slots filled/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Internal gutter:/), { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText(/Outer frame:/), { target: { value: '24' } })
    await userEvent.click(screen.getByRole('button', { name: 'Set background #20242B' }))
    fireEvent.input(screen.getByLabelText('Left edge'), { target: { value: '0.6' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save panel' }))

    await waitFor(() => expect(client.updatePanel).toHaveBeenCalledWith(5, expect.objectContaining({
      expected_revision: 3, gutter_px: 30, frame_px: 24, background_color: '#20242B',
      slots: [
        expect.objectContaining({ candidate_id: 12, slot_index: 0, x0: 0, x1: 0.6 }),
        expect.objectContaining({ candidate_id: 12, slot_index: 1, x0: 0.6, x1: 1 }),
      ],
    })))
    await userEvent.click(screen.getByRole('button', { name: 'Render / export' }))
    await waitFor(() => expect(client.renderPanel).toHaveBeenCalledWith(5, { expected_revision: 4 }))
  })

  it('exposes split, merge, add row and add column controls', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({ ...PANEL, slots: [{ ...createGrid(1, 1)[0], id: 1 }] })
    vi.mocked(client.getGallery).mockResolvedValue(ITEMS)
    renderAt('/panels/5/edit')
    await screen.findByLabelText('Panel canvas')
    expect(screen.getByLabelText('Left edge')).toBeDisabled()
    expect(screen.getByLabelText('Right edge')).toBeDisabled()
    expect(screen.getByLabelText('Top edge')).toBeDisabled()
    expect(screen.getByLabelText('Bottom edge')).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Split vertically' }))
    expect(screen.getAllByRole('button', { name: /Slot \d, empty/ })).toHaveLength(2)
    expect(screen.getByLabelText('Left edge')).toBeDisabled()
    expect(screen.getByLabelText('Right edge')).toBeEnabled()
    expect(screen.getByLabelText('Top edge')).toBeDisabled()
    expect(screen.getByLabelText('Bottom edge')).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Merge right' }))
    expect(screen.getAllByRole('button', { name: /Slot \d, empty/ })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Add row' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add column' }))
    expect(screen.getAllByRole('button', { name: /Slot \d, empty/ })).toHaveLength(4)
  })

  it('merges differently populated slots and retains the selected image', async () => {
    vi.mocked(client.getPanel).mockResolvedValue({
      ...PANEL,
      slots: slots.map((slot, index) => ({
        ...slot,
        candidate_id: ITEMS[index].candidate_id,
        content_url: ITEMS[index].content_url,
      })),
    })
    vi.mocked(client.getGallery).mockResolvedValue(ITEMS)
    renderAt('/panels/5/edit')
    await screen.findByLabelText('Panel canvas')

    const mergeRight = screen.getByRole('button', { name: 'Merge right' })
    expect(mergeRight).toBeEnabled()
    await userEvent.click(mergeRight)

    expect(screen.getByRole('button', { name: 'Slot 1, image 11' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Slot 2, image 12' })).not.toBeInTheDocument()
  })

  it('offers an actionable reload for revision conflicts', async () => {
    vi.mocked(client.getPanel).mockResolvedValue(PANEL)
    vi.mocked(client.getGallery).mockResolvedValue(ITEMS)
    vi.mocked(client.updatePanel).mockRejectedValue(new client.ApiError('stale', 'PanelRevisionConflictError', 409))
    renderAt('/panels/5/edit')
    await userEvent.clear(await screen.findByLabelText('Title'))
    await userEvent.type(screen.getByLabelText('Title'), 'Changed')
    await userEvent.click(screen.getByRole('button', { name: 'Save panel' }))
    expect(await screen.findByText(/changed elsewhere/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload panel' })).toBeInTheDocument()
  })
})
