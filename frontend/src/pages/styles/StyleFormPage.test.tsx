import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import { StyleFormPage } from './StyleFormPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getStyle: vi.fn(),
    createStyle: vi.fn(),
    updateStyle: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const EXISTING_STYLE = {
  id: 5,
  name: 'Ink Wash',
  style_contract: 'Loose ink wash.',
  ref_image_ids: [12, 15],
  created_at: '',
}

describe('StyleFormPage — reference image IDs', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    // mockReset (not just mockResolvedValue) so each test starts with a
    // clean call history — a previous test's successful submit must not
    // leak into a later test's "was this ever called" assertion.
    vi.mocked(client.getStyle).mockReset().mockResolvedValue(EXISTING_STYLE)
    vi.mocked(client.createStyle).mockReset().mockResolvedValue({ ...EXISTING_STYLE, id: 9 })
    vi.mocked(client.updateStyle).mockReset().mockResolvedValue(EXISTING_STYLE)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders an editable control for reference image IDs on a new style', async () => {
    render(
      <MemoryRouter initialEntries={['/styles/new']}>
        <Routes>
          <Route path="/styles/new" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    const field = await screen.findByLabelText('Reference image IDs')
    expect(field).toHaveValue('')
  })

  it('preserves existing reference image IDs when editing a style', async () => {
    render(
      <MemoryRouter initialEntries={['/styles/5/edit']}>
        <Routes>
          <Route path="/styles/:id/edit" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    const field = await screen.findByLabelText('Reference image IDs')
    expect(field).toHaveValue('12, 15')
    // No sha/hash text ever appears anywhere on the page.
    expect(document.body.textContent).not.toMatch(/[0-9a-f]{64}/)
  })

  it('submits edited reference image IDs as parsed integers, not raw text', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/styles/5/edit']}>
        <Routes>
          <Route path="/styles/:id/edit" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    const field = await screen.findByLabelText('Reference image IDs')
    await user.clear(field)
    await user.type(field, '3, 4, 5')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(client.updateStyle).toHaveBeenCalled())
    expect(client.updateStyle).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ ref_image_ids: [3, 4, 5] }),
    )
    expect(mockNavigate).toHaveBeenCalledWith('/styles')
  })

  it('rejects non-integer reference image IDs without submitting', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/styles/5/edit']}>
        <Routes>
          <Route path="/styles/:id/edit" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    const field = await screen.findByLabelText('Reference image IDs')
    await user.clear(field)
    await user.type(field, 'abc')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(/must be comma-separated integers/)).toBeInTheDocument()
    expect(client.updateStyle).not.toHaveBeenCalled()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('treats a blank reference-image-ID field as optional (empty list)', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/styles/5/edit']}>
        <Routes>
          <Route path="/styles/:id/edit" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    const field = await screen.findByLabelText('Reference image IDs')
    await user.clear(field)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(client.updateStyle).toHaveBeenCalled())
    expect(client.updateStyle).toHaveBeenCalledWith(5, expect.objectContaining({ ref_image_ids: [] }))
  })
})
