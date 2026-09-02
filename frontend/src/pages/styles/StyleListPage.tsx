import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  archiveStyle,
  listArchivedStyles,
  listStyles,
  restoreStyle,
} from '../../api/client'
import type { Style } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { Icon } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'

export function StyleListPage() {
  const [styles, setStyles] = useState<Style[] | null>(null)
  const [archived, setArchived] = useState<Style[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const mounted = useRef(true)

  const reload = () =>
    Promise.all([listStyles(), listArchivedStyles()])
      .then(([active, archivedStyles]) => {
        if (!mounted.current) return
        setStyles(active)
        setArchived(archivedStyles)
        setError(null)
      })
      .catch((err) => {
        if (mounted.current) setError(err instanceof ApiError ? err.message : String(err))
      })

  useEffect(() => {
    mounted.current = true
    void reload()
    return () => {
      mounted.current = false
    }
  }, [])

  const confirmArchive = async () => {
    const id = confirmId
    setConfirmId(null)
    if (id === null || busyId !== null) return
    setBusyId(id)
    setError(null)
    try {
      await archiveStyle(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not archive style: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  const handleRestore = async (id: number) => {
    if (busyId !== null) return
    setBusyId(id)
    setError(null)
    try {
      await restoreStyle(id)
      await reload()
    } catch (err) {
      if (mounted.current) setError(`Could not restore style: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setBusyId(null)
    }
  }

  const pendingStyle = confirmId !== null ? styles?.find((s) => s.id === confirmId) : undefined

  return (
    <section aria-busy={busyId !== null || undefined}>
      <PageHeader
        title="Styles"
        actions={(
          <Link to="/styles/new" className="btn btn--primary">
            <Icon name="plus" size={16} />
            New style
          </Link>
        )}
      />
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!styles && !error && <AsyncMessage kind="loading">Loading styles…</AsyncMessage>}
      {styles && styles.length === 0 && (
        <EmptyState
          icon="styles"
          title="No styles yet"
          description="Define a visual contract before staging your first panel."
          action={(
            <Link to="/styles/new" className="btn btn--primary">
              <Icon name="plus" size={16} />
              New style
            </Link>
          )}
        />
      )}
      {styles && styles.length > 0 && (
        <div className="resource-list">
          {styles.map((style) => (
            <article key={style.id} className="resource-card">
              <div className="resource-card__body">
                <h2 className="resource-card__title">{style.name}</h2>
                <p className="resource-card__summary text-clamp" title={style.style_contract}>
                  {style.style_contract || 'No style contract yet.'}
                </p>
              </div>
              <div className="resource-card__actions">
                <Link to={`/styles/${style.id}/edit`} className="btn">
                  <Icon name="edit" size={15} />
                  Edit
                </Link>
                <button
                  type="button"
                  className="btn btn--danger"
                  disabled={busyId !== null}
                  onClick={() => setConfirmId(style.id)}
                >
                  <Icon name="trash" size={15} />
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <div className="archived-section">
          <button
            type="button"
            className="btn archived-section__toggle"
            aria-expanded={showArchived}
            onClick={() => setShowArchived((value) => !value)}
          >
            {showArchived ? 'Hide' : 'Show'} archived styles ({archived.length})
          </button>
          {showArchived && (
            <div className="resource-list">
              {archived.map((style) => (
                <article key={style.id} className="resource-card resource-card--archived">
                  <div className="resource-card__body">
                    <h2 className="resource-card__title">{style.name}</h2>
                    <p className="resource-card__summary text-clamp" title={style.style_contract}>
                      {style.style_contract || 'No style contract yet.'}
                    </p>
                  </div>
                  <div className="resource-card__actions">
                    <button
                      type="button"
                      className="btn"
                      disabled={busyId !== null}
                      onClick={() => void handleRestore(style.id)}
                    >
                      {busyId === style.id ? 'Restoring…' : 'Restore'}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmId !== null}
        title="Archive this style?"
        description={
          pendingStyle
            ? `"${pendingStyle.name}" stays on existing panels but is hidden from lists and can't be used for new panels. You can restore it later.`
            : 'The style stays on existing panels but is hidden from lists. You can restore it later.'
        }
        confirmLabel="Archive style"
        onConfirm={() => void confirmArchive()}
        onCancel={() => setConfirmId(null)}
      />
    </section>
  )
}
