import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from './client'
import { OptionsProvider } from './OptionsProvider'
import { useOptions } from './useOptions'
import type { OptionsSummary } from './types'

vi.mock('./client', async () => {
  const actual = await vi.importActual<typeof import('./client')>('./client')
  return { ...actual, getOptionsSummary: vi.fn() }
})

const OPTIONS: OptionsSummary = {
  models: [],
  image_sizes: [],
  aspect_ratios: [],
  ref_image_roles: [],
  default_model: 'model',
  default_image_size: '1K',
  daily_spend_cap_cents: 300,
  spent_today_cents: 7,
  remaining_today_cents: 293,
  ref_image_weight_explanation: '',
  ref_set_immutability_explanation: '',
  scene_immutability_explanation: '',
}

function Consumer() {
  const options = useOptions()
  return <p>Configured model: {options.default_model}</p>
}

describe('OptionsProvider', () => {
  beforeEach(() => vi.mocked(client.getOptionsSummary).mockReset())

  it('announces loading and retries a configuration failure', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getOptionsSummary)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(OPTIONS)
    render(
      <OptionsProvider>
        <Consumer />
      </OptionsProvider>,
    )

    expect(screen.getByRole('status')).toHaveTextContent('Loading app configuration')
    await user.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('Configured model: model')).toBeInTheDocument()
    expect(client.getOptionsSummary).toHaveBeenCalledTimes(2)
  })
})
