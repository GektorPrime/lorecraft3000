import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { CastMemberInput, Character } from '../api/types'
import { CastSelector } from './CastSelector'

const CHARACTERS: Character[] = [
  {
    id: 1,
    name: 'Elias',
    slug: 'elias',
    lore_md: '',
    visual_contract: '',
    negative_traits: '',
    default_style_id: null,
    created_at: '',
    has_canonical_ref_set: true,
    avatar_url: null,
    avatar_initials: 'EL',
  },
  {
    id: 2,
    name: 'Mara',
    slug: 'mara',
    lore_md: '',
    visual_contract: '',
    negative_traits: '',
    default_style_id: null,
    created_at: '',
    has_canonical_ref_set: true,
    avatar_url: null,
    avatar_initials: 'MA',
  },
]

const UNREADY_CHARACTER: Character = {
  ...CHARACTERS[1],
  id: 3,
  name: 'Tomas',
  slug: 'tomas',
  has_canonical_ref_set: false,
  avatar_initials: 'TO',
}

function Harness() {
  const [cast, setCast] = useState<CastMemberInput[]>([])
  return <CastSelector characters={CHARACTERS} value={cast} onChange={setCast} />
}

describe('CastSelector', () => {
  it('never renders a raw character-ID text input', () => {
    render(<Harness />)
    // No numeric/text field is used to type a character id directly — only
    // named buttons for adding characters by name/avatar (issue #15).
    expect(screen.queryByRole('textbox', { name: /character.?id/i })).not.toBeInTheDocument()
  })

  it('adds a character to the ordered cast by clicking their card', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: /Elias/ }))
    expect(screen.getByText('Elias')).toBeInTheDocument()
  })

  it('reorders the cast with the up/down controls', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: /Elias/ }))
    await user.click(screen.getByRole('button', { name: /Mara/ }))

    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Elias')
    expect(items[1]).toHaveTextContent('Mara')

    const downButtons = screen.getAllByRole('button', { name: '↓' })
    await user.click(downButtons[0])

    const reordered = screen.getAllByRole('listitem')
    expect(reordered[0]).toHaveTextContent('Mara')
    expect(reordered[1]).toHaveTextContent('Elias')
  })

  it('removes a character from the cast', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: /Elias/ }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('shows visible cast-order and staging explanations, not only placeholder text', () => {
    render(<Harness />)
    // These must be real, visible text nodes (not just an input placeholder,
    // which is not reliably accessible) — issue #15 follow-up.
    expect(screen.getByText(/Cast order:/)).toBeInTheDocument()
    expect(screen.getByText(/Staging:/)).toBeInTheDocument()
  })

  it('associates the staging input with the visible staging explanation via aria-describedby', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: /Elias/ }))
    const stagingInput = screen.getByRole('textbox', { name: /Staging role for Elias/ })
    expect(stagingInput).toHaveAttribute('aria-describedby', 'staging-hint')
    expect(document.getElementById('staging-hint')).toHaveTextContent(/Staging:/)
  })

  it('shows noncanonical characters as disabled in a mixed list', () => {
    render(
      <CastSelector
        characters={[CHARACTERS[0], UNREADY_CHARACTER]}
        value={[]}
        onChange={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: /Tomas - Needs a canonical reference set/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Elias/ })).toBeEnabled()
  })

  it('keeps an already selected noncanonical character in the editable cast', () => {
    render(
      <CastSelector
        characters={[CHARACTERS[0], UNREADY_CHARACTER]}
        value={[{ character_id: UNREADY_CHARACTER.id, role: 'watching', prominence: 2 }]}
        onChange={() => {}}
      />,
    )

    expect(screen.getByRole('textbox', { name: 'Staging role for Tomas' })).toHaveValue('watching')
    expect(screen.getByRole('spinbutton', { name: 'Prominence for Tomas' })).toHaveValue(2)
  })
})
