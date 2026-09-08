import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, createComicPage, getComicPage, getGallery, renderComicPage, updateComicPage } from '../../api/client'
import type { ComicPage, ComicPagePanelInput, ComicPageUpdate, GalleryItem, PageRender } from '../../api/types'
import { COMIC_PAGE_FORMATS, COMIC_PAGE_TEMPLATES, getComicPageTemplate, templateRectangles, type ComicPageTemplateKey } from '../../comic-pages/templates'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { ImageWithFallback } from '../../components/ImageWithFallback'
import { PageHeader } from '../../components/PageHeader'
import { useUnsavedChanges } from '../../hooks/useUnsavedChanges'
import { RouteIdGuard } from '../../routing/routeId'
import { usePageTitle } from '../../routing/usePageTitle'
import { NotFoundPage } from '../NotFoundPage'

interface EditorPanel extends ComicPagePanelInput { content_url: string }
interface EditorValues extends Omit<ComicPageUpdate, 'expected_revision' | 'panels'> { panels: EditorPanel[] }

const errorMessage = (error: unknown) => error instanceof ApiError ? error.message : String(error)
const snapshot = (values: EditorValues) => JSON.stringify(values)
const positiveId = (value: string | null) => value && /^[1-9]\d*$/.test(value) ? Number(value) : null

function hydrate(page: ComicPage): EditorValues {
  return {
    title: page.title,
    format: page.format,
    background_color: page.background_color,
    gutter_px: page.gutter_px,
    template_key: page.template_key,
    template_version: page.template_version,
    divider_values: page.divider_values,
    panels: page.panels.map(({ candidate_id, slot_index, focal_x, focal_y, zoom, content_url }) => ({ candidate_id, slot_index, focal_x, focal_y, zoom, content_url })),
  }
}

export function ComicPageEditorPage() {
  const { id } = useParams()
  if (id === undefined) return <NewComicPageSetup />
  return <RouteIdGuard>{(pageId) => <ComicPageEditor key={pageId} pageId={pageId} />}</RouteIdGuard>
}

