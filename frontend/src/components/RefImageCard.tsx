import { useState } from 'react'
import type { RefImage } from '../api/types'

interface RefImageCardProps {
  image: RefImage
  roles: string[]
  editable: boolean
  weightExplanation: string
  onReRole?: (imageId: number, role: string) => void
  onRemove?: (imageId: number) => void
}

/**
 * A single reference image: thumbnail, larger click-to-preview, its role,
 * its displayed-but-immutable weight, and — only while the owning ref-set is
 * a draft — controls to re-role or remove it (issue #15). Weight is always
 * shown but never editable from the UI; `weightExplanation` (sourced from
 * the backend via OptionsSummary) is surfaced as a tooltip/caption so the
 * immutability is explained, not just enforced silently.
 */
export function RefImageCard({
  image,
  roles,
  editable,
  weightExplanation,
  onReRole,
  onRemove,
}: RefImageCardProps) {
  const [previewOpen, setPreviewOpen] = useState(false)

  return (
    <div className="ref-image-card">
      <img
        src={image.content_url}
        alt={`${image.role} reference thumbnail`}
        onClick={() => setPreviewOpen(true)}
      />
      <div className="ref-image-card__body">
        <div className="field" style={{ marginBottom: '0.4rem' }}>
          <label htmlFor={`role-${image.id}`}>Role</label>
          {editable ? (
            <select
              id={`role-${image.id}`}
              value={image.role}
              onChange={(e) => onReRole?.(image.id, e.target.value)}
            >
              {roles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          ) : (
            <strong>{image.role}</strong>
          )}
        </div>
        <p className="field__hint" title={weightExplanation}>
          Weight: {image.weight.toFixed(2)} (fixed)
        </p>
        {editable && (
          <button
            type="button"
            className="btn btn--danger"
            onClick={() => onRemove?.(image.id)}
          >
            Remove
          </button>
        )}
      </div>
      {previewOpen && (
        <div
          className="preview-overlay"
          role="dialog"
          aria-label={`${image.role} reference, larger preview`}
          onClick={() => setPreviewOpen(false)}
        >
          <img src={image.content_url} alt={`${image.role} reference, larger preview`} />
        </div>
      )}
    </div>
  )
}
