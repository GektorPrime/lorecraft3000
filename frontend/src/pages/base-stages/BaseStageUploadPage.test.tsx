import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { BaseStage } from '../../api/types'
import { BaseStageUploadPage } from './BaseStageUploadPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  uploadBaseStage: vi.fn(),
}))

const SAVED = { id: 9 } as BaseStage
const createObjectURL = vi.fn(() => 'blob:stage-preview')
const revokeObjectURL = vi.fn()

function renderPage() {
  const router = createMemoryRouter([
    { path: '/base-stages/upload', element: <BaseStageUploadPage /> },
    { path: '/base-stages', element: <h1>Base Stages</h1> },
  ], { initialEntries: ['/base-stages/upload'] })
  render(<RouterProvider router={router} />)
  return router
}

describe('BaseStageUploadPage', () => {
  beforeEach(() => {
    class MockURL extends URL {}
    Object.assign(MockURL, { createObjectURL, revokeObjectURL })
    vi.stubGlobal('URL', MockURL)
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    vi.mocked(client.uploadBaseStage).mockReset().mockResolvedValue(SAVED)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('adds and removes ordered textual targets', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Add target' }))
    await user.click(screen.getByRole('button', { name: 'Add target' }))
    await user.type(screen.getByLabelText('Target 1'), 'woman by the clock')
    await user.type(screen.getByLabelText('Target 2'), 'porter')
    await user.click(screen.getByRole('button', { name: 'Remove target 1' }))

    expect(screen.getByLabelText('Target 1')).toHaveValue('porter')
    expect(screen.queryByLabelText('Target 2')).not.toBeInTheDocument()
  })

  it('validates required, supported, complete, and 10MB-limited input', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Upload base stage' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a PNG')

    const oversized = new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'huge.png', { type: 'image/png' })
    await user.upload(screen.getByLabelText('Image'), oversized)
    await user.type(screen.getByLabelText('Description'), 'Large room')
    await user.click(screen.getByRole('button', { name: 'Upload base stage' }))
    expect(screen.getByRole('alert')).toHaveTextContent('larger than the 10MB upload limit')
    expect(client.uploadBaseStage).not.toHaveBeenCalled()
  })

  it('previews the selected file with its name and decoded dimensions', async () => {
    const user = userEvent.setup()
    renderPage()
    const file = new File(['image'], 'platform.webp', { type: 'image/webp' })
    await user.upload(screen.getByLabelText('Image'), file)

    const preview = screen.getByRole('img', { name: 'Selected base stage preview' })
    Object.defineProperties(preview, { naturalWidth: { value: 1200 }, naturalHeight: { value: 800 } })
    fireEvent.load(preview)
    expect(screen.getByText('platform.webp · 1200 × 800')).toBeInTheDocument()
    expect(preview).toHaveAttribute('src', 'blob:stage-preview')
  })

  it('submits trimmed values in target order and navigates on success', async () => {
    const user = userEvent.setup()
    const router = renderPage()
    const file = new File(['image'], 'platform.jpg', { type: 'image/jpeg' })
    await user.upload(screen.getByLabelText('Image'), file)
    await user.type(screen.getByLabelText('Description'), '  Night platform  ')
    await user.click(screen.getByRole('button', { name: 'Add target' }))
    await user.type(screen.getByLabelText('Target 1'), '  waiting traveler  ')
    await user.click(screen.getByRole('button', { name: 'Upload base stage' }))

    await waitFor(() => expect(client.uploadBaseStage).toHaveBeenCalledWith(file, 'Night platform', ['waiting traveler']))
    await waitFor(() => expect(router.state.location.pathname).toBe('/base-stages'))
  })

  it('keeps failed uploads editable and shows the API error', async () => {
    const user = userEvent.setup()
    vi.mocked(client.uploadBaseStage).mockRejectedValue(new Error('storage unavailable'))
    renderPage()
    await user.upload(screen.getByLabelText('Image'), new File(['image'], 'room.png', { type: 'image/png' }))
    await user.type(screen.getByLabelText('Description'), 'Sunlit room')
    await user.click(screen.getByRole('button', { name: 'Upload base stage' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not upload base stage: storage unavailable')
    expect(screen.getByLabelText('Description')).toHaveValue('Sunlit room')
  })

  it('protects unsaved form changes when canceling', async () => {
    const user = userEvent.setup()
    const router = renderPage()
    await user.type(screen.getByLabelText('Description'), 'Unfinished stage')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/base-stages/upload')
    await user.click(screen.getByRole('button', { name: 'Discard changes' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/base-stages'))
  })
})
