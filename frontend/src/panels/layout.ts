export type PanelFormat = 'portrait' | 'square' | 'landscape'
export type SplitDirection = 'horizontal' | 'vertical'
export type MergeDirection = 'left' | 'right' | 'up' | 'down'
export type SlotEdge = 'left' | 'right' | 'top' | 'bottom'

export interface LayoutSlot {
  candidate_id: number | null
  gallery_picture_id: number | null
  slot_index: number
  x0: number
  y0: number
  x1: number
  y1: number
  focal_x: number
  focal_y: number
  zoom: number
  content_url: string | null
}

export const PANEL_FORMATS: ReadonlyArray<{ key: PanelFormat; label: string; width: number; height: number }> = [
  { key: 'portrait', label: 'Portrait', width: 1200, height: 1800 },
  { key: 'square', label: 'Square', width: 1600, height: 1600 },
  { key: 'landscape', label: 'Landscape', width: 1800, height: 1200 },
]

export const MIN_CELL_SIZE = 0.04
export const MAX_SLOTS = 64
const EPSILON = 1e-7
const equal = (a: number, b: number) => Math.abs(a - b) < EPSILON

const emptySlot = (slot_index: number, x0: number, y0: number, x1: number, y1: number): LayoutSlot => ({
  candidate_id: null,
  gallery_picture_id: null,
  slot_index,
  x0,
  y0,
  x1,
  y1,
  focal_x: 0.5,
  focal_y: 0.5,
  zoom: 1,
  content_url: null,
})

export function sourceKey(source: Pick<LayoutSlot, 'candidate_id' | 'gallery_picture_id'>): string | null {
  if (source.candidate_id != null) return `candidate:${source.candidate_id}`
  if (source.gallery_picture_id != null) return `upload:${source.gallery_picture_id}`
  return null
}

const normalize = <T extends LayoutSlot>(slots: readonly T[]): T[] =>
  slots.map((slot, slot_index) => ({ ...slot, slot_index }))

/**
 * Mirrors the backend `PanelRenderService._crop_box`: computes the source crop
 * window (cover-fit to the target aspect, magnified by `zoom`, centred on the
 * focal point, then clamped inside the source) and expresses the image's
 * placement as percentages of the target slot box. Positioning an absolutely
 * placed <img> with these values reproduces the exported render exactly, unlike
 * `object-fit: cover` + `transform: scale`, which pivots and clamps differently.
 */
export function cropImageBox(
  sourceWidth: number,
  sourceHeight: number,
  targetAspect: number,
  focalX: number,
  focalY: number,
  zoom: number,
): { widthPct: number; heightPct: number; leftPct: number; topPct: number } {
  let cropWidth: number
  let cropHeight: number
  if (sourceWidth / sourceHeight >= targetAspect) {
    cropHeight = sourceHeight / zoom
    cropWidth = cropHeight * targetAspect
  } else {
    cropWidth = sourceWidth / zoom
    cropHeight = cropWidth / targetAspect
  }
  const centerX = focalX * sourceWidth
  const centerY = focalY * sourceHeight
  const left = Math.max(0, Math.min(centerX - cropWidth / 2, sourceWidth - cropWidth))
  const top = Math.max(0, Math.min(centerY - cropHeight / 2, sourceHeight - cropHeight))
  return {
    widthPct: (sourceWidth / cropWidth) * 100,
    heightPct: (sourceHeight / cropHeight) * 100,
    leftPct: -(left / cropWidth) * 100,
    topPct: -(top / cropHeight) * 100,
  }
}

export function createGrid(rows: number, columns: number): LayoutSlot[] {
  if (!Number.isInteger(rows) || !Number.isInteger(columns) || rows < 1 || columns < 1 || rows * columns > MAX_SLOTS) return []
  return Array.from({ length: rows * columns }, (_, index) => {
    const row = Math.floor(index / columns)
    const column = index % columns
    return emptySlot(index, column / columns, row / rows, (column + 1) / columns, (row + 1) / rows)
  })
}

