import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getGallery } from '../../api/client'
import type { GalleryItem } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { DateTime } from '../../components/DateTime'
import { ImageDialog } from '../../components/ImageDialog'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'

const itemLabel = (item: GalleryItem) => item.source_type === 'candidate'
  ? `Accepted image from scene ${item.scene_id}`
  : `Uploaded picture: ${item.description}`

export function GalleryPage() {
  const [items, setItems] = useState<GalleryItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const mounted = useRef(true)

  const reload = () =>
    getGallery()
      .then((value) => {
        if (!mounted.current) return
        setItems(value)
        setError(null)
      })
      .catch((err) => {
        if (mounted.current) setError(err instanceof ApiError ? err.message : String(err))
      })

  useEffect(() => {
    mounted.current = true
    reload()
    return () => {
      mounted.current = false
    }
  }, [])

  return (
    <section aria-busy={items === null && error === null || undefined}>
      <PageHeader
        title="Gallery"
        description="Accepted scene images and your uploaded pictures, ready for panels."
        actions={<Link to="/gallery/upload" className="btn btn--primary"><Icon name="plus" size="sm" />Upload picture</Link>}
      />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!items && !error && <AsyncMessage kind="loading">Loading gallery…</AsyncMessage>}
      {items && items.length === 0 && (
        <EmptyState
          icon="gallery"
          title="No gallery pictures yet."
          description="Upload a picture or accept a generated candidate to start building your gallery."
          action={<div className="btn-row"><Link className="btn btn--primary" to="/gallery/upload">Upload picture</Link><Link className="btn" to="/scenes">Review scenes</Link></div>}
        />
      )}
      {items && items.length > 0 && (
        <div className="resource-grid">
          {items.map((item, index) => {
            const previewItem = items[previewIndex ?? index]
            const label = itemLabel(item)
            const previewLabel = itemLabel(previewItem)
            return (
              <article className="card card--flush gallery-card" key={`${item.source_type}:${item.source_id}`}>
                <ImageDialog
                  src={item.content_url}
                  previewSrc={previewItem.content_url}
                  thumbnailAlt={label}
                  previewAlt={`${previewLabel}, full-size preview`}
                  triggerLabel={`Preview ${label.toLowerCase()}`}
                  dialogLabel={`${previewLabel}, larger preview`}
                  onPrevious={() => setPreviewIndex((current) => ((current ?? index) - 1 + items.length) % items.length)}
                  onNext={() => setPreviewIndex((current) => ((current ?? index) + 1) % items.length)}
                  onOpenChange={(open) => setPreviewIndex(open ? index : null)}
                />
                <div className="gallery-card__body">
                  <div className="gallery-card__topline">
                    <span className={`badge ${item.source_type === 'upload' ? 'badge--draft' : 'badge--canonical'}`}>{item.source_type === 'upload' ? 'Uploaded' : 'Generated'}</span>
                  </div>
                  <p className="gallery-card__summary text-clamp" title={item.description}>{item.description}</p>
                  <p className="gallery-card__meta">
                    {item.source_type === 'candidate' ? `Scene #${item.scene_id}` : `Picture #${item.gallery_picture_id}`} · {item.aspect_ratio} ·{' '}
                    <DateTime value={item.created_at} />
                  </p>
                </div>
                <div className="gallery-card__actions">
                  <Link to={`/panels/new?${item.source_type === 'candidate' ? 'candidate' : 'picture'}=${item.source_id}`} className="btn btn--primary">
                    <Icon name="plus" size="sm" />
                    Add to panel
                  </Link>
                  {item.source_type === 'candidate' && <Link to={`/scenes/${item.scene_id}/preview`} className="btn">
                    <Icon name="chevronRight" size="sm" />
                    Open scene
                  </Link>}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
