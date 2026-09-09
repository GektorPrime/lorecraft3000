import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, createPanel, getGallery, getPanel, renderPanel, updatePanel } from '../../api/client'
import type { GalleryItem, Panel, PanelRender, PanelSlotInput, PanelUpdate } from '../../api/types'
import { PANEL_FORMATS, addColumn, addRow, cropImageBox, getEdgeRange, mergeSlot, moveEdge, sourceKey, splitSlot, type MergeDirection, type SlotEdge, type SplitDirection } from '../../panels/layout'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { ImageWithFallback } from '../../components/ImageWithFallback'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

interface EditorSlot extends Omit<PanelSlotInput, 'candidate_id' | 'gallery_picture_id'> {
  candidate_id: number | null
  gallery_picture_id: number | null
  content_url: string | null
}
interface EditorValues extends Omit<PanelUpdate, 'expected_revision' | 'slots'> { slots: EditorSlot[] }

const SWATCHES = ['#FFFFFF', '#F4EBDD', '#D9E7F0', '#20242B', '#16120F', '#000000'] as const
const EDGES: ReadonlyArray<{ key: SlotEdge; label: string }> = [
  { key: 'left', label: 'Left edge' },
  { key: 'right', label: 'Right edge' },
  { key: 'top', label: 'Top edge' },
  { key: 'bottom', label: 'Bottom edge' },
]
const MERGES: ReadonlyArray<{ key: MergeDirection; label: string }> = [
  { key: 'left', label: 'Merge left' },
  { key: 'right', label: 'Merge right' },
  { key: 'up', label: 'Merge up' },
  { key: 'down', label: 'Merge down' },
]

const errorMessage = (error: unknown) => error instanceof ApiError ? error.message : String(error)
const snapshot = (values: EditorValues) => JSON.stringify(values)
const positiveId = (value: string | null) => value && /^[1-9]\d*$/.test(value) ? Number(value) : null
const gridLabel = (rows: number, columns: number) => `${columns} column${columns === 1 ? '' : 's'} × ${rows} row${rows === 1 ? '' : 's'}`
const galleryItemLabel = (item: GalleryItem) => item.source_type === 'candidate'
  ? `candidate ${item.candidate_id} from scene ${item.scene_id}`
  : `uploaded picture ${item.gallery_picture_id}: ${item.description}`
const slotSourceLabel = (slot: EditorSlot) => slot.candidate_id != null
  ? `candidate ${slot.candidate_id}`
  : slot.gallery_picture_id != null ? `uploaded picture ${slot.gallery_picture_id}` : null

function hydrate(panel: Panel): EditorValues {
  return {
    title: panel.title,
    format: panel.format,
    background_color: panel.background_color,
    gutter_px: panel.gutter_px,
    frame_px: panel.frame_px,
    slots: panel.slots.map(({ candidate_id, gallery_picture_id, slot_index, x0, y0, x1, y1, focal_x, focal_y, zoom, content_url }) => ({ candidate_id, gallery_picture_id, slot_index, x0, y0, x1, y1, focal_x, focal_y, zoom, content_url })),
  }
}

export function PanelEditorPage() {
  const { id } = useParams()
  if (id === undefined) return <NewPanelSetup />
  return <RouteIdGuard>{(panelId) => <PanelEditor key={panelId} panelId={panelId} />}</RouteIdGuard>
}

