import { describe, expect, it } from 'vitest'
import { parseRefImageIds } from './refImageIds'

describe('parseRefImageIds', () => {
  it('parses a comma-separated list of integers', () => {
    expect(parseRefImageIds('1, 2, 3')).toEqual([1, 2, 3])
  })

  it('trims whitespace around each entry', () => {
    expect(parseRefImageIds('  4 ,5  ,6')).toEqual([4, 5, 6])
  })

  it('treats an empty string as an empty list (optional field)', () => {
    expect(parseRefImageIds('')).toEqual([])
  })

  it('ignores blank entries between commas', () => {
    expect(parseRefImageIds('1,,2')).toEqual([1, 2])
  })

  it('throws a readable error for non-integer input', () => {
    expect(() => parseRefImageIds('abc')).toThrow(/must be comma-separated integers/)
  })

  it('throws for a partially valid list', () => {
    expect(() => parseRefImageIds('1, two, 3')).toThrow(/"two"/)
  })
})
