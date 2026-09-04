import { useState } from 'react'
import type { GenerationSummary } from '../../api/types'
import { ImageDialog } from '../../components/ImageDialog'
import { AsyncMessage } from '../../components/AsyncMessage'
import { Icon } from '../../components/Icon'

interface CastMemberRef {
  character_id: number
  name: string
}

interface IdentityScores {
  cast?: Record<string, number>
  faces_detected?: number
}

interface CandidateCarouselProps {
  attempts: GenerationSummary[]
  reviewingCandidateId: number | null
  onReview: (candidateId: number, verdict: 'accepted' | 'rejected') => void
  /** Panel cast, used to label identity-score chips with character names. */
  cast?: CastMemberRef[]
}

const REVIEW_STATUS_LABEL: Record<string, string> = {
  pending: 'Waiting',
  accepted: 'Accepted',
  rejected: 'Rejected',
}

/** Tone thresholds for identity-score chips — advisory, never gates anything. */
function scoreTone(score: number): 'strong' | 'ok' | 'weak' {
  if (score >= 0.5) return 'strong'
  if (score >= 0.3) return 'ok'
  return 'weak'
}

function parseIdentityScores(value: unknown): IdentityScores | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as { cast?: unknown; faces_detected?: unknown }
  const payload: IdentityScores = {}
  if (raw.cast && typeof raw.cast === 'object') {
    const cast: Record<string, number> = {}
    for (const [key, val] of Object.entries(raw.cast)) {
      if (typeof val === 'number' && Number.isFinite(val)) cast[key] = val
    }
    if (Object.keys(cast).length > 0) payload.cast = cast
  }
  if (typeof raw.faces_detected === 'number') payload.faces_detected = raw.faces_detected
  return payload.cast || payload.faces_detected ? payload : null
}

/** Carousel that cycles through the generated images of each attempt (an
 * attempt stores exactly one candidate image), with per-image review status
 * and accept/reject controls. Used instead of a separate per-attempt detail
 * page. */
export function CandidateCarousel({
  attempts,
  reviewingCandidateId,
  onReview,
  cast,
}: CandidateCarouselProps) {
  const [index, setIndex] = useState(0)
  const reviewed = attempts.filter((attempt) => attempt.candidates.length > 0)
  const count = reviewed.length
  if (count === 0) return null

  const attempt = reviewed[index % count]
  const candidate = attempt.candidates[0]
  const identityScores = parseIdentityScores(candidate.identity_scores)
  const isReviewing = reviewingCandidateId !== null
  const reviewingThis = isReviewing && reviewingCandidateId === candidate.id
  const showPrevious = () => setIndex((i) => (i - 1 + count) % count)
  const showNext = () => setIndex((i) => (i + 1) % count)

  const identityChips = (cast ?? []).flatMap((member) => {
    const score = identityScores?.cast?.[String(member.character_id)]
    return score === undefined
      ? []
      : [(
        <span
          key={member.character_id}
          className={`identity-chip identity-chip--${scoreTone(score)}`}
          title={`Detected similarity to ${member.name}`}
        >
          {member.name}: {score.toFixed(2)}
        </span>
      )]
  })

  return (
    <div className="carousel" aria-label="Generated candidate across attempts">
      <div className="carousel__stage">
        <ImageDialog
          src={candidate.content_url}
          thumbnailAlt={`Generated image from attempt ${attempt.id}`}
          previewAlt={`Generated image from attempt ${attempt.id}, full-size preview`}
          triggerLabel={`Preview image from attempt ${attempt.id}`}
          dialogLabel={`Generated image from attempt ${attempt.id}, larger preview`}
          onPrevious={count > 1 ? showPrevious : undefined}
          onNext={count > 1 ? showNext : undefined}
        />
        <span className="carousel__counter">{index + 1} / {count}</span>
      </div>
      <div className="carousel__meta">
        <span className={`badge badge--attempt-${candidate.review_status}`}>
          {REVIEW_STATUS_LABEL[candidate.review_status] ?? candidate.review_status}
        </span>
        <span className="field__hint">Attempt #{attempt.id}</span>
      </div>
      {identityChips.length > 0 && (
        <div className="carousel__identity" aria-label="Character identity scores">
          {identityChips}
          {identityScores?.faces_detected !== undefined && (
            <span className="field__hint">
              {identityScores.faces_detected} face{identityScores.faces_detected === 1 ? '' : 's'} detected
            </span>
          )}
        </div>
      )}
      <div className="action-bar carousel__controls">
        <div className="action-bar__group action-bar__group--start">
          <button
            type="button"
            className="btn"
            disabled={count <= 1}
            onClick={showPrevious}
            aria-label="Previous attempt"
          >
            <Icon name="chevronLeft" size={16} />
            Previous
          </button>
          <button
            type="button"
            className="btn"
            disabled={count <= 1}
            onClick={showNext}
            aria-label="Next attempt"
          >
            Next
            <Icon name="chevronRight" size={16} />
          </button>
        </div>
        <div className="action-bar__group action-bar__group--end">
          <button
            type="button"
            className="btn btn--primary"
            disabled={isReviewing}
            onClick={() => onReview(candidate.id, 'accepted')}
          >
            <Icon name="check" size={16} />
            Accept
          </button>
          <button
            type="button"
            className="btn btn--danger"
            disabled={isReviewing}
            onClick={() => onReview(candidate.id, 'rejected')}
          >
            Reject
          </button>
        </div>
      </div>
      {reviewingThis && <AsyncMessage kind="loading">Reviewing image…</AsyncMessage>}
    </div>
  )
}
