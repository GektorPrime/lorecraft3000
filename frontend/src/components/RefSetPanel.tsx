import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  copyRefSet,
  getRefSet,
  promoteRefSet,
  reRoleRefImage,
  removeRefImage,
  uploadRefImage,
} from '../api/client'
import { useOptions } from '../api/useOptions'
import type { RefSet } from '../api/types'
import { RefImageCard } from './RefImageCard'

interface RefSetPanelProps {
  refSetId: number
  onChanged: () => void
}

const STATUS_LABEL: Record<RefSet['status'], string> = {
  draft: 'Draft',
  canonical: 'Canonical',
  retired: 'Retired',
}

/** Manages one reference-set version: images, promotion, and copy (issue #15). */
export function RefSetPanel({ refSetId, onChanged }: RefSetPanelProps) {
  const options = useOptions()
  const [refSet, setRefSet] = useState<RefSet | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [role, setRole] = useState(options.ref_image_roles[0] ?? 'face_front')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = () =>
    getRefSet(refSetId)
      .then(setRefSet)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)))

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refSetId])

  if (!refSet) {
    return error ? <p className="banner banner--error">{error}</p> : <p>Loading…</p>
  }

  const isDraft = refSet.status === 'draft'

  const runAction = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      await reload()
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleUpload = (e: FormEvent) => {
    e.preventDefault()
    if (!file) return
    void runAction(async () => {
      await uploadRefImage(refSetId, file, role)
      setFile(null)
    })
  }

  return (
    <div className="card" style={{ marginTop: '0.75rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>
          v{refSet.version} <span className={`badge badge--${refSet.status}`}>{STATUS_LABEL[refSet.status]}</span>
        </h3>
        <div className="btn-row" style={{ marginTop: 0 }}>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void runAction(() => copyRefSet(refSetId))}
          >
            Copy to new draft
          </button>
          {isDraft && (
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || refSet.images.length === 0}
              onClick={() => void runAction(() => promoteRefSet(refSetId))}
            >
              Promote to canonical
            </button>
          )}
        </div>
      </div>

      {!isDraft && (
        <p className="field__hint">{options.ref_set_immutability_explanation}</p>
      )}

      {error && <p className="banner banner--error">{error}</p>}

      {refSet.images.length === 0 ? (
        <p className="field__hint">No images yet.</p>
      ) : (
        <div className="ref-image-grid">
          {refSet.images.map((image) => (
            <RefImageCard
              key={image.id}
              image={image}
              roles={options.ref_image_roles}
              editable={isDraft}
              weightExplanation={options.ref_image_weight_explanation}
              onReRole={(imageId, newRole) =>
                void runAction(() => reRoleRefImage(refSetId, imageId, newRole))
              }
              onRemove={(imageId) => void runAction(() => removeRefImage(refSetId, imageId))}
            />
          ))}
        </div>
      )}

      {isDraft && (
        <form onSubmit={handleUpload} className="btn-row" style={{ alignItems: 'center' }}>
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="New image role">
            {options.ref_image_roles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            aria-label="Reference image file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button type="submit" className="btn" disabled={busy || !file}>
            Upload
          </button>
        </form>
      )}
    </div>
  )
}