function GridPicker({ rows, columns, onSelect }: { rows: number; columns: number; onSelect: (rows: number, columns: number) => void }) {
  const [preview, setPreview] = useState({ rows, columns })
  const buttons = useRef<Array<HTMLButtonElement | null>>([])
  const select = (nextRows: number, nextColumns: number) => {
    setPreview({ rows: nextRows, columns: nextColumns })
    onSelect(nextRows, nextColumns)
  }
  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, row: number, column: number) => {
    const offsets: Partial<Record<string, [number, number]>> = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }
    const offset = offsets[event.key]
    if (!offset) return
    event.preventDefault()
    const nextRow = Math.max(1, Math.min(8, row + offset[0]))
    const nextColumn = Math.max(1, Math.min(8, column + offset[1]))
    buttons.current[(nextRow - 1) * 8 + nextColumn - 1]?.focus()
  }
  return <fieldset className="panel-grid-picker" onMouseLeave={() => setPreview({ rows, columns })}>
    <legend>Starting layout</legend>
    <p className="panel-grid-picker__label" aria-live="polite">{gridLabel(preview.rows, preview.columns)}</p>
    <div className="panel-grid-picker__cells" role="group" aria-label="Choose rows and columns">
      {Array.from({ length: 64 }, (_, index) => {
        const row = Math.floor(index / 8) + 1
        const column = index % 8 + 1
        const previewed = row <= preview.rows && column <= preview.columns
        const selected = row <= rows && column <= columns
        return <button
          key={index}
          ref={(node) => { buttons.current[index] = node }}
          type="button"
          className={`${previewed ? 'is-previewed' : ''}${selected ? ' is-selected' : ''}`}
          aria-label={gridLabel(row, column)}
          aria-pressed={row === rows && column === columns}
          onMouseEnter={() => setPreview({ rows: row, columns: column })}
          onFocus={() => setPreview({ rows: row, columns: column })}
          onKeyDown={(event) => moveFocus(event, row, column)}
          onClick={() => select(row, column)}
        />
      })}
    </div>
  </fieldset>
}

