import type { RefImage } from '../api/types'
import { ImageDialog } from './ImageDialog'
import { Icon } from './Icon'

interface RefImageCardProps {
  image: RefImage
  roles: string[]
  editable: boolean
  weightExplanation: string
  disabled?: boolean
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
  disabled = false,
  onReRole,
  onRemove,
}: RefImageCardProps) {
  return (
    <div className="ref-image-card">
      <ImageDialog
        src={image.content_url}
        thumbnailAlt={`${image.role} reference thumbnail`}
        previewAlt={`${image.role} reference, larger preview`}
        triggerLabel={`Preview ${image.role} reference`}
        dialogLabel={`${image.role} reference, larger preview`}
      />
      <div className="ref-image-card__body">
        <div className="field ref-image-card__field">
          <label htmlFor={`role-${image.id}`}>Role</label>
          {editable ? (
            <select
              id={`role-${image.id}`}
              value={image.role}
              disabled={disabled}
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
        <p className="ref-image-card__meta" title={weightExplanation}>
          Weight: {image.weight.toFixed(2)} (fixed)
        </p>
        {editable && (
          <div className="ref-image-card__actions">
            <button
              type="button"
              className="btn btn--danger"
              disabled={disabled}
              onClick={() => onRemove?.(image.id)}
            >
              <Icon name="trash" size="sm" />
              Remove
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
