import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { RefImage } from '../api/types'
import { RefImageCard } from './RefImageCard'

const image: RefImage = {
  id: 11,
  ref_set_id: 7,
  role: 'face_front',
  weight: 1,
  quality_flags: [],
  created_at: '',
  content_url: '/api/v1/ref-images/11/content',
}

describe('RefImageCard', () => {
  it('opens its reference preview from a button', async () => {
    const user = userEvent.setup()
    render(
      <RefImageCard
        image={image}
        roles={['face_front']}
        editable={false}
        weightExplanation="Weights are fixed."
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Preview face_front reference' }))

    expect(
      screen.getByRole('dialog', { name: 'face_front reference, larger preview' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'face_front reference, larger preview' }),
    ).toHaveAttribute('src', '/api/v1/ref-images/11/content')
  })
})