export function splitSlot<T extends LayoutSlot>(slots: readonly T[], index: number, direction: SplitDirection): T[] | readonly T[] {
  const selected = slots[index]
  if (!selected || slots.length >= MAX_SLOTS) return slots
  const size = direction === 'horizontal' ? selected.y1 - selected.y0 : selected.x1 - selected.x0
  if (size < MIN_CELL_SIZE * 2 - EPSILON) return slots
  const midpoint = direction === 'horizontal' ? (selected.y0 + selected.y1) / 2 : (selected.x0 + selected.x1) / 2
  const retained = { ...selected, ...(direction === 'horizontal' ? { y1: midpoint } : { x1: midpoint }) }
  const added = {
    ...emptySlot(slots.length, selected.x0, selected.y0, selected.x1, selected.y1),
    ...(direction === 'horizontal' ? { y0: midpoint } : { x0: midpoint }),
  } as T
  return normalize(slots.map((slot, slotIndex) => slotIndex === index ? retained : slot).concat(added))
}

function adjacent<T extends LayoutSlot>(slots: readonly T[], index: number, direction: MergeDirection): number[] {
  const selected = slots[index]
  if (!selected) return []
  return slots.flatMap((slot, slotIndex) => {
    if (slotIndex === index) return []
    const matches = direction === 'left'
      ? equal(slot.x1, selected.x0) && equal(slot.y0, selected.y0) && equal(slot.y1, selected.y1)
      : direction === 'right'
        ? equal(slot.x0, selected.x1) && equal(slot.y0, selected.y0) && equal(slot.y1, selected.y1)
        : direction === 'up'
          ? equal(slot.y1, selected.y0) && equal(slot.x0, selected.x0) && equal(slot.x1, selected.x1)
          : equal(slot.y0, selected.y1) && equal(slot.x0, selected.x0) && equal(slot.x1, selected.x1)
    return matches ? [slotIndex] : []
  })
}

export function mergeSlot<T extends LayoutSlot>(slots: readonly T[], index: number, direction: MergeDirection): T[] | readonly T[] {
  const selected = slots[index]
  const matches = adjacent(slots, index, direction)
  if (!selected || matches.length !== 1) return slots
  const neighborIndex = matches[0]
  const neighbor = slots[neighborIndex]
  const content = sourceKey(selected) !== null ? selected : neighbor
  const merged = {
    ...selected,
    candidate_id: content.candidate_id,
    gallery_picture_id: content.gallery_picture_id,
    content_url: content.content_url,
    focal_x: content.focal_x,
    focal_y: content.focal_y,
    zoom: content.zoom,
    x0: Math.min(selected.x0, neighbor.x0),
    y0: Math.min(selected.y0, neighbor.y0),
    x1: Math.max(selected.x1, neighbor.x1),
    y1: Math.max(selected.y1, neighbor.y1),
  }
  return normalize(slots.flatMap((slot, slotIndex) => slotIndex === neighborIndex ? [] : [slotIndex === index ? merged : slot]))
}

interface EdgeRange { min: number; max: number }

export function getEdgeRange<T extends LayoutSlot>(slots: readonly T[], index: number, edge: SlotEdge): EdgeRange | null {
  const selected = slots[index]
  if (!selected) return null
  const vertical = edge === 'left' || edge === 'right'
  const position = edge === 'left' ? selected.x0 : edge === 'right' ? selected.x1 : edge === 'top' ? selected.y0 : selected.y1
  if (equal(position, 0) || equal(position, 1)) return null
  const start = vertical ? selected.y0 : selected.x0
  const end = vertical ? selected.y1 : selected.x1
  const neighbors = slots.filter((slot, slotIndex) => slotIndex !== index && (
    edge === 'left' ? equal(slot.x1, position) && slot.y1 > start + EPSILON && slot.y0 < end - EPSILON
      : edge === 'right' ? equal(slot.x0, position) && slot.y1 > start + EPSILON && slot.y0 < end - EPSILON
        : edge === 'top' ? equal(slot.y1, position) && slot.x1 > start + EPSILON && slot.x0 < end - EPSILON
          : equal(slot.y0, position) && slot.x1 > start + EPSILON && slot.x0 < end - EPSILON
  ))
  if (neighbors.length === 0) return null
  const intervals = neighbors.map((slot) => vertical ? [slot.y0, slot.y1] : [slot.x0, slot.x1]).sort((a, b) => a[0] - b[0])
  let cursor = start
  for (const [intervalStart, intervalEnd] of intervals) {
    if (!equal(intervalStart, cursor) || intervalStart < start - EPSILON || intervalEnd > end + EPSILON) return null
    cursor = intervalEnd
  }
  if (!equal(cursor, end)) return null

  if (edge === 'left') return { min: Math.max(...neighbors.map((slot) => slot.x0 + MIN_CELL_SIZE)), max: selected.x1 - MIN_CELL_SIZE }
  if (edge === 'right') return { min: selected.x0 + MIN_CELL_SIZE, max: Math.min(...neighbors.map((slot) => slot.x1 - MIN_CELL_SIZE)) }
  if (edge === 'top') return { min: Math.max(...neighbors.map((slot) => slot.y0 + MIN_CELL_SIZE)), max: selected.y1 - MIN_CELL_SIZE }
  return { min: selected.y0 + MIN_CELL_SIZE, max: Math.min(...neighbors.map((slot) => slot.y1 - MIN_CELL_SIZE)) }
}

