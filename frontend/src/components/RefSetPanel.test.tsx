import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../api/client'
import { OptionsContext } from '../api/optionsContext'
import type { OptionsSummary, RefSet } from '../api/types'
import { RefSetPanel } from './RefSetPanel'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    getRefSet: vi.fn(),
    promoteRefSet: vi.fn(),
    removeRefImage: vi.fn(),
    uploadRefImage: vi.fn(),
    copyRefSet: vi.fn(),
    reRoleRefImage: vi.fn(),
  }
})

const options: OptionsSummary = {
  models: [],
  image_sizes: [],
  aspect_ratios: [],
  ref_image_roles: ['face_front'],
  default_model: 'gemini-3.1-flash-image',
  default_image_size: '1K',
  daily_spend_cap_cents: 100,
  spent_today_cents: 0,
  remaining_today_cents: 100,
  ref_image_weight_explanation: 'Weights are fixed.',
  ref_set_immutability_explanation: 'Canonical sets are immutable.',
  panel_immutability_explanation: 'Generated panels are immutable.',
}

const draft: RefSet = {
  id: 7,
  character_id: 2,
  version: 1,
  status: 'draft',
  created_at: '',
  images: [
    {
      id: 11,
      ref_set_id: 7,
      role: 'face_front',
      weight: 1,
      quality_flags: [],
      created_at: '',
      content_url: '/api/v1/ref-images/11/content',
    },
  ],
}

function renderPanel(refSet: RefSet = draft) {
  vi.mocked(client.getRefSet).mockResolvedValue(refSet)
  return render(
    <OptionsContext.Provider value={options}>
      <RefSetPanel refSetId={refSet.id} status={refSet.status} onChanged={vi.fn()} />
    </OptionsContext.Provider>,
  )
}

describe('RefSetPanel destructive confirmations', () => {
  beforeEach(() => {
    vi.mocked(client.getRefSet).mockReset()
    vi.mocked(client.promoteRefSet).mockReset().mockResolvedValue(draft)
    vi.mocked(client.removeRefImage).mockReset().mockResolvedValue(undefined)
    vi.mocked(client.uploadRefImage).mockReset()
    vi.mocked(client.copyRefSet).mockReset()
    vi.mocked(client.reRoleRefImage).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not remove an image when confirmation is cancelled', async () => {
    const user = userEvent.setup()
    renderPanel()

    const trigger = await screen.findByRole('button', { name: 'Remove' })
    await user.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Remove reference image?' })).toHaveTextContent(
      'permanently removed',
    )
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(client.removeRefImage).not.toHaveBeenCalled()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('removes an image exactly once after confirmation', async () => {
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Remove' }))
    await user.click(screen.getByRole('button', { name: 'Remove image' }))

    await waitFor(() => expect(client.removeRefImage).toHaveBeenCalledOnce())
    expect(client.removeRefImage).toHaveBeenCalledWith(7, 11)
  })

  it('does not promote when confirmation is cancelled', async () => {
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Promote to canonical' }))
    expect(screen.getByRole('dialog', { name: 'Promote reference set?' })).toHaveTextContent(
      'current canonical set',
    )
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(client.promoteRefSet).not.toHaveBeenCalled()
  })

  it('promotes exactly once and remains disabled while busy', async () => {
    const canonical = { ...draft, status: 'canonical' as const }
    let finishPromotion!: (value: RefSet) => void
    vi.mocked(client.getRefSet)
      .mockResolvedValueOnce(draft)
      .mockResolvedValueOnce(canonical)
    vi.mocked(client.promoteRefSet).mockReturnValue(
      new Promise((resolve) => {
        finishPromotion = resolve
      }),
    )
    const user = userEvent.setup()
    renderPanel()
    const button = await screen.findByRole('button', { name: 'Promote to canonical' })

    await user.click(button)
    await user.click(screen.getByRole('button', { name: 'Promote' }))

    expect(client.promoteRefSet).toHaveBeenCalledOnce()
    expect(button).toBeDisabled()
    finishPromotion(canonical)
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Promote to canonical' })).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Canonical sets are immutable.')).toBeInTheDocument()
  })

  it('reloads when the parent reports a status transition', async () => {
    const canonical = { ...draft, status: 'canonical' as const }
    const retired = { ...draft, status: 'retired' as const }
    vi.mocked(client.getRefSet)
      .mockResolvedValueOnce(canonical)
      .mockResolvedValueOnce(retired)

    const view = render(
      <OptionsContext.Provider value={options}>
        <RefSetPanel refSetId={draft.id} status="canonical" onChanged={vi.fn()} />
      </OptionsContext.Provider>,
    )
    expect(await screen.findByText('Canonical')).toBeInTheDocument()

    view.rerender(
      <OptionsContext.Provider value={options}>
        <RefSetPanel refSetId={draft.id} status="retired" onChanged={vi.fn()} />
      </OptionsContext.Provider>,
    )

    expect(await screen.findByText('Retired')).toBeInTheDocument()
    expect(client.getRefSet).toHaveBeenCalledTimes(2)
  })

  it('keeps promotion disabled for an empty draft', async () => {
    renderPanel({ ...draft, images: [] })

    expect(await screen.findByRole('button', { name: 'Promote to canonical' })).toBeDisabled()
  })

  it('keeps the loaded images and selected file when upload fails', async () => {
    const user = userEvent.setup()
    vi.mocked(client.uploadRefImage).mockRejectedValue(new Error('upload offline'))
    renderPanel()
    const input = await screen.findByLabelText('Reference image file')
    const file = new File(['image'], 'elias.png', { type: 'image/png' })

    await user.upload(input, file)
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not upload reference image: Error: upload offline',
    )
    expect(screen.getByRole('button', { name: 'Preview face_front reference' })).toBeInTheDocument()
    expect(input).toHaveValue('C:\\fakepath\\elias.png')
  })
})
