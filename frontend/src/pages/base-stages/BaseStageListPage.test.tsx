import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { BaseStage } from '../../api/types'
import { BaseStageListPage } from './BaseStageListPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  listBaseStages: vi.fn(),
  listArchivedBaseStages: vi.fn(),
  archiveBaseStage: vi.fn(),
  restoreBaseStage: vi.fn(),
}))

const STAGE: BaseStage = {
  id: 4,
  archived_at: null,
  aspect_ratio: '3:2',
  beat_text: null,
  camera: null,
  content_url: '/api/v1/base-stages/4/content',
  created_at: '2026-01-01T00:00:00Z',
  description: 'A rain-soaked station platform at night.',
  dimensions: { width: 1536, height: 1024 },
  framing: null,
  image_size: null,
  model: null,
  mood: null,
  origin: 'upload',
  revision: 1,
  selected_candidate_id: null,
  state: 'ready',
  style_id: null,
  targets: [{ id: 1, position: 0, description: 'woman beneath the clock' }],
  usage_count: 2,
}

function renderPage() {
  render(<MemoryRouter><BaseStageListPage /></MemoryRouter>)
}

describe('BaseStageListPage', () => {
  beforeEach(() => {
    vi.mocked(client.listBaseStages).mockReset().mockResolvedValue([])
    vi.mocked(client.listArchivedBaseStages).mockReset().mockResolvedValue([])
    vi.mocked(client.archiveBaseStage).mockReset().mockResolvedValue(undefined)
    vi.mocked(client.restoreBaseStage).mockReset().mockResolvedValue(STAGE)
  })

  it('shows loading and then the upload-focused empty state', async () => {
    let resolveStages!: (stages: BaseStage[]) => void
    vi.mocked(client.listBaseStages).mockReturnValue(new Promise((resolve) => { resolveStages = resolve }))
    renderPage()

    expect(screen.getByText('Loading base stages…')).toBeInTheDocument()
    resolveStages([])
    expect(await screen.findByRole('heading', { name: 'No base stages yet' })).toBeInTheDocument()
  })

  it('renders preview and metadata without turning the card into a dead link', async () => {
    vi.mocked(client.listBaseStages).mockResolvedValue([STAGE])
    renderPage()

    expect(await screen.findByRole('button', { name: 'Preview base stage #4' })).toBeInTheDocument()
    expect(screen.getByText('1536 × 1024')).toBeInTheDocument()
    expect(screen.getByText('1 target')).toBeInTheDocument()
    expect(screen.getByText('Used 2 times')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Base stage #4/ })).not.toBeInTheDocument()
  })

  it('archives after explaining that stored content and links are preserved', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listBaseStages).mockResolvedValueOnce([STAGE]).mockResolvedValueOnce([])
    vi.mocked(client.listArchivedBaseStages).mockResolvedValueOnce([]).mockResolvedValueOnce([{ ...STAGE, archived_at: '2026-02-01T00:00:00Z' }])
    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(screen.getByText(/preserving its stored content and existing links/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Archive base stage' }))

    await waitFor(() => expect(client.archiveBaseStage).toHaveBeenCalledWith(4))
    expect(await screen.findByRole('button', { name: /Show archived base stages/ })).toBeInTheDocument()
  })

  it('restores an archived stage', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listArchivedBaseStages).mockResolvedValue([{ ...STAGE, archived_at: '2026-02-01T00:00:00Z' }])
    renderPage()

    await user.click(await screen.findByRole('button', { name: /Show archived base stages/ }))
    await user.click(screen.getByRole('button', { name: 'Restore' }))
    await waitFor(() => expect(client.restoreBaseStage).toHaveBeenCalledWith(4))
  })

  it('surfaces load failures', async () => {
    vi.mocked(client.listBaseStages).mockRejectedValue(new Error('library offline'))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('library offline')
  })
})