export function moveEdge<T extends LayoutSlot>(slots: readonly T[], index: number, edge: SlotEdge, newPosition: number): T[] | readonly T[] {
  const selected = slots[index]
  const range = getEdgeRange(slots, index, edge)
  if (!selected || !range || newPosition < range.min - EPSILON || newPosition > range.max + EPSILON) return slots
  const oldPosition = edge === 'left' ? selected.x0 : edge === 'right' ? selected.x1 : edge === 'top' ? selected.y0 : selected.y1
  if (equal(oldPosition, newPosition)) return slots
  return normalize(slots.map((slot, slotIndex) => {
    if (slotIndex === index) return { ...slot, [edge === 'left' ? 'x0' : edge === 'right' ? 'x1' : edge === 'top' ? 'y0' : 'y1']: newPosition }
    if (edge === 'left' && equal(slot.x1, oldPosition) && slot.y1 > selected.y0 + EPSILON && slot.y0 < selected.y1 - EPSILON) return { ...slot, x1: newPosition }
    if (edge === 'right' && equal(slot.x0, oldPosition) && slot.y1 > selected.y0 + EPSILON && slot.y0 < selected.y1 - EPSILON) return { ...slot, x0: newPosition }
    if (edge === 'top' && equal(slot.y1, oldPosition) && slot.x1 > selected.x0 + EPSILON && slot.x0 < selected.x1 - EPSILON) return { ...slot, y1: newPosition }
    if (edge === 'bottom' && equal(slot.y0, oldPosition) && slot.x1 > selected.x0 + EPSILON && slot.x0 < selected.x1 - EPSILON) return { ...slot, y0: newPosition }
    return { ...slot }
  }))
}

function addBand<T extends LayoutSlot>(slots: readonly T[], axis: 'row' | 'column'): T[] | readonly T[] {
  const farEdge = axis === 'row' ? 'y1' : 'x1'
  const nearEdge = axis === 'row' ? 'y0' : 'x0'
  const edgeSlots = slots.filter((slot) => equal(slot[farEdge], 1))
  if (edgeSlots.length === 0) return slots
  const line = (Math.max(...edgeSlots.map((slot) => slot[nearEdge])) + 1) / 2
  const crossing = slots.filter((slot) => slot[nearEdge] < line - EPSILON && slot[farEdge] > line + EPSILON)
  if (crossing.length === 0 || slots.length + crossing.length > MAX_SLOTS) return slots
  const retained = slots.map((slot) => crossing.includes(slot) ? { ...slot, [farEdge]: line } : slot)
  const added = crossing.map((slot, offset) => ({
    ...emptySlot(slots.length + offset, slot.x0, slot.y0, slot.x1, slot.y1),
    [nearEdge]: line,
  }) as T)
  return normalize(retained.concat(added))
}

export const addRow = <T extends LayoutSlot>(slots: readonly T[]) => addBand(slots, 'row')
export const addColumn = <T extends LayoutSlot>(slots: readonly T[]) => addBand(slots, 'column')
