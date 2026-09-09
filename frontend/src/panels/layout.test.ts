import { describe, expect, it } from 'vitest'
import { addColumn, addRow, createGrid, cropImageBox, mergeSlot, moveEdge, splitSlot } from './layout'

describe('panel layout', () => {
  it('creates normalized row-major grids', () => {
    const slots = createGrid(2, 3)
    expect(slots).toHaveLength(6)
    expect(slots[0]).toMatchObject({ slot_index: 0, x0: 0, y0: 0, x1: 1 / 3, y1: 0.5, candidate_id: null, gallery_picture_id: null })
    expect(slots[5]).toMatchObject({ slot_index: 5, x0: 2 / 3, y0: 0.5, x1: 1, y1: 1 })
  })

  it('splits with the original image retained and merges into the selection', () => {
    const original = [{ ...createGrid(1, 1)[0], candidate_id: 7, content_url: '/7.png' }]
    const split = splitSlot(original, 0, 'vertical')
    expect(split).toHaveLength(2)
    expect(split[0]).toMatchObject({ candidate_id: 7, x0: 0, x1: 0.5 })
    expect(split[1]).toMatchObject({ candidate_id: null, x0: 0.5, x1: 1 })
    expect(mergeSlot(split, 1, 'left')).toEqual([{ ...split[0], slot_index: 0, x0: 0, x1: 1 }])
    expect(mergeSlot(split, 0, 'up')).toBe(split)
  })

  it('preserves the selected content when merging populated slots', () => {
    const slots = createGrid(1, 2)
    const neighborOnly = [{ ...slots[0] }, { ...slots[1], candidate_id: 8, content_url: '/8.png' }]
    expect(mergeSlot(neighborOnly, 0, 'right')).toEqual([
      expect.objectContaining({ candidate_id: 8, content_url: '/8.png', x0: 0, x1: 1 }),
    ])

    const both = [
      { ...slots[0], candidate_id: 7, content_url: '/7.png', focal_x: 0.25, focal_y: 0.75, zoom: 2 },
      { ...slots[1], candidate_id: 8, content_url: '/8.png' },
    ]
    expect(mergeSlot(both, 0, 'right')).toEqual([
      expect.objectContaining({ candidate_id: 7, content_url: '/7.png', focal_x: 0.25, focal_y: 0.75, zoom: 2, x0: 0, x1: 1 }),
    ])
  })

  it('preserves uploaded picture identity through split and merge', () => {
    const original = [{ ...createGrid(1, 1)[0], gallery_picture_id: 42, content_url: '/uploads/42.png' }]
    const split = splitSlot(original, 0, 'vertical')
    expect(split[0]).toMatchObject({ candidate_id: null, gallery_picture_id: 42 })
    expect(split[1]).toMatchObject({ candidate_id: null, gallery_picture_id: null })
    expect(mergeSlot(split, 1, 'left')).toEqual([
      expect.objectContaining({ candidate_id: null, gallery_picture_id: 42, content_url: '/uploads/42.png' }),
    ])
  })

  it('moves a boundary shared by one large and several aligned cells', () => {
    const left = splitSlot(createGrid(1, 2), 0, 'horizontal')
    const moved = moveEdge(left, 1, 'left', 0.6)
    expect(moved).not.toBe(left)
    expect(moved.map((slot) => [slot.x0, slot.x1])).toEqual([[0, 0.6], [0.6, 1], [0, 0.6]])
    expect(moveEdge(left, 1, 'left', 0.99)).toBe(left)
  })

  it('rejects partial or overhanging adjacent coverage', () => {
    const slots = createGrid(1, 2)
    const broken = [{ ...slots[0], y1: 0.5 }, slots[1]]
    expect(moveEdge(broken, 1, 'left', 0.6)).toBe(broken)
  })

  it('adds aligned lines through every slot in the bottom and right bands', () => {
    const row = addRow(createGrid(1, 2))
    expect(row).toHaveLength(4)
    expect(row.filter((slot) => slot.y0 === 0.5)).toHaveLength(2)
    const column = addColumn(createGrid(2, 1))
    expect(column).toHaveLength(4)
    expect(column.filter((slot) => slot.x0 === 0.5)).toHaveLength(2)
  })

  it('reproduces the backend crop window for zoomed, off-centre focal points', () => {
    // Ground truth from PanelRenderService._crop_box(1600, 1000, 1.5, 0.07, 0.0, 2.2).
    const box = cropImageBox(1600, 1000, 1.5, 0.07, 0.0, 2.2)
    expect(box.widthPct).toBeCloseTo(234.6667, 3)
    expect(box.heightPct).toBeCloseTo(220, 3)
    expect(box.leftPct).toBeCloseTo(0, 6)
    expect(box.topPct).toBeCloseTo(0, 6)
  })

  it('centres the crop when the focal point allows it', () => {
    // _crop_box(1000, 1000, 1.0, 0.5, 0.5, 2.0) -> left=top=250, crop 500x500.
    const box = cropImageBox(1000, 1000, 1, 0.5, 0.5, 2)
    expect(box.widthPct).toBeCloseTo(200, 6)
    expect(box.heightPct).toBeCloseTo(200, 6)
    expect(box.leftPct).toBeCloseTo(-50, 6)
    expect(box.topPct).toBeCloseTo(-50, 6)
  })
})
