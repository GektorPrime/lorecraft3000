import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from './client'
import { BudgetProvider } from './BudgetProvider'
import { BudgetContext, type BudgetContextValue } from './budgetContext'
import { OptionsContext } from './optionsContext'
import { useBudget } from './useBudget'
import type { OptionsSummary } from './types'
import { Header } from '../components/Header'

function RefreshButton() {
  const { refreshBudget } = useBudget()
  return (
    <button type="button" onClick={() => refreshBudget()}>
      Refresh budget
    </button>
  )
}

vi.mock('./client', async () => {
  const actual = await vi.importActual<typeof import('./client')>('./client')
  return { ...actual, getBudget: vi.fn() }
})

const OPTIONS: OptionsSummary = {
  models: ['gemini-3.1-flash-image'],
  image_sizes: ['1K'],
  aspect_ratios: ['3:2'],
  ref_image_roles: ['face_front'],
  default_model: 'gemini-3.1-flash-image',
  default_image_size: '1K',
  daily_spend_cap_cents: 300,
  spent_today_cents: 7,
  remaining_today_cents: 293,
  ref_image_weight_explanation: '',
  ref_set_immutability_explanation: '',
  panel_immutability_explanation: '',
}

function renderHeader() {
  return render(
    <MemoryRouter>
      <OptionsContext.Provider value={OPTIONS}>
        <BudgetProvider>
          <Header />
          <RefreshButton />
        </BudgetProvider>
      </OptionsContext.Provider>
    </MemoryRouter>,
  )
}

describe('BudgetProvider', () => {
  beforeEach(() => vi.mocked(client.getBudget).mockReset())

  it('starts from the options snapshot and refreshes the header on demand', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getBudget).mockResolvedValue({
      daily_spend_cap_cents: 300,
      spent_today_cents: 27,
      remaining_today_cents: 273,
    })
    renderHeader()
    expect(screen.getByText('Budget: $0.07 / $3.00')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Refresh budget' }))

    await screen.findByText('Budget: $0.27 / $3.00')
  })

  it('refreshes when the window regains focus', async () => {
    vi.mocked(client.getBudget).mockResolvedValue({
      daily_spend_cap_cents: 300,
      spent_today_cents: 42,
      remaining_today_cents: 258,
    })
    renderHeader()

    await waitFor(() => window.dispatchEvent(new Event('focus')))

    await screen.findByText('Budget: $0.42 / $3.00')
  })

  it('shows a stale-budget warning while keeping the last budget in the header', () => {
    const value: BudgetContextValue = {
      budget: { daily_spend_cap_cents: 300, spent_today_cents: 7, remaining_today_cents: 293 },
      refreshBudget: async () => {},
      refreshError: 'budget unavailable',
    }
    render(
      <MemoryRouter>
        <BudgetContext.Provider value={value}>
          <Header />
        </BudgetContext.Provider>
      </MemoryRouter>,
    )

    expect(screen.getByText('Budget may be out of date')).toBeInTheDocument()
    expect(screen.getByText('Budget: $0.07 / $3.00')).toBeInTheDocument()
  })
})
