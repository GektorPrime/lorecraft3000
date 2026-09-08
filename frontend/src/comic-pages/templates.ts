export type ComicPageFormat = 'portrait' | 'square' | 'landscape'
export type ComicPageTemplateKey =
  | 'full'
  | 'two_rows'
  | 'two_columns'
  | 'feature_top'
  | 'feature_bottom'
  | 'three_rows'
  | 'four_grid'
  | 'feature_left'
  | 'six_grid'

export interface PageRectangle {
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface ComicPageTemplate {
  key: ComicPageTemplateKey
  label: string
  slotCount: number
  defaultDividers: readonly number[]
  dividerLabels: readonly string[]
}

export const COMIC_PAGE_FORMATS: ReadonlyArray<{ key: ComicPageFormat; label: string; width: number; height: number }> = [
  { key: 'portrait', label: 'Portrait', width: 1200, height: 1800 },
  { key: 'square', label: 'Square', width: 1600, height: 1600 },
  { key: 'landscape', label: 'Landscape', width: 1800, height: 1200 },
]

export const COMIC_PAGE_TEMPLATES: readonly ComicPageTemplate[] = [
  { key: 'full', label: 'Full page', slotCount: 1, defaultDividers: [], dividerLabels: [] },
  { key: 'two_rows', label: 'Two rows', slotCount: 2, defaultDividers: [0.5], dividerLabels: ['Row split'] },
  { key: 'two_columns', label: 'Two columns', slotCount: 2, defaultDividers: [0.5], dividerLabels: ['Column split'] },
  { key: 'feature_top', label: 'Feature top', slotCount: 3, defaultDividers: [0.55, 0.5], dividerLabels: ['Feature height', 'Lower column split'] },
  { key: 'feature_bottom', label: 'Feature bottom', slotCount: 3, defaultDividers: [0.45, 0.5], dividerLabels: ['Upper row height', 'Upper column split'] },
  { key: 'three_rows', label: 'Three rows', slotCount: 3, defaultDividers: [1 / 3, 2 / 3], dividerLabels: ['First row end', 'Second row end'] },
  { key: 'four_grid', label: 'Four panel grid', slotCount: 4, defaultDividers: [0.5, 0.5], dividerLabels: ['Column split', 'Row split'] },
  { key: 'feature_left', label: 'Feature left', slotCount: 3, defaultDividers: [0.55, 0.5], dividerLabels: ['Feature width', 'Right row split'] },
  { key: 'six_grid', label: 'Six panel grid', slotCount: 6, defaultDividers: [1 / 3, 2 / 3, 0.5], dividerLabels: ['First column end', 'Second column end', 'Row split'] },
]

export function getComicPageTemplate(key: string): ComicPageTemplate {
  return COMIC_PAGE_TEMPLATES.find((template) => template.key === key) ?? COMIC_PAGE_TEMPLATES[0]
}

export function templateRectangles(key: ComicPageTemplateKey, dividers: readonly number[]): PageRectangle[] {
  const rect = (x0: number, y0: number, x1: number, y1: number): PageRectangle => ({ x0, y0, x1, y1 })
  if (key === 'full') return [rect(0, 0, 1, 1)]
  if (key === 'two_rows') return [rect(0, 0, 1, dividers[0]), rect(0, dividers[0], 1, 1)]
  if (key === 'two_columns') return [rect(0, 0, dividers[0], 1), rect(dividers[0], 0, 1, 1)]
  if (key === 'feature_top') return [rect(0, 0, 1, dividers[0]), rect(0, dividers[0], dividers[1], 1), rect(dividers[1], dividers[0], 1, 1)]
  if (key === 'feature_bottom') return [rect(0, 0, dividers[1], dividers[0]), rect(dividers[1], 0, 1, dividers[0]), rect(0, dividers[0], 1, 1)]
  if (key === 'three_rows') return [rect(0, 0, 1, dividers[0]), rect(0, dividers[0], 1, dividers[1]), rect(0, dividers[1], 1, 1)]
  if (key === 'four_grid') return [rect(0, 0, dividers[0], dividers[1]), rect(dividers[0], 0, 1, dividers[1]), rect(0, dividers[1], dividers[0], 1), rect(dividers[0], dividers[1], 1, 1)]
  if (key === 'feature_left') return [rect(0, 0, dividers[0], 1), rect(dividers[0], 0, 1, dividers[1]), rect(dividers[0], dividers[1], 1, 1)]
  return [
    rect(0, 0, dividers[0], dividers[2]), rect(dividers[0], 0, dividers[1], dividers[2]), rect(dividers[1], 0, 1, dividers[2]),
    rect(0, dividers[2], dividers[0], 1), rect(dividers[0], dividers[2], dividers[1], 1), rect(dividers[1], dividers[2], 1, 1),
  ]
}
