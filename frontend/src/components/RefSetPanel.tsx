import { useEffect, useRef, useState, type FormEvent } from 'react'
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
import { AsyncMessage } from './AsyncMessage'

interface RefSetPanelProps {
  refSetId: number
  onChanged: () => void | string | null | Promise<void | string | null>
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
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<{
    kind: 'success' | 'error'
    text: string
  } | null>(null)
  const [role, setRole] = useState(options.ref_image_roles[0] ?? 'face_front')
  const [file, setFile] = useState<File | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const mounted = useRef(true)
  const requestVersion = useRef(0)

  const reload = async () => {
    const version = ++requestVersion.current
    try {
      const nextRefSet = await getRefSet(refSetId)
      if (!mounted.current || version !== requestVersion.current) return null
      setRefSet(nextRefSet)
      setLoadError(null)
      return null
    } catch (err) {
      if (!mounted.current || version !== requestVersion.current) return null
      const message = err instanceof ApiError ? err.message : String(err)
      setLoadError(message)
      return message
    }
  }

  useEffect(() => {
    mounted.current = true
    void reload()
    return () => {
      mounted.current = false
      requestVersion.current += 1
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refSetId])

  if (!refSet) {
    return loadError ? (
      <div>
        <AsyncMessage kind="error">Could not load reference set: {loadError}</AsyncMessage>
        <button type="button" className="btn" onClick={() => void reload()}>Retry</button>
      </div>
    ) : <AsyncMessage kind="loading">Loading reference set…</AsyncMessage>
  }

  const isDraft = refSet.status === 'draft'

  const runAction = async (
    label: string,
    successText: string,
    action: () => Promise<unknown>,
    onSucceeded?: () => void,
  ) => {
    if (busyAction) return
    setBusyAction(label)
    setActionMessage(null)
    try {
      await action()
      if (!mounted.current) return
    } catch (err) {
      if (!mounted.current) return
      setActionMessage({
        kind: 'error',
        text: `Could not ${label}: ${err instanceof ApiError ? err.message : String(err)}`,
      })
      setBusyAction(null)
      return
    }

    onSucceeded?.()
    const ownRefreshError = await reload()
    if (!mounted.current) return
    let parentRefreshError: string | null = null
    try {
      const result = await onChanged()
      if (!mounted.current) return
      if (typeof result === 'string') parentRefreshError = result
    } catch (err) {
      if (!mounted.current) return
      parentRefreshError = err instanceof ApiError ? err.message : String(err)
    }
    const refreshError = ownRefreshError ?? parentRefreshError
    if (refreshError) setLoadError(null)
    setActionMessage(
      refreshError
        ? { kind: 'error', text: `${successText} However, reference-set data could not be refreshed: ${refreshError}` }
        : { kind: 'success', text: successText },
    )
    setBusyAction(null)
  }

  const handleUpload = (e: FormEvent) => {
    e.preventDefault()
    if (!file) return
    void runAction(
      'upload reference image',
      'Reference image uploaded.',
      () => uploadRefImage(refSetId, file, role),
      () => {
        setFile(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
      },
    )
  }

  const handlePromote = () => {
    if (
      !window.confirm(
        'Promote this draft to canonical? The draft will become immutable, and the current canonical, if any, will be retired.',
      )
    ) {
      return
    }
    void runAction('promote reference set', 'Reference set promoted to canonical.', () => promoteRefSet(refSetId))
  }

  const handleRemove = (imageId: number) => {
    if (!window.confirm('Remove this image from the draft?')) return
    void runAction('remove reference image', 'Reference image removed.', () => removeRefImage(refSetId, imageId))
  }

  return (
    <div className="card" style={{ marginTop: '0.75rem' }} aria-busy={busyAction !== null || undefined}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>
          v{refSet.version} <span className={`badge badge--${refSet.status}`}>{STATUS_LABEL[refSet.status]}</span>
        </h3>
        <div className="btn-row" style={{ marginTop: 0 }}>
          <button
            type="button"
            className="btn"
            disabled={busyAction !== null}
            onClick={() => void runAction('copy reference set', 'Reference set copied to a new draft.', () => copyRefSet(refSetId))}
          >
            Copy to new draft
          </button>
          {isDraft && (
            <button
              type="button"
              className="btn btn--primary"
              disabled={busyAction !== null || refSet.images.length === 0}
              onClick={handlePromote}
            >
              Promote to canonical
            </button>
          )}
        </div>
      </div>

      {!isDraft && (
        <p className="field__hint">{options.ref_set_immutability_explanation}</p>
      )}

      {busyAction && <AsyncMessage kind="loading">Working: {busyAction}…</AsyncMessage>}
      {loadError && <AsyncMessage kind="error">Could not refresh reference set: {loadError}</AsyncMessage>}
      {actionMessage && <AsyncMessage kind={actionMessage.kind}>{actionMessage.text}</AsyncMessage>}

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
              disabled={busyAction !== null}
              onReRole={(imageId, newRole) =>
                void runAction('change reference image role', 'Reference image role changed.', () => reRoleRefImage(refSetId, imageId, newRole))
              }
              onRemove={handleRemove}
            />
          ))}
        </div>
      )}

      {isDraft && (
        <form onSubmit={handleUpload} className="btn-row" style={{ alignItems: 'center' }}>
          <select
            value={role}
            disabled={busyAction !== null}
            onChange={(e) => setRole(e.target.value)}
            aria-label="New image role"
          >
            {options.ref_image_roles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            type="file"
            ref={fileInputRef}
            disabled={busyAction !== null}
            accept="image/png,image/jpeg,image/webp"
            aria-label="Reference image file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button type="submit" className="btn" disabled={busyAction !== null || !file}>
            Upload
          </button>
        </form>
      )}
    </div>
  )
}
