import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, duplicatePanel, listPanels } from '../../api/client'
import type { Panel } from '../../api/types'
import { AsyncMessage } from '../../components/AsyncMessage'

export function PanelListPage() {
  const navigate = useNavigate()
  const [panels, setPanels] = useState<Panel[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [duplicatingId, setDuplicatingId] = useState<number | null>(null)
  const mounted = useRef(true)

  const reload = () =>
    listPanels()
      .then((value) => {
        if (!mounted.current) return
        setPanels(value)
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

  // Duplicate a locked panel and go straight to editing the new, editable
  // copy — duplicating alone does not let the user edit anything, so this
  // must navigate, not just refresh the list (issue #15 follow-up).
  const handleDuplicateAndEdit = async (id: number) => {
    if (duplicatingId !== null) return
    setDuplicatingId(id)
    setError(null)
    try {
      const copy = await duplicatePanel(id)
      if (!mounted.current) return
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      if (!mounted.current) return
      setError(`Could not duplicate panel: ${err instanceof ApiError ? err.message : String(err)}`)
    } finally {
      if (mounted.current) setDuplicatingId(null)
    }
  }

  return (
    <section aria-busy={duplicatingId !== null || undefined}>
      <div className="btn-row list-page-header">
        <h1>Panels</h1>
        <Link to="/panels/new" className="btn btn--primary">
          Stage new panel
        </Link>
      </div>
      {error && <AsyncMessage kind="error">{error}</AsyncMessage>}
      {!panels && !error && <AsyncMessage kind="loading">Loading panels…</AsyncMessage>}
      {panels && panels.length === 0 && <p>No panels yet.</p>}
      {panels && panels.length > 0 && (
        <div className="stack-list">
          {panels.map((panel) => (
            <div key={panel.id} className="h-tile">
              <div className="h-tile__main">
                <span className={`badge ${panel.is_editable ? 'badge--draft' : 'badge--canonical'}`}>
                  {panel.is_editable ? 'Editable' : 'Locked'}
                </span>
                <p className="text-clamp" style={{ margin: '0.4rem 0' }}>{panel.beat_text}</p>
                <p className="field__hint" style={{ margin: 0 }}>
                  Cast: {panel.cast.map((m) => m.name).join(', ') || 'none'}
                </p>
                <p className="field__hint" style={{ margin: 0 }}>
                  {panel.generation_count} generation attempt
                  {panel.generation_count === 1 ? '' : 's'}
                </p>
              </div>
              <div className="h-tile__actions">
                <Link to={`/panels/${panel.id}/preview`} className="btn">
                  Preview
                </Link>
                {panel.is_editable ? (
                  <Link to={`/panels/${panel.id}/edit`} className="btn">
                    Edit
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    disabled={duplicatingId !== null}
                    onClick={() => void handleDuplicateAndEdit(panel.id)}
                  >
                    {duplicatingId === panel.id ? 'Duplicating…' : 'Duplicate & edit'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
