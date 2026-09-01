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
  render(
    <OptionsContext.Provider value={options}>
      <RefSetPanel refSetId={refSet.id} onChanged={vi.fn()} />
    </OptionsContext.Provider>,
  )
}

describe('RefSetPanel destructive confirmations', () => {
  beforeEach(() => {
    vi.mocked(client.getRefSet).mockReset()
    vi.mocked(client.promoteRefSet).mockReset().mockResolvedValue(draft)
    vi.mocked(client.removeRefImage).mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not remove an image when confirmation is cancelled', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Remove' }))

    expect(confirm).toHaveBeenCalledOnce()
    expect(confirm).toHaveBeenCalledWith('Remove this image from the draft?')
    expect(client.removeRefImage).not.toHaveBeenCalled()
  })

  it('removes an image exactly once after confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(client.removeRefImage).toHaveBeenCalledOnce())
    expect(confirm).toHaveBeenCalledOnce()
    expect(client.removeRefImage).toHaveBeenCalledWith(7, 11)
  })

  it('does not promote when confirmation is cancelled', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Promote to canonical' }))

    expect(confirm).toHaveBeenCalledOnce()
    expect(confirm).toHaveBeenCalledWith(
      'Promote this draft to canonical? The draft will become immutable, and the current canonical, if any, will be retired.',
    )
    expect(client.promoteRefSet).not.toHaveBeenCalled()
  })

  it('promotes exactly once and remains disabled while busy', async () => {
    let finishPromotion!: (value: RefSet) => void
    vi.mocked(client.promoteRefSet).mockReturnValue(
      new Promise((resolve) => {
        finishPromotion = resolve
      }),
    )
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPanel()
    const button = await screen.findByRole('button', { name: 'Promote to canonical' })

    await user.click(button)

    expect(confirm).toHaveBeenCalledOnce()
    expect(client.promoteRefSet).toHaveBeenCalledOnce()
    expect(button).toBeDisabled()
    finishPromotion(draft)
    await waitFor(() => expect(button).toBeEnabled())
  })

  it('keeps promotion disabled for an empty draft', async () => {
    renderPanel({ ...draft, images: [] })

    expect(await screen.findByRole('button', { name: 'Promote to canonical' })).toBeDisabled()
  })
})
