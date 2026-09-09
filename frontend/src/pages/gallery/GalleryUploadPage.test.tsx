import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { GalleryPicture } from '../../api/types'
import { GalleryUploadPage } from './GalleryUploadPage'

vi.mock('../../api/client', async () => ({
  ...await vi.importActual<typeof import('../../api/client')>('../../api/client'),
  uploadGalleryPicture: vi.fn(),
}))

const SAVED = { id: 9 } as GalleryPicture
const createObjectURL = vi.fn(() => 'blob:gallery-preview')
const revokeObjectURL = vi.fn()

function renderPage() {
  const router = createMemoryRouter([
    { path: '/gallery/upload', element: <GalleryUploadPage /> },
    { path: '/gallery', element: <h1>Gallery</h1> },
  ], { initialEntries: ['/gallery/upload'] })
  render(<RouterProvider router={router} />)
  return router
}

describe('GalleryUploadPage', () => {
  beforeEach(() => {
    class MockURL extends URL {}
    Object.assign(MockURL, { createObjectURL, revokeObjectURL })
    vi.stubGlobal('URL', MockURL)
    vi.mocked(client.uploadGalleryPicture).mockReset().mockResolvedValue(SAVED)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('validates image type, upload size, and required title', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole('button', { name: 'Upload picture' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a PNG')

    fireEvent.change(screen.getByLabelText('Image'), { target: { files: [new File(['text'], 'notes.txt', { type: 'text/plain' })] } })
    await user.type(screen.getByLabelText('Title'), 'Notes')
    await user.click(screen.getByRole('button', { name: 'Upload picture' }))
    expect(screen.getByRole('alert')).toHaveTextContent('must be PNG, JPEG, or WebP')

    const oversized = new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'huge.webp', { type: 'image/webp' })
    fireEvent.change(screen.getByLabelText('Image'), { target: { files: [oversized] } })
    await user.click(screen.getByRole('button', { name: 'Upload picture' }))
    expect(screen.getByRole('alert')).toHaveTextContent('larger than the 10MB upload limit')

    fireEvent.change(screen.getByLabelText('Image'), { target: { files: [new File(['image'], 'valid.png', { type: 'image/png' })] } })
    await user.clear(screen.getByLabelText('Title'))
    await user.click(screen.getByRole('button', { name: 'Upload picture' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a title for this picture')
    expect(client.uploadGalleryPicture).not.toHaveBeenCalled()
  })

  it('previews dimensions, submits a trimmed title, and navigates to Gallery', async () => {
    const user = userEvent.setup()
    const router = renderPage()
    const file = new File(['image'], 'cover.jpg', { type: 'image/jpeg' })
    await user.type(screen.getByLabelText('Title'), '  Issue one cover  ')
    await user.upload(screen.getByLabelText('Image'), file)
    const preview = screen.getByRole('img', { name: 'Selected gallery picture preview' })
    Object.defineProperties(preview, { naturalWidth: { value: 1800 }, naturalHeight: { value: 1200 } })
    fireEvent.load(preview)
    expect(screen.getByText('cover.jpg · 1800 × 1200')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Upload picture' }))
    await waitFor(() => expect(client.uploadGalleryPicture).toHaveBeenCalledWith(file, 'Issue one cover'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/gallery'))
  })

  it('protects unsaved changes when canceling', async () => {
    const user = userEvent.setup()
    const router = renderPage()
    await user.type(screen.getByLabelText('Title'), 'Unfinished')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/gallery/upload')
  })
})
