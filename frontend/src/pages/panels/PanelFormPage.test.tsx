import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { OptionsSummary } from '../../api/types'
import { PanelFormPage } from './PanelFormPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    listCharacters: vi.fn(),
    listStyles: vi.fn(),
  }
})

const OPTIONS: OptionsSummary = {
  models: ['gemini-3.1-flash-image'],
  image_sizes: ['1K', '2K'],
  aspect_ratios: ['3:2', '16:9'],
  ref_image_roles: ['face_front'],
  default_model: 'gemini-3.1-flash-image',
  default_image_size: '1K',
  daily_spend_cap_cents: 300,
  spent_today_cents: 0,
  remaining_today_cents: 300,
  ref_image_weight_explanation: 'x',
  ref_set_immutability_explanation: 'y',
  panel_immutability_explanation: 'z',
}

vi.mock('../../api/useOptions', () => ({
  useOptions: () => OPTIONS,
}))

describe('PanelFormPage — field descriptions', () => {
  beforeEach(() => {
    vi.mocked(client.listCharacters).mockReset().mockResolvedValue([])
    vi.mocked(client.listStyles)
      .mockReset()
      .mockResolvedValue([
        { id: 1, name: 'Victorian Oil Painting', style_contract: '', ref_image_ids: [], created_at: '' },
      ])
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function renderForm() {
    return render(
      <MemoryRouter initialEntries={['/panels/new']}>
        <Routes>
          <Route path="/panels/new" element={<PanelFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('describes camera as viewer position/angle, distinct from framing as crop', async () => {
    renderForm()
    await screen.findByLabelText('Action')

    const cameraHint = document.getElementById('camera-hint')
    const framingHint = document.getElementById('framing-hint')
    expect(cameraHint).toHaveTextContent(/viewer's position and angle/i)
    expect(framingHint?.textContent).not.toMatch(/viewer's position/i)
    expect(framingHint).toHaveTextContent(/how tightly the shot is cropped/i)
    expect(framingHint).toHaveTextContent(/what remains visible/i)

    expect(screen.getByLabelText('Camera')).toHaveAttribute('aria-describedby', 'camera-hint')
    expect(screen.getByLabelText('Shot framing')).toHaveAttribute('aria-describedby', 'framing-hint')
  })

  it('provides a visible description with an example for aspect ratio, style, and image size', async () => {
    renderForm()
    await screen.findByLabelText('Action')

    const aspectHint = document.getElementById('aspect_ratio-hint')
    const styleHint = document.getElementById('style_id-hint')
    const sizeHint = document.getElementById('image_size-hint')

    expect(aspectHint).toHaveTextContent(/example/i)
    expect(styleHint).toHaveTextContent(/example/i)
    expect(sizeHint).toHaveTextContent(/example/i)

    expect(screen.getByLabelText('Aspect ratio')).toHaveAttribute('aria-describedby', 'aspect_ratio-hint')
    expect(screen.getByLabelText('Style')).toHaveAttribute('aria-describedby', 'style_id-hint')
    expect(screen.getByLabelText('Image size')).toHaveAttribute('aria-describedby', 'image_size-hint')
  })

  it('describes cast order and staging visibly (not only via placeholder)', async () => {
    renderForm()
    await screen.findByLabelText('Action')
    expect(screen.getByText(/Cast order:/)).toBeInTheDocument()
    expect(screen.getByText(/Staging:/)).toBeInTheDocument()
  })

  it('describes every remaining field (action, mood)', async () => {
    renderForm()
    await screen.findByLabelText('Action')
    expect(document.getElementById('beat_text-hint')).toBeTruthy()
    expect(document.getElementById('mood-hint')).toBeTruthy()
    expect(screen.getByLabelText('Action')).toHaveAttribute('aria-describedby', 'beat_text-hint')
    expect(screen.getByLabelText('Mood')).toHaveAttribute('aria-describedby', 'mood-hint')
  })

  it('waits for character/style lists to load without throwing', async () => {
    renderForm()
    await waitFor(() => expect(client.listCharacters).toHaveBeenCalled())
    await waitFor(() => expect(client.listStyles).toHaveBeenCalled())
  })
})
