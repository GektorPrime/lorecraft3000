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
    duplicatePanel: vi.fn(),
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

describe('PanelListPage — Duplicate & edit', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listPanels).mockReset().mockResolvedValue([LOCKED_PANEL])
    vi.mocked(client.duplicatePanel).mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('duplicates a locked panel and navigates to editing the new panel', async () => {
    const user = userEvent.setup()
    vi.mocked(client.duplicatePanel).mockResolvedValue({
      ...LOCKED_PANEL,
      id: 42,
      is_editable: true,
      generation_count: 0,
    })

    render(
      <MemoryRouter>
        <PanelListPage />
      </MemoryRouter>,
    )

    const duplicateButton = await screen.findByRole('button', { name: /Duplicate & edit/ })
    await user.click(duplicateButton)

    await waitFor(() => expect(client.duplicatePanel).toHaveBeenCalledWith(7))
    // Duplicating alone doesn't edit anything — it must navigate to the new
    // panel's edit page (issue #15 follow-up).
    expect(mockNavigate).toHaveBeenCalledWith('/panels/42/edit')
  })
})
