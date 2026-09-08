import { describe, expect, it } from 'vitest'
import { COMIC_PAGE_TEMPLATES, templateRectangles } from './templates'

describe('comic page templates', () => {
  it('defines all backend templates with matching slot counts and defaults', () => {
    expect(COMIC_PAGE_TEMPLATES.map(({ key, slotCount, defaultDividers }) => [key, slotCount, defaultDividers])).toEqual([
      ['full', 1, []],
      ['two_rows', 2, [0.5]],
      ['two_columns', 2, [0.5]],
      ['feature_top', 3, [0.55, 0.5]],
      ['feature_bottom', 3, [0.45, 0.5]],
      ['three_rows', 3, [1 / 3, 2 / 3]],
      ['four_grid', 4, [0.5, 0.5]],
      ['feature_left', 3, [0.55, 0.5]],
      ['six_grid', 6, [1 / 3, 2 / 3, 0.5]],
    ])
  })

  it('matches backend rectangle ordering and semantics', () => {
    expect(templateRectangles('feature_top', [0.6, 0.4])).toEqual([
      { x0: 0, y0: 0, x1: 1, y1: 0.6 },
      { x0: 0, y0: 0.6, x1: 0.4, y1: 1 },
      { x0: 0.4, y0: 0.6, x1: 1, y1: 1 },
    ])
    expect(templateRectangles('six_grid', [0.3, 0.7, 0.45])).toHaveLength(6)
    expect(templateRectangles('six_grid', [0.3, 0.7, 0.45])[4]).toEqual({ x0: 0.3, y0: 0.45, x1: 0.7, y1: 1 })
  })
})
