import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ImageDialog } from './ImageDialog'

function renderDialog() {
  return render(
    <ImageDialog
      src="/portrait.jpg"
      thumbnailAlt="Portrait thumbnail"
      previewAlt="Portrait full size"
      triggerLabel="Preview portrait"
      dialogLabel="Portrait preview"
    />,
  )
}

describe('ImageDialog', () => {
  it('opens with showModal, an accessible name, and initial close-button focus', async () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, 'showModal')
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: 'Preview portrait' }))

    expect(showModal).toHaveBeenCalledOnce()
    expect(screen.getByRole('dialog', { name: 'Portrait preview' })).toHaveAttribute(
      'aria-modal',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Close preview' })).toHaveFocus()
    expect(screen.getByRole('img', { name: 'Portrait full size' })).toHaveAttribute(
      'src',
      '/portrait.jpg',
    )
  })

  it('ignores content clicks and closes from the backdrop with trigger focus restored', async () => {
    const user = userEvent.setup()
    renderDialog()
    const trigger = screen.getByRole('button', { name: 'Preview portrait' })
    await user.click(trigger)

    await user.click(screen.getByRole('img', { name: 'Portrait full size' }))
    expect(screen.getByRole('dialog', { name: 'Portrait preview' })).toBeInTheDocument()

    await user.click(screen.getByRole('dialog', { name: 'Portrait preview' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('synchronizes cancel and native close events', async () => {
    const user = userEvent.setup()
    renderDialog()
    const trigger = screen.getByRole('button', { name: 'Preview portrait' })

    await user.click(trigger)
    fireEvent(
      screen.getByRole('dialog', { name: 'Portrait preview' }),
      new Event('cancel', { cancelable: true }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Portrait preview' }) as HTMLDialogElement
    dialog.close()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })
})