function NewPanelSetup() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const candidateId = positiveId(params.get('candidate'))
  const pictureId = candidateId === null ? positiveId(params.get('picture')) : null
  const [title, setTitle] = useState('Untitled panel')
  const [format, setFormat] = useState('portrait')
  const [rows, setRows] = useState(1)
  const [columns, setColumns] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(title !== 'Untitled panel' || format !== 'portrait' || rows !== 1 || columns !== 1)
  usePageTitle('New Panel')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const panel = await createPanel({ title, format, rows, columns, ...(candidateId !== null ? { candidate_id: candidateId } : pictureId !== null ? { gallery_picture_id: pictureId } : {}) })
      allowNavigation()
      navigate(`/panels/${panel.id}/edit`, { replace: true })
    } catch (reason) {
      setError(errorMessage(reason))
      setSubmitting(false)
    }
  }

  return <section className="form-page">
    <PageHeader title="New panel" description="Choose a format and starting grid. You can reshape every slot next." />
    {error && <AsyncMessage kind="error">Could not create panel: {error}</AsyncMessage>}
    <form className="form-card" onSubmit={submit} aria-busy={submitting}>
      <fieldset className="form-section"><legend>Panel settings</legend>
        <div className="field"><label htmlFor="panel-title">Title</label><input id="panel-title" type="text" required maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} /></div>
        <div className="field"><label htmlFor="panel-format">Format</label><select id="panel-format" value={format} onChange={(event) => setFormat(event.target.value)}>{PANEL_FORMATS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></div>
        <GridPicker rows={rows} columns={columns} onSelect={(nextRows, nextColumns) => { setRows(nextRows); setColumns(nextColumns) }} />
        {candidateId && <p className="field__hint">Generated candidate #{candidateId} will be placed in the first slot.</p>}
        {pictureId && <p className="field__hint">Uploaded picture #{pictureId} will be placed in the first slot.</p>}
      </fieldset>
      <div className="form-actions"><button className="btn btn--primary" disabled={submitting} type="submit">{submitting ? 'Creating…' : 'Create and compose'}</button><Link className="btn" to="/panels">Cancel</Link></div>
    </form>
    <ConfirmDialog {...confirmationProps} />
  </section>
}

function PanelEditor({ panelId }: { panelId: number }) {
  const [values, setValues] = useState<EditorValues | null>(null)
  const [gallery, setGallery] = useState<GalleryItem[] | null>(null)
  const [revision, setRevision] = useState<number | null>(null)
  const [baseline, setBaseline] = useState<string | null>(null)
  const [render, setRender] = useState<PanelRender | null>(null)
  const [selectedSlot, setSelectedSlot] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [saving, setSaving] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [galleryQuery, setGalleryQuery] = useState('')
  const [canvasZoom, setCanvasZoom] = useState(1)
  const [naturalSizes, setNaturalSizes] = useState<Record<string, { w: number; h: number }>>({})
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; focalX: number; focalY: number; xPerPx: number; yPerPx: number } | null>(null)
  const mounted = useRef(true)
  const dirty = values !== null && baseline !== null && snapshot(values) !== baseline
  const { confirmationProps } = useUnsavedChanges(dirty)
  const selectedSlotValue = values?.slots[selectedSlot]
  const filled = values?.slots.filter((slot) => sourceKey(slot) !== null).length ?? 0
  const complete = values !== null && values.slots.length > 0 && filled === values.slots.length
  const currentRender = render?.panel_revision === revision ? render : null
  usePageTitle(values ? `Edit ${values.title}` : 'Edit Panel')

  useEffect(() => {
    mounted.current = true
    Promise.all([getPanel(panelId), getGallery()]).then(([panel, items]) => {
      if (!mounted.current) return
      const hydrated = hydrate(panel)
      setValues(hydrated)
      setBaseline(snapshot(hydrated))
      setRevision(panel.revision)
      setRender(panel.latest_render)
      setGallery(items)
      setError(null)
      setConflict(false)
      setSelectedSlot(0)
    }).catch((reason) => {
      if (!mounted.current) return
      if (reason instanceof ApiError && reason.status === 404) setNotFound(true)
      else setError(errorMessage(reason))
    })
    return () => { mounted.current = false }
  }, [panelId, loadAttempt])

  const patchSlot = (patch: Partial<EditorSlot>) => setValues((current) => current && ({ ...current, slots: current.slots.map((slot, index) => index === selectedSlot ? { ...slot, ...patch } : slot) }))
  const beginSlotDrag = (event: ReactPointerEvent<HTMLImageElement>, slot: EditorSlot, targetAspect: number) => {
    const key = sourceKey(slot)
    if (event.button !== 0 || key === null) return
    const natural = naturalSizes[key]
    if (!natural || natural.w <= 0 || natural.h <= 0) return
    const rect = event.currentTarget.parentElement?.getBoundingClientRect()
    if (!rect || rect.width <= 0 || rect.height <= 0) return
    const cropHeight = natural.w / natural.h >= targetAspect ? natural.h / slot.zoom : (natural.w / slot.zoom) / targetAspect
    const cropWidth = natural.w / natural.h >= targetAspect ? cropHeight * targetAspect : natural.w / slot.zoom
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      focalX: slot.focal_x,
      focalY: slot.focal_y,
      xPerPx: -(cropWidth / natural.w) / rect.width,
      yPerPx: -(cropHeight / natural.h) / rect.height,
    }
  }
  const moveSlotDrag = (event: ReactPointerEvent<HTMLImageElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const focalX = Math.min(1, Math.max(0, drag.focalX + (event.clientX - drag.startX) * drag.xPerPx))
    const focalY = Math.min(1, Math.max(0, drag.focalY + (event.clientY - drag.startY) * drag.yPerPx))
    patchSlot({ focal_x: focalX, focal_y: focalY })
  }
  const endSlotDrag = (event: ReactPointerEvent<HTMLImageElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    dragRef.current = null
  }
  const assign = (item: GalleryItem) => patchSlot({ candidate_id: item.candidate_id, gallery_picture_id: item.gallery_picture_id, content_url: item.content_url, focal_x: 0.5, focal_y: 0.5, zoom: 1 })
  const replaceSlots = (next: readonly EditorSlot[]) => setValues((current) => current ? { ...current, slots: [...next] } : current)
  const split = (direction: SplitDirection) => {
    if (!values) return
    const next = splitSlot(values.slots, selectedSlot, direction)
    if (next !== values.slots) replaceSlots(next)
  }
  const merge = (direction: MergeDirection) => {
    if (!values || !selectedSlotValue) return
    const next = mergeSlot(values.slots, selectedSlot, direction)
    if (next === values.slots) return
    const retained = next.findIndex((slot) => slot.x0 <= selectedSlotValue.x0 && slot.y0 <= selectedSlotValue.y0 && slot.x1 >= selectedSlotValue.x1 && slot.y1 >= selectedSlotValue.y1)
    replaceSlots(next)
    setSelectedSlot(Math.max(0, retained))
  }

  const save = async () => {
    if (!values || revision === null) return
    setSaving(true)
    setError(null)
    setConflict(false)
    try {
      const slots: PanelSlotInput[] = values.slots.map(({ candidate_id, gallery_picture_id, slot_index, x0, y0, x1, y1, focal_x, focal_y, zoom }) => ({ candidate_id, gallery_picture_id, slot_index, x0, y0, x1, y1, focal_x, focal_y, zoom }))
      const panel = await updatePanel(panelId, { ...values, slots, expected_revision: revision })
      if (!mounted.current) return
      const hydrated = hydrate(panel)
      setValues(hydrated)
      setBaseline(snapshot(hydrated))
      setRevision(panel.revision)
      setRender(panel.latest_render)
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) setConflict(true)
      else setError(errorMessage(reason))
    } finally {
      if (mounted.current) setSaving(false)
    }
  }

  const exportPanel = async () => {
    if (revision === null) return
    setRendering(true)
    setError(null)
    try { setRender(await renderPanel(panelId, { expected_revision: revision })) }
    catch (reason) { setError(errorMessage(reason)) }
    finally { if (mounted.current) setRendering(false) }
  }

  if (notFound) return <NotFoundPage />
  if (!values || !gallery || revision === null) return <div>{error ? <><AsyncMessage kind="error">Could not load panel: {error}</AsyncMessage><button className="btn" type="button" onClick={() => { setError(null); setLoadAttempt((value) => value + 1) }}>Retry</button></> : <AsyncMessage kind="loading">Loading panels…</AsyncMessage>}</div>

  const format = PANEL_FORMATS.find((item) => item.key === values.format) ?? PANEL_FORMATS[0]
  const contentWidth = Math.max(1, format.width - values.frame_px * 2)
  const contentHeight = Math.max(1, format.height - values.frame_px * 2)
  const rowResult = addRow(values.slots)
  const columnResult = addColumn(values.slots)
  return <section className="panel-editor">
    <PageHeader title="Panel composer" description={`Revision ${revision} · ${format.width} × ${format.height}px`} actions={<Link className="btn btn--primary" to="/panels">Back to panels</Link>} />
    {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
    {conflict && <AsyncMessage kind="error">This panel changed elsewhere. Reload the latest revision before saving. <button className="btn btn--sm" type="button" onClick={() => { setValues(null); setBaseline(null); setLoadAttempt((value) => value + 1) }}>Reload panel</button></AsyncMessage>}
    <div className="panel-editor__workspace">
      <aside className="panel-editor__settings card" aria-label="Panel settings">
        <h2>Panel settings</h2>
        <div className="field"><label htmlFor="edit-title">Title</label><input id="edit-title" type="text" maxLength={120} value={values.title} onChange={(event) => setValues({ ...values, title: event.target.value })} /></div>
        <fieldset className="panel-editor__layout"><legend>Layout</legend>
          <div className="btn-row"><button className="btn btn--sm" type="button" disabled={rowResult === values.slots} onClick={() => replaceSlots(rowResult)}>Add row</button><button className="btn btn--sm" type="button" disabled={columnResult === values.slots} onClick={() => replaceSlots(columnResult)}>Add column</button></div>
          <p className="field__hint">Selected slot: {selectedSlot + 1}</p>
          <div className="btn-row">{MERGES.map(({ key, label }) => <button className="btn btn--sm" key={key} type="button" disabled={mergeSlot(values.slots, selectedSlot, key) === values.slots} onClick={() => merge(key)}>{label}</button>)}</div>
          <div className="btn-row"><button className="btn btn--sm" type="button" disabled={splitSlot(values.slots, selectedSlot, 'horizontal') === values.slots} onClick={() => split('horizontal')}>Split horizontally</button><button className="btn btn--sm" type="button" disabled={splitSlot(values.slots, selectedSlot, 'vertical') === values.slots} onClick={() => split('vertical')}>Split vertically</button></div>
          {selectedSlotValue && <div className="panel-editor__edges">{EDGES.map(({ key, label }) => {
            const range = getEdgeRange(values.slots, selectedSlot, key)
            const enabled = range !== null && range.max - range.min >= 0.001
            const value = key === 'left' ? selectedSlotValue.x0 : key === 'right' ? selectedSlotValue.x1 : key === 'top' ? selectedSlotValue.y0 : selectedSlotValue.y1
            return <div className="field" key={key}><label htmlFor={`slot-edge-${key}`}>{label}</label><input id={`slot-edge-${key}`} type="range" min={range?.min ?? 0} max={range?.max ?? 1} step="0.001" value={value} disabled={!enabled} onInput={(event) => replaceSlots(moveEdge(values.slots, selectedSlot, key, Number(event.currentTarget.value)))} /></div>
          })}</div>}
        </fieldset>
        <details className="panel-editor__page-settings" open>
          <summary>Page settings</summary>
          <div className="field"><label htmlFor="edit-format">Format</label><select id="edit-format" value={values.format} onChange={(event) => setValues({ ...values, format: event.target.value })}>{PANEL_FORMATS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></div>
          <div className="field"><label htmlFor="panel-gutter">Internal gutter: {values.gutter_px}px</label><input id="panel-gutter" type="range" min="0" max="80" value={values.gutter_px} onChange={(event) => setValues({ ...values, gutter_px: Number(event.target.value) })} /></div>
          <div className="field"><label htmlFor="panel-frame">Outer frame: {values.frame_px}px</label><input id="panel-frame" type="range" min="0" max="80" value={values.frame_px} onChange={(event) => setValues({ ...values, frame_px: Number(event.target.value) })} /></div>
          <fieldset className="panel-background"><legend>Background color</legend>
            <div className="panel-background__swatches">{SWATCHES.map((color) => <button key={color} type="button" aria-label={`Set background ${color}`} aria-pressed={values.background_color === color} style={{ backgroundColor: color }} onClick={() => setValues({ ...values, background_color: color })} />)}</div>
            <div className="form-grid"><div className="field"><label htmlFor="panel-color-picker">Color palette</label><input id="panel-color-picker" type="color" value={/^#[0-9A-F]{6}$/.test(values.background_color) ? values.background_color : '#FFFFFF'} onChange={(event) => setValues({ ...values, background_color: event.target.value.toUpperCase() })} /></div>
            <div className="field"><label htmlFor="panel-background">Hex color</label><input id="panel-background" type="text" maxLength={7} pattern="#[0-9A-Fa-f]{6}" value={values.background_color} onChange={(event) => setValues({ ...values, background_color: event.target.value.toUpperCase() })} /></div></div>
          </fieldset>
        </details>
      </aside>
      <div className="panel-editor__stage">
        <div className="panel-editor__zoom">
          <span className="field__hint">Canvas zoom</span>
          <button className="btn btn--sm" type="button" aria-label="Zoom out" disabled={canvasZoom <= 0.5} onClick={() => setCanvasZoom((value) => Math.max(0.5, Math.round((value - 0.25) * 100) / 100))}>−</button>
          <input aria-label="Canvas zoom" type="range" min="0.5" max="5" step="0.25" value={canvasZoom} onChange={(event) => setCanvasZoom(Number(event.target.value))} />
          <button className="btn btn--sm" type="button" aria-label="Zoom in" disabled={canvasZoom >= 5} onClick={() => setCanvasZoom((value) => Math.min(5, Math.round((value + 0.25) * 100) / 100))}>+</button>
          <button className="btn btn--sm" type="button" disabled={canvasZoom === 1} onClick={() => setCanvasZoom(1)}>{Math.round(canvasZoom * 100)}%</button>
        </div>
        {(() => { const active = selectedSlotValue ? sourceKey(selectedSlotValue) !== null : false; const slotZoom = active && selectedSlotValue ? selectedSlotValue.zoom : 1; return (
        <div className="panel-editor__zoom">
          <span className="field__hint">Slot zoom</span>
          <button className="btn btn--sm" type="button" aria-label="Slot zoom out" disabled={!active || slotZoom <= 1} onClick={() => patchSlot({ zoom: Math.max(1, Math.round((slotZoom - 0.05) * 100) / 100) })}>−</button>
          <input aria-label="Slot zoom" type="range" min="1" max="5" step="0.05" value={slotZoom} disabled={!active} onChange={(event) => patchSlot({ zoom: Number(event.target.value) })} />
          <button className="btn btn--sm" type="button" aria-label="Slot zoom in" disabled={!active || slotZoom >= 5} onClick={() => patchSlot({ zoom: Math.min(5, Math.round((slotZoom + 0.05) * 100) / 100) })}>+</button>
          <button className="btn btn--sm" type="button" disabled={!active || slotZoom === 1} onClick={() => patchSlot({ zoom: 1 })}>{Math.round(slotZoom * 100)}%</button>
        </div>
        ) })()}
        <div className="panel-canvas__viewport">
        <div className="panel-canvas" aria-label="Panel canvas" style={{ '--panel-ratio': `${format.width} / ${format.height}`, '--panel-max-width': `${68 * format.width / format.height}svh`, '--panel-zoom': canvasZoom, '--panel-background': values.background_color } as CSSProperties}>
          <div className="panel-canvas__content" style={{ left: `${values.frame_px / format.width * 100}%`, right: `${values.frame_px / format.width * 100}%`, top: `${values.frame_px / format.height * 100}%`, bottom: `${values.frame_px / format.height * 100}%` }}>
            {values.slots.map((slot, index) => {
              const xBefore = slot.x0 > 0 ? values.gutter_px - Math.floor(values.gutter_px / 2) : 0
              const xAfter = slot.x1 < 1 ? Math.floor(values.gutter_px / 2) : 0
              const yBefore = slot.y0 > 0 ? values.gutter_px - Math.floor(values.gutter_px / 2) : 0
              const yAfter = slot.y1 < 1 ? Math.floor(values.gutter_px / 2) : 0
              const style = { left: `calc(${slot.x0 * 100}% + ${xBefore / contentWidth * 100}%)`, top: `calc(${slot.y0 * 100}% + ${yBefore / contentHeight * 100}%)`, width: `calc(${(slot.x1 - slot.x0) * 100}% - ${(xBefore + xAfter) / contentWidth * 100}%)`, height: `calc(${(slot.y1 - slot.y0) * 100}% - ${(yBefore + yAfter) / contentHeight * 100}%)` } as CSSProperties
              const targetWidth = (slot.x1 - slot.x0) * contentWidth - (xBefore + xAfter)
              const targetHeight = (slot.y1 - slot.y0) * contentHeight - (yBefore + yAfter)
              const key = sourceKey(slot)
              const natural = key !== null ? naturalSizes[key] : undefined
              const imageStyle = key !== null
                ? (natural && targetWidth > 0 && targetHeight > 0
                  ? (() => { const box = cropImageBox(natural.w, natural.h, targetWidth / targetHeight, slot.focal_x, slot.focal_y, slot.zoom); return { position: 'absolute', width: `${box.widthPct}%`, height: `${box.heightPct}%`, left: `${box.leftPct}%`, top: `${box.topPct}%`, maxWidth: 'none', objectFit: 'fill' } as CSSProperties })()
                  : { objectPosition: `${slot.focal_x * 100}% ${slot.focal_y * 100}%`, transformOrigin: `${slot.focal_x * 100}% ${slot.focal_y * 100}%`, transform: `scale(${slot.zoom})` } as CSSProperties)
                : undefined
              const draggable = index === selectedSlot && natural && targetWidth > 0 && targetHeight > 0
              const sourceLabel = slotSourceLabel(slot)
              return <button key={slot.slot_index} type="button" className={`panel-slot${index === selectedSlot ? ' panel-slot--selected' : ''}${draggable ? ' panel-slot--draggable' : ''}`} style={style} aria-label={`Slot ${index + 1}${sourceLabel ? `, ${sourceLabel}` : ', empty'}`} aria-pressed={index === selectedSlot} onClick={() => setSelectedSlot(index)}>{key !== null && slot.content_url ? <><ImageWithFallback src={slot.content_url} alt="" style={imageStyle} onLoad={(event) => { const image = event.currentTarget; if (key !== null && image.naturalWidth > 0) setNaturalSizes((current) => current[key]?.w === image.naturalWidth && current[key]?.h === image.naturalHeight ? current : { ...current, [key]: { w: image.naturalWidth, h: image.naturalHeight } }) }} {...(draggable ? { onPointerDown: (event: ReactPointerEvent<HTMLImageElement>) => beginSlotDrag(event, slot, targetWidth / targetHeight), onPointerMove: moveSlotDrag, onPointerUp: endSlotDrag, onPointerCancel: endSlotDrag } : {})} /><span className="panel-slot__remove" role="button" tabIndex={0} aria-label={`Remove image from slot ${index + 1}`} title="Remove from slot" onClick={(event) => { event.stopPropagation(); setSelectedSlot(index); setValues((current) => current && ({ ...current, slots: current.slots.map((item) => item.slot_index === slot.slot_index ? { ...item, candidate_id: null, gallery_picture_id: null, content_url: null } : item) })) }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); setSelectedSlot(index); setValues((current) => current && ({ ...current, slots: current.slots.map((item) => item.slot_index === slot.slot_index ? { ...item, candidate_id: null, gallery_picture_id: null, content_url: null } : item) })) } }}><Icon name="trash" size="sm" /></span></> : <span>{index + 1}</span>}</button>
            })}
          </div>
        </div>
        </div>
        <p className="panel-editor__status" role="status">{filled} of {values.slots.length} slots filled{dirty ? ' · Unsaved changes' : ' · Saved'}</p>
        <div className="panel-editor__actions"><button className="btn btn--primary" type="button" disabled={!dirty || saving || !values.title.trim() || !/^#[0-9A-F]{6}$/.test(values.background_color)} onClick={() => void save()}>{saving ? 'Saving…' : 'Save panel'}</button><button className="btn" type="button" disabled={!complete || dirty || rendering} onClick={() => void exportPanel()}>{rendering ? 'Rendering…' : 'Render / export'}</button>{currentRender && <><a className="btn" href={currentRender.content_url} target="_blank" rel="noreferrer">Preview</a><a className="btn" href={currentRender.download_url}>Download</a></>}</div>
      </div>
      <aside className="panel-source-picker card" aria-label="Gallery picture picker">
        <div className="panel-source-picker__header"><h2>Gallery pictures</h2><span>{gallery.length}</span></div>
        {gallery.length === 0 ? <p className="field__hint">No gallery pictures. <Link to="/gallery/upload">Upload a picture</Link> or review a scene candidate.</p> : <>
          <div className="field"><label htmlFor="gallery-filter">Filter pictures</label><input id="gallery-filter" type="text" placeholder="Title, description, or scene" value={galleryQuery} onChange={(event) => setGalleryQuery(event.target.value)} /></div>
          <div className="panel-source-picker__grid">{gallery.filter((item) => `${item.source_type} ${item.source_id} ${item.scene_id ?? ''} ${item.description}`.toLowerCase().includes(galleryQuery.trim().toLowerCase())).map((item) => { const itemKey = sourceKey(item); const used = values.slots.some((slot) => sourceKey(slot) === itemKey); return <button key={itemKey} type="button" aria-label={`Assign ${galleryItemLabel(item)} to selected slot`} title={item.description} onClick={() => assign(item)}><ImageWithFallback src={item.content_url} alt="" /><span>{used ? 'Used · assign again' : item.source_type === 'candidate' ? `Scene ${item.scene_id}` : 'Uploaded'}</span></button> })}</div>
        </>}
      </aside>
    </div>
    <ConfirmDialog {...confirmationProps} />
  </section>
}
