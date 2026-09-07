import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Scene } from '../../api/types'
import { SceneListPage } from './SceneListPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    listScenes: vi.fn(),
    deleteScene: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const LOCKED_PANEL: Scene = {
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
  latest_attempt_preview_url: '/api/v1/candidates/44/content',
  base_stage_id: null,
  base_stage: null,
}

const EDITABLE_PANEL: Scene = {
  ...LOCKED_PANEL,
  id: 3,
  beat_text: 'A quiet dawn over the harbor.',
  is_editable: true,
  generation_count: 0,
  latest_attempt_preview_url: null,
}

describe('SceneListPage — locked scene actions', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listScenes).mockReset().mockResolvedValue([LOCKED_PANEL])
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not offer Duplicate & edit on the listing page', async () => {
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )

    await screen.findByText('Elias draws his sword.')
    expect(screen.queryByRole('button', { name: /Duplicate & edit/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(screen.getByAltText('Latest generation attempt for scene #7')).toHaveAttribute(
      'src',
      '/api/v1/candidates/44/content',
    )
  })
})

describe('SceneListPage — preview via tile click', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listScenes).mockReset().mockResolvedValue([EDITABLE_PANEL])
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('no longer renders a separate Preview button', async () => {
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    expect(screen.queryByRole('link', { name: /Preview/ })).not.toBeInTheDocument()
  })

  it('opens the preview when the whole tile is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )
    const tile = await screen.findByRole('button', { name: /Preview scene #3/ })
    await user.click(tile)
    expect(mockNavigate).toHaveBeenCalledWith('/scenes/3/preview')
  })

  it('does not open the preview when an action button is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    await user.click(screen.getByRole('button', { name: /Delete/ }))
    expect(mockNavigate).not.toHaveBeenCalledWith('/scenes/3/preview')
  })

  it('does not expose Edit on editable scene cards', async () => {
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('places the status badge first in the metadata row', async () => {
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )
    await screen.findByText('A quiet dawn over the harbor.')
    const metadata = screen.getByText(/Cast:/).closest('.resource-card__meta')
    expect(metadata?.firstElementChild).toHaveTextContent('Editable')
  })

  it('marks scenes composed from a Base Stage with a navigable badge', async () => {
    vi.mocked(client.listScenes).mockResolvedValue([{ ...EDITABLE_PANEL, base_stage_id: 4 }])
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )

    const badge = await screen.findByRole('link', { name: 'Base Stage' })
    expect(badge).toHaveClass('badge')
    expect(badge).toHaveAttribute('href', '/base-stages/4/preview')
  })
})

describe('SceneListPage — delete', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listScenes).mockReset().mockResolvedValue([EDITABLE_PANEL])
    vi.mocked(client.deleteScene).mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('confirms then permanently deletes the scene and reloads', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listScenes)
      .mockResolvedValueOnce([EDITABLE_PANEL])
      .mockResolvedValueOnce([])
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Delete/ }))
    await user.click(await screen.findByRole('button', { name: 'Delete scene' }))

    await waitFor(() => expect(client.deleteScene).toHaveBeenCalledWith(3))
    await waitFor(() =>
      expect(screen.queryByText('A quiet dawn over the harbor.')).not.toBeInTheDocument(),
    )
    // Deleting a scene must not navigate to its (now gone) preview.
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('surfaces an error and keeps the scene when deletion fails', async () => {
    const user = userEvent.setup()
    vi.mocked(client.deleteScene).mockRejectedValue(new Error('offline'))
    render(
      <MemoryRouter>
        <SceneListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Delete/ }))
    await user.click(await screen.findByRole('button', { name: 'Delete scene' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not delete scene: Error: offline')
    expect(screen.getByText('A quiet dawn over the harbor.')).toBeInTheDocument()
  })
})
