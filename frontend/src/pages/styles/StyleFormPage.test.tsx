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
  created_at: '',
}

describe('StyleFormPage', () => {
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

  it('does not render a reference image control', async () => {
    render(
      <MemoryRouter initialEntries={['/styles/new']}>
        <Routes>
          <Route path="/styles/new" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.queryByLabelText('Reference image IDs')).not.toBeInTheDocument()
  })

  it('loads and updates a style without reference image IDs', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/styles/5/edit']}>
        <Routes>
          <Route path="/styles/:id/edit" element={<StyleFormPage />} />
        </Routes>
      </MemoryRouter>,
    )
    const contract = await screen.findByLabelText('Style contract')
    await user.clear(contract)
    await user.type(contract, 'Updated wash.')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(client.updateStyle).toHaveBeenCalled())
    expect(client.updateStyle).toHaveBeenCalledWith(5, {
      name: 'Ink Wash',
      style_contract: 'Updated wash.',
    })
    expect(mockNavigate).toHaveBeenCalledWith('/styles')
  })
})
