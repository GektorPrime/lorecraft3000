import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, duplicatePanel, listPanels } from '../../api/client'
import type { Panel } from '../../api/types'

export function PanelListPage() {
  const navigate = useNavigate()
  const [panels, setPanels] = useState<Panel[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = () =>
    listPanels()
      .then(setPanels)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))

  useEffect(() => {
    reload()
  }, [])

  // Duplicate a locked panel and go straight to editing the new, editable
  // copy — duplicating alone does not let the user edit anything, so this
  // must navigate, not just refresh the list (issue #15 follow-up).
  const handleDuplicateAndEdit = async (id: number) => {
    try {
      const copy = await duplicatePanel(id)
      navigate(`/panels/${copy.id}/edit`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  return (
    <section>
      <div className="btn-row" style={{ justifyContent: 'space-between', marginTop: 0 }}>
        <h1>Panels</h1>
        <Link to="/panels/new" className="btn btn--primary">
          Stage new panel
        </Link>
      </div>
      {error && <p className="banner banner--error">{error}</p>}
      {!panels && !error && <p>Loading…</p>}
      {panels && panels.length === 0 && <p>No panels yet.</p>}
      {panels && panels.length > 0 && (
        <div className="card-grid">
          {panels.map((panel) => (
            <div key={panel.id} className="card">
              <span className={`badge ${panel.is_editable ? 'badge--draft' : 'badge--canonical'}`}>
                {panel.is_editable ? 'Editable' : 'Locked'}
              </span>
              <p>{panel.beat_text}</p>
              <p className="field__hint">
                Cast: {panel.cast.map((m) => m.name).join(', ') || 'none'}
              </p>
              <p className="field__hint">
                {panel.generation_count} generation attempt
                {panel.generation_count === 1 ? '' : 's'}
              </p>
              <div className="btn-row" style={{ marginTop: '0.5rem' }}>
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
                    onClick={() => void handleDuplicateAndEdit(panel.id)}
                  >
                    Duplicate &amp; edit
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
