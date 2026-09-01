import { describe, expect, it } from 'vitest'
import {
  formatDateTime,
  formatFullDateTime,
  parseDate,
  toIsoDateTime,
} from './dates'

describe('date utilities', () => {
  it('parses SQLite timestamps as UTC rather than local time', () => {
    const date = parseDate('2026-08-31 15:00:00')

    expect(date?.toISOString()).toBe('2026-08-31T15:00:00.000Z')
    expect(toIsoDateTime('2026-08-31 15:00:00')).toBe(
      '2026-08-31T15:00:00.000Z',
    )
  })

  it('accepts ISO timestamps with explicit offsets', () => {
    expect(toIsoDateTime('2026-08-31T17:00:00+02:00')).toBe(
      '2026-08-31T15:00:00.000Z',
    )
  })

  it('formats valid values through Intl.DateTimeFormat', () => {
    const options: Intl.DateTimeFormatOptions = {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'UTC',
    }
    const expected = new Intl.DateTimeFormat('en-US', options).format(
      new Date('2026-08-31T15:00:00Z'),
    )

    expect(formatDateTime('2026-08-31 15:00:00', options, 'en-US')).toBe(
      expected,
    )
    expect(formatFullDateTime('2026-08-31T15:00:00Z')).toBeTruthy()
  })

  it('returns null for invalid values', () => {
    expect(parseDate('not-a-date')).toBeNull()
    expect(toIsoDateTime('not-a-date')).toBeNull()
    expect(formatDateTime('not-a-date')).toBeNull()
  })
})
