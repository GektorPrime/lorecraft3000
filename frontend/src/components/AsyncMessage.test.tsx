import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AsyncMessage } from './AsyncMessage'

describe('AsyncMessage', () => {
  it.each(['loading', 'success'] as const)(
    'politely announces a %s message as a status',
    (kind) => {
      render(<AsyncMessage kind={kind}>Request complete</AsyncMessage>)

      const message = screen.getByRole('status')
      expect(message).toHaveAttribute('aria-live', 'polite')
      expect(message).toHaveTextContent('Request complete')
    },
  )

  it('announces errors as alerts', () => {
    render(<AsyncMessage kind="error">Request failed</AsyncMessage>)

    expect(screen.getByRole('alert')).toHaveTextContent('Request failed')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('preserves additional paragraph attributes and classes', () => {
    render(
      <AsyncMessage kind="success" className="custom-message" data-testid="message">
        Saved
      </AsyncMessage>,
    )

    expect(screen.getByTestId('message')).toHaveClass(
      'banner',
      'banner--info',
      'custom-message',
    )
  })
})