function NewComicPageSetup() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const candidateId = positiveId(params.get('candidate'))
  const [title, setTitle] = useState('Untitled page')
  const [format, setFormat] = useState('portrait')
  const [templateKey, setTemplateKey] = useState<ComicPageTemplateKey>('full')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { allowNavigation, confirmationProps } = useUnsavedChanges(title !== 'Untitled page' || format !== 'portrait' || templateKey !== 'full')
  usePageTitle('New Comic Page')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const page = await createComicPage({
        title,
        format,
        template_key: templateKey,
        ...(candidateId === null ? {} : { candidate_id: candidateId }),
      })
      allowNavigation()
      navigate(`/panels/${page.id}/edit`, { replace: true })
    } catch (reason) {
      setError(errorMessage(reason))
      setSubmitting(false)
    }
  }

  return <section className="form-page">
    <PageHeader title="New comic page" description="Choose a format and starting layout. You can refine every panel next." />
    {error && <AsyncMessage kind="error">Could not create comic page: {error}</AsyncMessage>}
    <form className="form-card" onSubmit={submit} aria-busy={submitting}>
      <fieldset className="form-section"><legend>Page setup</legend>
        <div className="field"><label htmlFor="page-title">Title</label><input id="page-title" required maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} /></div>
        <div className="form-grid">
          <div className="field"><label htmlFor="page-format">Format</label><select id="page-format" value={format} onChange={(event) => setFormat(event.target.value)}>{COMIC_PAGE_FORMATS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></div>
          <div className="field"><label htmlFor="page-template">Template</label><select id="page-template" value={templateKey} onChange={(event) => setTemplateKey(event.target.value as ComicPageTemplateKey)}>{COMIC_PAGE_TEMPLATES.map((item) => <option key={item.key} value={item.key}>{item.label} · {item.slotCount} panel{item.slotCount === 1 ? '' : 's'}</option>)}</select></div>
        </div>
        {candidateId && <p className="field__hint">Gallery image #{candidateId} will be placed in the first panel.</p>}
      </fieldset>
      <div className="form-actions"><button className="btn btn--primary" disabled={submitting} type="submit">{submitting ? 'Creating…' : 'Create and compose'}</button><Link className="btn" to="/panels">Cancel</Link></div>
    </form>
    <ConfirmDialog {...confirmationProps} />
  </section>
}

function ComicPageEditor({ pageId }: { pageId: number }) {
  const [values, setValues] = useState<EditorValues | null>(null)
  const [gallery, setGallery] = useState<GalleryItem[] | null>(null)
  const [revision, setRevision] = useState<number | null>(null)
  const [baseline, setBaseline] = useState<string | null>(null)
  const [render, setRender] = useState<PageRender | null>(null)
  const [selectedSlot, setSelectedSlot] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [saving, setSaving] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [galleryQuery, setGalleryQuery] = useState('')
  const mounted = useRef(true)
  const dirty = values !== null && baseline !== null && snapshot(values) !== baseline
  const { confirmationProps } = useUnsavedChanges(dirty)
  const template = values ? getComicPageTemplate(values.template_key) : null
  const selectedPanel = values?.panels.find((panel) => panel.slot_index === selectedSlot)
  const complete = values !== null && values.panels.length === template?.slotCount
  const currentRender = render?.page_revision === revision ? render : null
  usePageTitle(values ? `Edit ${values.title}` : 'Edit Comic Page')

  useEffect(() => {
    mounted.current = true
    Promise.all([getComicPage(pageId), getGallery()]).then(([page, items]) => {
      if (!mounted.current) return
      const hydrated = hydrate(page)
      setValues(hydrated)
      setBaseline(snapshot(hydrated))
      setRevision(page.revision)
      setRender(page.latest_render)
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
  }, [pageId, loadAttempt])

  const patchPanel = (patch: Partial<EditorPanel>) => setValues((current) => current && ({ ...current, panels: current.panels.map((panel) => panel.slot_index === selectedSlot ? { ...panel, ...patch } : panel) }))
  const assign = (item: GalleryItem) => setValues((current) => {
    if (!current || current.panels.some((panel) => panel.candidate_id === item.candidate_id)) return current
    const slot = current.panels.some((panel) => panel.slot_index === selectedSlot)
      ? selectedSlot
      : Array.from({ length: getComicPageTemplate(current.template_key).slotCount }, (_, index) => index).find((index) => !current.panels.some((panel) => panel.slot_index === index)) ?? selectedSlot
    return { ...current, panels: [...current.panels.filter((panel) => panel.slot_index !== slot), { candidate_id: item.candidate_id, slot_index: slot, focal_x: 0.5, focal_y: 0.5, zoom: 1, content_url: item.content_url }].sort((a, b) => a.slot_index - b.slot_index) }
  })

  const save = async () => {
    if (!values || revision === null) return
    setSaving(true)
    setError(null)
    setConflict(false)
    try {
      const panels = values.panels.map((panel) => ({
        candidate_id: panel.candidate_id,
        slot_index: panel.slot_index,
        focal_x: panel.focal_x,
        focal_y: panel.focal_y,
        zoom: panel.zoom,
      }))
      const page = await updateComicPage(pageId, { ...values, panels, expected_revision: revision })
      if (!mounted.current) return
      const hydrated = hydrate(page)
      setValues(hydrated)
      setBaseline(snapshot(hydrated))
      setRevision(page.revision)
      setRender(page.latest_render)
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) setConflict(true)
      else setError(errorMessage(reason))
    } finally {
      if (mounted.current) setSaving(false)
    }
  }

  const exportPage = async () => {
    if (revision === null) return
    setRendering(true)
    setError(null)
    try { setRender(await renderComicPage(pageId, { expected_revision: revision })) }
    catch (reason) { setError(errorMessage(reason)) }
    finally { if (mounted.current) setRendering(false) }
  }

  if (notFound) return <NotFoundPage />
  if (!values || !gallery || revision === null || !template) return <div>{error ? <><AsyncMessage kind="error">Could not load comic page: {error}</AsyncMessage><button className="btn" type="button" onClick={() => { setError(null); setLoadAttempt((value) => value + 1) }}>Retry</button></> : <AsyncMessage kind="loading">Loading comic page composer…</AsyncMessage>}</div>

  const rectangles = templateRectangles(template.key, values.divider_values)
  const format = COMIC_PAGE_FORMATS.find((item) => item.key === values.format) ?? COMIC_PAGE_FORMATS[0]
  return <section className="comic-editor">
    <PageHeader title="Comic page composer" description={`Revision ${revision} · ${format.width} × ${format.height}px`} actions={<Link className="btn" to="/panels">All pages</Link>} />
    {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
    {conflict && <AsyncMessage kind="error">This page changed elsewhere. Reload the latest revision before saving. <button className="btn btn--sm" type="button" onClick={() => { setValues(null); setBaseline(null); setLoadAttempt((value) => value + 1) }}>Reload page</button></AsyncMessage>}
    <div className="comic-editor__workspace">
      <aside className="comic-editor__settings card" aria-label="Page settings">
        <h2>Page</h2>
        <div className="field"><label htmlFor="edit-title">Title</label><input id="edit-title" maxLength={120} value={values.title} onChange={(event) => setValues({ ...values, title: event.target.value })} /></div>
        <div className="field"><label htmlFor="edit-format">Format</label><select id="edit-format" value={values.format} onChange={(event) => setValues({ ...values, format: event.target.value })}>{COMIC_PAGE_FORMATS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></div>
        <div className="field"><label htmlFor="edit-template">Layout</label><select id="edit-template" value={values.template_key} onChange={(event) => { const next = getComicPageTemplate(event.target.value); setValues({ ...values, template_key: next.key, divider_values: [...next.defaultDividers], panels: values.panels.filter((panel) => panel.slot_index < next.slotCount) }); setSelectedSlot((slot) => Math.min(slot, next.slotCount - 1)) }}>{COMIC_PAGE_TEMPLATES.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></div>
        <div className="field"><label htmlFor="page-gutter">Gutter: {values.gutter_px}px</label><input id="page-gutter" type="range" min="0" max="80" value={values.gutter_px} onChange={(event) => setValues({ ...values, gutter_px: Number(event.target.value) })} /></div>
        <div className="field"><label htmlFor="page-background">Background color</label><input id="page-background" pattern="#[0-9A-F]{6}" value={values.background_color} onChange={(event) => setValues({ ...values, background_color: event.target.value.toUpperCase() })} /></div>
        {template.dividerLabels.map((label, index) => <div className="field" key={label}><label htmlFor={`divider-${index}`}>{label}: {Math.round(values.divider_values[index] * 100)}%</label><input id={`divider-${index}`} type="range" min="0.2" max="0.8" step="0.01" value={values.divider_values[index]} onChange={(event) => { const dividers = [...values.divider_values]; dividers[index] = Number(event.target.value); if ((template.key === 'three_rows' || template.key === 'six_grid') && index < 2) { if (index === 0) dividers[0] = Math.min(dividers[0], dividers[1] - 0.1); else dividers[1] = Math.max(dividers[1], dividers[0] + 0.1) } setValues({ ...values, divider_values: dividers }) }} /></div>)}
        {selectedPanel && <fieldset className="comic-editor__crop"><legend>Panel {selectedSlot + 1} crop</legend>
          <div className="field"><label htmlFor="focal-x">Horizontal focal point: {Math.round(selectedPanel.focal_x * 100)}%</label><input id="focal-x" type="range" min="0" max="1" step="0.01" value={selectedPanel.focal_x} onChange={(event) => patchPanel({ focal_x: Number(event.target.value) })} /></div>
          <div className="field"><label htmlFor="focal-y">Vertical focal point: {Math.round(selectedPanel.focal_y * 100)}%</label><input id="focal-y" type="range" min="0" max="1" step="0.01" value={selectedPanel.focal_y} onChange={(event) => patchPanel({ focal_y: Number(event.target.value) })} /></div>
          <div className="field"><label htmlFor="panel-zoom">Zoom: {selectedPanel.zoom.toFixed(2)}×</label><input id="panel-zoom" type="range" min="1" max="3" step="0.05" value={selectedPanel.zoom} onChange={(event) => patchPanel({ zoom: Number(event.target.value) })} /></div>
          <button className="btn btn--danger btn--sm" type="button" onClick={() => setValues({ ...values, panels: values.panels.filter((panel) => panel.slot_index !== selectedSlot) })}>Remove from panel</button>
        </fieldset>}
      </aside>
      <div className="comic-editor__stage">
        <div className="comic-page-canvas" aria-label={`${template.label} page canvas`} style={{ '--page-ratio': `${format.width} / ${format.height}`, '--page-max-width': `${68 * format.width / format.height}svh`, '--page-background': values.background_color } as CSSProperties}>
          {rectangles.map((rectangle, slot) => {
            const panel = values.panels.find((item) => item.slot_index === slot)
            const xBefore = rectangle.x0 > 0 ? values.gutter_px - Math.floor(values.gutter_px / 2) : 0
            const xAfter = rectangle.x1 < 1 ? Math.floor(values.gutter_px / 2) : 0
            const yBefore = rectangle.y0 > 0 ? values.gutter_px - Math.floor(values.gutter_px / 2) : 0
            const yAfter = rectangle.y1 < 1 ? Math.floor(values.gutter_px / 2) : 0
            const style = {
              left: `calc(${rectangle.x0 * 100}% + ${xBefore / format.width * 100}%)`,
              top: `calc(${rectangle.y0 * 100}% + ${yBefore / format.height * 100}%)`,
              width: `calc(${(rectangle.x1 - rectangle.x0) * 100}% - ${(xBefore + xAfter) / format.width * 100}%)`,
              height: `calc(${(rectangle.y1 - rectangle.y0) * 100}% - ${(yBefore + yAfter) / format.height * 100}%)`,
            } as CSSProperties
            const imageStyle = panel ? { objectPosition: `${panel.focal_x * 100}% ${panel.focal_y * 100}%`, transformOrigin: `${panel.focal_x * 100}% ${panel.focal_y * 100}%`, transform: `scale(${panel.zoom})` } : undefined
            return <button key={slot} type="button" className={`comic-page-slot${slot === selectedSlot ? ' comic-page-slot--selected' : ''}`} style={style} aria-label={`Panel ${slot + 1}${panel ? `, image ${panel.candidate_id}` : ', empty'}`} aria-pressed={slot === selectedSlot} onClick={() => setSelectedSlot(slot)}>{panel ? <ImageWithFallback src={panel.content_url} alt="" style={imageStyle} /> : <span>{slot + 1}</span>}</button>
          })}
        </div>
        <p className="comic-editor__status" role="status">{values.panels.length} of {template.slotCount} panels filled{dirty ? ' · Unsaved changes' : ' · Saved'}</p>
        <div className="comic-editor__actions"><button className="btn btn--primary" type="button" disabled={!dirty || saving || !values.title.trim() || !/^#[0-9A-F]{6}$/.test(values.background_color)} onClick={() => void save()}>{saving ? 'Saving…' : 'Save page'}</button><button className="btn" type="button" disabled={!complete || dirty || rendering} onClick={() => void exportPage()}>{rendering ? 'Rendering…' : 'Render / export'}</button>{currentRender && <><a className="btn" href={currentRender.content_url} target="_blank" rel="noreferrer">Preview</a><a className="btn" href={currentRender.download_url}>Download</a></>}</div>
      </div>
      <aside className="comic-source-picker card" aria-label="Accepted image picker">
        <div className="comic-source-picker__header"><h2>Accepted images</h2><span>{gallery.length}</span></div>
        {gallery.length === 0 ? <p className="field__hint">No accepted images. <Link to="/gallery">Open Gallery</Link> to review scenes.</p> : <>
          <div className="field"><label htmlFor="gallery-filter">Filter images</label><input id="gallery-filter" type="search" placeholder="Scene or description" value={galleryQuery} onChange={(event) => setGalleryQuery(event.target.value)} /></div>
          <div className="comic-source-picker__grid">{gallery.filter((item) => `${item.scene_id} ${item.beat_text}`.toLowerCase().includes(galleryQuery.trim().toLowerCase())).map((item) => { const used = values.panels.some((panel) => panel.candidate_id === item.candidate_id); return <button key={item.candidate_id} type="button" disabled={used} aria-label={`${used ? 'Already used' : 'Add'} image ${item.candidate_id} to panel`} title={item.beat_text} onClick={() => assign(item)}><ImageWithFallback src={item.content_url} alt="" /><span>{used ? 'On page' : `Scene ${item.scene_id}`}</span></button> })}</div>
        </>}
      </aside>
    </div>
    <ConfirmDialog {...confirmationProps} />
  </section>
}
