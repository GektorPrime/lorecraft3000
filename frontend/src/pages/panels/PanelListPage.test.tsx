import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Panel } from '../../api/types'
import { PanelListPage } from './PanelListPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    listPanels: vi.fn(),
    deletePanel: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const LOCKED_PANEL: Panel = {
  id: 7,
  beat_text: 'Elias draws his sword.',
  camera: 'low angle',
  framing: 'close up',
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

const EDITABLE_PANEL: Panel = {
  ...LOCKED_PANEL,
  id: 3,
  beat_text: 'A quiet dawn over the harbor.',
  is_editable: true,
  generation_count: 0,
}

describe('PanelListPage — locked panel actions', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listPanels).mockReset().mockResolvedValue([LOCKED_PANEL])
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not offer Duplicate & edit on the listing page', async () => {
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )

    await screen.findByText('Elias draws his sword.')
    expect(screen.queryByRole('button', { name: /Duplicate & edit/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })
})

describe('PanelListPage — preview via tile click', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listPanels).mockReset().mockResolvedValue([EDITABLE_PANEL])
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('no longer renders a separate Preview button', async () => {
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    expect(screen.queryByRole('link', { name: /Preview/ })).not.toBeInTheDocument()
  })

  it('opens the preview when the whole tile is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )
    const tile = await screen.findByRole('button', { name: /Preview panel #3/ })
    await user.click(tile)
    expect(mockNavigate).toHaveBeenCalledWith('/panels/3/preview')
  })

  it('does not open the preview when an action button is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    await user.click(screen.getByRole('button', { name: /Delete/ }))
    expect(mockNavigate).not.toHaveBeenCalledWith('/panels/3/preview')
  })

  it('does not expose Edit on editable panel cards', async () => {
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('places the status badge first in the metadata row', async () => {
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    const metadata = screen.getByText(/Cast:/).closest('.resource-card__meta')
    expect(metadata?.firstElementChild).toHaveTextContent('Editable')
  })
})

describe('PanelListPage — delete', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listPanels).mockReset().mockResolvedValue([EDITABLE_PANEL])
    vi.mocked(client.deletePanel).mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('confirms then permanently deletes the panel and reloads', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listPanels)
      .mockResolvedValueOnce([EDITABLE_PANEL])
      .mockResolvedValueOnce([])
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Delete/ }))
    await user.click(await screen.findByRole('button', { name: 'Delete panel' }))

    await waitFor(() => expect(client.deletePanel).toHaveBeenCalledWith(3))
    await waitFor(() =>
      expect(screen.queryByText('A quiet dawn over the harbor.')).not.toBeInTheDocument(),
    )
    // Deleting a panel must not navigate to its (now gone) preview.
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('surfaces an error and keeps the panel when deletion fails', async () => {
    const user = userEvent.setup()
    vi.mocked(client.deletePanel).mockRejectedValue(new Error('offline'))
    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Delete/ }))
    await user.click(await screen.findByRole('button', { name: 'Delete panel' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not delete panel: Error: offline')
    expect(screen.getByText('A quiet dawn over the harbor.')).toBeInTheDocument()
  })
})
